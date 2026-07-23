"""실검색 AI 트렌드 → NewsCandidate 폴백 테스트.

배경: 고정 에버그린 뱅크가 소진되는 날에도 "후보 없음" 대신 오늘 실제
검색 수요가 있는 AI 주제로 후보를 만든다(2026-07-23). 여기서는 신호
서비스를 mock해서 (1) Trends에 AI 관련 항목이 있으면 그걸 쓰고, (2) 없으면
Autocomplete 헤드텀 프로브로 폴백하고, (3) 둘 다 없으면 빈 리스트를
반환하는지, (4) 만들어진 후보가 기존 evergreen_fallback 게이트를 그대로
통과할 수 있는 shape(topic_group=ai_work, content_type=ai_work_tip,
evergreen_fallback=True)인지 확인한다.
"""
from __future__ import annotations

from blogspot_automation.services import live_ai_demand_topic_service as svc
from blogspot_automation.services.google_trends_signal import TrendingKeyword


def test_trends_ai_keyword_becomes_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        svc.GoogleTrendsSignal,
        "get_trending_keywords",
        classmethod(lambda cls, **kw: [
            TrendingKeyword(keyword="local election results", approx_traffic="200,000+", related_news_titles=()),
            TrendingKeyword(keyword="Claude AI agent update", approx_traffic="50,000+", related_news_titles=()),
        ]),
    )
    candidates = svc.collect_live_ai_demand_candidates(max_candidates=3)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.topic == "Claude AI agent update"
    raw = candidate.raw
    assert raw["topic_group"] == "ai_work"
    assert raw["content_angle"]["content_type"] == "ai_work_tip"
    assert raw["evergreen_fallback"] is True
    assert raw["source_type"] == "evergreen_fallback"
    assert raw["live_demand_source"] == "google_trends"


def test_falls_back_to_autocomplete_when_no_ai_trend(monkeypatch) -> None:
    monkeypatch.setattr(
        svc.GoogleTrendsSignal,
        "get_trending_keywords",
        classmethod(lambda cls, **kw: [
            TrendingKeyword(keyword="local election results", approx_traffic="200,000+", related_news_titles=()),
        ]),
    )
    monkeypatch.setattr(svc, "is_autocomplete_signal_enabled", lambda: True)

    def _fake_suggestions(term: str) -> tuple[str, ...]:
        return ("chatgpt pricing", "chatgpt login") if term == "chatgpt" else ()

    monkeypatch.setattr(svc.SearchAutocompleteSignal, "suggestions_for", classmethod(lambda cls, q: _fake_suggestions(q)))

    candidates = svc.collect_live_ai_demand_candidates(max_candidates=3)
    assert len(candidates) == 1
    assert candidates[0].topic == "chatgpt"
    assert candidates[0].raw["live_demand_source"] == "autocomplete_fallback"
    assert candidates[0].raw["today_buzz_score"] == 5


def test_returns_empty_when_no_signal_at_all(monkeypatch) -> None:
    monkeypatch.setattr(svc.GoogleTrendsSignal, "get_trending_keywords", classmethod(lambda cls, **kw: []))
    monkeypatch.setattr(svc, "is_autocomplete_signal_enabled", lambda: True)
    monkeypatch.setattr(svc.SearchAutocompleteSignal, "suggestions_for", classmethod(lambda cls, q: ()))

    assert svc.collect_live_ai_demand_candidates() == []


def test_generic_ai_term_without_known_entity_still_matches() -> None:
    assert svc._is_ai_related("Best AI agent for scheduling")
    assert not svc._is_ai_related("local election results")


def test_trends_signal_failure_is_non_fatal(monkeypatch) -> None:
    def _raise(**kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(svc.GoogleTrendsSignal, "get_trending_keywords", classmethod(lambda cls, **kw: _raise(**kw)))
    monkeypatch.setattr(svc, "is_autocomplete_signal_enabled", lambda: False)

    assert svc.collect_live_ai_demand_candidates() == []
