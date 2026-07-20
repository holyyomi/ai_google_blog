"""초안 발행이 스스로 삭제되던 버그의 회귀 테스트.

배경(2026-07-08 실측): NEWS_PUBLISH_AS_DRAFT=true로 실제 리허설을 돌리자,
Blogger가 초안 post의 url로 블로그 홈 URL을 돌려줬다. 그 홈 URL을 그대로
post_publish_audit의 라이브 fetch 감사에 넘기니, 감사가 '홈페이지에 있던
이전 글'과 새 후보 제목/슬러그를 비교해 필연적으로 전부 불일치가 났고
(published_title_mismatch, permalink_slug_mismatch, ai_topic_leaked_to_news_blog
등), 그 결과 방금 만든 초안이 자동 삭제됐다 — publish_draft 모드가 매번
자멸하는 구조였다.

수정: NewsPipeline._draft_review_result가 is_draft 발행 결과를 감지하면
라이브 fetch 감사를 아예 건너뛰고, Blogger 대시보드 편집 링크만 남긴 채
'draft_saved_for_review'로 종료한다. published/publish_succeeded는 정직하게
False로 둬서 dedup·재시도 루프가 이걸 실발행처럼 취급하지 않게 한다.
"""
from __future__ import annotations

from datetime import date, timedelta

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.news_publish_service import NewsPublishOutcome
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _make_pipeline() -> NewsPipeline:
    return NewsPipeline.__new__(NewsPipeline)


def test_live_outcome_returns_none_and_does_not_short_circuit() -> None:
    outcome = NewsPublishOutcome(
        post_id="1", post_url="https://holyyomiai.blogspot.com/2026/07/x.html",
        status="live", response_json={}, is_draft=False, dashboard_url="",
    )
    assert NewsPipeline._draft_review_result(outcome, topic="테스트 주제") is None


def test_draft_outcome_skips_audit_and_uses_dashboard_url() -> None:
    outcome = NewsPublishOutcome(
        post_id="999", post_url="https://holyyomiai.blogspot.com/",  # Blogger가 돌려주는 홈 URL(신뢰 불가)
        status="draft", response_json={}, is_draft=True,
        dashboard_url="https://www.blogger.com/blog/post/edit/123/999",
    )
    result = NewsPipeline._draft_review_result(outcome, topic="네이버 AI 검색 기능 설정")
    assert result is not None
    assert result["status"] == "draft_saved_for_review"
    assert result["blogger_url"] == "https://www.blogger.com/blog/post/edit/123/999"
    # 홈 URL이 감사나 결과 어디에도 새어나가지 않아야 한다 — 그게 원래 버그였다.
    assert "blogspot.com/" not in result["blogger_url"] or "post/edit" in result["blogger_url"]
    assert result["post_publish_audit"] == {"skipped": True, "reason": "draft_not_live_fetchable"}


def test_draft_outcome_reports_honest_not_published() -> None:
    """published/publish_succeeded가 정직하게 False여야 dedup·재시도가 오작동하지 않는다."""
    outcome = NewsPublishOutcome(
        post_id="1", post_url="https://holyyomiai.blogspot.com/",
        status="draft", response_json={}, is_draft=True,
        dashboard_url="https://www.blogger.com/blog/post/edit/1/1",
    )
    result = NewsPipeline._draft_review_result(outcome, topic="t")
    assert result["published"] is False
    assert result["publish_succeeded"] is False


def test_draft_status_not_in_retryable_set() -> None:
    """draft_saved_for_review는 재시도 대상이 아니어야 한다(구조적 버그라 재시도해도 안 고쳐짐)."""
    pipeline = _make_pipeline()
    pipeline.dry_run = False
    pipeline.news_publish_mode = "publish"
    assert pipeline._should_retry_publish_result({"status": "draft_saved_for_review"}) is False


def test_draft_status_not_treated_as_succeeded() -> None:
    assert NewsPipeline._publish_result_succeeded({"status": "draft_saved_for_review", "publish_succeeded": False}) is False


def test_draft_history_record_does_not_block_future_dedup() -> None:
    """초안 리허설 기록이 이후 실행의 dedup을 막으면 안 된다(실제 발행이 아니므로)."""
    dedup = TopicDedupService()
    draft_history_record = {
        "status": "draft_saved_for_review",
        "published": False,
        "publish_succeeded": False,
        "post_id": "999",
        "selected_topic": "네이버 AI 검색 기능 설정",
    }
    assert dedup.record_blocks_duplicate(draft_history_record) is False


# --- draft 소프트 소비 (2026-07-18 실측: 같은 주제가 3연속 재선택돼 고아 초안 3개) ---


def _scored(topic: str, *, raw: dict | None = None) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(topic=topic, category="ai", summary="", raw=raw or {}),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="",
    )


def _draft_record(topic: str, *, days_ago: int = 0) -> dict:
    return {
        "date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "status": "draft_saved_for_review",
        "published": False,
        "publish_succeeded": False,
        "post_id": "999",
        "selected_topic": topic,
    }


def test_draft_blocks_same_topic_within_48_hours() -> None:
    """draft_saved_for_review로 끝난 주제는 48시간 동안 재선택되면 안 된다."""
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    topic = "Notion AI meeting notes automation setup"
    assert dedup.is_duplicate(_scored(topic), [_draft_record(topic, days_ago=1)]) is True


def test_draft_does_not_block_same_topic_after_48_hours() -> None:
    """48시간이 지난 초안은 소프트 소비가 풀려 같은 주제를 다시 시도할 수 있다."""
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    topic = "Notion AI meeting notes automation setup"
    assert dedup.is_duplicate(_scored(topic), [_draft_record(topic, days_ago=3)]) is False


def test_draft_does_not_trigger_entity_cooldown() -> None:
    """초안은 엔티티(회사) 쿨다운의 근거가 아니다 — 같은 회사의 '다른' 주제는 통과."""
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    # 둘 다 naver 엔티티지만 키워드 겹침은 1개("검색") 이하 — 발행 기록이었다면
    # 엔티티 쿨다운으로 차단됐을 쌍(test_entity_cooldown_zero_disables_entity_rule 참고).
    candidate = _scored("클로바X 종료 후 검색 방향")
    draft = _draft_record("네이버 지도 리뷰 개편", days_ago=1)
    assert dedup.is_duplicate(candidate, [draft]) is False


def test_published_record_behavior_unchanged_by_draft_soft_consume() -> None:
    """발행 기록의 dedup·쿨다운 판정은 소프트 소비 도입 전과 동일해야 한다."""
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    published = {
        "date": (date.today() - timedelta(days=1)).isoformat(),
        "status": "published",
        "published": True,
        "selected_topic": "네이버 지도 리뷰 개편",
    }
    # 발행 기록은 같은 엔티티(naver)면 다른 주제라도 쿨다운 차단.
    assert dedup.is_duplicate(_scored("클로바X 종료 후 검색 방향"), [published]) is True
    # 창 밖(10일 전) 발행 기록은 통과.
    old_published = dict(published, date=(date.today() - timedelta(days=10)).isoformat())
    assert dedup.is_duplicate(_scored("클로바X 종료 후 검색 방향"), [old_published]) is False
    assert dedup.record_blocks_duplicate(published) is True


def test_dashboard_url_computed_only_for_draft() -> None:
    from blogspot_automation.services.news_publish_service import NewsPublishOutcome as _O
    live = _O(post_id="5", post_url="https://x/y.html", status="live", response_json={}, is_draft=False)
    assert live.dashboard_url == ""
