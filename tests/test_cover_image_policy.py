from __future__ import annotations

from blogspot_automation.services.cover_image_policy import (
    cover_image_coverage,
    cover_image_url_from_env,
    ensure_cover_image_html,
)


def test_ensure_cover_image_html_inserts_public_image_after_h1() -> None:
    html = "<article><h1>Today issue checklist</h1><p>Body</p></article>"

    result = ensure_cover_image_html(
        html,
        image_url="https://cdn.example.com/news-cover.jpg",
        alt_text="Today issue cover",
        title="Today issue checklist",
    )

    assert '<figure class="news-cover-image"' in result
    assert '<img src="https://cdn.example.com/news-cover.jpg"' in result
    assert result.index("</h1>") < result.index("news-cover-image")
    coverage = cover_image_coverage(result)
    assert coverage["cover_image_present"]
    assert coverage["cover_image_public_url"]


def test_ensure_cover_image_html_does_not_duplicate_existing_image() -> None:
    html = '<article><h1>Title</h1><img src="https://cdn.example.com/existing.jpg" alt="x"></article>'

    result = ensure_cover_image_html(
        html,
        image_url="https://cdn.example.com/news-cover.jpg",
        alt_text="Cover",
        title="Title",
    )

    assert result.count("<img") == 1
    assert "existing.jpg" in result


def test_ensure_cover_image_html_ignores_non_public_url() -> None:
    html = "<article><h1>Title</h1><p>Body</p></article>"

    result = ensure_cover_image_html(
        html,
        image_url="data:image/svg+xml,abc",
        alt_text="Cover",
        title="Title",
    )

    assert result == html
    assert not cover_image_coverage(result)["cover_image_present"]


def test_cover_image_url_from_env_prefers_content_type_specific_url(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_COVER_IMAGE_URL", "https://cdn.example.com/default.jpg")
    monkeypatch.setenv("NEWS_COVER_IMAGE_URL_TODAY_ISSUE_EXPLAINER", "https://cdn.example.com/today.jpg")

    result = cover_image_url_from_env(content_type="today_issue_explainer", topic_group="today_issue")

    assert result == "https://cdn.example.com/today.jpg"
