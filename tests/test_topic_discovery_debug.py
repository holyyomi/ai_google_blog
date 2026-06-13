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
    SourceArticle,
)
from blogspot_automation.storage import BlogWorkItemRepository, PublishStatus, SQLiteBlogStore


class TopicDiscoveryDebugTests(unittest.TestCase):
    def test_debug_fields_are_returned_for_successful_selection(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repository = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            service = DefaultTopicSelectionService(
                repository=repository,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article("AI 자동화 부업 적용 확산", "자동화 기반 부업 적용 사례가 늘고 있다는 기사입니다.", "https://news.hankyung.com/article/202603180001"),
                            _article("챗GPT 판매 자동화 검색 체계", "검색 체계 설계가 실제 수익 차이를 만든다는 기사입니다.", "https://www.mk.co.kr/news/it/11223344"),
                            _article("생성형 AI 운영 체크포인트", "실행 가능성과 검증 난이도를 함께 봐야 한다는 기사입니다.", "https://www.etnews.com/202603180002"),
                        ]
                    )
                ],
            )

            result = service.discover_and_select_today_topic()

            self.assertEqual(result.publish_status, PublishStatus.PLANNED.value)
            self.assertEqual(result.raw_candidate_count, 3)
            self.assertEqual(result.parsed_candidate_count, 3)
            self.assertEqual(result.filtered_candidate_count, 3)
            self.assertEqual(result.final_discovery_status, "selected")
            self.assertEqual(len(result.discovery_debug.get("source_attempts", [])), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_debug_fields_show_no_provider_failure(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            result = run_topic_selection_pipeline(root_dir=Path(temp_dir))

            self.assertEqual(result.publish_status, PublishStatus.SOURCE_INSUFFICIENT.value)
            self.assertEqual(result.final_discovery_status, PublishStatus.SOURCE_INSUFFICIENT.value)
            self.assertEqual(result.discovery_debug.get("attempted_strategy_type"), "no_provider_configured")
            self.assertEqual(result.raw_candidate_count, 0)
            self.assertEqual(result.parsed_candidate_count, 0)
            self.assertEqual(result.filtered_candidate_count, 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _article(title: str, summary: str, url: str) -> SourceArticle:
    return SourceArticle(
        provider_name="test-provider",
        source_url="https://news.provider.local/rss",
        title=title,
        summary=f"{summary} monetization workflow creator revenue business pricing",
        article_url=url,
        published_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    )


if __name__ == "__main__":
    unittest.main()
