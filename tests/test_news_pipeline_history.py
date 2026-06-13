from __future__ import annotations

from blogspot_automation.pipelines.news_pipeline import NewsPipeline


def test_history_record_keeps_published_url_for_future_internal_links() -> None:
    record = NewsPipeline._build_history_record(
        status="published",
        result={
            "selected_title": "카카오 서비스 변경 전 확인할 조건",
            "selected_topic": "카카오 서비스 변경",
            "topic_group": "platform_issue",
            "content_angle": {"content_type": "platform_change"},
            "post_url": "https://holyeverymoments.blogspot.com/2026/05/kakao-service-news.html",
            "post_id": "post-1",
            "publish_quality_gate": {"passed": True},
        },
    )

    assert record["published"] is True
    assert record["url"].endswith("/kakao-service-news.html")
    assert record["post_id"] == "post-1"
