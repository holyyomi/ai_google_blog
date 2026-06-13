from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.services.topic_selection_service import (
    DefaultTopicSelectionService,
    PillarDiscoveryStrategy,
    ProviderFetchDebug,
    SourceArticle,
)
from blogspot_automation.storage import BlogWorkItemRepository, PublishStatus, SQLiteBlogStore


class RetryAwareProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        provider_type: str,
        pillar_name: str,
        query_group: str,
        query_text: str = "",
        success_terms: tuple[str, ...] = (),
        articles: list[SourceArticle] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.pillar_name = pillar_name
        self.query_group = query_group
        self.query_text = query_text
        self.url = f"https://retry.test/{provider_name}"
        self._success_terms = tuple(term.lower() for term in success_terms)
        self._articles = list(articles or [])

    def with_query(self, query_text: str, query_language: str) -> "RetryAwareProvider":
        return RetryAwareProvider(
            provider_name=f"{self.provider_name}-{query_language}",
            provider_type=self.provider_type,
            pillar_name=self.pillar_name,
            query_group=f"expanded_{query_language}",
            query_text=query_text,
            success_terms=self._success_terms,
            articles=self._articles,
        )

    def fetch_with_debug(self) -> tuple[list[SourceArticle], ProviderFetchDebug]:
        lowered = self.query_text.lower()
        success = not self._success_terms or any(term in lowered for term in self._success_terms)
        articles = list(self._articles) if success else []
        return articles, ProviderFetchDebug(
            provider_type=self.provider_type,
            provider_name=self.provider_name,
            source_url=self.url,
            query_text=self.query_text,
            fetch_status="success",
            parse_status="success",
            response_length=len(articles),
            parse_count=len(articles),
        )


class TopicRetryLoopTests(unittest.TestCase):
    def test_query_expansion_recovers_same_pillar(self) -> None:
        repo, temp_dir = _repo()
        try:
            service = DefaultTopicSelectionService(
                repository=repo,
                providers=[
                    RetryAwareProvider(
                        provider_name="ai-google",
                        provider_type="google_news_search_rss",
                        pillar_name="AI 부업 / 온라인 수익화 실전",
                        query_group="search_queries_en",
                        query_text="ai side hustle",
                        success_terms=("guide",),
                        articles=_articles("ai"),
                    )
                ],
                pillar_strategy_map={
                    "AI 부업 / 온라인 수익화 실전": PillarDiscoveryStrategy(
                        pillar_name="AI 부업 / 온라인 수익화 실전",
                        strategy_types=["hybrid_news_search", "official_source_driven"],
                        provider_priority=["google_news_search_rss", "rss_feed"],
                        query_groups=["search_queries_en"],
                        min_source_articles=3,
                        min_unique_domains=2,
                        query_expansion_en=["ai side hustle guide"],
                    )
                },
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
            self.assertGreaterEqual(result.retry_count, 1)
            self.assertTrue(
                "AI 부업 / 온라인 수익화 실전:duplicate_angle_retry" in result.retry_path
                or "AI 부업 / 온라인 수익화 실전:query_expansion" in result.retry_path
            )
            self.assertIn(result.fallback_strategy_used, {"query_expansion", "provider_mix_expansion"})
            self.assertIn("guide", " ".join(result.discovery_debug.get("final_selected_queries", [])))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_provider_mix_expansion_recovers_same_pillar(self) -> None:
        repo, temp_dir = _repo()
        try:
            service = DefaultTopicSelectionService(
                repository=repo,
                providers=[
                    RetryAwareProvider(
                        provider_name="daily-google",
                        provider_type="google_news_search_rss",
                        pillar_name="매일 새로운 부업 해부",
                        query_group="search_queries_en",
                        query_text="creator monetization",
                        success_terms=("never-match",),
                        articles=_articles("daily-google"),
                    ),
                    RetryAwareProvider(
                        provider_name="daily-rss",
                        provider_type="rss_feed",
                        pillar_name="매일 새로운 부업 해부",
                        query_group="rss_sources",
                        articles=_articles("daily-rss"),
                    ),
                ],
                pillar_strategy_map={
                    "매일 새로운 부업 해부": PillarDiscoveryStrategy(
                        pillar_name="매일 새로운 부업 해부",
                        strategy_types=["hybrid_news_search"],
                        provider_priority=["google_news_search_rss", "rss_feed"],
                        query_groups=["search_queries_en", "rss_sources"],
                        min_source_articles=3,
                        min_unique_domains=2,
                    )
                },
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
            self.assertTrue(
                "매일 새로운 부업 해부:duplicate_angle_retry" in result.retry_path
                or "매일 새로운 부업 해부:provider_mix_expansion" in result.retry_path
            )
            self.assertIn(result.fallback_strategy_used, {"query_expansion", "provider_mix_expansion"})
            self.assertTrue(
                any(attempt.get("retry_stage") in {"duplicate_angle_retry", "provider_mix_expansion"} for attempt in result.discovery_attempts)
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pillar_fallback_moves_to_evergreen_pillar(self) -> None:
        repo, temp_dir = _repo()
        try:
            service = DefaultTopicSelectionService(
                repository=repo,
                providers=[
                    RetryAwareProvider(
                        provider_name="stock-google",
                        provider_type="google_news_search_rss",
                        pillar_name="한국뉴스 기반 관심 한국주식 해설",
                        query_group="search_queries_en",
                        query_text="kospi filing",
                        success_terms=("never-match",),
                        articles=_articles("stock"),
                    ),
                    RetryAwareProvider(
                        provider_name="tax-evergreen",
                        provider_type="evergreen_source",
                        pillar_name="부업 세금 / N잡 세금",
                        query_group="evergreen_sources",
                        articles=_articles("tax"),
                    ),
                ],
                pillar_strategy_map={
                    "한국뉴스 기반 관심 한국주식 해설": PillarDiscoveryStrategy(
                        pillar_name="한국뉴스 기반 관심 한국주식 해설",
                        strategy_types=["news_driven"],
                        provider_priority=["google_news_search_rss"],
                        query_groups=["search_queries_en"],
                        min_source_articles=3,
                        min_unique_domains=2,
                        fallback_pillars=["side_hustle_tax"],
                    ),
                    "부업 세금 / N잡 세금": PillarDiscoveryStrategy(
                        pillar_name="부업 세금 / N잡 세금",
                        strategy_types=["evergreen_search", "official_source_driven"],
                        provider_priority=["evergreen_source", "official_newsroom"],
                        query_groups=["evergreen_sources"],
                        min_source_articles=3,
                        min_unique_domains=2,
                    ),
                },
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
            self.assertEqual(result.selected_pillar, "부업 세금 / N잡 세금")
            self.assertEqual(result.fallback_strategy_used, "pillar_fallback")
            self.assertEqual(result.fallback_pillar_used, "부업 세금 / N잡 세금")
            self.assertIn("부업 세금 / N잡 세금:initial", result.retry_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _repo() -> tuple[BlogWorkItemRepository, str]:
    temp_dir = tempfile.mkdtemp()
    return BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir))), temp_dir


def _articles(label: str) -> list[SourceArticle]:
    now = datetime.now(timezone.utc)
    return [
        SourceArticle(
            provider_name=f"{label}-provider-1",
            source_url=f"https://{label}1.test/feed",
            title=f"{label} workflow breakdown one",
            summary="This article explains concrete steps, cost, time, and risk for a practical execution workflow.",
            article_url=f"https://{label}1.test/article-1",
            published_at=(now - timedelta(hours=2)).isoformat(),
        ),
        SourceArticle(
            provider_name=f"{label}-provider-2",
            source_url=f"https://{label}2.test/feed",
            title=f"{label} workflow breakdown two",
            summary="This article compares realistic effort, setup order, and failure points with clear action steps.",
            article_url=f"https://{label}2.test/article-2",
            published_at=(now - timedelta(hours=3)).isoformat(),
        ),
        SourceArticle(
            provider_name=f"{label}-provider-3",
            source_url=f"https://{label}3.test/feed",
            title=f"{label} workflow breakdown three",
            summary="This article covers implementation details, expected timeline, and trustworthy source-backed cautions.",
            article_url=f"https://{label}3.test/article-3",
            published_at=(now - timedelta(hours=4)).isoformat(),
        ),
    ]


if __name__ == "__main__":
    unittest.main()
