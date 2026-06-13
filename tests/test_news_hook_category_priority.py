from __future__ import annotations

import unittest

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.news_scoring_service import NewsScoringService


class TestNewsHookCategoryPriority(unittest.TestCase):
    def test_viral_news_category_gets_first_priority(self) -> None:
        raw = {
            "content_angle": {"content_type": "viral_issue_decode"},
            "query_group": "sports_reaction",
            "viral_safety_score": 85,
            "viral_risk_flags": [],
        }

        priority = NewsScoringService._hook_category_priority(
            raw,
            "safe sports reaction topic",
            "entertainment_sports",
            "viral_issue_decode",
        )
        bonus = NewsScoringService._hook_category_bonus(
            raw,
            "safe sports reaction topic",
            "entertainment_sports",
            "viral_issue_decode",
        )

        self.assertEqual(priority, 0)
        self.assertGreaterEqual(bonus, 12)

    def test_front_page_multi_source_news_gets_second_priority(self) -> None:
        raw = {
            "content_angle": {"content_type": "platform_change"},
            "query_group": "breaking_issue",
            "discovery_engine": True,
            "today_buzz_score": 8,
            "source_count": 3,
            "source_type": "news",
        }

        priority = NewsScoringService._hook_category_priority(
            raw,
            "major service outage compensation announced",
            "platform_issue",
            "platform_change",
        )
        bonus = NewsScoringService._hook_category_bonus(
            raw,
            "major service outage compensation announced",
            "platform_issue",
            "platform_change",
        )

        self.assertEqual(priority, 1)
        self.assertGreaterEqual(bonus, 9)

    def test_life_schedule_issue_gets_front_page_priority(self) -> None:
        raw = {
            "content_angle": {"content_type": "consumer_warning"},
            "query_group": "money_life",
            "source_type": "news",
            "source_count": 2,
        }

        priority = NewsScoringService._hook_category_priority(
            raw,
            "6월3일 택배 휴무 배송조회 집화 마감 확인",
            "delivery_money",
            "consumer_warning",
        )
        bonus = NewsScoringService._hook_category_bonus(
            raw,
            "6월3일 택배 휴무 배송조회 집화 마감 확인",
            "delivery_money",
            "consumer_warning",
        )

        self.assertEqual(priority, 1)
        self.assertGreaterEqual(bonus, 9)

    def test_topic_engine_score_uses_front_page_bonus(self) -> None:
        base = {
            "content_angle": {"content_type": "platform_change"},
            "query_group": "general",
            "source_type": "news",
            "click_potential_score": 6,
            "viral_safety_score": 90,
            "viral_risk_flags": [],
            "is_stale": False,
            "search_demand_topic": "service outage compensation",
            "reader_search_questions": ["what changed", "who is affected"],
            "angle_type": "platform_check",
            "practical_value_score": 9,
        }
        front_page = {
            **base,
            "query_group": "breaking_issue",
            "discovery_engine": True,
            "today_buzz_score": 8,
            "source_count": 3,
        }

        standard_scores = NewsScoringService._compute_topic_engine_v2_scores(
            base,
            "service outage compensation",
            "service outage compensation",
            "platform_issue",
        )
        front_page_scores = NewsScoringService._compute_topic_engine_v2_scores(
            front_page,
            "service outage compensation",
            "service outage compensation",
            "platform_issue",
        )

        self.assertEqual(front_page_scores["topic_hook_category_priority"], 1)
        self.assertGreater(
            front_page_scores["topic_engine_score"],
            standard_scores["topic_engine_score"],
        )

    def test_score_candidates_records_hook_priority_fields(self) -> None:
        candidate = NewsCandidate(
            topic="safe streaming finale audience reaction",
            category="news",
            summary="viewer reaction and watch points",
            published_at="2026-05-29T00:00:00+09:00",
            raw={
                "source_type": "news",
                "discovery_engine": True,
                "topic_group": "entertainment_sports",
                "content_angle": {"content_type": "viral_issue_decode"},
                "query_group": "sports_reaction",
                "viral_safety_score": 85,
                "viral_risk_flags": [],
                "today_buzz_score": 7,
                "source_count": 2,
            },
        )

        scored = NewsScoringService().score_candidates([candidate])[0]
        raw = scored.candidate.raw
        strategy = raw["strategy_score_breakdown"]

        self.assertEqual(raw["hook_category_priority"], 0)
        self.assertGreaterEqual(raw["hook_category_bonus"], 12)
        self.assertEqual(strategy["raw_total_score"], raw["raw_total_score"])
        self.assertEqual(raw["topic_hook_category_priority"], 0)


if __name__ == "__main__":
    unittest.main()
