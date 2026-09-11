"""AI 주제 이탈 + 제목 표기 통일 회귀 테스트 (2026-09-11).

두 구멍을 막는다 — 둘 다 실제 발행/리허설 산출물에서 확인된 것이다.

1. **AI 주제 이탈**: 2026-09-10 저녁 슬롯이 발행한 글의 제목은
   "Volvo EX40 Price Range 2026", 소제목은 "what the spec databases show
   about the ex40" / "what the verified specs mean for a buyer" — AI
   블로그에 올라간 전기차 구매가이드였다. 원본 헤드라인 꼬리에 붙은
   "and Gemini AI" 하나로 AI 주제 판정을 통과했고, topic_engine_score 49 ·
   topic_candidate_grade D · article_focus 68 이었는데도 자동발행됐다.

2. **제목 표기 통일 누락**: normalize_english_title이 select_best_title
   한 곳에만 걸려 있어서 (a) LLM이 만든 제목과 (b) 후보가 전부 막혔을 때의
   검색어 원문 폴백이 정규화를 건너뛰었다. 리허설 실측 제목:
   "copilot how to use agents: Publishing for Organizations 2026".
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm


_VOLVO_HTML = """
<article>
  <h2>The short answer</h2>
  <p>Volvo has cancelled the EX40 in the US market.</p>
  <h2>What the spec databases show about the ex40</h2>
  <p>Range and battery figures differ by trim.</p>
  <h2>Naming change tracked in monitoring project</h2>
  <h2>What remains unconfirmed</h2>
  <h2>What the verified specs mean for a buyer</h2>
</article>
"""

_AI_ARTICLE_HTML = """
<article>
  <h2>The short answer</h2>
  <h2>What changed in the pricing tiers</h2>
  <h2>How the new model compares</h2>
</article>
"""


class AiSubjectDriftGateTest(unittest.TestCase):
    def test_car_buying_guide_is_detected_as_non_ai_subject(self):
        self.assertTrue(
            NewsPipeline._looks_like_non_ai_subject_article(
                title="Volvo EX40 Price Range 2026", html=_VOLVO_HTML
            )
        )

    def test_substring_ai_inside_ordinary_words_is_not_an_ai_signal(self):
        """'remains'/'email'/'available'의 'ai'를 AI 신호로 세면 안 된다.

        단순 부분문자열 검사를 쓰면 Volvo 글의 소제목 "what remains
        unconfirmed"만으로 통과해버린다 — 이 테스트가 그 회귀를 막는다.
        """
        self.assertTrue(
            NewsPipeline._looks_like_non_ai_subject_article(
                title="Volvo EX40 Price Range 2026",
                html="<h2>What remains unconfirmed</h2><h2>Email the dealer</h2>",
            )
        )

    def test_real_ai_article_passes(self):
        self.assertFalse(
            NewsPipeline._looks_like_non_ai_subject_article(
                title="Anthropic Claude Pricing Changes 2026", html=_AI_ARTICLE_HTML
            )
        )

    def test_ai_signal_in_headings_alone_is_enough(self):
        self.assertFalse(
            NewsPipeline._looks_like_non_ai_subject_article(
                title="Volvo EX40 Price Range 2026",
                html="<h2>How the onboard assistant uses Gemini</h2><h2>Price</h2>",
            )
        )

    def test_missing_headings_means_no_evidence_so_no_block(self):
        """소제목을 못 뽑으면 본문 주제를 읽을 근거가 없다 → 차단하지 않는다."""
        self.assertFalse(
            NewsPipeline._looks_like_non_ai_subject_article(
                title="Volvo EX40 Price Range 2026", html="<p>no headings here</p>"
            )
        )

    def test_korean_era_titles_are_not_false_positives(self):
        """한국어 시절 발행글(회사 별칭이 2자 한글)이 오탐되면 안 된다."""
        self.assertFalse(
            NewsPipeline._looks_like_non_ai_subject_article(
                title="메타 라마 스피크 1.1 API 활용 핵심 3가지",
                html="<h2>라마 스피크란</h2><h2>요금</h2>",
            )
        )

    def test_gate_blocks_auto_publish_for_non_ai_subject(self):
        pipeline = NewsPipeline.__new__(NewsPipeline)
        pipeline.auto_publish = True
        base_result = {
            "selected_title": "Volvo EX40 Price Range 2026",
            "selected_topic": (
                "Volvo cancels EX40 in the US, updates XC40 with better "
                "sensors and Gemini AI"
            ),
            "topic_group": "ai_work",
            "content_angle": {"content_type": "ai_work_tip"},
            "source_type": "google_news_rss",
            "article_candidate_generated": True,
            "publish_ready": True,
            "geo_ready": True,
            "sge_ready": True,
        }
        with mock.patch.object(
            NewsPipeline, "_ai_blog_mode_enabled", staticmethod(lambda: True)
        ):
            result = pipeline._evaluate_auto_publish_gate(
                base_result=base_result,
                publish_quality_gate={"passed": True},
                html=_VOLVO_HTML,
            )
        self.assertIn("article_subject_is_not_ai", result["blocking_reasons"])
        self.assertFalse(result["allowed"])


class _FakeLlm:
    """가짜 LLM — 준비된 JSON을 그대로 돌려준다(tests/test_ai_slot_enricher.py와 동형)."""

    def __init__(self, response: dict) -> None:
        self._response = response

    def gather_facts(self, topic: str) -> str:
        return ""

    def call_with_fallback(self, user_prompt, system_prompt=None, min_chars=0, validator=None):
        text = json.dumps(self._response, ensure_ascii=False)
        if validator is not None:
            validator(text)
        return text


_LLM_RESPONSE = {
    "hook_opening": (
        "Copilot agents now ship to organizations on a staged schedule. "
        "Admins decide who can publish them. This guide walks that setup."
    ),
    "yomi_judgment": (
        "The publishing switch is an admin control, not a user setting. "
        "Check the tenant policy before you build anything."
    ),
    "faq": [
        {"Q": "Is publishing on by default?", "A": "No, an admin enables it per tenant."},
        {"Q": "Do agents cost extra?", "A": "Licensed seats cover the published agents."},
        {"Q": "Can I limit the audience?", "A": "Yes, publishing targets a group."},
    ],
    "real_criterion": (
        "Step 1: confirm the tenant policy.\n"
        "Step 2: publish the agent to a pilot group.\n"
        "Step 3: review usage before a wider rollout."
    ),
    "misconceptions": [
        {"착각": "Anyone can publish an agent", "실제": "Publishing is an admin-gated action"},
        {"착각": "Published agents are public", "실제": "They are scoped to the chosen group"},
        {"착각": "No review is needed", "실제": "Usage should be reviewed before wider rollout"},
    ],
}


class LlmTitleNormalizationTest(unittest.TestCase):
    def test_llm_title_is_case_normalized_before_adoption(self):
        """LLM 제목 채택 경로가 normalize_english_title을 건너뛰면 안 된다.

        2026-09-10 리허설 실측 제목이 그대로 재현 입력이다.
        """
        response = dict(
            _LLM_RESPONSE,
            title="copilot how to use agents: publishing for organizations 2026",
        )
        out = enrich_slots_with_llm(
            slots={"hook_opening": "static", "yomi_judgment": "static", "faq": []},
            topic="copilot how to use agents",
            content_type="ai_work_tip",
            llm_service=_FakeLlm(response),
        )
        title = out.get("_llm_title")
        self.assertTrue(title, "LLM 제목이 채택되지 않았다")
        self.assertTrue(title[0].isupper(), f"소문자 제목이 그대로 채택됐다: {title}")
        self.assertIn("Copilot", title)

    def test_korean_llm_title_is_left_alone(self):
        response = dict(_LLM_RESPONSE, title="노션 자동화, 반복 입력 줄이는 설정 순서")
        out = enrich_slots_with_llm(
            slots={"hook_opening": "static", "yomi_judgment": "static", "faq": []},
            topic="노션 자동화",
            content_type="ai_work_tip",
            llm_service=_FakeLlm(response),
        )
        self.assertEqual(out.get("_llm_title"), "노션 자동화, 반복 입력 줄이는 설정 순서")

    def test_build_title_fallback_normalizes_raw_search_query(self):
        """후보가 전부 막혀 검색어 원문으로 폴백해도 소문자로 나가면 안 된다."""
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline

        pipeline = AiTopicPipeline.__new__(AiTopicPipeline)

        class _Svc:
            @staticmethod
            def generate_candidates(**_kwargs):
                return {"best_title": {}}

        pipeline.title_candidate_service = _Svc()
        _tr, selected_title, _ctr = pipeline._build_title(
            topic="chatgpt free version attachment limits 2026",
            ct="ai_work_tip",
            tg="ai_work",
            pattern_id="ai_work_time_savings",
            raw_candidate={},
        )
        self.assertTrue(
            selected_title[0].isupper(),
            f"검색어 원문이 소문자 그대로 제목이 됐다: {selected_title}",
        )
        self.assertIn("ChatGPT", selected_title)


if __name__ == "__main__":
    unittest.main()
