from __future__ import annotations

import json

from blogspot_automation.config.settings import Settings
from blogspot_automation.publishing.client import BloggerClient


def _settings() -> Settings:
    return Settings(
        blogger_client_id="client-id",
        blogger_client_secret="client-secret",
        blogger_refresh_token="refresh-token",
        blogger_blog_id="blog-1",
    )


def test_blogger_client_accepts_draft_url_before_title_patch(monkeypatch) -> None:
    client = BloggerClient(_settings())
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    calls: list[dict] = []
    responses = iter(
        [
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/",
                "status": "DRAFT",
            },
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/poll-politics-update-news-a1b2c3.html",
                "status": "LIVE",
            },
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/poll-politics-update-news-a1b2c3.html",
                "status": "LIVE",
            },
        ]
    )

    def fake_post_json_with_retry(**kwargs):
        calls.append(kwargs)
        return json.dumps(next(responses))

    monkeypatch.setattr(
        "blogspot_automation.publishing.client.post_json_with_retry",
        fake_post_json_with_retry,
    )

    result = client.publish_post(
        title="Korean final title",
        article_html="<article><p>Body</p></article>",
        labels=["news"],
        meta_description="Search description long enough for this Blogger publish test case.",
        permalink_slug="poll-politics-update-news-a1b2c3",
    )

    assert result["status"] == "LIVE"
    assert calls[1]["operation_name"] == "blogger_publish_draft"
    assert calls[2]["operation_name"] == "blogger_patch_title_after_permalink_seed"
    assert calls[2]["payload"]["title"] == "Korean final title"
    metadata = json.loads(calls[2]["payload"]["customMetaData"])
    assert metadata["description"].startswith("Search description long enough")
    assert metadata["searchDescription"] == metadata["description"]
    assert metadata["metaDescription"] == metadata["description"]
    assert metadata["itemprop:description"] == metadata["description"]


def test_blogger_client_warns_on_published_url_without_seeded_slug_before_title_patch(monkeypatch) -> None:
    client = BloggerClient(_settings())
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    calls: list[dict] = []
    responses = iter(
        [
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/",
                "status": "DRAFT",
            },
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/blog-post_23.html",
                "status": "LIVE",
            },
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/blog-post_23.html",
                "status": "LIVE",
            },
        ]
    )

    def fake_post_json_with_retry(**kwargs):
        calls.append(kwargs)
        return json.dumps(next(responses))

    monkeypatch.setattr(
        "blogspot_automation.publishing.client.post_json_with_retry",
        fake_post_json_with_retry,
    )

    result = client.publish_post(
        title="Korean final title",
        article_html="<article><p>Body</p></article>",
        labels=["news"],
        meta_description="Search description long enough for this Blogger publish test case.",
        permalink_slug="poll-politics-update-news-a1b2c3",
    )

    assert result["status"] == "LIVE"
    assert result["url"] == "https://holyeverymoments.blogspot.com/2026/05/blog-post_23.html"
    assert result["permalink_slug_matches"] is False
    assert "expected English permalink slug" in str(result["permalink_warning"])
    assert calls[1]["operation_name"] == "blogger_publish_draft"
    assert calls[2]["operation_name"] == "blogger_patch_title_after_permalink_seed"
    assert calls[2]["payload"]["title"] == "Korean final title"
    assert len(calls) == 3


def test_blogger_client_returns_permalink_and_search_description(monkeypatch) -> None:
    client = BloggerClient(_settings())
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    responses = iter(
        [
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/poll-politics-update-news-a1b2c3.html",
                "status": "LIVE",
            },
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/poll-politics-update-news-a1b2c3.html",
                "status": "DRAFT",
            },
            {
                "id": "post-1",
                "url": "https://holyeverymoments.blogspot.com/2026/05/poll-politics-update-news-a1b2c3.html",
                "status": "LIVE",
            },
        ]
    )

    def fake_post_json_with_retry(**kwargs):
        del kwargs
        return json.dumps(next(responses))

    monkeypatch.setattr(
        "blogspot_automation.publishing.client.post_json_with_retry",
        fake_post_json_with_retry,
    )

    result = client.publish_post(
        title="Korean final title",
        article_html="<article><p>Body</p></article>",
        labels=["news"],
        meta_description="Search description long enough for this Blogger publish test case.",
        permalink_slug="poll-politics-update-news-a1b2c3",
    )

    assert result["status"] == "LIVE"
    assert "poll-politics-update-news" in str(result["url"])
    assert result["permalink_slug"]
    assert result["permalink_slug_matches"] is True
    assert result["permalink_warning"] == ""
    assert result["search_description"]
