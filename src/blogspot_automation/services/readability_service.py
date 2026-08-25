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
        return " ".join(unescape(" ".join(self._parts)).split())


def measure(text: str) -> dict[str, object]:
    plain = " ".join(unescape(text or "").split())
    words = _word_tokens(plain)
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
    if int(m.get("words") or 0) <= 0 or int(m.get("sentences") or 0) <= 0:
        return False
    return (
        float(m.get("flesch_reading_ease") or 0.0) < _env_float("READABILITY_TARGET_FRE", 55.0)
        or float(m.get("avg_sentence_words") or 0.0) > _env_float("READABILITY_TARGET_ASL", 18.0)
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


def _sentence_tokens(text: str) -> list[str]:
    normalized = " ".join((text or "").split())
    if not normalized:
        return []
    sentences = [m.group(0).strip() for m in _SENTENCE_RE.finditer(normalized)]
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
