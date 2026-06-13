from __future__ import annotations

import os
import unittest

from blogspot_automation.services.news_scoring_service import NewsScoringService
from blogspot_automation.pipelines.news_pipeline import NewsPipeline

_svc = NewsScoringService()

_DANGEROUS_LOWERED = "아이돌 열애설 사생활 폭로 루머 확인"
_SAFE_VIRAL = "넷플릭스 신작 반응 갈린 이유 시청자 먼저 본 3가지"
_EVERGREEN_AI = "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"
_EVERGREEN_TAX = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
_DELIVERY_NOISE = "배달료 논란 갑론을박"


def _raw_viral(topic: str = _SAFE_VIRAL) -> dict:
    return {
        "topic_group": "ott_drama_reaction",
        "content_angle": {"content_type": "viral_issue_decode"},
        "query_group": "ott_drama_reaction",
        "source_type": "news",
        "click_potential_score": 10,
        "viral_safety_score": 80,
        "viral_risk_flags": [],
        "is_stale": False,
        "search_demand_topic": topic,
        "reader_search_questions": ["왜 반응이 갈렸나?", "어떻게 봐야 하나?"],
        "angle_type": "viral_issue_decode",
        "practical_value_score": 12,
    }


def _raw_evergreen_ai() -> dict:
    return {
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
        "query_group": "ai_work",
        "source_type": "evergreen_fallback",
        "click_potential_score": 8,
        "viral_safety_score": 100,
        "viral_risk_flags": [],
        "is_stale": False,
        "search_demand_topic": _EVERGREEN_AI,
        "reader_search_questions": ["왜 안 줄어드나?", "어떻게 써야 하나?"],
        "angle_type": "ai_setting",
        "practical_value_score": 14,
    }


def _raw_dangerous() -> dict:
    return {
        "topic_group": "entertainment_sports",
        "content_angle": {"content_type": "viral_issue_decode"},
        "query_group": "entertainment_sports",
        "source_type": "news",
        "click_potential_score": 12,
        "viral_safety_score": 20,
        "viral_risk_flags": ["열애설", "사생활 폭로"],
        "is_stale": False,
        "search_demand_topic": "열애설 루머",
        "reader_search_questions": [],
        "angle_type": "viral_issue_decode",
        "practical_value_score": 2,
    }


def _raw_delivery() -> dict:
    return {
        "topic_group": "delivery_money",
        "content_angle": {"content_type": "money_checklist"},
        "query_group": "money_life",
        "source_type": "news",
        "click_potential_score": 5,
        "viral_safety_score": 90,
        "viral_risk_flags": [],
        "is_stale": False,
        "search_demand_topic": _DELIVERY_NOISE,
        "reader_search_questions": [],
        "angle_type": "money_compare",
        "practical_value_score": 8,
    }


class TestTopicBucketClassification(unittest.TestCase):
    def test_viral_bucket(self) -> None:
        raw = _raw_viral()
        bucket = NewsScoringService._classify_topic_bucket(raw, "ott_drama_reaction")
        self.assertEqual(bucket, "viral_traffic_candidate")

    def test_evergreen_bucket(self) -> None:
        raw = _raw_evergreen_ai()
        bucket = NewsScoringService._classify_topic_bucket(raw, "ai_work")
        self.assertEqual(bucket, "evergreen_useful_candidate")

    def test_high_cpc_bucket_content_type(self) -> None:
        raw = {"content_angle": {"content_type": "platform_change"}}
        bucket = NewsScoringService._classify_topic_bucket(raw, "general_life")
        self.assertEqual(bucket, "high_cpc_guide_candidate")

    def test_general_bucket_fallback(self) -> None:
        raw = {"content_angle": {"content_type": "general_life"}}
        bucket = NewsScoringService._classify_topic_bucket(raw, "general_life")
        self.assertEqual(bucket, "general")

    def test_ticketing_goods_bucket(self) -> None:
        raw = {"content_angle": {}}
        bucket = NewsScoringService._classify_topic_bucket(raw, "ticketing_goods_issue")
        self.assertEqual(bucket, "viral_traffic_candidate")

    def test_youtube_creator_bucket(self) -> None:
        raw = {"content_angle": {}}
        bucket = NewsScoringService._classify_topic_bucket(raw, "youtube_creator_issue")
        self.assertEqual(bucket, "viral_traffic_candidate")


class TestTopicEngineV2Scores(unittest.TestCase):
    def test_safe_viral_high_score(self) -> None:
        raw = _raw_viral()
        scores = NewsScoringService._compute_topic_engine_v2_scores(
            raw, _SAFE_VIRAL, _SAFE_VIRAL.lower(), "ott_drama_reaction"
        )
        self.assertGreaterEqual(scores["topic_engine_score"], 60)
        self.assertGreaterEqual(scores["topic_safety_score"], 10)
        self.assertGreater(scores["topic_traffic_potential_score"], 0)

    def test_evergreen_ai_high_usefulness(self) -> None:
        raw = _raw_evergreen_ai()
        scores = NewsScoringService._compute_topic_engine_v2_scores(
            raw, _EVERGREEN_AI, _EVERGREEN_AI.lower(), "ai_work"
        )
        self.assertGreaterEqual(scores["topic_usefulness_score"], 10)
        self.assertGreaterEqual(scores["topic_engine_score"], 50)

    def test_dangerous_low_safety(self) -> None:
        raw = _raw_dangerous()
        scores = NewsScoringService._compute_topic_engine_v2_scores(
            raw, _DANGEROUS_LOWERED, _DANGEROUS_LOWERED.lower(), "entertainment_sports"
        )
        self.assertEqual(scores["topic_safety_score"], 0)

    def test_scores_bounded(self) -> None:
        for raw, topic, group in [
            (_raw_viral(), _SAFE_VIRAL, "ott_drama_reaction"),
            (_raw_evergreen_ai(), _EVERGREEN_AI, "ai_work"),
            (_raw_dangerous(), _DANGEROUS_LOWERED, "entertainment_sports"),
        ]:
            scores = NewsScoringService._compute_topic_engine_v2_scores(
                raw, topic, topic.lower(), group
            )
            self.assertLessEqual(scores["topic_traffic_potential_score"], 30)
            self.assertLessEqual(scores["topic_search_intent_score"], 20)
            self.assertLessEqual(scores["topic_usefulness_score"], 20)
            self.assertLessEqual(scores["topic_safety_score"], 15)
            self.assertLessEqual(scores["topic_monetization_score"], 15)
            self.assertLessEqual(scores["topic_engine_score"], 100)
            self.assertGreaterEqual(scores["topic_engine_score"], 0)

    def test_scores_structure(self) -> None:
        raw = _raw_viral()
        scores = NewsScoringService._compute_topic_engine_v2_scores(
            raw, _SAFE_VIRAL, _SAFE_VIRAL.lower(), "ott_drama_reaction"
        )
        for k in ("topic_traffic_potential_score", "topic_search_intent_score",
                  "topic_usefulness_score", "topic_safety_score",
                  "topic_monetization_score", "topic_engine_score"):
            self.assertIn(k, scores)


class TestTopicCandidateGrade(unittest.TestCase):
    def test_A_grade_safe_high_score(self) -> None:
        scores = {
            "topic_engine_score": 85,
            "topic_safety_score": 12,
            "topic_usefulness_score": 16,
            "topic_traffic_potential_score": 25,
        }
        self.assertEqual(NewsScoringService._compute_topic_candidate_grade(scores), "A")

    def test_B_grade_moderate_score(self) -> None:
        scores = {
            "topic_engine_score": 73,
            "topic_safety_score": 11,
            "topic_usefulness_score": 12,
            "topic_traffic_potential_score": 15,
        }
        self.assertEqual(NewsScoringService._compute_topic_candidate_grade(scores), "B")

    def test_C_grade(self) -> None:
        scores = {
            "topic_engine_score": 58,
            "topic_safety_score": 8,
            "topic_usefulness_score": 6,
            "topic_traffic_potential_score": 20,
        }
        self.assertEqual(NewsScoringService._compute_topic_candidate_grade(scores), "C")

    def test_D_grade_zero_safety(self) -> None:
        scores = {
            "topic_engine_score": 90,
            "topic_safety_score": 0,
            "topic_usefulness_score": 15,
            "topic_traffic_potential_score": 28,
        }
        self.assertEqual(NewsScoringService._compute_topic_candidate_grade(scores), "D")

    def test_D_grade_low_score(self) -> None:
        scores = {
            "topic_engine_score": 30,
            "topic_safety_score": 10,
            "topic_usefulness_score": 5,
            "topic_traffic_potential_score": 5,
        }
        self.assertEqual(NewsScoringService._compute_topic_candidate_grade(scores), "D")

    def test_dangerous_raw_grade_D(self) -> None:
        raw = _raw_dangerous()
        scores = NewsScoringService._compute_topic_engine_v2_scores(
            raw, _DANGEROUS_LOWERED, _DANGEROUS_LOWERED.lower(), "entertainment_sports"
        )
        grade = NewsScoringService._compute_topic_candidate_grade(scores)
        self.assertEqual(grade, "D")


class TestHumanReviewRequired(unittest.TestCase):
    def test_phase_hold_forces_review(self) -> None:
        os.environ["PUBLISH_HOLD_PHASE2"] = "true"
        self.assertTrue(NewsPipeline._is_publish_hold_phase2())

    def test_phase_hold_false_no_forced_review(self) -> None:
        os.environ["PUBLISH_HOLD_PHASE2"] = "false"
        self.assertFalse(NewsPipeline._is_publish_hold_phase2())
        os.environ.pop("PUBLISH_HOLD_PHASE2", None)


class TestGoldenPatternMatchingAlignment(unittest.TestCase):
    """Topic Engine 후보가 golden patterns에 정상 매칭되는지 검증."""

    def setUp(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        self.ps = GoldenPatternService()

    def test_netflix_viral_matches_ott_pattern(self) -> None:
        r = self.ps.match_pattern(topic="넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지")
        self.assertTrue(r["matched"], f"confidence={r['confidence']}")
        self.assertEqual(r["pattern_id"], "viral_ott_reaction_decode")
        self.assertGreaterEqual(r["confidence"], 80)

    def test_tax_refund_matches_hometax_pattern(self) -> None:
        r = self.ps.match_pattern(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        self.assertTrue(r["matched"])
        self.assertEqual(r["pattern_id"], "tax_refund_hometax_check")
        self.assertGreaterEqual(r["confidence"], 80)

    def test_chatgpt_worker_matches_ai_pattern(self) -> None:
        r = self.ps.match_pattern(topic="직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유")
        self.assertTrue(r["matched"])
        self.assertEqual(r["pattern_id"], "ai_work_time_savings")
        self.assertGreaterEqual(r["confidence"], 80)

    def test_delivery_noise_not_matched(self) -> None:
        r = self.ps.match_pattern(topic="배달료 논란")
        self.assertFalse(r["matched"])
        self.assertLess(r["confidence"], 80)

    def test_dangerous_privacy_rumor_low_or_no_match(self) -> None:
        scores = NewsScoringService._compute_topic_engine_v2_scores(
            _raw_dangerous(), _DANGEROUS_LOWERED, _DANGEROUS_LOWERED.lower(), "entertainment_sports"
        )
        self.assertEqual(scores["topic_safety_score"], 0)
        grade = NewsScoringService._compute_topic_candidate_grade(scores)
        self.assertEqual(grade, "D")

    def test_evergreen_tax_refund_topics_match(self) -> None:
        """evergreen_topic_service의 tax_refund_support 토픽들이 패턴에 매칭되는지 확인."""
        topics = [
            "국세환급금 조회 전 계좌 오류부터 확인하세요",
            "종합소득세 환급금이 늦어질 때 먼저 확인할 것",
            "미수령 환급금 조회할 때 놓치기 쉬운 항목",
        ]
        for t in topics:
            with self.subTest(topic=t):
                r = self.ps.match_pattern(topic=t)
                self.assertTrue(r["matched"], f"topic='{t}' confidence={r['confidence']}")
                self.assertGreaterEqual(r["confidence"], 80)

    def test_evergreen_ai_topics_match(self) -> None:
        """evergreen_topic_service의 ai_automation 토픽들이 패턴에 매칭되는지 확인."""
        topics = [
            "AI 업무 자동화할 때 처음 버려야 할 반복 작업 5가지",
            "무료 AI 도구를 업무에 쓸 때 먼저 확인할 한계",
        ]
        for t in topics:
            with self.subTest(topic=t):
                r = self.ps.match_pattern(topic=t)
                self.assertTrue(r["matched"], f"topic='{t}' confidence={r['confidence']}")
                self.assertGreaterEqual(r["confidence"], 80)

    def test_suggest_pattern_id_by_hint_ct(self) -> None:
        r = self.ps.suggest_pattern_id_by_hint("", content_type="tax_refund")
        self.assertEqual(r, "tax_refund_hometax_check")

    def test_suggest_pattern_id_by_hint_tg(self) -> None:
        r = self.ps.suggest_pattern_id_by_hint("", topic_group="ott_platform")
        self.assertEqual(r, "viral_ott_reaction_decode")

    def test_suggest_pattern_id_by_hint_keyword(self) -> None:
        r = self.ps.suggest_pattern_id_by_hint("넷플릭스 신작 반응이 갈린 이유")
        self.assertEqual(r, "viral_ott_reaction_decode")

    def test_suggest_pattern_none_for_unrelated(self) -> None:
        r = self.ps.suggest_pattern_id_by_hint("배달료 논란")
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
