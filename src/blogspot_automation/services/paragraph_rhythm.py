"""긴 문단을 문장 경계에서 잘라 읽기 쉬운 리듬으로 만든다.

배경 (2026-09-11 실측). 본문 생성 프롬프트에는 이미 문단 계약이 적혀 있다 —
`llm_content_service._SYSTEM_PROMPT_EN` 의 "each paragraph is 2-3 sentences and
at most 70 words". 그런데 **아무도 확인하지 않는다**: `_validate_generated_content`
는 문단 길이를 보지 않고, 발행 게이트는 90단어에서 경고만 찍고 막지 않는다.
결과적으로 최근 발행 12편 중 8편에 `dense_paragraph_over_90_words` 가 떴고,
라이브 글 하나를 내려받아 재보니 문단 평균 59단어 · 최대 82단어였다.

그래서 부탁(프롬프트) 대신 **코드로 교정**한다. LLM에게 다시 써달라고 하는 것은
비싸고 결과가 흔들리지만, 문장 경계에서 자르는 것은 공짜이고 결정적이다.

안전 장치:
- `class` 속성이 있는 `<p>` 는 건드리지 않는다. 구조 블록(section-label,
  intent-q 등)이라 쪼개면 스타일·다운스트림 정규식이 깨진다
  ([[reference_bare_p_tag_trap]] 과 같은 이유).
- 인라인 태그(`<strong>`, `<a>` …)가 열려 있는 지점에서는 자르지 않는다.
  태그가 문단 경계를 넘어가면 HTML이 깨진다.
- 문장 경계를 못 찾으면 원문 그대로 둔다 — 자르는 것보다 그대로가 낫다.
- 멱등이다. 한 번 돌린 결과를 다시 돌려도 바뀌지 않는다(상한 이하이므로).
"""

from __future__ import annotations

import re

# 프롬프트 계약(llm_content_service)이 "at most 70 words"다. 같은 값을 쓴다 —
# 건드리지 않고 명백히 넘긴 것만 교정한다. 게이트 경고선은 90이라 그 아래로
# 확실히 내려간다.
SPLIT_THRESHOLD_WORDS = 70
# 자른 조각의 목표 길이. 2~3문장이면 대개 이 근처다.
TARGET_CHUNK_WORDS = 55

_PARAGRAPH_RE = re.compile(r"<p(?P<attrs>[^>]*)>(?P<inner>.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<(?P<closing>/?)(?P<name>[a-zA-Z][a-zA-Z0-9]*)[^>]*?(?P<selfclose>/?)>")
_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}
# 문장 끝: 마침표/물음표/느낌표 + 공백. 약어(e.g. / U.S. / Inc.)는 자르지 않는다.
_SENTENCE_END_RE = re.compile(r"(?<![A-Z])(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)[.!?][\"')\]]?\s+")


def _visible_word_count(fragment: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", fragment or "").split())


def _safe_split_points(inner: str) -> list[int]:
    """인라인 태그가 모두 닫힌 상태인 문장 경계 오프셋 목록."""
    points: list[int] = []
    for match in _SENTENCE_END_RE.finditer(inner):
        cut = match.end()
        prefix = inner[:cut]
        depth = 0
        balanced = True
        for tag in _TAG_RE.finditer(prefix):
            name = tag.group("name").lower()
            if name in _VOID_TAGS or tag.group("selfclose"):
                continue
            if tag.group("closing"):
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
            else:
                depth += 1
        if balanced and depth == 0:
            points.append(cut)
    return points


def _sentence_segments(inner: str) -> list[str]:
    """인라인 태그가 닫힌 문장 경계로만 자른 조각들."""
    points = _safe_split_points(inner)
    if not points:
        return [inner]
    segments: list[str] = []
    prev = 0
    for cut in points:
        segments.append(inner[prev:cut])
        prev = cut
    tail = inner[prev:]
    if tail.strip():
        segments.append(tail)
    return [seg for seg in segments if seg]


def _split_inner(inner: str) -> list[str]:
    """문단 하나를 목표 길이에 맞춰 문장 단위로 묶는다. 못 나누면 [원문].

    누적이 목표를 **넘긴 뒤에** 자르면 마지막 문장 하나짜리 문단에서는 경계가
    한 번도 안 걸려 원문이 그대로 남는다(2026-09-11 라이브 글 실측: 82단어
    3문장 문단이 안 잘렸다). 그래서 "다음 문장을 넣으면 목표를 넘길 때 끊는"
    탐욕적 묶기로 바꾼다.
    """
    segments = _sentence_segments(inner)
    if len(segments) < 2:
        return [inner]
    chunks: list[str] = []
    current = ""
    current_words = 0
    for segment in segments:
        words = _visible_word_count(segment)
        if current and current_words + words > TARGET_CHUNK_WORDS:
            chunks.append(current)
            current, current_words = segment, words
        else:
            current += segment
            current_words += words
    if current:
        chunks.append(current)
    if len(chunks) < 2:
        return [inner]
    # 꼬리가 한 문장도 안 되게 짧으면 앞 조각에 붙인다 — 고아 문장 방지.
    if _visible_word_count(chunks[-1]) < 12:
        chunks[-2] = chunks[-2] + chunks[-1]
        chunks.pop()
    return chunks if len(chunks) >= 2 else [inner]


def split_dense_paragraphs(html: str, *, threshold_words: int = SPLIT_THRESHOLD_WORDS) -> str:
    """`<p>` 중 threshold 를 넘는 것만 문장 경계에서 나눈다."""
    if not html:
        return html

    def _replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        inner = match.group("inner") or ""
        if "class=" in attrs.lower():
            return match.group(0)
        if _visible_word_count(inner) <= threshold_words:
            return match.group(0)
        parts = _split_inner(inner)
        if len(parts) < 2:
            return match.group(0)
        return "".join(f"<p{attrs}>{part.strip()}</p>" for part in parts)

    return _PARAGRAPH_RE.sub(_replace, html)


def dense_paragraph_count(html: str, *, threshold_words: int = 90) -> int:
    """게이트와 같은 기준으로 남은 과밀 문단 수를 센다(검증·테스트용)."""
    return sum(
        1
        for match in _PARAGRAPH_RE.finditer(html or "")
        if _visible_word_count(match.group("inner")) > threshold_words
    )


# ---------------------------------------------------------------------------
# 단계 문자열 -> 목록
# ---------------------------------------------------------------------------
# real_criterion 슬롯은 명세부터 "Step 1: ... / Step 2: ..."(영어) 또는
# "1단계: ... / 2단계: ..."(한국어) 형식의 **한 문자열**이다. 그런데 렌더러가
# 이걸 <p> 하나로 escape 하면서 줄바꿈이 사라져, 3단계짜리 실행 가이드가 통짜
# 문단으로 뭉개져 나갔다(2026-09-11 확인). 여기서 단계를 되살린다.
_STEP_MARKER_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s.;:!?)]))(?:Step\s*\d+|\d+\s*단계)\s*[:.\-]\s*",
    re.IGNORECASE,
)


def split_numbered_steps(text: str) -> list[str]:
    """단계 표지가 붙은 한 문자열을 단계 목록으로 나눈다.

    표지를 2개 이상 못 찾으면 빈 목록을 돌려준다 — 호출부가 기존 `<p>` 렌더로
    돌아가게 해서, 단계 글이 아닌 산문을 억지로 목록으로 만들지 않는다.
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    marks = list(_STEP_MARKER_RE.finditer(raw))
    if len(marks) < 2:
        return []
    pieces: list[str] = []
    for index, mark in enumerate(marks):
        begin = mark.end()
        stop = marks[index + 1].start() if index + 1 < len(marks) else len(raw)
        piece = " ".join(raw[begin:stop].split()).strip(" .;")
        if piece:
            pieces.append(piece)
    return pieces if len(pieces) >= 2 else []
