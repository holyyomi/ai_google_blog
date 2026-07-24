"""실검색 AI 트렌드 → NewsCandidate 폴백 테스트.

배경: 고정 에버그린 뱅크가 소진되는 날에도 "후보 없음" 대신 오늘 실제
검색 수요가 있는 AI 주제로 후보를 만든다(2026-07-23). Google Trends의
AI 관련 트렌드만 신호로 쓴다 — 초판에 있던 "고정 헤드텀을 Autocomplete로
프로브하는 폴백"은 사용자 피드백("도구에 제한을 두지 말고 매일 새로운
AI·이슈가 되는 AI를 찾아라")에 따라 제거했다: 그 자체가 몇 개 대기업
제품명으로만 매일 좁혀지는 고정 목록 편향이었다. Trends에 AI 신호가 없는
날은 community_topic_service(Reddit/HN)가 이 역할을 대신한다.
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


def test_returns_empty_when_no_ai_trend_today(monkeypatch) -> None:
    monkeypatch.setattr(
        svc.GoogleTrendsSignal,
        "get_trending_keywords",
        classmethod(lambda cls, **kw: [
            TrendingKeyword(keyword="local election results", approx_traffic="200,000+", related_news_titles=()),
        ]),
    )
    assert svc.collect_live_ai_demand_candidates() == []


def test_returns_empty_when_no_signal_at_all(monkeypatch) -> None:
    monkeypatch.setattr(svc.GoogleTrendsSignal, "get_trending_keywords", classmethod(lambda cls, **kw: []))
    assert svc.collect_live_ai_demand_candidates() == []


def test_generic_ai_term_without_known_entity_still_matches() -> None:
    # 특정 회사명이 없어도(신생/무명 AI 포함) 일반 AI 용어만으로 매칭된다 —
    # 알려진 대기업 목록에 갇히지 않는다는 게 핵심.
    assert svc._is_ai_related("Best AI agent for scheduling")
    assert svc._is_ai_related("New AI startup raises funding")
    assert not svc._is_ai_related("local election results")


def test_trends_signal_failure_is_non_fatal(monkeypatch) -> None:
    def _raise(**kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(svc.GoogleTrendsSignal, "get_trending_keywords", classmethod(lambda cls, **kw: _raise(**kw)))
    assert svc.collect_live_ai_demand_candidates() == []
