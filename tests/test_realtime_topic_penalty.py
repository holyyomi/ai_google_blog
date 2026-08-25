from __future__ import annotations

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.news_scoring_service import (
    NewsScoringService,
    realtime_event_penalty,
)


def test_realtime_event_topics_are_penalized():
    """장애·중단·상태 주제는 블로그가 이길 수 없다.

    2026-08-25 실측 사고: outage 뉴스를 골라 "claude status 99.35% uptime 2026"으로
    발행했다. 그 검색을 하는 독자가 원하는 건 실시간 상태 페이지이고, 구글은 공식
    status 페이지를 띄운다 — 어제 쓴 글은 그 자리를 못 뺏는다.
    """
    for topic in (
        "Anthropic Claude and API service outages",
        "Claude API status page updated",
        "Gemini agent mode goes down for users",
        "Claude service restored after disruption",
    ):
        penalty, reason = realtime_event_penalty(topic)
        assert penalty > 0, topic
        assert reason.startswith("realtime_event:"), reason


def test_informational_topics_are_not_penalized():
    for topic in (
        "OpenAI releases GPT-5.6 pricing tiers",
        "How to reduce Claude API costs",
        "Claude Code skills marketplace explained",
    ):
        assert realtime_event_penalty(topic) == (0, "")


def test_penalty_lowers_total_score_and_is_recorded():
    service = NewsScoringService(min_topic_score=0)

    def _score(topic: str) -> tuple[int, dict]:
        candidate = NewsCandidate(topic=topic, summary="", category="ai", raw={})
        scored = service.score_candidates([candidate])
        assert scored, topic
        return scored[0].total_score, (scored[0].candidate.raw or {})

    outage_score, outage_raw = _score("Anthropic Claude API service outages hit users")
    calm_score, calm_raw = _score("Anthropic Claude API pricing tiers explained")

    assert outage_score < calm_score, (outage_score, calm_score)
    assert outage_raw.get("realtime_event_penalty_applied") is True
    assert "realtime_event" in str(outage_raw.get("realtime_event_reason"))
    assert calm_raw.get("realtime_event_penalty_applied") is None
