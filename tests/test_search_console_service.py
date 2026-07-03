from __future__ import annotations

import json
import unittest

from blogspot_automation.services.search_console_service import (
    load_search_performance,
    save_search_performance,
    topic_boost_for,
)


def _performance(queries: list[dict]) -> dict:
    return {"site_url": "https://holyyomiai.blogspot.com/", "queries": queries, "pages": []}


class TestTopicBoost(unittest.TestCase):
    def test_clicked_query_overlap_boosts(self):
        perf = _performance([
            {"key": "chatgpt 회의록 요약", "clicks": 4, "impressions": 120},
            {"key": "노션 수식 사용법", "clicks": 2, "impressions": 60},
        ])
        result = topic_boost_for("ChatGPT로 회의록 요약 자동화하는 법", perf)
        self.assertGreaterEqual(result["boost"], 3)
        self.assertIn("chatgpt 회의록 요약", result["matched_queries"])

    def test_impression_only_query_gives_smaller_boost(self):
        perf = _performance([
            {"key": "claude 무료 한도", "clicks": 0, "impressions": 90},
        ])
        result = topic_boost_for("Claude 무료 한도와 유료 전환 기준", perf)
        self.assertEqual(result["boost"], 1)

    def test_unrelated_topic_gets_zero(self):
        perf = _performance([
            {"key": "chatgpt 회의록 요약", "clicks": 4, "impressions": 120},
        ])
        result = topic_boost_for("미드저니 이미지 프롬프트 잘 쓰는 법", perf)
        self.assertEqual(result["boost"], 0)

    def test_single_common_token_does_not_boost(self):
        # 'ai'나 '무료' 같은 흔한 단어 하나만 겹치는 우연 일치는 부스트 금지
        perf = _performance([
            {"key": "무료 ai 도구", "clicks": 10, "impressions": 300},
        ])
        result = topic_boost_for("코파일럿 코드 리뷰 활용법", perf)
        self.assertEqual(result["boost"], 0)

    def test_boost_capped(self):
        perf = _performance([
            {"key": f"chatgpt 업무 자동화 {i}단계", "clicks": 5, "impressions": 100}
            for i in range(10)
        ])
        result = topic_boost_for("chatgpt 업무 자동화 단계별 정리", perf)
        self.assertLessEqual(result["boost"], 8)

    def test_empty_performance_is_noop(self):
        self.assertEqual(topic_boost_for("아무 주제", {})["boost"], 0)
        self.assertEqual(topic_boost_for("아무 주제", {"queries": []})["boost"], 0)


class TestStore(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "perf.json"
            data = _performance([{"key": "q", "clicks": 1, "impressions": 2}])
            self.assertTrue(save_search_performance(data, path=path))
            loaded = load_search_performance(path=path)
            self.assertEqual(loaded["queries"][0]["key"], "q")

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load_search_performance(path="does/not/exist.json"), {})

    def test_save_empty_returns_false(self):
        self.assertFalse(save_search_performance({}))


if __name__ == "__main__":
    unittest.main()
