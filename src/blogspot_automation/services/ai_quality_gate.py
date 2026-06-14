"""AI 글 발행 품질 게이트 (soft).

설계 원칙: 매일 자동 발행이 사소한 품질 미달로 막히지 않도록,
- hard_block(발행 중지)은 '치명적'인 경우로만 한정한다.
- 나머지는 soft_warning(로그/기록만, 발행은 진행)으로 처리한다.

렌더러가 표준 요소(내부링크·해시태그·히어로·FAQ·JSON-LD)를 항상 포함하므로
정상 글은 hard_block에 거의 걸리지 않는다.
"""
from __future__ import annotations

import re
from typing import Any

# 치명적 차단 문구 (명예훼손·허위 단정·과장 보장). 발견 시 발행 중지.
_HARD_BANNED_PHRASES: tuple[str, ...] = (
    "월 1000만원 보장",
    "무조건 수익",
    "100% 보장",
    "절대 안전합니다",
    "직접 써보니 최고였습니다",
)

# 본문 최소 길이(하드) — 진짜 깨진 글만 거른다. 정상 글은 2000자+라 여유롭다.
_HARD_MIN_CHARS = 700
# 권장 길이(소프트) — E-E-A-T 분량 권장치.
_SOFT_MIN_CHARS = 2000


def _visible_text(html: str) -> str:
    body = re.sub(r"<head>.*?</head>", "", html or "", flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text).strip()


def evaluate_ai_publish_quality(html: str, *, content_type: str = "") -> dict[str, Any]:
    """AI 발행 후보 HTML 품질 평가.

    Returns:
        {
          "passed": bool,          # hard_block 없으면 True (발행 허용)
          "hard_blocks": [str],    # 발행을 막는 치명적 문제
          "soft_warnings": [str],  # 발행은 하되 개선 권장
          "quality_score": int,    # 0~100, 참고용
          "char_count": int,
        }
    """
    html = html or ""
    text = _visible_text(html)
    chars = len(re.sub(r"\s", "", text))

    hard_blocks: list[str] = []
    soft_warnings: list[str] = []

    # ---- HARD: 치명적 ----
    if "<h1" not in html.lower():
        hard_blocks.append("missing_h1")
    if chars < _HARD_MIN_CHARS:
        hard_blocks.append(f"body_too_short:{chars}")
    if 'id="AI_CITATION_SUMMARY"' not in html:
        hard_blocks.append("missing_ai_citation_summary")
    for phrase in _HARD_BANNED_PHRASES:
        if phrase in html:
            hard_blocks.append(f"banned_phrase:{phrase[:20]}")

    # ---- SOFT: 개선 권장 (발행은 진행) ----
    if chars < _SOFT_MIN_CHARS:
        soft_warnings.append(f"below_recommended_length:{chars}")
    _il = re.search(r'<section[^>]*class="yomi-internal-links"[^>]*>(.*?)</section>', html, re.DOTALL)
    if not _il:
        soft_warnings.append("internal_links_missing")
    elif len(re.findall(r"<a\b", _il.group(1))) < 2:
        soft_warnings.append("internal_links_below_2")
    if not ("yomi-hashtags" in html or "hashtag-box" in html):
        soft_warnings.append("hashtags_missing")
    if not ("ai-hero" in html or "ai-cover-image" in html):
        soft_warnings.append("hero_or_cover_missing")
    if not ('"FAQPage"' in html or 'class="faq' in html or 'intent-qa-item' in html):
        soft_warnings.append("faq_missing")
    if '"@context"' not in html:
        soft_warnings.append("jsonld_missing")
    if "use-case" not in html:
        soft_warnings.append("use_cases_missing")

    # quality_score: 소프트 항목 충족도 기반(참고용)
    soft_checks_total = 7
    score = max(0, min(100, round((soft_checks_total - len(soft_warnings)) / soft_checks_total * 100)))
    if hard_blocks:
        score = min(score, 40)

    return {
        "passed": not hard_blocks,
        "hard_blocks": hard_blocks,
        "soft_warnings": soft_warnings,
        "quality_score": score,
        "char_count": chars,
    }
