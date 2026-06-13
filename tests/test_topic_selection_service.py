from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.pipelines import run_topic_selection_pipeline
from blogspot_automation.services.topic_selection_service import (
    DefaultTopicSelectionService,
    InMemoryNewsProvider,
    PillarDiscoveryStrategy,
    SourceArticle,
)
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    ContentPillar,
    PublishStatus,
    SQLiteBlogStore,
    create_sample_work_item,
)


class TopicSelectionServiceTests(unittest.TestCase):
    def test_selects_topic_only_when_three_real_articles_exist(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            service = DefaultTopicSelectionService(
                repository=repository,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article(
                                "AI workflow automation expands creator-side income options",
                                "A practical article about connecting AI workflow automation to monetization and side-income execution.",
                                "https://news.hankyung.com/article/202603180001",
                            ),
                            _article(
                                "ChatGPT workflow packaging improves sellable creator offers",
                                "This article explains repeatable AI workflow packaging for creator revenue and business offers.",
                                "https://www.mk.co.kr/news/it/11223344",
                            ),
                            _article(
                                "Content automation startup costs and review checkpoints",
                                "A hands-on source covering implementation details, cost control, and validation steps.",
                                "https://www.etnews.com/202603180002",
                            ),
                        ]
                    )
                ],
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
            self.assertEqual(result.source_quality_status, "sufficient")
            self.assertGreaterEqual(result.source_count, 3)
            self.assertGreaterEqual(len(result.source_domains), 2)
            self.assertEqual(result.raw_candidate_count, 3)
            self.assertEqual(result.parsed_candidate_count, 3)
            self.assertEqual(result.filtered_candidate_count, 3)
            self.assertEqual(result.final_discovery_status, "selected")
            self.assertTrue(result.discovery_debug.get("source_attempts"))
            self.assertEqual(len(result.title_candidates), 5)
            self.assertEqual(result.article_pack.get("selected_topic"), result.selected_topic)
            self.assertEqual(result.article_pack.get("source_count"), result.source_count)
            self.assertGreaterEqual(len(result.article_pack.get("hard_facts", [])), 3)
            self.assertGreaterEqual(len(result.article_pack.get("source_consensus", [])), 1)
            self.assertEqual(
                result.title_candidate_types,
                ["문제형", "초보형", "실행형", "비교형", "뉴스해설형"],
            )
            self.assertTrue(result.saved_work_item_id)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_marks_source_insufficient_when_real_articles_are_not_enough(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            service = DefaultTopicSelectionService(
                repository=repository,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article(
                                "Side hustle tax checklist before filing season",
                                "A tax checklist article with one valid source only.",
                                "https://www.joseilbo.com/news/htmls/2026/03/20260318123456.html",
                            ),
                            _article(
                                "N-job withholding tax basics",
                                "A second article exists but is still not enough to meet the minimum source requirement.",
                                "https://www.taxwatch.co.kr/article/tax-20260318-1",
                            ),
                        ]
                    )
                ],
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.SOURCE_INSUFFICIENT.value)
            self.assertIn("3", result.stop_reason)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_duplicate_recent_topic_is_blocked_as_planned_fail(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            existing = create_sample_work_item(item_id="published-001")
            existing.content_pillar = ContentPillar.AI_SIDE_HUSTLE.value
            existing.topic_title = "ai automation 흐름에서 찾은 AI 부업 실전 적용 포인트"
            existing.primary_keyword = "ai automation"
            existing.source_domains = ["news.hankyung.com", "www.mk.co.kr", "www.etnews.com"]
            existing.source_articles = [
                {"title": "AI workflow automation for side income one", "article_url": "https://news.hankyung.com/article/202603180111"},
                {"title": "AI workflow automation for side income two", "article_url": "https://www.mk.co.kr/news/it/99887766"},
                {"title": "AI workflow automation for side income three", "article_url": "https://www.etnews.com/202603180333"},
            ]
            existing.publish_status = PublishStatus.PUBLISHED.value
            repository.upsert(existing)

            service = DefaultTopicSelectionService(
                repository=repository,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article(
                                "AI workflow automation for side income one",
                                "A practical monetization article about AI workflow automation for side income.",
                                "https://news.hankyung.com/article/202603180111",
                            ),
                            _article(
                                "AI workflow automation for side income two",
                                "A second source covering the same AI workflow automation and monetization angle.",
                                "https://www.mk.co.kr/news/it/99887766",
                            ),
                            _article(
                                "AI workflow automation for side income three",
                                "A third source with the same business angle and source cluster.",
                                "https://www.etnews.com/202603180333",
                            ),
                        ]
                    )
                ],
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED_FAIL.value)
            self.assertIn("최근 30일", result.stop_reason)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pipeline_wrapper_returns_source_insufficient_without_providers(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            result = run_topic_selection_pipeline(root_dir=Path(temp_dir))
            self.assertEqual(result.publish_status, PublishStatus.SOURCE_INSUFFICIENT.value)
            self.assertTrue(result.saved_work_item_id)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ai_side_hustle_filters_out_generic_ai_articles(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            service = DefaultTopicSelectionService(
                repository=repository,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article(
                                "AI game development guide",
                                "A generic gaming article about AI tools for game scenes.",
                                "https://generic-ai.test/article-1",
                            ),
                            _article(
                                "AI medical research update",
                                "A research-focused update with no monetization or workflow angle.",
                                "https://generic-ai.test/article-2",
                            ),
                            _article(
                                "Model benchmark dataset release",
                                "A benchmark article about datasets and lab evaluation only.",
                                "https://generic-ai.test/article-3",
                            ),
                        ],
                        pillar_name=ContentPillar.AI_SIDE_HUSTLE.value,
                        provider_type="google_news_search_rss",
                    )
                ],
                pillar_strategy_map={
                    ContentPillar.AI_SIDE_HUSTLE.value: PillarDiscoveryStrategy(
                        pillar_name=ContentPillar.AI_SIDE_HUSTLE.value,
                        strategy_types=["hybrid_news_search", "official_source_driven"],
                        provider_priority=["google_news_search_rss"],
                        query_groups=["search_queries_en"],
                        min_source_articles=3,
                        min_unique_domains=2,
                    )
                },
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.SOURCE_INSUFFICIENT.value)
            self.assertTrue(
                "ai_generic_non_business_article" in result.reject_reason_summary
                or "ai_monetization_relevance_low" in result.reject_reason_summary
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_duplicate_logic_allows_similar_keyword_when_source_angle_differs(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            existing = create_sample_work_item(item_id="published-allow")
            existing.content_pillar = ContentPillar.AI_SIDE_HUSTLE.value
            existing.topic_title = "AI workflow automation breakdown for creators"
            existing.primary_keyword = "ai workflow"
            existing.source_domains = ["legacy-source.test"]
            existing.source_articles = [
                {"title": "Legacy creator workflow angle", "article_url": "https://legacy-source.test/1"}
            ]
            existing.publish_status = PublishStatus.PUBLISHED.value
            repository.upsert(existing)

            service = DefaultTopicSelectionService(
                repository=repository,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article(
                                "AI pricing workflow for freelance service offers",
                                "A monetization article about pricing, service packaging, and client delivery.",
                                "https://fresh-source-a.test/article-1",
                            ),
                            _article(
                                "Creator revenue workflow with AI review checklist",
                                "This one focuses on review steps, lead generation, and revenue workflow.",
                                "https://fresh-source-b.test/article-2",
                            ),
                            _article(
                                "AI side hustle packaging for agencies",
                                "A third source covers agency offer design and audience growth.",
                                "https://fresh-source-c.test/article-3",
                            ),
                        ]
                    )
                ],
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
            self.assertFalse(result.discovery_debug.get("duplicate_evaluation", {}).get("is_duplicate", False))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _article(title: str, summary: str, url: str) -> SourceArticle:
    return SourceArticle(
        provider_name="test-provider",
        source_url="https://news.provider.local/rss",
        title=title,
        summary=summary,
        article_url=url,
        published_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
    )


if __name__ == "__main__":
    unittest.main()
