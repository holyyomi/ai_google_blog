from __future__ import annotations

from pathlib import Path
import unittest

from blogspot_automation.services.topic_selection_service import load_topic_discovery_runtime_config
from blogspot_automation.storage import ContentPillar


class TopicStrategyConfigTests(unittest.TestCase):
    def test_default_config_contains_top5_strategy_split(self) -> None:
        runtime = load_topic_discovery_runtime_config(Path.cwd())

        self.assertIn(ContentPillar.DAILY_SIDE_HUSTLE.value, runtime.pillar_strategy_map)
        self.assertIn(ContentPillar.KOREAN_STOCK_NEWS.value, runtime.pillar_strategy_map)
        self.assertIn(ContentPillar.AI_SIDE_HUSTLE.value, runtime.pillar_strategy_map)
        self.assertIn(ContentPillar.SIDE_HUSTLE_TAX.value, runtime.pillar_strategy_map)
        self.assertIn(ContentPillar.KOREAN_STOCK_BEGINNER.value, runtime.pillar_strategy_map)
        self.assertEqual(runtime.pillar_strategy_map[ContentPillar.DAILY_SIDE_HUSTLE.value].strategy_types, ["hybrid_news_search"])
        self.assertEqual(runtime.pillar_strategy_map[ContentPillar.KOREAN_STOCK_NEWS.value].strategy_types, ["news_driven"])
        self.assertEqual(
            runtime.pillar_strategy_map[ContentPillar.AI_SIDE_HUSTLE.value].strategy_types,
            ["hybrid_news_search", "official_source_driven"],
        )
        self.assertEqual(
            runtime.pillar_strategy_map[ContentPillar.SIDE_HUSTLE_TAX.value].strategy_types,
            ["evergreen_search", "official_source_driven"],
        )
        self.assertEqual(runtime.pillar_strategy_map[ContentPillar.KOREAN_STOCK_BEGINNER.value].strategy_types, ["evergreen_search"])


if __name__ == "__main__":
    unittest.main()
