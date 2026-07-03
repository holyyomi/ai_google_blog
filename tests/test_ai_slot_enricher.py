from __future__ import annotations

import json
import unittest

from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm


class _FakeLlm:
    """가짜 LLM — 받은 프롬프트를 기록하고 준비된 JSON을 돌려준다."""

    def __init__(self, response: dict | None, facts: str = "") -> None:
        self._response = response
        self._facts = facts
        self.prompts: list[str] = []
        self.facts_calls = 0

    def gather_facts(self, topic: str) -> str:
        self.facts_calls += 1
        return self._facts

    def call_with_fallback(self, user_prompt, system_prompt=None, min_chars=0, validator=None):
        self.prompts.append(user_prompt)
        if self._response is None:
            return None
        text = json.dumps(self._response, ensure_ascii=False)
        if validator is not None:
            validator(text)
        return text


_BASE_RESPONSE = {
    "hook_opening": "노션 자동화에 시간을 쓰는 팀이 늘고 있다. 반복 입력을 줄이는 설정이 핵심이다. 이 글은 그 순서를 정리한다.",
    "yomi_judgment": "핵심은 데이터베이스 수식과 반복 템플릿이다. 이 두 가지만 잡아도 입력 시간이 크게 준다.",
    "faq": [
        {"Q": "무료 플랜으로 되나?", "A": "개인 사용 범위에서는 충분하다."},
        {"Q": "수식이 어렵지 않나?", "A": "dateBetween 등 기본 함수 3개면 시작할 수 있다."},
        {"Q": "팀 적용은?", "A": "권한 설정 후 템플릿 공유로 시작한다."},
    ],
}


def _slots() -> dict:
    return {"hook_opening": "정적 훅", "yomi_judgment": "정적 판단", "faq": []}


class TestFactInjection(unittest.TestCase):
    def test_facts_are_injected_into_prompt(self):
        llm = _FakeLlm(_BASE_RESPONSE, facts="[뉴스] 노션이 2026년 6월 신규 수식 v3를 출시했다.")
        enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertEqual(llm.facts_calls, 1)
        self.assertIn("웹 검색으로 수집한 최신 근거", llm.prompts[0])
        self.assertIn("신규 수식 v3", llm.prompts[0])
        self.assertIn("근거에 없는 수치는 단정하지 말 것", llm.prompts[0])

    def test_no_facts_still_generates(self):
        llm = _FakeLlm(_BASE_RESPONSE, facts="")
        out = enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertNotIn("웹 검색으로 수집한 최신 근거", llm.prompts[0])
        self.assertNotEqual(out["hook_opening"], "정적 훅")

    def test_fact_failure_is_nonfatal(self):
        llm = _FakeLlm(_BASE_RESPONSE)
        llm.gather_facts = lambda topic: (_ for _ in ()).throw(RuntimeError("search down"))
        out = enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertNotEqual(out["hook_opening"], "정적 훅")


class TestGeoBlockKeys(unittest.TestCase):
    def test_llm_geo_blocks_extracted(self):
        response = dict(_BASE_RESPONSE)
        response["citation_summary"] = (
            "노션 자동화의 핵심은 데이터베이스 수식과 반복 템플릿이다. "
            "dateBetween 함수로 마감일 추적을 자동화할 수 있다. "
            "무료 플랜에서도 개인 사용 범위는 충분히 커버된다."
        )
        response["target_reader"] = "주간 보고서와 프로젝트 마감일을 노션에서 직접 관리하는 팀 실무자에게 필요한 글이다. 특히 반복 입력에 시간을 쓰는 사람에게 맞다."
        response["confirmed_facts"] = ["노션 무료 플랜은 개인 블록 무제한이다.", "수식 속성은 무료 플랜에서도 지원된다."]
        response["check_needed"] = ["팀 플랜 인당 요금은 변경될 수 있다.", "API 호출 한도는 플랜별로 다르다."]
        llm = _FakeLlm(response)
        out = enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertIn("dateBetween", out["_llm_citation_summary"])
        self.assertIn("팀 실무자", out["_llm_target_reader"])
        self.assertEqual(len(out["_llm_confirmed"]), 2)
        self.assertEqual(len(out["_llm_check_needed"]), 2)

    def test_short_or_missing_geo_blocks_are_skipped(self):
        llm = _FakeLlm(dict(_BASE_RESPONSE, citation_summary="너무 짧음", confirmed_facts=["하나뿐"]))
        out = enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertNotIn("_llm_citation_summary", out)
        self.assertNotIn("_llm_confirmed", out)


class TestFallbackUnchanged(unittest.TestCase):
    def test_llm_none_returns_original_slots(self):
        llm = _FakeLlm(None)
        slots = _slots()
        out = enrich_slots_with_llm(slots=slots, topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertEqual(out, slots)


if __name__ == "__main__":
    unittest.main()
