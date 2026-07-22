"""에버그린 폴백 수요 재정렬 테스트 (2026-07-22).

2026-07-21 발행 2건이 모두 evergreen_fallback이었고 수요 신호 없이 뱅크 순서로
뽑혀 가격축 2건이 연속 발행됐다. (1) 최근 72h 가격축 발행 시 가격축 에버그린
후보를 뒤로 미루고 (2) Autocomplete 수요가 높은 주제를 앞으로 당기는지 검증.
"""
from __future__ import annotations

import pytest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline


@pytest.fixture(autouse=True)
def _english_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")


def _scored(topic: str, search_topic: str) -> ScoredNewsCandidate:
    nc = NewsCandidate(
        topic=topic,
        category="tech",
        summary="",
        source_hint="evergreen_fallback",
        published_at=None,
        url=None,
        raw={"source_type": "evergreen_fallback", "search_demand_topic": search_topic},
    )
    return ScoredNewsCandidate(
        candidate=nc,
        freshness_score=0,
        search_demand_score=0,
        contrarian_gap_score=0,
        mass_impact_score=0,
        adsense_value_score=0,
        hook_score=0,
        risk_penalty=0,
        total_score=80,
        reason="test",
    )


def _pipeline() -> NewsPipeline:
    return NewsPipeline.__new__(NewsPipeline)


def test_pricing_cooldown_pushes_pricing_topic_back(monkeypatch):
    pipeline = _pipeline()
    pricing = _scored("AI assistant pricing and limits comparison", "ai assistant pricing")
    non_pricing = _scored("fix ChatGPT file upload errors", "chatgpt file upload error")
    monkeypatch.setattr(
        NewsPipeline, "_recent_pricing_family_published", staticmethod(lambda **kw: True)
    )
    monkeypatch.setattr(
        "blogspot_automation.services.search_autocomplete_signal.score_topic_boost",
        lambda text, max_boost=12: (0, []),
    )
    reranked = pipeline._rank_evergreen_pool_by_search_demand([pricing, non_pricing])
    assert reranked[0] is non_pricing
    assert reranked[1] is pricing


def test_autocomplete_demand_pulls_topic_forward(monkeypatch):
    pipeline = _pipeline()
    low = _scored("obscure AI workflow notes", "obscure ai workflow")
    high = _scored("ChatGPT for excel automation", "chatgpt excel automation")
    monkeypatch.setattr(
        NewsPipeline, "_recent_pricing_family_published", staticmethod(lambda **kw: False)
    )

    def _fake_boost(text, max_boost=12):
        return (10, ["autocomplete:x(9)"]) if "excel" in text else (0, [])

    monkeypatch.setattr(
        "blogspot_automation.services.search_autocomplete_signal.score_topic_boost",
        _fake_boost,
    )
    reranked = pipeline._rank_evergreen_pool_by_search_demand([low, high])
    assert reranked[0] is high
    assert (high.candidate.raw or {}).get("demand_signal_boost") == 10


def test_failures_keep_original_order(monkeypatch):
    pipeline = _pipeline()
    first = _scored("topic one guide", "topic one")
    second = _scored("topic two guide", "topic two")

    def _boom(**kw):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(
        NewsPipeline, "_recent_pricing_family_published", staticmethod(_boom)
    )
    monkeypatch.setattr(
        "blogspot_automation.services.search_autocomplete_signal.score_topic_boost",
        lambda text, max_boost=12: (0, []),
    )
    reranked = pipeline._rank_evergreen_pool_by_search_demand([first, second])
    assert reranked == [first, second]


def test_topic_is_pricing_family_word_boundaries():
    assert NewsPipeline._topic_is_pricing_family("AI Assistant Pricing Compared: X vs Y")
    assert NewsPipeline._topic_is_pricing_family("hidden costs of AI subscriptions")
    assert not NewsPipeline._topic_is_pricing_family("fix ChatGPT upload errors fast")
