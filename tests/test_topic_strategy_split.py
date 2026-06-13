from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.services.topic_selection_service import (
    DefaultTopicSelectionService,
    InMemoryNewsProvider,
    PillarDiscoveryStrategy,
    SourceArticle,
)
from blogspot_automation.storage import BlogWorkItemRepository, ContentPillar, PublishStatus, SQLiteBlogStore


class TopicStrategySplitTests(unittest.TestCase):
    def test_each_top5_pillar_uses_its_own_strategy_plan(self) -> None:
        cases = [
            (
                ContentPillar.DAILY_SIDE_HUSTLE.value,
                ["hybrid_news_search"],
                [
                    _article("부업 수익화 흐름 점검", "온라인 부업 수익화 흐름과 실행 포인트를 정리한 기사입니다.", "https://news.hankyung.com/article/1"),
                    _article("N잡 사례 분석", "N잡 수익 구조를 실제 사례로 설명한 기사입니다.", "https://www.mk.co.kr/news/2"),
                    _article("온라인 부업 실전 체크", "온라인 부업을 바로 실행할 때 필요한 체크포인트를 담은 기사입니다.", "https://www.etnews.com/3"),
                ],
            ),
            (
                ContentPillar.KOREAN_STOCK_NEWS.value,
                ["news_driven"],
                [
                    _article("코스피 실적 이슈", "국내 증시 실적과 공시 이슈를 설명한 기사입니다.", "https://www.yna.co.kr/view/1"),
                    _article("반도체 공시 해설", "반도체 종목 공시 배경을 해설한 기사입니다.", "https://www.mk.co.kr/news/stock/2"),
                    _article("증시 변동성 점검", "오늘 한국 증시 변동성을 정리한 기사입니다.", "https://news.hankyung.com/article/3"),
                ],
            ),
            (
                ContentPillar.AI_SIDE_HUSTLE.value,
                ["hybrid_news_search", "official_source_driven"],
                [
                    _article("AI 자동화 수익화", "AI 자동화 수익화 사례를 담은 기사입니다.", "https://openai.com/news/1"),
                    _article("챗GPT 부업 실전", "챗GPT를 부업에 적용하는 실전 사례 기사입니다.", "https://www.itworld.co.kr/news/2"),
                    _article("생성형 AI 운영", "생성형 AI 운영과 수익화 워크플로를 다룬 기사입니다.", "https://huggingface.co/blog/3"),
                ],
            ),
            (
                ContentPillar.SIDE_HUSTLE_TAX.value,
                ["evergreen_search", "official_source_driven"],
                [
                    _article("부업 세금 신고 체크", "부업 세금 신고 기준을 정리한 상시형 기사입니다.", "https://www.moef.go.kr/article/1"),
                    _article("N잡 종합소득세", "N잡 종합소득세 신고 포인트를 설명한 기사입니다.", "https://www.nts.go.kr/article/2"),
                    _article("부업 세금 기준", "부업 세금 기준과 신고 시점을 안내한 기사입니다.", "https://www.taxwatch.co.kr/article/3"),
                ],
            ),
            (
                ContentPillar.KOREAN_STOCK_BEGINNER.value,
                ["evergreen_search"],
                [
                    _article("주식 초보 가이드", "주식 초보가 계좌부터 이해할 수 있게 돕는 가이드 기사입니다.", "https://www.investopedia.com/article/1"),
                    _article("ETF 초보 체크리스트", "ETF 초보가 꼭 알아야 할 개념을 정리한 글입니다.", "https://www.yna.co.kr/view/2"),
                    _article("국내주식 입문 가이드", "국내주식 입문 순서를 설명한 기사입니다.", "https://news.hankyung.com/article/3"),
                ],
            ),
        ]

        for pillar_name, strategy_types, articles in cases:
            with self.subTest(pillar_name=pillar_name):
                temp_dir = tempfile.mkdtemp()
                try:
                    repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
                    service = DefaultTopicSelectionService(
                        repository=repository,
                        providers=[
                            InMemoryNewsProvider(
                                articles,
                                pillar_name=pillar_name,
                                query_group="test_group",
                            )
                        ],
                        pillar_strategy_map={
                            pillar_name: PillarDiscoveryStrategy(
                                pillar_name=pillar_name,
                                strategy_types=strategy_types,
                                provider_priority=["in_memory"],
                                query_groups=["test_group"],
                                min_source_articles=3,
                                min_unique_domains=2,
                            )
                        },
                    )

                    result = service.discover_and_select_today_topic()

                    self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
                    self.assertEqual(result.selected_pillar, pillar_name)
                    self.assertEqual(result.discovery_debug.get("selected_strategy_type"), strategy_types)
                    self.assertEqual(result.discovery_debug.get("query_group"), ["test_group"])
                    self.assertEqual(result.raw_candidate_count, 3)
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)


def _article(title: str, summary: str, url: str) -> SourceArticle:
    return SourceArticle(
        provider_name="strategy-test",
        source_url="https://strategy.test/rss",
        title=title,
        summary=summary,
        article_url=url,
        published_at=(datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
    )


if __name__ == "__main__":
    unittest.main()
