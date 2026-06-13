"""신규 뉴스 패턴(platform_change/consumer_warning/policy_deadline)의 slot fill 회귀 테스트.

목표:
- 3개 신규 패턴 모두 slot_fill_rate >= 0.8
- 8개 required_slots 모두 채워짐
- evergreen/general_life는 영향 없음
"""

from __future__ import annotations

import unittest

from blogspot_automation.services.slot_filler_service import SlotFillerService
from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService


class TestNewSlotBuilders(unittest.TestCase):
    """3개 신규 builder가 모든 required_slots를 채우는지 확인."""

    def setUp(self):
        self.sf = SlotFillerService()

    def test_platform_change_slot_fill(self):
        result = self.sf.fill_slots(
            "platform_change_service_update",
            "쿠팡 멤버십 가격 인상 변경 안내",
            {"content_angle": {"content_type": "platform_change"}},
        )
        self.assertGreaterEqual(result["slot_fill_rate"], 0.8)
        self.assertEqual(result["missing_required_slots"], [])
        # 핵심 슬롯이 모두 채워졌는지
        for slot_name in ["hook_opening", "yomi_judgment", "misconceptions",
                          "real_criterion", "quick_decision_table", "actions",
                          "faq", "hashtags"]:
            self.assertTrue(result["slots"].get(slot_name),
                            f"Slot '{slot_name}' is empty for platform_change")

    def test_consumer_warning_slot_fill(self):
        result = self.sf.fill_slots(
            "consumer_warning_refund",
            "환불 논란 결제 오류 피해 대응",
            {"content_angle": {"content_type": "consumer_warning"}},
        )
        self.assertGreaterEqual(result["slot_fill_rate"], 0.8)
        self.assertEqual(result["missing_required_slots"], [])
        for slot_name in ["hook_opening", "yomi_judgment", "misconceptions",
                          "real_criterion", "quick_decision_table", "actions",
                          "faq", "hashtags"]:
            self.assertTrue(result["slots"].get(slot_name),
                            f"Slot '{slot_name}' is empty for consumer_warning")

    def test_policy_deadline_slot_fill(self):
        result = self.sf.fill_slots(
            "policy_deadline_support",
            "청년 지원금 신청 마감 대상 조건",
            {"content_angle": {"content_type": "policy_deadline"}},
        )
        self.assertGreaterEqual(result["slot_fill_rate"], 0.8)
        self.assertEqual(result["missing_required_slots"], [])
        for slot_name in ["hook_opening", "yomi_judgment", "misconceptions",
                          "real_criterion", "quick_decision_table", "actions",
                          "faq", "hashtags"]:
            self.assertTrue(result["slots"].get(slot_name),
                            f"Slot '{slot_name}' is empty for policy_deadline")

    def test_policy_deadline_quick_table_renders_check_condition(self):
        result = self.sf.fill_slots(
            "policy_deadline_support",
            "청년 운전면허 지원금 신청방법과 대상 조건",
            {"content_angle": {"content_type": "policy_deadline"}},
        )

        html = GoldenArticlePreviewService().render_html(
            {"pattern_id": "policy_deadline_support", "confidence": 100},
            result,
        )

        self.assertIn("공식 기준", html)
        self.assertNotIn("<td></td>", html)

    def test_policy_deadline_preserves_source_specific_facts(self):
        result = self.sf.fill_slots(
            "policy_deadline_support",
            "안심페이 참여 모집 지원금 신청방법과 대상 조건",
            {
                "content_angle": {"content_type": "policy_deadline"},
                "source_title": "2026년 울산형 석유화학업 근로자 안심페이 지원사업 참여자 모집 공고",
                "source_summary": "울산 소재 석유화학업 재직 근로자에게 1인 50만원 울산페이를 지급합니다.",
            },
        )
        text = " ".join(str(value) for value in result["slots"].values())

        self.assertIn("울산", text)
        self.assertIn("석유화학업", text)
        self.assertIn("1인 50만원", text)
        self.assertIn("울산페이", text)
        self.assertLessEqual(len(result["slots"].get("hashtags", [])), 3)

    def test_policy_deadline_does_not_seed_tax_internal_links(self):
        result = self.sf.fill_slots(
            "policy_deadline_support",
            "울산형 석유화학업 근로자 안심페이 지원사업",
            {
                "content_angle": {"content_type": "policy_deadline"},
                "source_title": "2026년 울산형 석유화학업 근로자 안심페이 지원사업 참여자 모집 공고",
                "source_summary": "울산 소재 석유화학업 재직 근로자에게 1인 50만원 울산페이를 지급합니다.",
            },
        )
        text = " ".join(str(value) for value in result["slots"].values())
        self.assertEqual(result["slots"].get("internal_links"), [])
        self.assertNotIn("홈택스", text)
        self.assertNotIn("환급금 조회", text)

    def test_slot_actions_have_three_items(self):
        """actions는 정확히 3개 항목."""
        for pid in ["platform_change_service_update", "consumer_warning_refund",
                    "policy_deadline_support"]:
            result = self.sf.fill_slots(pid, "테스트", {})
            actions = result["slots"].get("actions", [])
            self.assertEqual(len(actions), 3,
                             f"{pid}: actions count = {len(actions)}, expected 3")

    def test_slot_faq_have_three_items(self):
        """faq는 3개 이상 항목."""
        for pid in ["platform_change_service_update", "consumer_warning_refund",
                    "policy_deadline_support"]:
            result = self.sf.fill_slots(pid, "테스트", {})
            faq = result["slots"].get("faq", [])
            self.assertGreaterEqual(len(faq), 3,
                                    f"{pid}: faq count = {len(faq)}, expected >= 3")

    def test_consumer_warning_avoids_lookup_phrases(self):
        """consumer_warning에 정책/세금 문구 누수 없음."""
        result = self.sf.fill_slots("consumer_warning_refund", "환불 논란", {})
        text = " ".join(str(v) for v in result["slots"].values())
        self.assertNotIn("홈택스", text, "consumer_warning에 홈택스 문구 누수")
        self.assertNotIn("환급금 조회", text, "consumer_warning에 환급금 조회 누수")

    def test_platform_change_avoids_consumer_phrases(self):
        """platform_change에 환불/소비자 피해 표현 과다 누수 없음."""
        result = self.sf.fill_slots("platform_change_service_update", "서비스 종료", {})
        text = " ".join(str(v) for v in result["slots"].values())
        # 일부 "환불"은 platform_change 컨텍스트에서도 가능하지만 "환불 거부", "소비자 피해" 같은 강한 표현은 없어야 함
        self.assertNotIn("환불 거부", text)


class TestEvergreenStillBlocked(unittest.TestCase):
    """slot builder 추가가 evergreen 차단을 약화시키지 않음."""

    def test_generic_fallback_still_used_for_unknown_pattern(self):
        sf = SlotFillerService()
        result = sf.fill_slots("nonexistent_pattern_xyz", "테스트", {})
        # nonexistent pattern은 generic fallback → 슬롯이 잘 안 채워짐
        # 또는 pattern not found 에러 반환
        # 핵심은 새 builder가 우연히 unknown pattern을 처리하지 않는 것
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
