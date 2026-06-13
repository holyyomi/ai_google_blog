from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.pipeline.service import run_full_pipeline
from blogspot_automation.storage import StateStore
from test_qa_flow import _FakeChatClient, _FailingImageClient, _sample_topic_candidate, _seed_fact_pack
from test_publishing import FakeBloggerClient


class PipelineTests(unittest.TestCase):
    def test_run_full_pipeline_dry_run_only_returns_summary(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate()])
            _seed_fact_pack(store, "topic-flow")

            result = run_full_pipeline(
                topic_id="topic-flow",
                store=store,
                settings=settings,
                dry_run_only=True,
                auto_approve=True,
                content_client=_FakeChatClient(),
                image_client=_FailingImageClient(),
            )

            self.assertEqual(result.topic_id, "topic-flow")
            self.assertEqual(result.status, "dry_run_completed")
            self.assertIsNotNone(result.final_title)
            self.assertIsNotNone(result.meta_description)
            self.assertTrue(result.publish_ready_html_path.endswith("publish_ready.html"))
            self.assertTrue(result.publish_ready_meta_path.endswith("publish_ready_metadata.json"))
            self.assertTrue(Path(result.run_log_path).exists())
            self.assertGreaterEqual(len(result.step_logs), 5)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_full_pipeline_refine_timeout_falls_back_and_publishes(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate()])
            _seed_fact_pack(store, "topic-flow")

            result = run_full_pipeline(
                topic_id="topic-flow",
                store=store,
                settings=settings,
                dry_run_only=False,
                auto_approve=True,
                skip_refine_on_timeout=True,
                qa_soft_fail=True,
                content_client=_WeakTimeoutChatClient(),
                image_client=_FailingImageClient(),
                publish_client=FakeBloggerClient(),
            )

            self.assertEqual(result.status, "published_with_timeout_fallback")
            self.assertEqual(result.blogger_post_url, "https://example.blogspot.com/2026/03/test-post.html")
            refine_log = next(item for item in result.step_logs if item["step"] == "refine_content")
            self.assertEqual(refine_log["status"], "warning")
            self.assertEqual(refine_log["details"]["error_class"], "TimeoutError")
            self.assertEqual(refine_log["details"]["timeout_seconds"], 180)
            self.assertTrue((root / "contents" / "topic-flow" / "publish" / "publish_ready.html").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class _WeakTimeoutChatClient:
    def __init__(self) -> None:
        self._responses = [
            '{"angle":"약한 초안 방향","objective":"약한 구조","key_points":["하나"],"recommended_readers":["초보자"],"automation_opportunities":["요약"],"monetization_opportunities":["서비스"],"search_intent":"기본 검색"}',
            (
                '{"title_candidates":["약한 제목"],'
                '"meta_description":"짧은 설명",'
                '"excerpt":"짧은 요약",'
                '"intro_paragraph":"이 글은 업데이트를 설명합니다.",'
                '"article_outline":["개요"],'
                '"key_takeaways":["하나"],'
                '"article_sections":[{"heading":"개요","level":"h2","purpose":"설명","paragraphs":["짧은 문단"],"bullets":[]},{"heading":"반복","level":"h2","purpose":"설명","paragraphs":["짧은 문단"],"bullets":[]}],'
                '"practical_checklist":{"heading":"체크","items":["항목 하나"]},'
                '"faq_items":[{"question":"무엇인가요?","answer":"설명입니다."}],'
                '"labels":["AI"],'
                '"hashtags":["#AI"],'
                '"internal_links":[],'
                '"external_citation_placeholders":[{"label":"공식 출처","source_url":"https://openai.com/index/workflow-update"}],'
                '"author_note":"메모",'
                '"conclusion":"결론",'
                '"cta_text":"CTA",'
                '"image_prompt":"Editorial AI cover, clean, minimal",'
                '"alt_text_candidates":["AI workflow cover"]}'
            ),
            '{"final_title":"약한 초안 제목","reason":"기본 선택"}',
        ]

    def create_chat_completion(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        if self._responses:
            return self._responses.pop(0)
        raise TimeoutError("The read operation timed out")


if __name__ == "__main__":
    unittest.main()
