from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.publishing.service import publish_status, publish_topic
from blogspot_automation.storage import StateStore


class FakeBloggerClient:
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
            "id": "blogger-post-123",
            "url": "https://example.blogspot.com/2026/03/test-post.html",
            "published": "2026-03-17T10:00:00Z",
            "status": "LIVE",
            "title": "Published Test Post",
        }

    def verify_public_url(self, url: str) -> int:
        del url
        return 200


class PublishingTests(unittest.TestCase):
    def test_publish_topic_dry_run_writes_request_and_status(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            _seed_final_ready_package(store, "topic-001")

            result = publish_topic(
                topic_id="topic-001",
                store=store,
                settings=settings,
                dry_run=True,
            )

            publish_dir = root / "contents" / "topic-001" / "publish"
            self.assertEqual(result.status, "dry_run")
            self.assertTrue((publish_dir / "publish_ready.html").exists())
            self.assertTrue((publish_dir / "publish_ready_metadata.json").exists())
            self.assertTrue((publish_dir / "publish_request.json").exists())
            self.assertTrue((publish_dir / "publish_response.json").exists())
            self.assertTrue((publish_dir / "publish_log.jsonl").exists())
            self.assertFalse((publish_dir / "published_post.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_publish_topic_live_updates_local_state(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            _seed_final_ready_package(store, "topic-002")

            result = publish_topic(
                topic_id="topic-002",
                store=store,
                settings=settings,
                client=FakeBloggerClient(),
            )

            self.assertEqual(result.status, "published")
            status_payload = publish_status(topic_id="topic-002", store=store)
            self.assertEqual(status_payload["status"], "published")
            self.assertEqual(status_payload["blogger_post_id"], "blogger-post-123")
            self.assertTrue((root / "contents" / "topic-002" / "publish" / "history").exists())
            final_ready_payload = store.load_final_ready_package("topic-002")
            self.assertEqual(final_ready_payload["final_ready_package"]["status"], "published")
            published_post = json.loads((root / "contents" / "topic-002" / "publish" / "published_post.json").read_text(encoding="utf-8"))
            self.assertEqual(published_post["response_status"], "LIVE")
            self.assertEqual(published_post["verified_status_code"], 200)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_publish_topic_blocks_duplicate_publish_without_force(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            _seed_final_ready_package(store, "topic-003")

            publish_topic(
                topic_id="topic-003",
                store=store,
                settings=settings,
                client=FakeBloggerClient(),
            )

            with self.assertRaises(RuntimeError):
                publish_topic(
                    topic_id="topic-003",
                    store=store,
                    settings=settings,
                    client=FakeBloggerClient(),
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_publish_topic_fails_when_final_ready_package_missing(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()

            with self.assertRaises(FileNotFoundError):
                publish_topic(topic_id="missing-topic", store=store, settings=settings, dry_run=True)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_publish_topic_blocks_when_qa_is_not_pass_without_force(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            _seed_final_ready_package(store, "topic-004", qa_result="FIX_REQUIRED")

            with self.assertRaises(RuntimeError):
                publish_topic(topic_id="topic-004", store=store, settings=settings, dry_run=True)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _seed_final_ready_package(store: StateStore, topic_id: str, qa_result: str = "PASS") -> None:
    output_dir = store.topic_output_dir(topic_id)
    final_ready_payload = {
        "topic_data": {"topic_id": topic_id},
        "brief": {"topic_id": topic_id},
        "blog_package": {
            "topic_id": topic_id,
            "slug": f"topic-{topic_id}",
            "meta_description": "이 글은 실제 발행 전 검증을 위한 메타 설명입니다.",
            "image_prompt": "Editorial AI cover, clean and minimal",
            "image_alt": ["AI workflow cover image"],
            "faq_items": [
                {"question": "무엇인가요?", "answer": "테스트용 FAQ 답변입니다."},
                {"question": "왜 중요한가요?", "answer": "발행 산출물 검증에 필요합니다."},
            ],
            "json_ld": {"@type": "BlogPosting"},
            "internal_links": [
                {"anchor_text": "관련 글", "target_slug": "related-post", "reason": "주제 클러스터 확장"}
            ],
            "external_sources": [
                {"label": "공식 소스", "source_url": "https://example.com/source"}
            ],
        },
        "qa": {"approved": True, "qa_result": qa_result},
        "final_ready_package": {
            "title": f"Topic {topic_id} Final Title",
            "article_html": "<article><h1>Title</h1><p>Body</p></article>",
            "labels": ["AI", "Automation"],
            "status": "final_ready",
        },
    }
    (output_dir / "final_ready_package.json").write_text(
        json.dumps(final_ready_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
