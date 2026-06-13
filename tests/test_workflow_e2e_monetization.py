from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.app import build_service_runtime
from blogspot_automation.config import Settings
from blogspot_automation.services.image_asset_service import GeneratedImageAsset
from blogspot_automation.services.topic_selection_service import (
    DefaultTopicSelectionService,
    InMemoryNewsProvider,
    SourceArticle,
)
from blogspot_automation.storage import PublishStatus


class MonetizationWorkflowE2ETests(unittest.TestCase):
    def test_end_to_end_workflow_from_topic_to_publish(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            runtime = build_service_runtime(
                root_dir=Path(temp_dir),
                settings=Settings(data_dir=Path(temp_dir), sqlite_path="data/test.db"),
                publish_client=_FakeBloggerClient(),
            )
            topic_service = DefaultTopicSelectionService(
                repository=runtime.work_repo,
                providers=[
                    InMemoryNewsProvider(
                        [
                            _article(
                                "AI 자동화 툴 확산, 온라인 수익화 실전 적용 늘었다",
                                "AI 자동화 툴을 바로 부업과 연결하는 실제 적용 흐름을 설명한다.",
                                "https://news.hankyung.com/article/202603180001",
                            ),
                            _article(
                                "챗GPT 템플릿 판매, 자동화 검수 체계가 수익 차이를 만든다",
                                "자동화와 검수의 분리 설계가 실제 수익화 효율을 높인다는 기사다.",
                                "https://www.mk.co.kr/news/it/11223344",
                            ),
                            _article(
                                "생성형 AI 워크플로, 1인 운영자가 먼저 확인할 체크포인트",
                                "실행 가능성과 검색 의도를 함께 봐야 한다는 실전 해설 기사다.",
                                "https://www.etnews.com/202603180002",
                            ),
                        ]
                    )
                ],
            )

            selected = topic_service.discover_and_select_today_topic()
            self.assertTrue(selected.article_pack)
            self.assertGreaterEqual(len(selected.article_pack.get("hard_facts", [])), 3)
            self.assertTrue(selected.article_pack.get("search_intent_guess"))
            brief = runtime.brief_service.generate_from_selected_topic(selected)
            package = runtime.package_service.build_package(work_item_id=selected.saved_work_item_id)
            image_result = runtime.image_service.process_cover_image(
                work_item_id=selected.saved_work_item_id,
                generation_provider=_FakeImageGenerationProvider(),
                hosting_provider=_FailingImageHostingProvider(),
                allow_publish_without_image=True,
            )
            qa_result = runtime.qa_service.qa_review(work_item_id=selected.saved_work_item_id)
            if qa_result.qa_result != "PASS":
                runtime.qa_service.refine(work_item_id=selected.saved_work_item_id)
                qa_result = runtime.qa_service.qa_review(work_item_id=selected.saved_work_item_id)
            publish_result = runtime.publish_service.publish(
                work_item_id=selected.saved_work_item_id,
                publish_mode="public",
                manual_soft_fail_approval=(qa_result.qa_result == "SOFT_FAIL"),
            )
            status = runtime.publish_service.get_publish_status(work_item_id=selected.saved_work_item_id)
            work_item = runtime.work_repo.get_by_id(selected.saved_work_item_id)

            self.assertEqual(selected.publish_status, PublishStatus.PLANNED.value)
            self.assertTrue(brief.brief_summary)
            self.assertEqual(brief.search_intent, selected.article_pack.get("search_intent_guess"))
            self.assertEqual(brief.content_density_status, "dense")
            self.assertTrue(brief.estimated_time_to_start)
            self.assertTrue(brief.potential_income_range)
            self.assertTrue(package.final_title)
            self.assertIn("실전 체크리스트", package.article_html)
            self.assertIn("준비물 / 시간 / 비용 / 예상수익", package.article_html)
            self.assertIn("FAQ", package.article_html)
            self.assertEqual(image_result.status, "fallback_branding_image")
            self.assertEqual(image_result.final_image_url, "")
            self.assertIn(qa_result.qa_result, {"PASS", "SOFT_FAIL"})
            self.assertEqual(publish_result.blog_post_id, "blogger-post-e2e")
            self.assertEqual(status["publish_status"], PublishStatus.PUBLISHED.value)
            self.assertIsNotNone(work_item)
            self.assertEqual(work_item.publish_status, PublishStatus.PUBLISHED.value)
            self.assertTrue(work_item.blog_url)
            self.assertEqual(work_item.content_density_status, "dense")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class _FakeImageGenerationProvider:
    def generate(self, *, prompt: str) -> GeneratedImageAsset:
        del prompt
        return GeneratedImageAsset(
            image_bytes=b"fake-image-bytes",
            mime_type="image/png",
            source_format="base64",
            raw_response={"data": [{"b64_json": "ZmFrZS1pbWFnZS1ieXRlcw=="}]},
        )


class _FailingImageHostingProvider:
    def upload(self, *, image_bytes: bytes, filename: str) -> str:
        del image_bytes, filename
        raise RuntimeError("hosting unavailable in test")


class _FakeBloggerClient:
    def publish_post(
        self,
        *,
        title: str,
        article_html: str,
        labels: list[str],
        meta_description: str = "",
        permalink_slug: str = "",
        is_draft: bool = False,
    ) -> dict[str, object]:
        del title, article_html, labels, meta_description, permalink_slug, is_draft
        return {
            "id": "blogger-post-e2e",
            "url": "https://example.blogspot.com/2026/03/e2e-post.html",
            "status": "LIVE",
            "title": "E2E Post",
        }


def _article(title: str, summary: str, url: str) -> SourceArticle:
    return SourceArticle(
        provider_name="test-provider",
        source_url="https://news.provider.local/rss",
        title=title,
        summary=summary,
        article_url=url,
        published_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    )


if __name__ == "__main__":
    unittest.main()
