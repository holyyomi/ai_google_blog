"""임시글로 되돌린 글은 내부링크 후보에서 빠진다(2026-10-14 애드센스 정비)."""
import json

from blogspot_automation.services import seo_policy


def _record(url: str, title: str) -> dict:
    return {"url": url, "title": title, "published": True, "published_at": "2026-09-20T00:00:00Z"}


def test_retracted_post_is_not_linked(monkeypatch, tmp_path):
    retracted = "https://holyyomiai.blogspot.com/2026/09/gemini-free-api-limits-old.html"
    kept = "https://holyyomiai.blogspot.com/2026/09/gemini-free-api-limits-2026.html"
    path = tmp_path / "retracted_posts.json"
    path.write_text(json.dumps({"posts": [{"url": retracted}]}), encoding="utf-8")
    monkeypatch.setattr(seo_policy, "_RETRACTED_POSTS_PATH", path)
    seo_policy._retracted_post_urls.cache_clear()
    try:
        links = seo_policy.build_internal_links_from_history(
            [_record(retracted, "Gemini Free API Limits Explained"), _record(kept, "Gemini Free API Limits 2026")],
            current_title="Gemini API free tier rate limits",
            current_topic="gemini api limits",
        )
    finally:
        seo_policy._retracted_post_urls.cache_clear()
    urls = [url for _, url in links]
    assert retracted not in urls


def test_shipped_retracted_file_is_valid():
    seo_policy._retracted_post_urls.cache_clear()
    urls = seo_policy._retracted_post_urls()
    assert all(url.startswith("https://holyyomiai.blogspot.com/") for url in urls)
