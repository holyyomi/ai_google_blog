from __future__ import annotations

from blogspot_automation.services.site_audit_service import classify_sitemap_url, render_audit_markdown


def test_classify_sitemap_url_flags_blogspot_auto_slug() -> None:
    item = classify_sitemap_url("https://holyyomiai.blogspot.com/2026/05/blog-post_23.html")

    assert item.risk_level == "high"
    assert item.action == "rewrite_or_unpublish"
    assert "weak_auto_permalink" in item.reasons


def test_classify_sitemap_url_flags_numeric_slug() -> None:
    item = classify_sitemap_url("https://holyyomiai.blogspot.com/2026/05/461-419.html")

    assert item.risk_level == "high"
    assert "weak_numeric_permalink" in item.reasons


def test_classify_sitemap_url_flags_ai_slug() -> None:
    item = classify_sitemap_url("https://holyyomiai.blogspot.com/2026/05/gemini-omni-ai.html")

    assert item.risk_level == "low"
    assert item.action == "keep"
    assert item.cleanup_bucket == "keep"
    assert "no_url_level_issue_detected" in item.reasons


def test_classify_sitemap_url_keeps_descriptive_ai_slug() -> None:
    item = classify_sitemap_url("https://holyyomiai.blogspot.com/2026/05/chatgpt-prompt-checklist.html")

    assert item.risk_level == "low"
    assert item.action == "keep"
    assert item.cleanup_bucket == "keep"


def test_render_audit_markdown_lists_risky_urls() -> None:
    payload = {
        "generated_at": "2026-05-26T00:00:00+00:00",
        "sitemap_url": "https://example.com/sitemap.xml",
        "summary": {"total_urls": 1, "high_risk_urls": 1, "medium_risk_urls": 0},
        "items": [
            {
                "risk_level": "high",
                "action": "rewrite_or_unpublish",
                "reasons": ["weak_auto_permalink"],
                "url": "https://example.com/2026/05/blog-post.html",
            }
        ],
    }

    md = render_audit_markdown(payload)

    assert "weak_auto_permalink" in md
    assert "blog-post.html" in md

