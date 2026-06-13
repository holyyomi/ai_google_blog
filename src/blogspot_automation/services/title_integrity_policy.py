from __future__ import annotations

import re
from html import unescape
from typing import Any


SOURCE_SERIES_PREFIX_RE = re.compile(
    r"^\s*(?:\[[^\]]{1,40}\]|(?:재계는 지금|이슈체크|뉴스분석|오늘의 이슈|단독|속보|사설|기자수첩)\]?)\s*[:：]?\s*"
)

SOURCE_SERIES_NAMES: tuple[str, ...] = (
    "재계는 지금",
    "이슈체크",
    "뉴스분석",
    "오늘의 이슈",
    "단독",
    "속보",
    "사설",
    "기자수첩",
)

BROKEN_TITLE_PHRASES: tuple[str, ...] = (
    "화제 된 이 반응",
    "사람들이 본 에",
    "사람들이 본 의",
    "신청전 많이 묻는 질문",
    "신청 전 많이 묻는 질문",
)

MALFORMED_TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("source_series_prefix_visible", r"^[가-힣A-Za-z0-9·\s]{2,24\]\s+"),
    ("duplicated_confirm_before", r"확인할\s+전에"),
    ("orphan_confirm_particle", r"확인할\s+[을를이가은는]\b"),
    ("orphan_function_particle", r"\b[을를이가은는]\s+(?:제대로|먼저|확인|보기|볼)\b"),
    ("malformed_reaction_phrase", r"화제\s*된\s*이\s*반응"),
    ("empty_seen_object_particle", r"사람들이\s*본\s*[의에](?:\s|$)"),
    ("policy_faq_heading_leak", r"신청\s*전?\s*많이\s*묻는\s*질문"),
)

TELECOM_PLAN_TERMS: tuple[str, ...] = (
    "요금제",
    "통신비",
    "선택약정",
    "가족결합",
    "결합할인",
    "멤버십",
    "KT초이스",
    "통신사",
    "SKT",
    "SK텔레콤",
    "LG유플러스",
    "LGU+",
)

TELECOM_BRANDS: tuple[str, ...] = ("KT", "SKT", "SK텔레콤", "LG유플러스", "LGU+")

# LLM이 한국어 본문에 외국어 단어를 혼입하는 사고 차단 (실사례: 제목에 "зарубеж").
# 키릴·그리스·아랍·히브리·태국·일본 가나는 한국 블로그 제목·본문에 정당한 용도가 없다.
FOREIGN_SCRIPT_RE = re.compile(
    r"[Ѐ-ӿ"   # Cyrillic
    r"Ͱ-Ͽ"    # Greek
    r"؀-ۿ"    # Arabic
    r"֐-׿"    # Hebrew
    r"฀-๿"    # Thai
    r"぀-ヿ"    # Hiragana + Katakana
    r"]"
)


def contains_foreign_script(text: str) -> bool:
    return bool(FOREIGN_SCRIPT_RE.search(text or ""))


def clean_source_title(title: str) -> str:
    """Clean source/RSS titles before they enter topic and title generation."""
    cleaned = unescape(title or "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    while True:
        next_cleaned = SOURCE_SERIES_PREFIX_RE.sub("", cleaned).strip()
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    cleaned = cleaned.strip(" \"'“”‘’[]()")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def audit_title_integrity(
    title: str,
    *,
    content_type: str = "",
    topic_group: str = "",
    pattern_id: str = "",
    source_text: str = "",
) -> dict[str, Any]:
    """Return blocking issues for malformed, source-leaked, or misrouted titles."""
    text = " ".join(str(title or "").split()).strip()
    issues: list[str] = []
    if not text:
        issues.append("missing_title")
        return {"passed": False, "blocking_issues": issues}

    for name in SOURCE_SERIES_NAMES:
        if name in text:
            issues.append(f"source_series_name_leaked:{name}")
    for phrase in BROKEN_TITLE_PHRASES:
        if phrase in text:
            issues.append(f"broken_title_phrase:{phrase}")
    for issue_name, pattern in MALFORMED_TITLE_PATTERNS:
        if re.search(pattern, text):
            issues.append(issue_name)
    if _has_bad_subject_particle(text):
        issues.append("bad_subject_particle")
    if contains_foreign_script(text):
        issues.append("foreign_script_in_title")
    if _is_viral_context(content_type=content_type, topic_group=topic_group, pattern_id=pattern_id):
        if "평점보다 먼저 볼 포인트" in text:
            issues.append("low_value_viral_rating_title")
        if _is_telecom_plan_text(f"{text} {source_text}"):
            issues.append("telecom_plan_topic_using_viral_reaction_template")
    return {"passed": not issues, "blocking_issues": list(dict.fromkeys(issues))}


def _is_viral_context(*, content_type: str, topic_group: str, pattern_id: str) -> bool:
    return (
        content_type == "viral_issue_decode"
        or pattern_id == "viral_ott_reaction_decode"
        or topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"}
    )


def _is_telecom_plan_text(text: str) -> bool:
    value = text or ""
    return any(brand in value for brand in TELECOM_BRANDS) and any(term in value for term in TELECOM_PLAN_TERMS)


def _has_bad_subject_particle(title: str) -> bool:
    for match in re.finditer(r"(?:^|\s)([가-힣A-Za-z0-9·]{2,})가(?=\s|,|$)", title or ""):
        stem = match.group(1)
        if _has_korean_final_consonant(stem[-1]):
            return True
    return False


def _has_korean_final_consonant(ch: str) -> bool:
    code = ord(ch)
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
