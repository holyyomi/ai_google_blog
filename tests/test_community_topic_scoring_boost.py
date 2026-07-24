"""CommunityTopicSignal이 news_scoring_service.score_candidates에 실제로
연결됐는지 검증 (2026-07-23).

배경: CommunityTopicSignal.score_topic_boost는 GoogleTrendsSignal과 동일한
구조로 이미 구현돼 있었지만 score_candidates에서 호출하는 코드가 없어서
한 번도 실행된 적이 없었다 — Reddit/HN 실제 토론량(mention_score)이 매일
수집되고도 스코어링에 전혀 반영되지 않아 커뮤니티 후보가 min_topic_score를
넘기 어려웠다(2026-07-23 실측: GHA 리허설에서 후보 33개 중 evergreen_fallback만
살아남음). 이 테스트는 실제 네트워크 호출 없이(mock) 그 연결선만 검증한다.
"""
from __future__ import annotations

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.community_topic_service import CommunityTopicSignal
from blogspot_automation.services.news_scoring_service import NewsScoringService


def _candidate(topic: str = "Claude agent workflow tips for busy teams") -> NewsCandidate:
    return NewsCandidate(
        topic=topic,
        category="today_issue",
        summary=topic,
        source_hint="community_hackernews",
        published_at=None,
        url=None,
        raw={
            "source_type": "community_hackernews",
            "topic_group": "ai_work",
            "content_angle": {"content_type": "ai_work_tip"},
            "is_stale": False,
        },
    )


def test_community_topic_boost_is_added_to_total_score(monkeypatch) -> None:
    monkeypatch.setattr(
        CommunityTopicSignal,
        "score_topic_boost",
        classmethod(lambda cls, text, max_boost=15: (12, ["claude", "agent"])),
    )
    sc = NewsScoringService()
    scored = sc.score_candidates([_candidate()])[0]
    assert scored.candidate.raw["community_topic_boost"] == 12
    assert scored.candidate.raw["community_topic_matched"] == ["claude", "agent"]


def test_no_community_boost_field_when_no_match(monkeypatch) -> None:
    monkeypatch.setattr(
        CommunityTopicSignal,
        "score_topic_boost",
        classmethod(lambda cls, text, max_boost=15: (0, [])),
    )
    sc = NewsScoringService()
    scored = sc.score_candidates([_candidate()])[0]
    assert "community_topic_boost" not in scored.candidate.raw


def test_community_boost_failure_is_non_fatal(monkeypatch) -> None:
    def _boom(cls, text, max_boost=15):
        raise RuntimeError("network down")

    monkeypatch.setattr(CommunityTopicSignal, "score_topic_boost", classmethod(_boom))
    sc = NewsScoringService()
    scored = sc.score_candidates([_candidate()])  # must not raise
    assert scored
