"""커뮤니티 언급량 후보가 실제로 golden-pattern에 매칭될 수 있는지 검증 (2026-07-23).

배경: community_topic_service에서 만든 NewsCandidate.raw에 topic_group/
content_angle이 없어서 golden_pattern_service.match_pattern(topic_group="")이
ai_work 패턴(모든 AI_BLOG_MODE 골든패턴이 요구하는 조합)과 절대 매칭될 수
없었다. 즉 "Reddit/HN에서 실제로 가장 많이 언급되는 AI" 신호가 매일 18~20개
수집되고도 선정 단계에서 전부 구조적으로 탈락하고 있었다(사용자 피드백:
"도구들을 고정하지 말고 매일 검색해서 가장 조회수 높을만한 주제를 찾아서
업로드"). news_pipeline.py의 community candidate 생성부에 topic_group="ai_work"
+ content_angle을 채워 이 경로를 살렸다.
"""
from __future__ import annotations

from blogspot_automation.services.golden_pattern_service import GoldenPatternService
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
