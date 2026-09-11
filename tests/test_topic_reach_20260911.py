"""주제가 이길 수 있는 자리를 겨냥하게 만드는 두 수정 (2026-09-11).

배경 — GSC 실측:
    holyyomiai 발행 68편, 색인 0 · 120일 노출 0 · 클릭 0.
    같은 계정 holyteminsight 는 색인된 글이 있고 노출도 난다. 차이는 겨냥한
    자리다 (아무도 안 쓰는 제품명 vs 벤더가 소유한 머리 키워드).

1. dedup 오탐: 일반 독자 질문이 브랜드 한 단어로 정규화돼 영구 차단됐다.
   리허설 6회 시도 전부 deduped=0 으로 뉴스 리라이트로 흘러내렸다.
2. SERP 경쟁도 필터: 벤더 공식문서·대형 테크매체가 점유한 주제를 후보에서 뺀다.
"""
from __future__ import annotations

import json
import types
import unittest
from pathlib import Path

from blogspot_automation.services.serp_competition_service import (
    MIN_RESULTS_TO_JUDGE,
    TIER_BLOG,
    TIER_MEDIA,
    TIER_PLATFORM,
    TIER_UNKNOWN,
    TIER_VENDOR,
    assess_from_domains,
    classify_domain,
)
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _candidate(topic: str, slot: str):
    raw = {
        "topic_cluster": True,
        "cluster_key": "consumer_demand_live",
        "cluster_slot": slot,
        "search_demand_topic": topic,
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
    }
    inner = types.SimpleNamespace(
        topic=topic, title=topic, raw=raw, url="", summary="", category="ai_work"
    )
    return types.SimpleNamespace(candidate=inner, score=96, reason="", search_angle={})


class ConsumerQuestionDedupTest(unittest.TestCase):
    def setUp(self):
        self.svc = TopicDedupService()
        path = Path(__file__).resolve().parents[1] / "data" / "publish_history.json"
        self.history = json.loads(path.read_text(encoding="utf-8"))

    def test_question_phrases_normalize_to_a_bare_brand(self):
        self.assertEqual(self.svc.normalize_text("is chatgpt worth it"), "chatgpt")
        self.assertEqual(self.svc.normalize_text("is gemini free"), "gemini")

    def test_bare_brand_norm_is_not_a_duplicate(self):
        for topic in ("is chatgpt worth it", "is claude worth it", "is gemini free"):
            with self.subTest(topic=topic):
                blocked = self.svc.is_duplicate(
                    _candidate(topic, topic.replace(" ", "_")), self.history
                )
                self.assertFalse(blocked, "브랜드명 한 단어라는 이유로 차단됐다")

    def test_exact_norm_match_is_still_a_duplicate(self):
        self.assertTrue(self.svc._norms_match("chatgpt", "chatgpt"))

    def test_multi_token_containment_is_still_a_duplicate(self):
        self.assertTrue(
            self.svc._norms_match("chatgpt free limits", "chatgpt free limits 2026 guide")
        )

    def test_single_token_containment_no_longer_matches(self):
        self.assertFalse(self.svc._norms_match("chatgpt", "chatgpt limit reduced"))


class DomainTierTest(unittest.TestCase):
    def test_vendor_and_subdomains(self):
        for host in ("openai.com", "help.openai.com", "platform.openai.com", "anthropic.com"):
            self.assertEqual(classify_domain(host), TIER_VENDOR, host)

    def test_docs_subdomain_defaults_to_vendor(self):
        self.assertEqual(classify_domain("docs.somevendor.io"), TIER_VENDOR)

    def test_big_media_and_platform(self):
        self.assertEqual(classify_domain("www.techradar.com"), TIER_MEDIA)
        self.assertEqual(classify_domain("reddit.com"), TIER_PLATFORM)

    def test_small_publishers(self):
        for host in ("someone.blogspot.com", "x.wordpress.com", "medium.com", "dev.to"):
            self.assertEqual(classify_domain(host), TIER_BLOG, host)

    def test_unknown_is_not_optimistically_a_blog(self):
        self.assertEqual(classify_domain("some-random-site.example"), TIER_UNKNOWN)


VENDOR_HELD = [
    "https://help.openai.com/en/articles/x",
    "https://community.openai.com/t/1",
    "https://www.reddit.com/r/ChatGPT/x",
    "https://zapier.com/blog/chatgpt-free",
    "https://www.techradar.com/x",
    "https://www.tomsguide.com/x",
    "https://www.makeuseof.com/x",
    "https://www.youtube.com/watch",
    "https://platform.openai.com/docs",
    "https://www.pcmag.com/x",
]

OPEN_FIELD = [
    "https://github.com/org/repo/issues/4627",
    "https://stackoverflow.com/questions/1",
    "https://someguy.blogspot.com/2026/01/x.html",
    "https://dev.to/someone/x",
    "https://notes.example.dev/x",
    "https://medium.com/someone/x",
    "https://smallsite.io/blog/x",
    "https://another.github.io/post",
    "https://randomtool.dev/docs-x",
    "https://tinyblog.wordpress.com/x",
]


class CompetitionVerdictTest(unittest.TestCase):
    def test_vendor_held_query_is_not_winnable(self):
        verdict = assess_from_domains("chatgpt free version limits", VENDOR_HELD)
        self.assertIs(verdict.winnable, False)
        self.assertEqual(verdict.tier_counts.get(TIER_BLOG, 0), 0)

    def test_open_field_query_is_winnable(self):
        verdict = assess_from_domains("obscure api error", OPEN_FIELD)
        self.assertIs(verdict.winnable, True)
        self.assertGreaterEqual(verdict.tier_counts.get(TIER_BLOG, 0), 2)

    def test_too_few_results_is_unknown_not_blocked(self):
        few = ["https://openai.com/a"] * (MIN_RESULTS_TO_JUDGE - 1)
        self.assertIsNone(assess_from_domains("x", few).winnable)

    def test_verdict_serializes(self):
        keys = set(assess_from_domains("q", OPEN_FIELD).as_dict())
        self.assertTrue({"winnable", "competition_score", "reason"} <= keys)


class CompetitionFilterSafetyTest(unittest.TestCase):
    """필터가 발행을 0건으로 만들지 않는지 — 이 repo 가 실제로 밟은 사고."""

    @staticmethod
    def _verdict(winnable, score=0):
        from blogspot_automation.services.serp_competition_service import CompetitionVerdict

        return CompetitionVerdict(topic="t", winnable=winnable, score=score, reason="test")

    def _pipeline(self, verdicts):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        pipeline = NewsPipeline.__new__(NewsPipeline)

        class _Svc:
            def assess(self, topic):
                return verdicts[topic]

        pipeline._serp_competition_service = _Svc()
        return pipeline

    def test_all_blocked_keeps_everything(self):
        a, b = _candidate("topic a", "a"), _candidate("topic b", "b")
        pipeline = self._pipeline(
            {"topic a": self._verdict(False), "topic b": self._verdict(False)}
        )
        self.assertEqual(len(pipeline._filter_by_serp_competition([a, b])), 2)

    def test_partial_block_drops_only_the_losers(self):
        a, b = _candidate("topic a", "a"), _candidate("topic b", "b")
        pipeline = self._pipeline(
            {"topic a": self._verdict(False), "topic b": self._verdict(True, 80)}
        )
        kept = pipeline._filter_by_serp_competition([a, b])
        self.assertEqual([k.candidate.topic for k in kept], ["topic b"])

    def test_unknown_verdict_never_blocks(self):
        a = _candidate("topic a", "a")
        pipeline = self._pipeline({"topic a": self._verdict(None)})
        self.assertEqual(len(pipeline._filter_by_serp_competition([a])), 1)

    def test_verdict_is_recorded_on_the_candidate(self):
        a = _candidate("topic a", "a")
        pipeline = self._pipeline({"topic a": self._verdict(True, 72)})
        pipeline._filter_by_serp_competition([a])
        self.assertEqual(a.candidate.raw["serp_competition"]["competition_score"], 72)


if __name__ == "__main__":
    unittest.main()
