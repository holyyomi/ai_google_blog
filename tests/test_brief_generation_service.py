from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.services import BlogBriefGenerationService, SelectedTopicResult
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    BriefRecordRepository,
    ContentPillar,
    PublishStatus,
    SQLiteBlogStore,
    create_sample_work_item,
)


class BriefGenerationServiceTests(unittest.TestCase):
    def test_generates_execution_focused_brief_with_density_fields(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            store = SQLiteBlogStore(Path(temp_dir))
            work_repo = BlogWorkItemRepository(store)
            brief_repo = BriefRecordRepository(store)
            item = create_sample_work_item(item_id="work-001", content_pillar=ContentPillar.AI_SIDE_HUSTLE)
            item.topic_title = "AI 자동화 흐름에서 찾은 AI 부업 실전 적용 포인트"
            item.primary_keyword = "AI 자동화"
            item.publish_status = PublishStatus.PLANNED.value
            work_repo.upsert(item)

            service = BlogBriefGenerationService(
                work_item_repository=work_repo,
                brief_repository=brief_repo,
            )
            result = service.generate_from_selected_topic(
                SelectedTopicResult(
                    selected_pillar=ContentPillar.AI_SIDE_HUSTLE.value,
                    selected_topic="AI 자동화 흐름에서 찾은 AI 부업 실전 적용 포인트",
                    why_selected="실제 기사 3건과 3개 도메인이 같은 흐름을 보여 선정했다.",
                    source_articles=[
                        {
                            "provider_name": "p1",
                            "source_url": "https://news.hankyung.com/rss",
                            "title": "AI 자동화 툴이 반복 업무 비용을 낮춘다",
                            "summary": "반복 업무 자동화가 부업 운영 비용을 낮춘다는 실전 기사다.",
                            "article_url": "https://news.hankyung.com/article/202603180001",
                            "published_at": "2026-03-17T00:00:00+00:00",
                        },
                        {
                            "provider_name": "p2",
                            "source_url": "https://www.mk.co.kr/rss",
                            "title": "챗GPT 템플릿 판매, 자동화 검수 체계가 수익 차이를 만든다",
                            "summary": "자동화와 사람 검수를 함께 설계해야 실제 수익화가 가능하다는 내용이다.",
                            "article_url": "https://www.mk.co.kr/news/it/11223344",
                            "published_at": "2026-03-17T01:00:00+00:00",
                        },
                        {
                            "provider_name": "p3",
                            "source_url": "https://www.etnews.com/rss",
                            "title": "생성형 AI 워크플로, 소규모 운영자가 먼저 보는 체크포인트",
                            "summary": "검색 의도와 자동화 적용 범위를 함께 봐야 한다는 기사다.",
                            "article_url": "https://www.etnews.com/202603180002",
                            "published_at": "2026-03-17T02:00:00+00:00",
                        },
                    ],
                    source_count=3,
                    source_domains=["news.hankyung.com", "www.mk.co.kr", "www.etnews.com"],
                    keyword_set={"primary_keyword": "AI 자동화", "secondary_keywords": ["템플릿", "반복 업무"]},
                    title_candidates=["a", "b", "c", "d", "e"],
                    title_candidate_types=["문제형", "초보형", "실행형", "비교형", "뉴스해설형"],
                    topic_score=88.0,
                    source_quality_status="sufficient",
                    publish_status=PublishStatus.PLANNED.value,
                    stop_reason="",
                    saved_work_item_id="work-001",
                )
            )

            self.assertTrue(result.brief_summary)
            self.assertTrue(result.reader_problem)
            self.assertTrue(result.why_now)
            self.assertGreaterEqual(len(result.key_takeaways), 3)
            self.assertGreaterEqual(len(result.hard_facts_from_sources), 4)
            self.assertGreaterEqual(len(result.source_consensus), 2)
            self.assertGreaterEqual(len(result.source_differences), 1)
            self.assertGreaterEqual(len(result.practical_actions), 3)
            self.assertTrue(result.estimated_time_to_start)
            self.assertTrue(result.estimated_cost_to_start)
            self.assertTrue(result.potential_income_range)
            self.assertTrue(result.difficulty_level)
            self.assertGreaterEqual(len(result.recommended_for), 1)
            self.assertGreaterEqual(len(result.not_recommended_for), 1)
            self.assertGreaterEqual(len(result.failure_points), 3)
            self.assertGreaterEqual(len(result.faq_items), 5)
            self.assertEqual(result.content_density_status, "dense")
            self.assertEqual(work_repo.get_by_id("work-001").publish_status, PublishStatus.GENERATED.value)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_blocks_brief_generation_for_source_insufficient_topic(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            store = SQLiteBlogStore(Path(temp_dir))
            work_repo = BlogWorkItemRepository(store)
            brief_repo = BriefRecordRepository(store)
            item = create_sample_work_item(item_id="work-002", content_pillar=ContentPillar.SIDE_HUSTLE_TAX)
            item.publish_status = PublishStatus.SOURCE_INSUFFICIENT.value
            work_repo.upsert(item)

            service = BlogBriefGenerationService(
                work_item_repository=work_repo,
                brief_repository=brief_repo,
            )

            with self.assertRaises(ValueError):
                service.generate_from_selected_topic(
                    SelectedTopicResult(
                        selected_pillar=ContentPillar.SIDE_HUSTLE_TAX.value,
                        selected_topic="N잡 세금 이슈로 보는 부업 세금 실수 방지 가이드",
                        why_selected="기사 수 부족",
                        source_articles=[
                            {
                                "provider_name": "tax",
                                "source_url": "https://www.joseilbo.com/rss",
                                "title": "N잡 세금 신고 체크포인트",
                                "summary": "기사 1건만 확보됐다.",
                                "article_url": "https://www.joseilbo.com/news/htmls/2026/03/20260318123456.html",
                                "published_at": "2026-03-17T00:00:00+00:00",
                            }
                        ],
                        source_count=1,
                        source_domains=["www.joseilbo.com"],
                        keyword_set={"primary_keyword": "N잡 세금", "secondary_keywords": ["신고"]},
                        title_candidates=["a", "b", "c", "d", "e"],
                        title_candidate_types=["문제형", "초보형", "실행형", "비교형", "뉴스해설형"],
                        topic_score=44.0,
                        source_quality_status="insufficient_source_count",
                        publish_status=PublishStatus.SOURCE_INSUFFICIENT.value,
                        stop_reason="실제 기사 부족",
                        saved_work_item_id="work-002",
                    )
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
