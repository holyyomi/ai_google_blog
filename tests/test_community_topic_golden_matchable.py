"""커뮤니티 언급량 후보가 실제로 선정될 수 있는지 검증 (2026-07-23).

배경: community_topic_service에서 만든 NewsCandidate.raw에 topic_group/
content_angle이 없어서 golden_pattern_service.match_pattern(topic_group="")이
ai_work 패턴(모든 AI_BLOG_MODE 골든패턴이 요구하는 조합)과 절대 매칭될 수
없었다. 즉 "Reddit/HN에서 실제로 가장 많이 언급되는 AI" 신호가 매일 18~20개
수집되고도 선정 단계에서 전부 구조적으로 탈락하고 있었다(사용자 피드백:
"도구들을 고정하지 말고 매일 검색해서 가장 조회수 높을만한 주제를 찾아서
업로드"). topic_group 수정만으로는 부족했다 — 일반 헤드라인은 키워드 기반
휴리스틱 점수가 낮아(실측 37~53점) min_topic_score(75)를 못 넘었다.
discovery_engine 후보용 score floor(news_scoring_service)를 재사용해 실제
버즈량(community_mention_score 기반)이 높으면 문턱을 넘게 했다 — 실측: 오늘
실제 HN candidate 20개 중 12개가 publishable(>=75)로 전환됨(수정 전 0개).
"""
from __future__ import annotations

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.community_topic_service import CommunityTopicSignal
from blogspot_automation.services.golden_pattern_service import GoldenPatternService
from blogspot_automation.services.news_scoring_service import NewsScoringService
from blogspot_automation.utils.text_clip import clip_at_word_boundary as clip_wb


def test_community_candidate_shape_now_beats_golden_match_threshold() -> None:
    ps = GoldenPatternService()
    title = "New Claude Opus benchmark blows away GPT-5 on coding tasks"
    clipped = clip_wb(title, 90)

    # Before the fix, community candidates carried no topic_group/content_type
    # (exactly this call) and could never near_match an ai_work_tip pattern.
    unfixed = ps.match_pattern(topic=clipped, content_type="", topic_group="", summary="")
    assert not unfixed["matched"]
    assert not unfixed.get("topic_group_match")

    # After the fix, news_pipeline.py tags community candidates with
    # topic_group="ai_work" / content_type="ai_work_tip" — the same title now
    # clears both match dimensions and scores higher.
    fixed = ps.match_pattern(
        topic=clipped, content_type="ai_work_tip", topic_group="ai_work", summary=""
    )
    assert fixed["topic_group_match"]
    assert fixed["content_type_match"]
    assert fixed["confidence"] > unfixed["confidence"]


def _community_candidate(*, mention_score: int, buzz: int, specificity: int) -> NewsCandidate:
    topic = "OpenAI and Hugging Face address security incident during model evaluation"
    return NewsCandidate(
        topic=topic,
        category="today_issue",
        summary=topic,
        source_hint="hackernews",
        published_at=None,
        url=None,
        raw={
            "source_type": "community_hackernews",
            "community_mention_score": mention_score,
            "topic_group": "ai_work",
            "content_angle": {"content_type": "ai_work_tip"},
            "is_stale": False,
            "discovery_engine": True,
            "today_buzz_score": buzz,
            "entity_specificity_score": specificity,
            "safe_commentary_score": 6,
        },
    )


def test_high_buzz_community_candidate_clears_publish_threshold(monkeypatch) -> None:
    monkeypatch.setattr(
        CommunityTopicSignal,
        "score_topic_boost",
        classmethod(lambda cls, text, max_boost=15: (15, ["openai"])),
    )
    sc = NewsScoringService(min_topic_score=75)
    scored = sc.score_candidates([_community_candidate(mention_score=3769, buzz=10, specificity=7)])[0]
    assert scored.total_score >= 75


def test_low_buzz_community_candidate_does_not_get_an_unearned_floor(monkeypatch) -> None:
    monkeypatch.setattr(
        CommunityTopicSignal,
        "score_topic_boost",
        classmethod(lambda cls, text, max_boost=15: (0, [])),
    )
    sc = NewsScoringService(min_topic_score=75)
    scored = sc.score_candidates([_community_candidate(mention_score=10, buzz=4, specificity=6)])[0]
    assert scored.total_score < 75
