"""에버그린 폴백의 엔티티 다양성 소프트 랭킹 테스트 (2026-07-23).

배경: 엔티티 쿨다운을 evergreen에서 면제(하드 차단 제거, 풀 전멸 방지)한
뒤에도, 완전히 무신경하면 같은 AI(ChatGPT 등)가 며칠 연속 뽑힐 수 있다
(사용자 피드백: "최근 3일내 같은 AI 업로드한거 제외하고 다른 AI 찾아서").
그래서 하드 차단 대신 소프트 랭킹을 추가했다 — 최근 발행 엔티티와 전부
겹치는 후보는 뒤로 밀리고, 다른 AI를 다루는 후보가 있으면 그게 우선한다.
풀이 전부 겹쳐도 탈락은 아니라(순서만 밀림) 2026-07-22 사고는 재발하지
않는다.
"""
from __future__ import annotations

from datetime import date, timedelta

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _scored(topic: str) -> ScoredNewsCandidate:
    nc = NewsCandidate(
        topic=topic,
        category="tech",
        summary="",
        source_hint="evergreen_fallback",
        published_at=None,
        url=None,
        raw={"source_type": "evergreen_fallback", "search_demand_topic": topic},
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
    pipeline = NewsPipeline.__new__(NewsPipeline)
    pipeline.dedup_service = TopicDedupService()
    return pipeline


def _published(topic: str, *, days_ago: int) -> dict:
    return {
        "date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "status": "published",
        "published": True,
        "selected_topic": topic,
    }


def test_topic_repeating_only_recent_entity_ranks_behind_fresh_entity() -> None:
    pipeline = _pipeline()
    chatgpt_again = _scored("ChatGPT resume writing tips")
    claude_fresh = _scored("Claude for legal contract review")
    recent_entities = frozenset({"openai"})  # ChatGPT/OpenAI covered in the last 3 days

    key_repeat = pipeline._evergreen_publish_fallback_sort_key(
        chatgpt_again,
        recent_evergreen_axes=[],
        preferred_axis="ai_automation",
        recent_entities=recent_entities,
    )
    key_fresh = pipeline._evergreen_publish_fallback_sort_key(
        claude_fresh,
        recent_evergreen_axes=[],
        preferred_axis="ai_automation",
        recent_entities=recent_entities,
    )
    assert key_fresh < key_repeat  # fresh entity sorts first


def test_no_entity_candidate_is_not_penalized() -> None:
    pipeline = _pipeline()
    generic = _scored("best AI tools for real estate agents")
    recent_entities = frozenset({"openai", "anthropic"})
    key = pipeline._evergreen_publish_fallback_sort_key(
        generic,
        recent_evergreen_axes=[],
        preferred_axis="ai_automation",
        recent_entities=recent_entities,
    )
    assert key[2] == 0  # entity_repeat_rank position


def test_all_candidates_repeat_entities_still_produces_an_order_not_a_block() -> None:
    # 풀이 전부 최근 엔티티와 겹쳐도(=진짜 새 AI가 없어도) 정렬만 될 뿐 제거되지 않는다.
    pipeline = _pipeline()
    a = _scored("ChatGPT free vs paid: what you actually get")
    b = _scored("OpenAI API cost for small business")
    recent_entities = frozenset({"openai"})
    ordered = sorted(
        [a, b],
        key=lambda item: pipeline._evergreen_publish_fallback_sort_key(
            item,
            recent_evergreen_axes=[],
            preferred_axis="ai_automation",
            recent_entities=recent_entities,
        ),
    )
    assert len(ordered) == 2  # 둘 다 살아있다 — 하드 차단 아님


def test_recent_published_entities_only_counts_published_within_window() -> None:
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=3)
    history = [
        _published("ChatGPT rolls out a new voice feature", days_ago=1),
        _published("Claude adds a new coding mode", days_ago=10),  # outside window
        {
            "date": date.today().isoformat(),
            "status": "blocked_by_quality_gate",
            "published": False,
            "selected_topic": "Gemini pricing overhaul",
        },
    ]
    entities = dedup.recent_published_entities(days=3, history_records=history)
    assert entities == {"openai"}


def test_candidate_entities_matches_extract_entities_on_subject_text() -> None:
    dedup = TopicDedupService()
    candidate = _scored("Claude vs ChatGPT for spreadsheet work")
    assert dedup.candidate_entities(candidate) == {"anthropic", "openai"}
