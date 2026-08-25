from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from blogspot_automation.services.news_quality_gate import NewsQualityGate


@pytest.fixture
def en_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")


def test_stock_heading_warning_after_three_reused_headings(en_mode) -> None:
    html = (
        "<h2>Where beginners get stuck</h2>"
        "<h2>Worked example</h2>"
        "<h2>Bottom line first</h2>"
    )

    assert NewsQualityGate._stock_heading_warnings(html) == ["stock_headings_reused:3"]


def test_stock_heading_warning_ignores_single_reused_heading(en_mode) -> None:
    html = (
        "<h2>Where beginners get stuck</h2>"
        "<h2>Claude Code install limits</h2>"
        "<h2>Team setup risks</h2>"
    )

    assert NewsQualityGate._stock_heading_warnings(html) == []


def test_heading_overlap_recent_posts_warns_above_half(en_mode) -> None:
    records = [
        {
            "section_headings": [
                "claude code install limits",
                "team setup risks",
                "pricing checks before rollout",
                "data handling settings",
            ],
            "published": True,
        }
    ]

    with patch(
        "blogspot_automation.services.publish_history_service.PublishHistoryService.recent_records",
        return_value=records,
    ) as recent_records:
        result = NewsQualityGate._headings_overlap_recent_posts(
            [
                "Claude Code install limits",
                "Team setup risks",
                "Pricing checks before rollout",
                "Data handling settings",
                "Workspace policy rollout",
            ]
        )

    recent_records.assert_called_once_with(limit=5, published_only=True)
    assert result["overlap"] is True
    assert result["pct"] == 80


def test_heading_overlap_recent_posts_ignores_low_overlap(en_mode) -> None:
    with patch(
        "blogspot_automation.services.publish_history_service.PublishHistoryService.recent_records",
        return_value=[{"section_headings": ["claude code install limits"]}],
    ):
        result = NewsQualityGate._headings_overlap_recent_posts(
            [
                "Claude Code install limits",
                "Team setup risks",
                "Pricing checks before rollout",
                "Data handling settings",
                "Workspace policy rollout",
            ]
        )

    assert result["overlap"] is False
    assert result["pct"] == 20


def test_heading_overlap_recent_posts_no_history_no_warning(en_mode) -> None:
    with patch(
        "blogspot_automation.services.publish_history_service.PublishHistoryService.recent_records",
        return_value=[],
    ):
        result = NewsQualityGate._headings_overlap_recent_posts(["Claude Code install limits"])

    assert result["overlap"] is False
    assert result["pct"] == 0
    assert result["compared_records"] == 0


def test_heading_reuse_checks_disabled_in_korean_mode(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    html = (
        "<h2>Where beginners get stuck</h2>"
        "<h2>Worked example</h2>"
        "<h2>Bottom line first</h2>"
    )

    assert NewsQualityGate._stock_heading_warnings(html) == []
    assert NewsQualityGate._headings_overlap_recent_posts(["Where beginners get stuck"])["overlap"] is False


def test_recent_heading_overlap_warning_does_not_add_blocking_issue(en_mode) -> None:
    gate = NewsQualityGate()
    html = (
        "<h1>Claude Code team setup</h1>"
        "<h2>Claude Code install limits</h2><p>Body.</p>"
        "<h2>Team setup risks</h2><p>Body.</p>"
        "<h2>Pricing checks before rollout</h2><p>Body.</p>"
    )

    selected = _make_selected()
    with patch.object(
        NewsQualityGate,
        "_headings_overlap_recent_posts",
        return_value={
            "overlap": False,
            "ratio": 0.0,
            "pct": 0,
            "shared_headings": [],
            "compared_records": 1,
        },
    ):
        baseline = gate.evaluate(
            selected=selected,
            selected_title="Claude Code team setup",
            html=html,
            dry_run=False,
            news_publish_mode="publish",
        )

    with patch.object(
        NewsQualityGate,
        "_headings_overlap_recent_posts",
        return_value={
            "overlap": True,
            "ratio": 0.8,
            "pct": 80,
            "shared_headings": ["claude code install limits"],
            "compared_records": 1,
        },
    ):
        overlapped = gate.evaluate(
            selected=selected,
            selected_title="Claude Code team setup",
            html=html,
            dry_run=False,
            news_publish_mode="publish",
        )

    assert "headings_overlap_recent_posts:80" in overlapped["warnings"]
    assert baseline["blocking_issues"] == overlapped["blocking_issues"]


def _make_selected():
    raw = {
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
        "source_type": "google_news_rss",
        "click_potential_score": 10,
        "hook_angle": {"safe_title_keyword": "claude code"},
        "image_prompt": "Claude Code team setup screen",
        "image_alt_text": "Claude Code team setup",
        "is_test_candidate": False,
        "publish_allowed": True,
    }
    candidate = MagicMock()
    candidate.topic = "Claude Code team setup"
    candidate.category = "ai_work"
    candidate.summary = "Team setup notes"
    candidate.raw = raw
    selected = MagicMock()
    selected.total_score = 80
    selected.candidate = candidate
    selected.reason = "test"
    return selected


def test_stock_heading_variants_are_detected(monkeypatch):
    """접미/접두가 붙은 변형도 상투어다.

    2026-08-25 실측: "Where beginners get stuck with GPT-5.6",
    "A little-known tip for routing across tiers"처럼 한두 마디를 덧붙인 형태가
    흔했고, 정확·접두 일치만 보던 초기 구현은 상투어 7개를 달고 있는 글 2편을
    통째로 놓쳤다.
    """
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    html = (
        "<div class='post-body'>"
        "<h2>Where beginners get stuck with GPT-5.6</h2><p>a</p>"
        "<h2>A little-known tip for routing across tiers</h2><p>b</p>"
        "<h2>What stays the same and what remains unconfirmed</h2><p>c</p>"
        "</div>"
    )
    assert NewsQualityGate._stock_heading_warnings(html) == ["stock_headings_reused:3"]


def test_topic_specific_headings_are_not_flagged(monkeypatch):
    """주제어가 든 소제목은 반복이 아니라 그 글의 내용이다."""
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    html = (
        "<div class='post-body'>"
        "<h2>Claude Code skills pricing</h2><p>a</p>"
        "<h2>How to install the marketplace</h2><p>b</p>"
        "<h2>Which plans include agent mode</h2><p>c</p>"
        "</div>"
    )
    assert NewsQualityGate._stock_heading_warnings(html) == []
