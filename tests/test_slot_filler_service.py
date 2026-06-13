from __future__ import annotations

import unittest

from blogspot_automation.services.slot_filler_service import SlotFillerService

_GLOBAL_BANNED_PHRASES = [
    "이 이슈는 나와 직접 관련이 없다",
    "정보가 너무 많음",
    "공식 안내를 확인한다",
    "오늘 내 선택 기준",
]


def _slots_to_text(slots: dict) -> str:
    """모든 슬롯 값을 하나의 문자열로 변환 — banned phrase 검사용."""
    parts: list[str] = []
    for v in slots.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.extend(str(vv) for vv in item.values())
        elif isinstance(v, dict):
            parts.extend(str(vv) for vv in v.values())
    return " ".join(parts)


class TestSlotFillerService(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = SlotFillerService()

    # ------------------------------------------------------------------ #
    # 3개 패턴 슬롯 채움률 >= 0.8                                           #
    # ------------------------------------------------------------------ #

    def test_tax_refund_fill_rate(self) -> None:
        result = self.svc.fill_slots(
            "tax_refund_hometax_check",
            "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
        )
        self.assertGreaterEqual(
            result["slot_fill_rate"], 0.8,
            f"fill_rate={result['slot_fill_rate']} missing={result['missing_required_slots']}",
        )

    def test_viral_ott_fill_rate(self) -> None:
        result = self.svc.fill_slots(
            "viral_ott_reaction_decode",
            "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지",
        )
        self.assertGreaterEqual(
            result["slot_fill_rate"], 0.8,
            f"fill_rate={result['slot_fill_rate']} missing={result['missing_required_slots']}",
        )

    def test_viral_slots_are_topic_aware_not_fixed_netflix_drama(self) -> None:
        result = self.svc.fill_slots(
            "viral_ott_reaction_decode",
            "티빙 개인정보가 화제 된 반응이 갈린 이유",
        )
        text = _slots_to_text(result["slots"])
        self.assertIn("티빙 개인정보", text)
        for phrase in ("같은 드라마", "넷플릭스 1위", "완주율 기반 판단", "2화까지"):
            self.assertNotIn(phrase, text)

    def test_ai_work_fill_rate(self) -> None:
        result = self.svc.fill_slots(
            "ai_work_time_savings",
            "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유",
        )
        self.assertGreaterEqual(
            result["slot_fill_rate"], 0.8,
            f"fill_rate={result['slot_fill_rate']} missing={result['missing_required_slots']}",
        )

    # ------------------------------------------------------------------ #
    # 알 수 없는 pattern_id 안전 처리                                       #
    # ------------------------------------------------------------------ #

    def test_unknown_pattern_safe(self) -> None:
        result = self.svc.fill_slots("nonexistent_pattern_xyz", "테스트 주제")
        self.assertIn("error", result)
        self.assertEqual(result["slot_fill_rate"], 0.0)
        self.assertEqual(result["slots"], {})
        self.assertEqual(result["required_slots"], [])

    # ------------------------------------------------------------------ #
    # default banned phrase 미포함 확인                                     #
    # ------------------------------------------------------------------ #

    def test_no_global_banned_phrases(self) -> None:
        cases = [
            ("tax_refund_hometax_check", "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"),
            ("viral_ott_reaction_decode", "넷플릭스 신작 반응이 갈린 이유"),
            ("ai_work_time_savings", "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"),
        ]
        for pattern_id, topic in cases:
            with self.subTest(pattern_id=pattern_id):
                result = self.svc.fill_slots(pattern_id, topic)
                all_text = _slots_to_text(result["slots"])
                for phrase in _GLOBAL_BANNED_PHRASES:
                    self.assertNotIn(
                        phrase, all_text,
                        f"[{pattern_id}] banned phrase found: '{phrase}'",
                    )

    def test_no_pattern_banned_phrases(self) -> None:
        cases = [
            ("tax_refund_hometax_check", "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"),
            ("viral_ott_reaction_decode", "넷플릭스 신작 반응이 갈린 이유"),
            ("ai_work_time_savings", "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"),
        ]
        for pattern_id, topic in cases:
            with self.subTest(pattern_id=pattern_id):
                result = self.svc.fill_slots(pattern_id, topic)
                all_text = _slots_to_text(result["slots"])
                from blogspot_automation.services.golden_pattern_service import GoldenPatternService
                banned = GoldenPatternService().get_banned_default_phrases(pattern_id)
                for phrase in banned:
                    self.assertNotIn(
                        phrase, all_text,
                        f"[{pattern_id}] pattern-banned phrase found: '{phrase}'",
                    )

    # ------------------------------------------------------------------ #
    # get_missing_required_slots 정상 동작                                 #
    # ------------------------------------------------------------------ #

    def test_get_missing_required_slots(self) -> None:
        slots = {
            "hook_opening": "내용 있음",
            "yomi_judgment": "",
            "misconceptions": [],
        }
        required = ["hook_opening", "yomi_judgment", "misconceptions", "faq"]
        missing = self.svc.get_missing_required_slots(slots, required)
        self.assertNotIn("hook_opening", missing)
        self.assertIn("yomi_judgment", missing)
        self.assertIn("misconceptions", missing)
        self.assertIn("faq", missing)

    def test_get_missing_required_slots_none_value(self) -> None:
        slots = {"a": None, "b": "값", "c": {}}
        required = ["a", "b", "c"]
        missing = self.svc.get_missing_required_slots(slots, required)
        self.assertIn("a", missing)
        self.assertNotIn("b", missing)
        self.assertIn("c", missing)

    # ------------------------------------------------------------------ #
    # calculate_slot_fill_rate 정상 동작                                   #
    # ------------------------------------------------------------------ #

    def test_calculate_slot_fill_rate_half(self) -> None:
        slots = {"a": "값", "b": "", "c": ["항목"], "d": None}
        required = ["a", "b", "c", "d"]
        rate = self.svc.calculate_slot_fill_rate(slots, required)
        self.assertAlmostEqual(rate, 0.5)

    def test_calculate_slot_fill_rate_all_filled(self) -> None:
        slots = {"a": "텍스트", "b": [1, 2], "c": {"k": "v"}}
        required = ["a", "b", "c"]
        self.assertAlmostEqual(
            self.svc.calculate_slot_fill_rate(slots, required), 1.0
        )

    def test_calculate_slot_fill_rate_empty_required(self) -> None:
        self.assertAlmostEqual(
            self.svc.calculate_slot_fill_rate({}, []), 1.0
        )

    def test_calculate_slot_fill_rate_all_missing(self) -> None:
        slots = {"a": "", "b": [], "c": None}
        required = ["a", "b", "c"]
        self.assertAlmostEqual(
            self.svc.calculate_slot_fill_rate(slots, required), 0.0
        )

    # ------------------------------------------------------------------ #
    # fill_slots 반환 구조 검증                                             #
    # ------------------------------------------------------------------ #

    def test_fill_slots_result_structure(self) -> None:
        result = self.svc.fill_slots(
            "tax_refund_hometax_check", "홈택스 환급금 테스트"
        )
        required_keys = [
            "pattern_id", "topic", "slots", "required_slots",
            "filled_required_slots", "missing_required_slots",
            "slot_fill_rate", "fill_strategy",
        ]
        for k in required_keys:
            self.assertIn(k, result, f"key '{k}' missing from result")

    def test_fill_slots_yomi_judgment_contains_marker(self) -> None:
        for pattern_id, topic in [
            ("tax_refund_hometax_check", "홈택스 환급금"),
            ("viral_ott_reaction_decode", "넷플릭스 반응"),
            ("ai_work_time_savings", "ChatGPT 직장인"),
        ]:
            with self.subTest(pattern_id=pattern_id):
                result = self.svc.fill_slots(pattern_id, topic)
                yomi = result["slots"].get("yomi_judgment", "")
                self.assertIn(
                    "요미 판단:", yomi,
                    f"[{pattern_id}] yomi_judgment missing '요미 판단:' marker",
                )

    def test_fill_slots_with_candidate_raw(self) -> None:
        raw = {"search_demand_topic": "홈택스 환급 조회", "topic_group": "policy_benefit"}
        result = self.svc.fill_slots(
            "tax_refund_hometax_check",
            "세금 환급금 조회",
            candidate_raw=raw,
        )
        self.assertGreaterEqual(result["slot_fill_rate"], 0.8)

    def test_fill_slots_filled_and_missing_consistency(self) -> None:
        result = self.svc.fill_slots(
            "tax_refund_hometax_check", "홈택스 환급"
        )
        total = len(result["required_slots"])
        filled = len(result["filled_required_slots"])
        missing = len(result["missing_required_slots"])
        self.assertEqual(filled + missing, total)


if __name__ == "__main__":
    unittest.main()
