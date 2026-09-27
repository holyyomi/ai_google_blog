"""큰 이슈 우선 선정(2026-09-27 요미님 지시) 회귀 방지.

그날 실측: HN 상위 12건 중 11건이 엔티티 3일 쿨다운에 잘렸고(전날 Claude·Gemini 글),
면제된 클러스터 후보 "gemini limits free users"가 재시도 6번 중 5번 뽑혔다.
"""
from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _scored(raw: dict, topic: str, score: int = 90) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(topic=topic, category="today_issue", summary=topic, raw=raw),
        freshness_score=0, search_demand_score=0, contrarian_gap_score=0,
        mass_impact_score=0, adsense_value_score=0, hook_score=0, risk_penalty=0,
        total_score=score, reason="",
    )


CLUSTER_RAW = {
    "source_type": "evergreen_fallback",
    "topic_cluster": True,
    "cluster_key": "free_ai_api_reality",
    "cluster_slot": "gemini_limits_free_users",
}


def _pipeline() -> NewsPipeline:
    return NewsPipeline.__new__(NewsPipeline)


def test_big_issue_beats_cluster_candidate(monkeypatch):
    monkeypatch.delenv("ISSUE_BUZZ_MIN", raising=False)
    cluster = _scored(CLUSTER_RAW, "gemini limits free users", 96)
    issue = _scored(
        {"source_type": "community_hackernews", "today_buzz_score": 10, "community_mention_score": 2232},
        "U.S. appeals court upholds designation of Anthropic as supply chain risk", 84,
    )
    assert _pipeline()._choose_selected_candidate([cluster, issue], {}) is issue


def test_biggest_issue_wins_among_issues(monkeypatch):
    monkeypatch.delenv("ISSUE_BUZZ_MIN", raising=False)
    mid = _scored({"today_buzz_score": 8, "community_mention_score": 825}, "OpenAI optics", 100)
    top = _scored({"today_buzz_score": 10, "community_mention_score": 2232}, "Anthropic ruling", 84)
    assert _pipeline()._choose_selected_candidate([mid, top], {}) is top


def test_small_news_still_loses_to_cluster(monkeypatch):
    monkeypatch.delenv("ISSUE_BUZZ_MIN", raising=False)
    cluster = _scored(CLUSTER_RAW, "gemini limits free users", 96)
    small = _scored({"source_type": "community_hackernews", "today_buzz_score": 4}, "Copilot+ PC brand is dead", 100)
    assert _pipeline()._choose_selected_candidate([small, cluster], {}) is cluster


def test_issue_first_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("ISSUE_BUZZ_MIN", "0")
    cluster = _scored(CLUSTER_RAW, "gemini limits free users", 96)
    issue = _scored({"today_buzz_score": 10}, "Anthropic ruling", 84)
    assert _pipeline()._choose_selected_candidate([cluster, issue], {}) is cluster


def test_only_big_issues_skip_entity_cooldown(monkeypatch):
    monkeypatch.delenv("ISSUE_BUZZ_MIN", raising=False)
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.setenv("ENTITY_COOLDOWN_APPLIES_TO_AI_BLOG_MODE", "true")
    big = _scored({"today_buzz_score": 10}, "Anthropic ruling")
    small = _scored({"today_buzz_score": 6}, "Anthropic minor update")
    assert TopicDedupService._is_entity_cooldown_exempt(big) is True
    assert TopicDedupService._is_entity_cooldown_exempt(small) is False
