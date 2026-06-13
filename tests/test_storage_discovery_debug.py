from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.storage import BlogWorkItemRepository, SQLiteBlogStore, create_sample_work_item


class StorageDiscoveryDebugTests(unittest.TestCase):
    def test_discovery_debug_fields_round_trip(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = BlogWorkItemRepository(SQLiteBlogStore(Path(temp_dir)))
            sample = create_sample_work_item(item_id="discovery-debug-001")
            sample.discovery_debug = {
                "attempted_strategy_type": "rss",
                "search_queries_used": ["ai 부업"],
                "source_attempts": [
                    {
                        "provider_type": "rss",
                        "provider_name": "demo",
                        "source_url": "https://demo.example/rss",
                        "fetch_status": "success",
                        "parse_status": "success",
                        "response_length": 10,
                        "parse_count": 3,
                        "filtered_out_count": 1,
                        "filtered_item_reasons": {"title_too_short": 1},
                        "query_text": "ai 부업",
                    }
                ],
                "final_discovery_status": "selected",
            }
            sample.raw_candidate_count = 4
            sample.parsed_candidate_count = 3
            sample.filtered_candidate_count = 3
            sample.reject_reason_summary = {"title_too_short": 1}
            sample.final_discovery_status = "selected"

            repo.upsert(sample)
            loaded = repo.get_by_id(sample.id)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.raw_candidate_count, 4)
            self.assertEqual(loaded.parsed_candidate_count, 3)
            self.assertEqual(loaded.filtered_candidate_count, 3)
            self.assertEqual(loaded.final_discovery_status, "selected")
            self.assertEqual(loaded.reject_reason_summary, {"title_too_short": 1})
            self.assertEqual(loaded.discovery_debug.get("attempted_strategy_type"), "rss")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
