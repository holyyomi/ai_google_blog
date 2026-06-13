from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import tempfile
import unittest

from blogspot_automation.services.topic_selection_service import (
    GoogleNewsSearchRssProvider,
    build_google_news_rss_url,
    load_topic_discovery_runtime_config,
    load_default_topic_providers,
)


class TopicProviderLoadingTests(unittest.TestCase):
    def test_build_google_news_rss_url_supports_ko_and_en(self) -> None:
        ko_url = build_google_news_rss_url(query_text="AI 부업", query_language="ko")
        en_url = build_google_news_rss_url(query_text="AI side hustle", query_language="en")

        self.assertIn("news.google.com/rss/search", ko_url)
        self.assertIn("hl=ko", ko_url)
        self.assertIn("gl=KR", ko_url)
        self.assertIn("ceid=KR:ko", ko_url)
        self.assertIn("hl=en-US", en_url)
        self.assertIn("gl=US", en_url)

    def test_runtime_config_loads_google_and_feed_providers(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "config" / "monetization_topic_sources.json").write_text(
                json.dumps(
                    {
                        "discovery_settings": {
                            "min_source_articles": 3,
                            "min_unique_domains": 2,
                            "enable_test_mode": False,
                            "enable_test_mode_env": "BLOG_DISCOVERY_TEST_MODE",
                            "test_mode_thresholds": {
                                "min_source_articles": 2,
                                "min_unique_domains": 1,
                            },
                        },
                        "pillar_sources": {
                            "ai_side_hustle": {
                                "search_queries_ko": ["AI 부업"],
                                "search_queries_en": ["AI side hustle"],
                                "rss_sources": [
                                    {
                                        "provider_name": "itworld",
                                        "url": "https://www.itworld.co.kr/rss/all.xml",
                                        "provider_type": "rss_feed",
                                    }
                                ],
                                "official_sources": [
                                    {
                                        "provider_name": "openai",
                                        "url": "https://openai.com/news/rss.xml",
                                        "provider_type": "official_blog",
                                    }
                                ],
                                "evergreen_sources": [
                                    {
                                        "provider_name": "huggingface",
                                        "url": "https://huggingface.co/blog/feed.xml",
                                        "provider_type": "evergreen_source",
                                    }
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            runtime = load_topic_discovery_runtime_config(root)

            self.assertEqual(runtime.min_source_articles, 3)
            self.assertEqual(runtime.min_unique_domains, 2)
            self.assertFalse(runtime.test_mode_enabled)
            self.assertEqual(len(runtime.providers), 5)
            self.assertTrue(any(isinstance(provider, GoogleNewsSearchRssProvider) for provider in runtime.providers))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_runtime_config_supports_test_mode_thresholds(self) -> None:
        temp_dir = tempfile.mkdtemp()
        previous = os.environ.get("BLOG_DISCOVERY_TEST_MODE")
        os.environ["BLOG_DISCOVERY_TEST_MODE"] = "1"
        try:
            root = Path(temp_dir)
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "config" / "monetization_topic_sources.json").write_text(
                json.dumps(
                    {
                        "discovery_settings": {
                            "min_source_articles": 3,
                            "min_unique_domains": 2,
                            "enable_test_mode": False,
                            "enable_test_mode_env": "BLOG_DISCOVERY_TEST_MODE",
                            "test_mode_thresholds": {
                                "min_source_articles": 2,
                                "min_unique_domains": 1,
                            },
                        },
                        "pillar_sources": {},
                    }
                ),
                encoding="utf-8",
            )

            runtime = load_topic_discovery_runtime_config(root)

            self.assertTrue(runtime.test_mode_enabled)
            self.assertEqual(runtime.min_source_articles, 2)
            self.assertEqual(runtime.min_unique_domains, 1)
        finally:
            if previous is None:
                os.environ.pop("BLOG_DISCOVERY_TEST_MODE", None)
            else:
                os.environ["BLOG_DISCOVERY_TEST_MODE"] = previous
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_mk_rss_urls_are_sanitized_to_www_domain(self) -> None:
        providers = load_default_topic_providers(Path.cwd())
        mk_urls = [str(getattr(provider, "url", "")) for provider in providers if "mk" in str(getattr(provider, "provider_name", ""))]
        self.assertTrue(mk_urls)
        self.assertTrue(all("rss.mk.co.kr" not in url for url in mk_urls))
        self.assertTrue(all("www.mk.co.kr/rss/" in url for url in mk_urls))


if __name__ == "__main__":
    unittest.main()
