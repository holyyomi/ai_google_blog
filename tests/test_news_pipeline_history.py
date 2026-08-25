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


def test_history_record_stores_normalized_section_headings_from_quality_gate() -> None:
    record = NewsPipeline._build_history_record(
        status="published",
        result={
            "selected_title": "Claude Code team setup",
            "selected_topic": "Claude Code team setup",
            "topic_group": "ai_work",
            "content_angle": {"content_type": "ai_work_tip"},
            "publish_quality_gate": {
                "passed": True,
                "section_headings": [
                    "Claude Code Install Limits",
                    "  Team Setup Risks  ",
                ],
            },
            "publish_succeeded": True,
        },
    )

    assert record["section_headings"] == [
        "claude code install limits",
        "team setup risks",
    ]


def test_history_record_extracts_section_headings_from_html_fallback() -> None:
    record = NewsPipeline._build_history_record(
        status="published",
        result={
            "selected_title": "Claude Code team setup",
            "selected_topic": "Claude Code team setup",
            "topic_group": "ai_work",
            "content_angle": {"content_type": "ai_work_tip"},
            "article_html": (
                "<h2>Claude Code Install Limits</h2>"
                "<h2>Team <em>Setup</em> Risks</h2>"
            ),
            "publish_quality_gate": {"passed": True},
            "publish_succeeded": True,
        },
    )

    assert record["section_headings"] == [
        "claude code install limits",
        "team setup risks",
    ]
