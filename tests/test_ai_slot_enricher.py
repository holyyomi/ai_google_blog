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
    # 검증기 필수 키(2026-07-10 강화): 이 둘이 빠지면 정적 템플릿의 ChatGPT 문구가
    # 부분 잔존해 ai_generic_chatgpt_template_leaked 게이트에 걸린다.
    "real_criterion": "1단계: 반복 입력 데이터베이스를 템플릿화한다.\n2단계: 수식으로 상태 필드를 자동 계산한다.\n3단계: 주간 리뷰 뷰를 저장해 재사용한다.",
    "misconceptions": [
        {"착각": "노션 자동화는 유료 플랜 전용이다", "실제": "무료 플랜에서도 템플릿·수식 자동화는 동작한다"},
        {"착각": "수식은 개발자만 쓸 수 있다", "실제": "기본 함수 3개로 대부분의 반복 계산을 대체할 수 있다"},
        {"착각": "자동화하면 검수가 필요 없다", "실제": "초기 2주는 수동 결과와 비교 검증이 필요하다"},
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


class _FakeLlmWithCitations(_FakeLlm):
    """gather_facts_with_citations를 지원하는 최신 LlmContentService를 흉내낸다."""

    def __init__(self, response: dict | None, facts: str = "", citations: list | None = None) -> None:
        super().__init__(response, facts=facts)
        self._citations = citations or []

    def gather_facts_with_citations(self, topic: str):
        self.facts_calls += 1
        return self._facts, self._citations


class TestSourceCitationPlumbing(unittest.TestCase):
    # 2026-07-16 회귀: llm_service가 gather_facts_with_citations를 지원하면 실제
    # 검색 URL을 enriched["_llm_source_citations"]로 넘겨 SOURCE_TRUST_BLOCK
    # 렌더러가 진짜 <a href> 인용 링크를 만들 수 있게 해야 한다.
    def test_real_citations_are_forwarded_when_available(self):
        llm = _FakeLlmWithCitations(
            _BASE_RESPONSE,
            facts="[뉴스] 요금 변경 발표.",
            citations=[
                {"name": "보도 A", "url": "https://news.example.com/a"},
                {"name": "보도 B", "url": "https://news.example.com/b"},
            ],
        )
        out = enrich_slots_with_llm(slots=_slots(), topic="AI 요금", content_type="platform_change", llm_service=llm)
        self.assertEqual(
            out["_llm_source_citations"],
            [
                {"name": "보도 A", "url": "https://news.example.com/a"},
                {"name": "보도 B", "url": "https://news.example.com/b"},
            ],
        )

    def test_single_citation_is_not_forwarded(self):
        # 게이트는 2건 이상을 요구하므로 1건뿐이면 굳이 슬롯에 담지 않는다.
        llm = _FakeLlmWithCitations(
            _BASE_RESPONSE, facts="[뉴스] 요금 변경 발표.",
            citations=[{"name": "보도 A", "url": "https://news.example.com/a"}],
        )
        out = enrich_slots_with_llm(slots=_slots(), topic="AI 요금", content_type="platform_change", llm_service=llm)
        self.assertNotIn("_llm_source_citations", out)

    def test_non_http_or_empty_name_citations_are_dropped(self):
        llm = _FakeLlmWithCitations(
            _BASE_RESPONSE,
            facts="[뉴스] 요금 변경 발표.",
            citations=[
                {"name": "보도 A", "url": "https://news.example.com/a"},
                {"name": "", "url": "https://news.example.com/no-name"},
                {"name": "잘못된 스킴", "url": "javascript:alert(1)"},
                {"name": "보도 B", "url": "https://news.example.com/b"},
            ],
        )
        out = enrich_slots_with_llm(slots=_slots(), topic="AI 요금", content_type="platform_change", llm_service=llm)
        self.assertEqual(
            out["_llm_source_citations"],
            [
                {"name": "보도 A", "url": "https://news.example.com/a"},
                {"name": "보도 B", "url": "https://news.example.com/b"},
            ],
        )

    def test_old_llm_service_without_citation_support_still_works(self):
        # _FakeLlm(구형/테스트 더블)에는 gather_facts_with_citations가 없다 —
        # hasattr 폴백 경로가 예외 없이 기존처럼 동작해야 한다(하위 호환).
        llm = _FakeLlm(_BASE_RESPONSE, facts="[뉴스] 요금 변경 발표.")
        out = enrich_slots_with_llm(slots=_slots(), topic="AI 요금", content_type="platform_change", llm_service=llm)
        self.assertNotIn("_llm_source_citations", out)
        self.assertEqual(llm.facts_calls, 1)


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

    def test_partial_response_missing_real_criterion_falls_back(self):
        """real_criterion/misconceptions 누락 응답은 검증기에서 불합격 → 원본 슬롯 유지.

        부분 적용을 허용하면 정적 템플릿의 ChatGPT 전용 문구가 비ChatGPT 주제 글에
        남아 ai_generic_chatgpt_template_leaked 게이트에 걸린다 (2026-07-10 실측).
        """
        partial = {k: v for k, v in _BASE_RESPONSE.items() if k not in ("real_criterion", "misconceptions")}
        llm = _FakeLlm(partial)
        slots = _slots()
        out = enrich_slots_with_llm(slots=slots, topic="네이버 AI 소식", content_type="ai_work_tip", llm_service=llm)
        self.assertEqual(out, slots)


class TestAngleFocus(unittest.TestCase):
    def test_angle_type_overrides_content_type_focus(self):
        llm = _FakeLlm(_BASE_RESPONSE)
        enrich_slots_with_llm(
            slots=_slots(), topic="챗GPT 요금 개편", content_type="ai_work_tip",
            angle_type="money_compare", llm_service=llm,
        )
        self.assertIn("무료/유료 선택 기준", llm.prompts[0])
        self.assertNotIn("업무 시간을 줄이는 구체적 방법", llm.prompts[0])

    def test_unknown_angle_falls_back_to_content_type_focus(self):
        llm = _FakeLlm(_BASE_RESPONSE)
        enrich_slots_with_llm(
            slots=_slots(), topic="노션 자동화", content_type="ai_work_tip",
            angle_type="", llm_service=llm,
        )
        self.assertIn("업무 시간을 줄이는 구체적 방법", llm.prompts[0])


class TestLlmTitleIntegrity(unittest.TestCase):
    def test_bad_subject_particle_title_rejected(self):
        """받침 있는 말 + '가' 조사 제목은 채택하지 않는다 — 게이트에서 후보가
        통째로 버려지기 전에 이 지점(유일한 LLM 제목 관문)에서 걸러야 한다."""
        response = dict(_BASE_RESPONSE, title="노션 자동화 설정법가 어려운 이유")
        llm = _FakeLlm(response)
        out = enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertNotIn("_llm_title", out)

    def test_clean_title_accepted(self):
        response = dict(_BASE_RESPONSE, title="노션 자동화, 반복 입력 줄이는 설정 순서")
        llm = _FakeLlm(response)
        out = enrich_slots_with_llm(slots=_slots(), topic="노션 자동화", content_type="ai_work_tip", llm_service=llm)
        self.assertEqual(out.get("_llm_title"), "노션 자동화, 반복 입력 줄이는 설정 순서")


if __name__ == "__main__":
    unittest.main()
