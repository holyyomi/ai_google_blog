from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.topic_discovery.parser import ParsedItem
from blogspot_automation.topic_discovery.scoring import score_item
from blogspot_automation.topic_discovery.service import build_duplicate_key
from blogspot_automation.topic_discovery.strategy import build_topic_strategy
from blogspot_automation.topic_discovery.grounding import build_fact_pack
from blogspot_automation.models import ScoreBreakdown, TopicCandidate, TopicCandidateStatus
from blogspot_automation.storage import StateStore
from pathlib import Path
import shutil
import tempfile


class TopicDiscoveryTests(unittest.TestCase):
    def test_duplicate_key_is_stable_for_same_topic_even_with_different_urls(self) -> None:
        key_a = build_duplicate_key(
            ai_name="OpenAI",
            topic_name="GPT-4.1 API Update",
            source_url="https://openai.com/index/gpt-4-1-api-update",
        )
        key_b = build_duplicate_key(
            ai_name="OpenAI",
            topic_name="GPT-4.1 API Update",
            source_url="https://another.example.com/openai-gpt-4-1-api-update",
        )
        self.assertEqual(key_a, key_b)

    def test_score_rewards_fresher_items(self) -> None:
        fresh_item = ParsedItem(
            source_name="OpenAI Blog",
            source_type="rss",
            source_url="https://openai.com/news/rss.xml",
            ai_name="OpenAI",
            title="OpenAI releases GPT-4.1 API for agents",
            summary="New API release for agent workflows and developer integration.",
            published_at=datetime.now(timezone.utc).isoformat(),
            item_url="https://openai.com/index/gpt-4-1-api",
            tags=["api", "agent"],
        )
        older_item = ParsedItem(
            source_name="OpenAI Blog",
            source_type="rss",
            source_url="https://openai.com/news/rss.xml",
            ai_name="OpenAI",
            title="OpenAI releases GPT-4.1 API for agents",
            summary="New API release for agent workflows and developer integration.",
            published_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            item_url="https://openai.com/index/gpt-4-1-api-old",
            tags=["api", "agent"],
        )

        self.assertGreater(score_item(fresh_item).total, score_item(older_item).total)

    def test_score_breakdown_stays_in_bounds(self) -> None:
        item = ParsedItem(
            source_name="Anthropic News",
            source_type="page",
            source_url="https://www.anthropic.com/news",
            ai_name="Anthropic",
            title="Claude benchmark comparison for enterprise agent workflows",
            summary="A benchmark and workflow comparison for enterprise users.",
            published_at=None,
            item_url="https://www.anthropic.com/news/claude-benchmark",
            tags=["benchmark", "enterprise"],
        )

        score = score_item(item)
        self.assertGreaterEqual(score.total, 0.0)
        self.assertLessEqual(score.total, 1.0)
        self.assertGreaterEqual(score.differentiation, 0.0)
        self.assertLessEqual(score.differentiation, 1.0)

    def test_topic_strategy_assigns_cluster_fields(self) -> None:
        item = ParsedItem(
            source_name="Tool Blog",
            source_type="rss",
            source_url="https://example.com/feed.xml",
            ai_name="ExampleAI",
            title="ExampleAI workflow automation update for agent teams",
            summary="A workflow automation release for agent operations.",
            published_at=None,
            item_url="https://example.com/workflow-update",
            tags=["workflow", "automation"],
        )
        strategy = build_topic_strategy(
            item=item,
            topic_name="workflow automation update",
            keyword_primary="workflow automation",
            keyword_secondary=["agent teams", "automation update"],
        )
        self.assertEqual(strategy.topic_cluster, "automation_workflows")
        self.assertEqual(strategy.user_intent, "how_to")

    def test_build_fact_pack_writes_source_grounded_artifacts(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate()])

            fact_pack = build_fact_pack(topic_id="topic-fact", store=store)
            saved = store.load_fact_pack("topic-fact")
            self.assertIn("what_it_is", fact_pack.fact_pack)
            self.assertIn("fact_pack", saved)
            self.assertIn("source_pack", saved)
            self.assertEqual(saved["topic_id"], "topic-fact")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _sample_topic_candidate() -> TopicCandidate:
    return TopicCandidate(
        run_id="discover-20260317T000000Z",
        topic_id="topic-fact",
        created_at="2026-03-17T00:00:00+00:00",
        ai_name="OpenAI",
        topic_name="Workflow Automation Guide",
        topic_type="developer_update",
        topic_angle="Explain how to use it.",
        keyword_primary="workflow automation",
        keyword_secondary=["agents", "integration"],
        topic_cluster="automation_workflows",
        topic_subcluster="agent_workflows",
        content_mode="evergreen_explainer",
        main_keyword="workflow automation",
        supporting_keywords=["agents", "integration"],
        user_intent="how_to",
        audience_level="beginner_to_intermediate",
        geo_targeting_hint="Global first",
        age_targeting_hint="Answer engine friendly",
        search_angle="Explain how to set up workflow automation",
        monetization_angle="Automation consulting",
        automation_angle="Repeatable workflows",
        source_name="OpenAI Blog",
        source_type="rss",
        source_url="https://openai.com/index/workflow-automation",
        source_published_at="2026-03-16T00:00:00+00:00",
        candidate_title="Workflow automation guide",
        candidate_summary="Guide to workflow automation",
        trend_score=0.82,
        score_breakdown=ScoreBreakdown(0.8, 0.7, 0.8, 0.5, 0.7, 0.6, 0.75),
        duplicate_key="openai-workflow-automation-111111",
        selected_reason="Selected for workflow depth.",
        status=TopicCandidateStatus.PLANNED,
    )


if __name__ == "__main__":
    unittest.main()
