from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.storage import (
    BlogWorkItemRepository,
    InvalidStatusTransitionError,
    PublishRecord,
    PublishRecordRepository,
    PublishStatus,
    QAReviewRecord,
    QAReviewRepository,
    SQLiteBlogStore,
    create_sample_work_item,
)


class StorageRepositoryTests(unittest.TestCase):
    def test_initialize_creates_sqlite_in_data_dir(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            store = SQLiteBlogStore(root)
            db_path = store.initialize()
            self.assertTrue(db_path.exists())
            self.assertEqual(db_path.parent, root / "data")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_upsert_and_get_round_trip_with_topic_quality_fields(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            sample = create_sample_work_item(item_id="item-001")
            sample.selected_pillar = sample.content_pillar
            sample.selected_topic = sample.topic_title
            sample.why_selected = "실제 기사 3건 기반"
            sample.source_count = 3
            sample.source_domains = ["news.hankyung.com", "www.mk.co.kr", "www.etnews.com"]
            sample.title_candidate_types = ["문제형", "초보형", "실행형", "비교형", "뉴스해설형"]
            sample.source_quality_status = "sufficient"
            sample.estimated_time_to_start = "하루 30~60분"
            sample.estimated_cost_to_start = "월 0~5만원"
            sample.potential_income_range = "월 5만~50만원"
            sample.difficulty_level = "중간"
            sample.recommended_for = ["직장인"]
            sample.not_recommended_for = ["즉시 고수익 기대자"]
            sample.failure_points = ["검수 없이 시작"]
            sample.faq_items = [{"question": "진짜 초보도 가능한가?", "answer": "작게 가능"}]
            sample.cta_type = "action_plan"
            sample.content_density_status = "dense"
            sample.retry_count = 2
            sample.retry_path = ["stock:initial", "tax:query_expansion"]
            sample.fallback_strategy_used = "pillar_fallback"
            sample.fallback_pillar_used = "부업 세금 / N잡 세금"
            sample.discovery_attempts = [{"pillar_name": "stock", "retry_stage": "initial"}]
            saved = repo.upsert(sample)
            loaded = repo.get_by_id("item-001")
            self.assertIsNotNone(loaded)
            self.assertEqual(saved.id, "item-001")
            self.assertEqual(loaded.topic_title, sample.topic_title)
            self.assertEqual(loaded.publish_status, PublishStatus.PLANNED.value)
            self.assertEqual(loaded.source_count, 3)
            self.assertEqual(len(loaded.source_domains), 3)
            self.assertEqual(len(loaded.title_candidate_types), 5)
            self.assertEqual(loaded.content_density_status, "dense")
            self.assertEqual(loaded.retry_count, 2)
            self.assertEqual(loaded.fallback_strategy_used, "pillar_fallback")
            self.assertEqual(len(loaded.discovery_attempts), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_status_transition_rules_are_enforced(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            repo.upsert(create_sample_work_item(item_id="item-002"))
            generated = repo.transition_status(item_id="item-002", next_status=PublishStatus.GENERATED)
            self.assertEqual(generated.publish_status, PublishStatus.GENERATED.value)
            published = repo.transition_status(item_id="item-002", next_status=PublishStatus.PUBLISHED)
            self.assertEqual(published.publish_status, PublishStatus.PUBLISHED.value)
            with self.assertRaises(InvalidStatusTransitionError):
                repo.transition_status(item_id="item-002", next_status=PublishStatus.FAILED)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_list_recent_for_streamlit_returns_operator_rows(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            repo.upsert(create_sample_work_item(item_id="item-003"))
            rows = repo.list_recent_for_streamlit(limit=5)
            self.assertEqual(len(rows), 1)
            self.assertIn("topic_title", rows[0])
            self.assertIn("publish_status", rows[0])
            self.assertIn("source_count", rows[0])
            self.assertIn("source_domains", rows[0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_create_sample_record_persists_testable_item(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            sample = repo.create_sample_record()
            loaded = repo.get_by_id(sample.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.primary_keyword, "AI 자동화 부업")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_qa_and_publish_records_round_trip(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            store = SQLiteBlogStore(Path(temp_dir))
            qa_repo = QAReviewRepository(store)
            publish_repo = PublishRecordRepository(store)

            qa_saved = qa_repo.upsert(
                QAReviewRecord(
                    work_item_id="item-004",
                    created_at="2026-03-17T00:00:00+00:00",
                    updated_at="2026-03-17T00:00:00+00:00",
                    qa_result="PASS",
                    qa_score=92,
                    issues=[],
                    fixes=[],
                    review_summary="qa ok",
                    requires_manual_approval=False,
                )
            )
            publish_saved = publish_repo.insert(
                PublishRecord(
                    publish_id="publish-001",
                    work_item_id="item-004",
                    created_at="2026-03-17T00:00:00+00:00",
                    updated_at="2026-03-17T00:00:00+00:00",
                    publish_mode="public",
                    target_status="public",
                    publish_result="published",
                    blog_url="https://myblog.example.org/post",
                    blog_post_id="post-123",
                    response_json={"id": "post-123"},
                    error_message="",
                )
            )

            self.assertEqual(qa_saved.qa_score, 92)
            self.assertEqual(publish_saved.blog_post_id, "post-123")
            self.assertEqual(len(publish_repo.list_for_work_item("item-004")), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
