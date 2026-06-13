from __future__ import annotations

from datetime import date

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.publish_history_service import PublishHistoryService
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _pipeline(tmp_path, *, dry_run: bool, news_publish_mode: str = "publish") -> NewsPipeline:
    return NewsPipeline(
        dry_run=dry_run,
        news_publish_mode=news_publish_mode,
        publish_history_service=PublishHistoryService(history_path=tmp_path / "publish_history.json"),
    )


def _scored_topic(topic: str) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(
            topic=topic,
            category="policy",
            summary="application details and eligibility checklist",
        ),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="high reader demand",
    )


def test_news_dry_run_does_not_append_publish_history(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, dry_run=True, news_publish_mode="dry_run")

    recorded = pipeline._try_record_history(
        status="dry_run_saved",
        result={
            "dry_run": True,
            "selected_topic": "dry run topic",
            "publish_succeeded": False,
        },
    )

    assert recorded is False
    assert pipeline.publish_history_service.load() == []


def test_news_blocked_result_appends_schedule_review_history(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")

    recorded = pipeline._try_record_history(
        status="blocked_by_quality_gate",
        result={
            "dry_run": False,
            "selected_topic": "blocked topic",
            "publish_succeeded": False,
            "publish_quality_gate": {
                "passed": False,
                "reader_value_score": 76,
                "article_focus_score": 62,
                "blocking_issues": ["article_focus_score_below_70"],
            },
            "auto_publish_gate": {
                "allowed": False,
                "blocking_reasons": ["publish_quality_gate_failed"],
            },
        },
    )

    records = pipeline.publish_history_service.load()
    assert recorded is True
    assert len(records) == 1
    assert records[0]["selected_topic"] == "blocked topic"
    assert records[0]["status"] == "blocked_by_quality_gate"
    assert records[0]["published"] is False
    assert records[0]["run_at"].endswith("+00:00")
    assert records[0]["quality_blocking_issues"] == ["article_focus_score_below_70"]
    assert "quality_gate_failed" in records[0]["learning_signals"]
    assert "auto_publish_blocked:publish_quality_gate_failed" in records[0]["learning_signals"]


def test_news_published_result_appends_publish_history(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")

    recorded = pipeline._try_record_history(
        status="published",
        result={
            "dry_run": False,
            "selected_topic": "published topic",
            "selected_title": "published title",
            "publish_succeeded": True,
            "url": "https://example.com/post",
            "publish_quality_gate": {"passed": True},
        },
    )

    records = pipeline.publish_history_service.load()
    assert recorded is True
    assert len(records) == 1
    assert records[0]["selected_topic"] == "published topic"
    assert records[0]["published"] is True
    assert records[0]["run_at"].endswith("+00:00")


def test_post_publish_audit_failure_records_unpublished_even_with_post_id(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")

    recorded = pipeline._try_record_history(
        status="blocked_by_post_publish_audit",
        result={
            "dry_run": False,
            "selected_topic": "deleted after audit",
            "selected_title": "deleted after audit title",
            "publish_succeeded": False,
            "post_id": "temporary-post-id",
            "post_url": "https://example.com/deleted",
            "post_publish_audit": {
                "passed": False,
                "issues": ["labels_missing"],
            },
        },
    )

    records = pipeline.publish_history_service.load()
    assert recorded is True
    assert records[0]["status"] == "blocked_by_post_publish_audit"
    assert records[0]["published"] is False


def test_topic_dedup_uses_selected_topic_from_publish_history_record() -> None:
    dedup_service = TopicDedupService(dedup_days=7)
    candidate = _scored_topic("driver license grant application")

    assert dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "driver license grant application",
            },
        ],
    )


def test_topic_dedup_uses_korean_selected_topic_with_candidate_context() -> None:
    dedup_service = TopicDedupService(dedup_days=7)
    candidate = _scored_topic("청주시 지원금 지급일과 신청방법 정리")

    assert dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "청주시 지원금 지급일과 신청방법 정리",
            },
        ],
    )


def test_topic_dedup_uses_korean_search_demand_topic_variant() -> None:
    dedup_service = TopicDedupService(dedup_days=7)
    candidate = ScoredNewsCandidate(
        candidate=NewsCandidate(
            topic="청주시 지원금",
            category="policy",
            summary="application details and eligibility checklist",
            raw={"search_demand_topic": "청주시 지원금 지급일과 신청방법 정리"},
        ),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="high reader demand",
    )

    assert dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "청주시 지원금 지급일과 신청방법 정리",
            },
        ],
    )


def test_topic_dedup_ignores_unpublished_history_attempt() -> None:
    dedup_service = TopicDedupService(dedup_days=7)
    candidate = _scored_topic("청주시 지원금 지급일과 신청방법 정리")

    assert not dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "skipped_duplicate",
                "published": False,
                "selected_topic": "청주시 지원금 지급일과 신청방법 정리",
            },
            {
                "date": date.today().isoformat(),
                "status": "blocked_by_quality_gate",
                "published": False,
                "selected_topic": "청주시 지원금 지급일과 신청방법 정리",
            },
        ],
    )


def test_topic_dedup_days_zero_disables_window() -> None:
    dedup_service = TopicDedupService(dedup_days=0)
    candidate = _scored_topic("driver license grant application")

    assert not dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "driver license grant application",
            },
        ],
    )


def test_topic_dedup_ignores_generic_support_intent_overlap() -> None:
    dedup_service = TopicDedupService(dedup_days=7)
    candidate = _scored_topic("고유가 피해지원금 지급일과 신청방법 정리")

    assert not dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "청년 운전면허 지원금 신청방법과 대상 조건",
            },
        ],
    )


def test_topic_dedup_keeps_specific_policy_duplicate_block() -> None:
    dedup_service = TopicDedupService(dedup_days=7)
    candidate = _scored_topic("청년 운전면허 지원금 지급일과 신청방법 정리")

    assert dedup_service.is_duplicate(
        candidate,
        [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "청년 운전면허 지원금 신청방법과 대상 조건",
            },
        ],
    )


def test_recent_duplicate_issue_checks_publish_history_service(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")
    pipeline.publish_history_service.append_record(
        {
            "date": date.today().isoformat(),
            "status": "published",
            "published": True,
            "selected_topic": "driver license grant application",
            "title": "Driver license grant checklist",
        }
    )

    assert (
        pipeline._recent_duplicate_issue(
            selected_topic="driver license grant application",
            selected_title="fresh title",
        )
        == "selected_topic_recently_published"
    )
    assert (
        pipeline._recent_duplicate_issue(
            selected_topic="fresh topic",
            selected_title="Driver license grant checklist",
        )
        == "selected_title_recently_published"
    )


def test_recent_duplicate_issue_ignores_unpublished_history(tmp_path) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")
    pipeline.publish_history_service.append_record(
        {
            "date": date.today().isoformat(),
            "status": "blocked_by_quality_gate",
            "published": False,
            "selected_topic": "blocked duplicate topic",
            "title": "Blocked duplicate title",
        }
    )

    assert (
        pipeline._recent_duplicate_issue(
            selected_topic="blocked duplicate topic",
            selected_title="fresh title",
        )
        == ""
    )


def test_manual_dedup_bypass_requires_workflow_dispatch_publish(tmp_path, monkeypatch) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("NEWS_MANUAL_DEDUP_BYPASS", "true")

    assert pipeline._manual_dedup_bypass_enabled() is True

    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert pipeline._manual_dedup_bypass_enabled() is False

    dry_run_pipeline = _pipeline(tmp_path, dry_run=True, news_publish_mode="publish")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert dry_run_pipeline._manual_dedup_bypass_enabled() is False


def test_manual_dedup_bypass_skips_recent_duplicate_issue(tmp_path, monkeypatch) -> None:
    pipeline = _pipeline(tmp_path, dry_run=False, news_publish_mode="publish")
    pipeline.publish_history_service.append_record(
        {
            "date": date.today().isoformat(),
            "status": "published",
            "published": True,
            "selected_topic": "same ai automation topic",
            "title": "Same AI Automation Title",
        }
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("NEWS_MANUAL_DEDUP_BYPASS", "true")

    assert (
        pipeline._recent_duplicate_issue(
            selected_topic="same ai automation topic",
            selected_title="Same AI Automation Title",
        )
        == ""
    )


def test_recent_records_published_only_filters_failed_attempts(tmp_path) -> None:
    service = PublishHistoryService(history_path=tmp_path / "publish_history.json")
    service.append_record(
        {
            "date": date.today().isoformat(),
            "status": "blocked_by_quality_gate",
            "published": False,
            "selected_topic": "blocked",
        }
    )
    service.append_record(
        {
            "date": date.today().isoformat(),
            "status": "published",
            "published": True,
            "selected_topic": "posted",
        }
    )

    recent = service.recent_records(limit=10, published_only=True)

    assert [record["selected_topic"] for record in recent] == ["posted"]


def test_recent_records_published_only_filters_dry_run_and_deleted_successes(tmp_path) -> None:
    service = PublishHistoryService(history_path=tmp_path / "publish_history.json")
    service.append_record(
        {
            "date": date.today().isoformat(),
            "run_at": "2026-06-11T00:05:17+00:00",
            "status": "trending_published",
            "published": False,
            "dry_run": True,
            "selected_topic": "deleted dry-run post",
            "note": "post_deleted_by_user (404, dereferenced 2026-06-11)",
        }
    )
    service.append_record(
        {
            "date": date.today().isoformat(),
            "run_at": "2026-06-11T08:13:00+00:00",
            "status": "trending_published",
            "published": True,
            "dry_run": False,
            "selected_topic": "live post",
        }
    )

    recent = service.recent_records(limit=10, published_only=True)

    assert [record["selected_topic"] for record in recent] == ["live post"]


def test_published_record_filter_rejects_post_publish_audit_failures() -> None:
    assert not PublishHistoryService.is_published_record(
        {
            "status": "published",
            "published": True,
            "post_publish_audit_passed": False,
            "selected_topic": "deleted after audit",
        }
    )


def test_published_record_filter_accepts_live_verified_audit_failure() -> None:
    assert PublishHistoryService.is_published_record(
        {
            "status": "trending_published",
            "published": True,
            "dry_run": True,
            "post_publish_audit_passed": False,
            "url_verified_status_code": 200,
            "live_url_verified": True,
            "selected_topic": "live but older structure",
        }
    )
