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


def test_cover_image_url_from_env_prefers_ai_content_type_specific_url(monkeypatch) -> None:
    monkeypatch.setenv("AI_COVER_IMAGE_URL", "https://cdn.example.com/default.jpg")
    monkeypatch.setenv("AI_COVER_IMAGE_URL_AI_WORK_TIP", "https://cdn.example.com/ai-work.jpg")

    result = cover_image_url_from_env(content_type="ai_work_tip", topic_group="ai_work")

    assert result == "https://cdn.example.com/ai-work.jpg"


def test_cover_image_url_from_env_uses_default_fallback(monkeypatch) -> None:
    monkeypatch.delenv("AI_COVER_IMAGE_URL", raising=False)
    monkeypatch.delenv("NEWS_COVER_IMAGE_URL", raising=False)
    monkeypatch.setenv("AI_DEFAULT_COVER_IMAGE_URL", "https://cdn.example.com/default-ai-cover.png")

    result = cover_image_url_from_env(content_type="ai_work_tip", topic_group="ai_work")

    assert result == "https://cdn.example.com/default-ai-cover.png"


def test_cover_image_url_from_env_can_skip_default_fallback(monkeypatch) -> None:
    monkeypatch.delenv("AI_COVER_IMAGE_URL", raising=False)
    monkeypatch.delenv("NEWS_COVER_IMAGE_URL", raising=False)
    monkeypatch.setenv("AI_DEFAULT_COVER_IMAGE_URL", "https://cdn.example.com/default-ai-cover.png")

    result = cover_image_url_from_env(
        content_type="ai_work_tip",
        topic_group="ai_work",
        include_default=False,
    )

    assert result == ""


def test_cover_image_url_from_env_keeps_news_name_as_compatibility_fallback(monkeypatch) -> None:
    monkeypatch.delenv("AI_COVER_IMAGE_URL", raising=False)
    monkeypatch.delenv("AI_DEFAULT_COVER_IMAGE_URL", raising=False)
    monkeypatch.setenv("NEWS_COVER_IMAGE_URL", "https://cdn.example.com/legacy-news-cover.jpg")

    result = cover_image_url_from_env(content_type="ai_work_tip", topic_group="ai_work")

    assert result == "https://cdn.example.com/legacy-news-cover.jpg"
