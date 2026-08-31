from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import os
import re


_WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*|\d+(?:[.,]\d+)*")
_ALPHA_RE = re.compile(r"[A-Za-z]+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")

_SKIP_TAGS = {
    "code",
    "head",
    "kbd",
    "noscript",
    "pre",
    "samp",
    "script",
    "style",
    "svg",
    "table",
}
_BLOCK_TAGS = {
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "ol",
    "p",
    "section",
    "td",
    "th",
    "tr",
    "ul",
}
_GEO_ID_FRAGMENTS = (
    "ai_citation_summary",
    "ai_overview_target_answer",
    "confirmed_vs_check_needed_block",
    "intent_answer_block",
    "issue_context_block",
    "people_also_ask_block",
    "source_trust_block",
)
_SKIP_CLASS_FRAGMENTS = (
    "ai-overview-box",
    "code-block",
    "intent-answer-box",
    "prompt-code",
    "source-trust-box",
    "yomi-citation-summary",
    "yomi-engine-support",
    "yomi-source",
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool]] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        parent_skipped = self._stack[-1][1] if self._stack else False
        skipped = parent_skipped or tag_l in _SKIP_TAGS or _attrs_excluded(attrs)
        self._stack.append((tag_l, skipped))
        if not skipped and tag_l in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        skipped = self._stack[-1][1] if self._stack else False
        if not skipped and tag_l in _BLOCK_TAGS:
            self._parts.append("\n")
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag_l:
                del self._stack[i:]
                break

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        parent_skipped = self._stack[-1][1] if self._stack else False
        if not parent_skipped and tag_l in _BLOCK_TAGS and not _attrs_excluded(attrs):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1][1]:
            return
        if data and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        # 블록 경계 줄바꿈을 살려서 돌려준다. 2026-08-25 실측 사고: 여기서
        # split()으로 뭉개는 바람에 <h2>가 다음 문단과 한 문장으로 붙었다
        # ("Frequently Asked Questions Use this if You run production workloads
        # on Grok and need to..."). 문장 수가 줄어 평균 문장길이가 부풀고,
        # 보정 패스에는 문장이 아닌 덩어리가 "어려운 문장"으로 넘어갔다.
        raw = unescape(" ".join(self._parts))
        lines = [" ".join(line.split()) for line in raw.split("\n")]
        return "\n".join(line for line in lines if line)


def measure(text: str) -> dict[str, object]:
    plain = _normalize_keeping_breaks(unescape(text or ""))
    words = _word_tokens(plain.replace("\n", " "))
    sentences = _sentence_tokens(plain)
    word_count = len(words)
    sentence_count = len(sentences)
    if word_count == 0 or sentence_count == 0:
        return {
            "words": word_count,
            "sentences": sentence_count,
            "avg_sentence_words": 0.0,
            "flesch_reading_ease": 0.0,
            "grade_level": 0.0,
            "long_word_pct": 0.0,
            "hard_sentences": [],
        }

    syllables = sum(_count_syllables(word) for word in words)
    avg_sentence_words = word_count / sentence_count
    syllables_per_word = syllables / word_count
    fre = 206.835 - (1.015 * avg_sentence_words) - (84.6 * syllables_per_word)
    grade = (0.39 * avg_sentence_words) + (11.8 * syllables_per_word) - 15.59
    long_words = sum(1 for word in words if _is_long_word(word))
    return {
        "words": word_count,
        "sentences": sentence_count,
        "avg_sentence_words": round(avg_sentence_words, 1),
        "flesch_reading_ease": round(fre, 1),
        "grade_level": round(max(0.0, grade), 1),
        "long_word_pct": round((long_words / word_count) * 100, 1),
        "hard_sentences": _hard_sentences(sentences),
    }


def measure_html(html: str) -> dict[str, object]:
    parser = _VisibleTextParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return measure("")
    return measure(parser.text())


def is_below_target(m: dict[str, object]) -> bool:
    """목표 미달이면 보강(repair)을 한 번 시도한다 — 발행을 막지는 않는다.

    2026-08-31 기본값 상향 (55 -> 60): 요미님이 "기존 글들이 너무 어렵다"고 지적했고,
    실제 발행 글 첫 문장이 *"CC Switch issue 4627 (June 2026) confirms most NIM
    models fail in Claude Code."* 였다. 시스템 프롬프트는 이미 8학년 수준을 요구하는데
    지켜지지 않았다 — 지시문만으로는 안 지켜지고 기계로 재야 움직인다.

    FRE 55는 "약간 어려움"(고교 상급)이고, 프롬프트가 목표로 적어둔 8학년 수준은
    60~70 구간이다. 즉 기존 목표치가 프롬프트의 요구와 어긋나 있었다.

    차단선(is_below_floor)은 40 그대로 둔다 — 그쪽을 올리면 발행이 통째로 멈출 수
    있어서, 먼저 보강 목표만 올려 실제 점수 분포를 보고 판단한다.
    """
    if int(m.get("words") or 0) <= 0 or int(m.get("sentences") or 0) <= 0:
        return False
    return (
        float(m.get("flesch_reading_ease") or 0.0) < _env_float("READABILITY_TARGET_FRE", 60.0)
        or float(m.get("avg_sentence_words") or 0.0) > _env_float("READABILITY_TARGET_ASL", 17.0)
    )


def is_below_floor(m: dict[str, object]) -> bool:
    if int(m.get("words") or 0) <= 0 or int(m.get("sentences") or 0) <= 0:
        return False
    return float(m.get("flesch_reading_ease") or 0.0) < _env_float("READABILITY_FLOOR_FRE", 40.0)


def _attrs_excluded(attrs: list[tuple[str, str | None]]) -> bool:
    attr_map = {name.lower(): str(value or "").strip().lower() for name, value in attrs}
    element_id = attr_map.get("id", "")
    class_name = attr_map.get("class", "")
    if any(fragment in element_id for fragment in _GEO_ID_FRAGMENTS):
        return True
    return any(fragment in class_name for fragment in _SKIP_CLASS_FRAGMENTS)


def _word_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _WORD_RE.finditer(text or "")]


def _normalize_keeping_breaks(text: str) -> str:
    """줄바꿈은 남기고 나머지 공백만 정리한다.

    소제목·목록 항목·표 셀은 마침표로 끝나지 않는 일이 흔하다. 줄바꿈을 지우면
    그것들이 뒤 문장에 흡수돼 문장 경계가 사라진다.
    """
    lines = [" ".join(line.split()) for line in str(text or "").split("\n")]
    return "\n".join(line for line in lines if line)


def _sentence_tokens(text: str) -> list[str]:
    normalized = _normalize_keeping_breaks(text or "")
    if not normalized:
        return []
    sentences: list[str] = []
    # 줄(=블록) 안에서만 마침표 기준으로 나눈다 — 줄 자체도 문장 경계다.
    for line in normalized.split("\n"):
        for m in _SENTENCE_RE.finditer(line):
            piece = m.group(0).strip()
            if piece:
                sentences.append(piece)
    return [s for s in sentences if _WORD_RE.search(s)]


def _count_syllables(word: str) -> int:
    alpha = "".join(_ALPHA_RE.findall(word or "")).lower()
    if not alpha:
        return 1
    count = len(_VOWEL_GROUP_RE.findall(alpha))
    if alpha.endswith("e") and not re.search(r"[^aeiouy]le$", alpha):
        count -= 1
    return max(1, count)


def _is_long_word(word: str) -> bool:
    alpha = "".join(_ALPHA_RE.findall(word or ""))
    return bool(alpha) and _count_syllables(alpha) >= 3


def _hard_sentences(sentences: list[str]) -> list[str]:
    ranked: list[tuple[int, int, int, str]] = []
    for sentence in sentences:
        words = _word_tokens(sentence)
        if not words:
            continue
        long_word_count = sum(1 for word in words if _is_long_word(word))
        word_count = len(words)
        if word_count > 25 or long_word_count >= 3:
            ranked.append((long_word_count * 8 + word_count, long_word_count, word_count, sentence))
    ranked.sort(reverse=True)
    return [sentence for _, _, _, sentence in ranked[:5]]


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
