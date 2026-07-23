"""오늘 실제로 가장 많이 검색되는 AI 주제 → NewsCandidate.

배경(2026-07-23): 고정 에버그린 뱅크(30개, ai_automation 축)가 엔티티
쿨다운/콘텐츠 dedup에 막혀 전멸하는 날(2026-07-22 실측: 골든매칭 14개 전부
제외 → 발행 0건)에도, "후보가 없으면 스킵"이 아니라 오늘 실제 검색 수요가
있는 AI 주제를 찾아 후보를 만든다.

1차 신호는 Google Trends(무키)의 오늘의 실제 트렌딩 검색어 중 AI 관련 항목,
2차(1차가 비면 대부분의 날) 신호는 Google Autocomplete(무키)로 고정 AI
헤드텀들의 제안 수를 프로브해 상시 수요가 가장 큰 term을 쓴다.

이 모듈은 후보를 "더 공급"할 뿐이다 — 품질/사실안전 게이트는 기존과 동일하게
전부 적용되며, 여기서 만든 후보도 통과 못 하면 그냥 탈락한다(정상 동작).
"""
from __future__ import annotations

import logging

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.google_trends_signal import GoogleTrendsSignal
from blogspot_automation.services.search_autocomplete_signal import (
    SearchAutocompleteSignal,
    is_signal_enabled as is_autocomplete_signal_enabled,
)
from blogspot_automation.services.topic_dedup_service import ENTITY_ALIASES

logger = logging.getLogger(__name__)

# ENTITY_ALIASES(회사명)로 안 잡히는 일반 AI 용어 — Trends 트렌딩 키워드가
# 특정 제품명 없이 "AI agent"류로 뜨는 경우를 잡기 위함.
_GENERIC_AI_TERMS: tuple[str, ...] = (
    "ai", "artificial intelligence", "chatbot", "llm", "large language model",
    "ai agent", "ai tool", "ai model",
)

# Autocomplete 폴백용 고정 헤드텀 — 상시 검색량이 있다고 이미 알려진 AI 제품군.
_AUTOCOMPLETE_PROBE_TERMS: tuple[str, ...] = (
    "chatgpt", "claude ai", "gemini ai", "copilot ai", "perplexity ai",
    "openai", "ai agent",
)

_EVERGREEN_REASON = (
    "Live search-demand signal (Google Trends / Autocomplete) — a real, "
    "currently-searched AI query used when the fixed evergreen bank is exhausted."
)


def _is_ai_related(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    for aliases in ENTITY_ALIASES.values():
        for alias in aliases:
            if alias.lower() in lowered:
                return True
    return any(term in lowered for term in _GENERIC_AI_TERMS)


def _traffic_rank(approx_traffic: str) -> int:
    digits = "".join(ch for ch in (approx_traffic or "") if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _reader_search_questions(query: str) -> list[str]:
    return [
        f"What is {query}?",
        f"How much does {query} cost?",
        f"Is {query} worth it right now?",
    ]


def _to_candidate(query: str, *, source: str, today_buzz_score: int) -> NewsCandidate:
    reader_questions = _reader_search_questions(query)
    click_reason = f"Readers are actively searching '{query}' right now but generic results don't answer it directly."
    reader_benefit = f"A current, sourced answer on {query} — pricing, limits, and a clear verdict."
    content_promise = f"Give a direct, numbers-first answer on {query} with an as-of date and a decision rule."
    search_angle = {
        "original_topic": query,
        "search_demand_topic": query,
        "reader_search_questions": reader_questions,
        "click_reason": click_reason,
        "reader_benefit": reader_benefit,
        "urgency_reason": "This is actively searched today; a current answer wins the click.",
        "content_promise": content_promise,
        "angle_type": "money_compare",
        "should_transform_title": True,
        "commercial_support_signal": False,
        "generic_support_keyword": "",
        "public_benefit_keyword": "",
        "public_benefit_confidence": "none",
        "public_benefit_promotion_blocked": False,
    }
    content_angle = {
        "content_type": "ai_work_tip",
        "reader_question": reader_questions[0],
        "reader_loss": click_reason,
        "practical_value": reader_benefit,
        "example_needed": True,
    }
    return NewsCandidate(
        topic=query,
        category="tech",
        summary=f"{query} — practical, numbers-first guide for working professionals.",
        source_hint="evergreen_fallback",
        published_at=None,
        url=None,
        raw={
            "source": "evergreen_fallback",
            "source_type": "evergreen_fallback",
            "is_test_candidate": False,
            "publish_allowed": True,
            "evergreen_axis": "ai_automation",
            "evergreen_reason": _EVERGREEN_REASON,
            "target_reader": "working professionals and solo business owners (US/UK/CA/IN)",
            "query_group": "ai_automation",
            "topic_group": "ai_work",
            "content_angle": content_angle,
            "search_angle": search_angle,
            "search_demand_topic": query,
            "reader_search_questions": reader_questions,
            "click_reason": click_reason,
            "reader_benefit": reader_benefit,
            "urgency_reason": "This is actively searched today; a current answer wins the click.",
            "content_promise": content_promise,
            "angle_type": "money_compare",
            "evergreen_fallback": True,
            "is_stale": False,
            "discovery_engine": True,
            "today_buzz_score": today_buzz_score,
            "live_demand_signal": True,
            "live_demand_source": source,
        },
    )


def _collect_from_trends(max_candidates: int) -> list[NewsCandidate]:
    try:
        keywords = GoogleTrendsSignal.get_trending_keywords()
    except Exception as exc:  # noqa: BLE001 — 실신호 실패는 항상 비치명
        logger.warning("live_ai_demand: google trends fetch failed (non-fatal): %s", exc)
        return []
    ai_keywords = [kw for kw in keywords if kw.keyword and _is_ai_related(kw.keyword)]
    ai_keywords.sort(key=lambda kw: _traffic_rank(kw.approx_traffic), reverse=True)
    return [
        _to_candidate(kw.keyword.strip(), source="google_trends", today_buzz_score=9)
        for kw in ai_keywords[:max_candidates]
    ]


def _collect_from_autocomplete(max_candidates: int) -> list[NewsCandidate]:
    if not is_autocomplete_signal_enabled():
        return []
    scored: list[tuple[int, str]] = []
    for term in _AUTOCOMPLETE_PROBE_TERMS:
        try:
            suggestions = SearchAutocompleteSignal.suggestions_for(term)
        except Exception as exc:  # noqa: BLE001
            logger.warning("live_ai_demand: autocomplete probe failed for %s (non-fatal): %s", term, exc)
            continue
        if suggestions:
            scored.append((len(suggestions), term))
    scored.sort(reverse=True)
    return [
        _to_candidate(term, source="autocomplete_fallback", today_buzz_score=5)
        for _count, term in scored[:max_candidates]
    ]


def collect_live_ai_demand_candidates(max_candidates: int = 3) -> list[NewsCandidate]:
    """오늘 실검색 수요가 있는 AI 주제를 찾아 후보로 만든다.

    Google Trends에 AI 관련 트렌드가 있으면 그걸 쓰고(강한 신호), 없으면
    Autocomplete로 상시 수요 AI 제품군을 프로브해 폴백한다(약한 신호).
    둘 다 실패하면 빈 리스트 — 호출부는 "신호 없음"으로 처리한다.
    """
    candidates = _collect_from_trends(max_candidates)
    if candidates:
        return candidates
    return _collect_from_autocomplete(max_candidates)
