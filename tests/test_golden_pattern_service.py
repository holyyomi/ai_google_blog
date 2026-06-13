from __future__ import annotations

import unittest

from blogspot_automation.services.golden_pattern_service import GoldenPatternService


class TestGoldenPatternService(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = GoldenPatternService()

    # ------------------------------------------------------------------ #
    # 골든 샘플 3개 매칭                                                    #
    # ------------------------------------------------------------------ #

    def test_tax_refund_matches(self) -> None:
        result = self.svc.match_pattern(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        self.assertTrue(result["matched"], f"expected matched=True: {result}")
        self.assertEqual(result["pattern_id"], "tax_refund_hometax_check")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_viral_ott_matches(self) -> None:
        result = self.svc.match_pattern(topic="넷플릭스 신작 반응이 갈린 이유")
        self.assertTrue(result["matched"], f"expected matched=True: {result}")
        self.assertEqual(result["pattern_id"], "viral_ott_reaction_decode")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_ai_work_matches(self) -> None:
        result = self.svc.match_pattern(topic="직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유")
        self.assertTrue(result["matched"], f"expected matched=True: {result}")
        self.assertEqual(result["pattern_id"], "ai_work_time_savings")
        self.assertGreaterEqual(result["confidence"], 80)

    # ------------------------------------------------------------------ #
    # 미매칭 케이스                                                         #
    # ------------------------------------------------------------------ #

    def test_no_match_for_delivery(self) -> None:
        result = self.svc.match_pattern(topic="배달료 논란")
        self.assertFalse(result["matched"], f"expected matched=False: {result}")
        self.assertLess(result["confidence"], 80)

    def test_no_match_for_unrelated(self) -> None:
        result = self.svc.match_pattern(topic="오늘 날씨 맑음")
        self.assertFalse(result["matched"])
        self.assertEqual(result["confidence"], 0)

    def test_privacy_topic_does_not_match_viral_ott(self) -> None:
        result = self.svc.match_pattern(
            topic="이번엔 티빙 개인정보가 화제 된 반응이 갈린 이유",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
        )
        self.assertFalse(result["matched"], f"privacy topic must not use OTT reaction pattern: {result}")
        self.assertLess(result["confidence"], 80)

    def test_policy_topic_does_not_match_viral_ott(self) -> None:
        result = self.svc.match_pattern(
            topic="기후보험 반응이 갈린 이유와 핵심 포인트",
            content_type="viral_issue_decode",
            topic_group="fandom_consumer",
        )
        self.assertFalse(result["matched"], f"policy topic must not use OTT reaction pattern: {result}")
        self.assertLess(result["confidence"], 80)

    def test_platform_fee_change_matches_platform_pattern(self) -> None:
        result = self.svc.match_pattern(
            topic="구글 수수료 변경 전에 확인할 것",
            content_type="platform_change",
            topic_group="platform_issue",
        )
        self.assertTrue(result["matched"], f"platform fee change should match platform pattern: {result}")
        self.assertEqual(result["pattern_id"], "platform_change_service_update")

    def test_delivery_worker_operation_matches_platform_pattern(self) -> None:
        result = self.svc.match_pattern(
            topic="배달앱 새벽배달 변경 전에 확인할 것",
            content_type="platform_change",
            topic_group="platform_issue",
        )
        self.assertTrue(result["matched"], f"delivery operation change should match platform pattern: {result}")
        self.assertEqual(result["pattern_id"], "platform_change_service_update")

    # ------------------------------------------------------------------ #
    # 점수 시스템                                                           #
    # ------------------------------------------------------------------ #

    def test_negative_hit_reduces_confidence(self) -> None:
        base = self.svc.match_pattern(topic="홈택스 환급금 조회")
        with_neg = self.svc.match_pattern(topic="홈택스 환급금 조회 지원금")
        self.assertGreater(
            base["confidence"],
            with_neg["confidence"],
            "negative keyword '지원금' should reduce confidence",
        )
        self.assertIn("지원금", with_neg["negative_hits"])

    def test_content_type_bonus_increases_confidence(self) -> None:
        no_ct = self.svc.match_pattern(topic="홈택스 환급금 조회")
        with_ct = self.svc.match_pattern(
            topic="홈택스 환급금 조회", content_type="tax_refund"
        )
        self.assertGreaterEqual(
            with_ct["confidence"],
            no_ct["confidence"],
            "content_type match should add bonus",
        )

    def test_topic_group_bonus_increases_confidence(self) -> None:
        no_tg = self.svc.match_pattern(topic="홈택스 환급금 조회")
        with_tg = self.svc.match_pattern(
            topic="홈택스 환급금 조회",
            content_type="tax_refund",
            topic_group="policy_benefit",
        )
        self.assertGreaterEqual(with_tg["confidence"], no_tg["confidence"])

    # ------------------------------------------------------------------ #
    # 결과 구조 검증                                                        #
    # ------------------------------------------------------------------ #

    def test_match_result_has_required_keys(self) -> None:
        result = self.svc.match_pattern(topic="홈택스 환급금")
        required = [
            "matched", "pattern_id", "pattern_title", "confidence",
            "matched_keywords", "negative_hits", "content_type_match",
            "topic_group_match", "reason",
        ]
        for k in required:
            self.assertIn(k, result, f"key '{k}' missing from result")

    def test_confidence_is_bounded(self) -> None:
        for topic in ["홈택스 환급금", "넷플릭스 반응", "배달료", "ChatGPT 직장인"]:
            result = self.svc.match_pattern(topic=topic)
            self.assertGreaterEqual(result["confidence"], 0)
            self.assertLessEqual(result["confidence"], 100)

    # ------------------------------------------------------------------ #
    # 보조 API                                                             #
    # ------------------------------------------------------------------ #

    def test_list_patterns(self) -> None:
        patterns = self.svc.list_patterns()
        self.assertGreaterEqual(len(patterns), 3)
        ids = [p["pattern_id"] for p in patterns]
        self.assertIn("tax_refund_hometax_check", ids)
        self.assertIn("viral_ott_reaction_decode", ids)
        self.assertIn("ai_work_time_savings", ids)

    def test_list_required_slots(self) -> None:
        slots = self.svc.list_required_slots("tax_refund_hometax_check")
        for s in ["hook_opening", "yomi_judgment", "misconceptions", "real_criterion",
                  "quick_decision_table", "actions", "faq", "hashtags", "internal_links"]:
            self.assertIn(s, slots, f"required slot '{s}' missing")

    def test_get_publish_policy(self) -> None:
        policy = self.svc.get_publish_policy("tax_refund_hometax_check")
        self.assertTrue(policy.get("human_publish_required"))
        self.assertGreaterEqual(policy.get("pattern_match_confidence_gte", 0), 80)

    def test_get_banned_phrases(self) -> None:
        phrases = self.svc.get_banned_default_phrases("ai_work_time_savings")
        self.assertGreater(len(phrases), 0)

    def test_get_pattern_returns_none_for_unknown(self) -> None:
        self.assertIsNone(self.svc.get_pattern("no_such_pattern"))

    # ------------------------------------------------------------------ #
    # 엣지 케이스 / 안전성                                                  #
    # ------------------------------------------------------------------ #

    def test_missing_patterns_file_graceful(self) -> None:
        svc = GoldenPatternService(patterns_path="/nonexistent/path/patterns.json")
        result = svc.match_pattern(topic="아무 주제")
        self.assertFalse(result["matched"])
        self.assertEqual(result["confidence"], 0)

    def test_empty_topic_does_not_crash(self) -> None:
        result = self.svc.match_pattern(topic="")
        self.assertFalse(result["matched"])

    def test_load_patterns_idempotent(self) -> None:
        first = self.svc.load_patterns()
        second = self.svc.load_patterns()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
