from __future__ import annotations

import re
import unittest

from blogspot_automation.services.golden_article_preview_service import (
    GoldenArticlePreviewService,
)

_BANNED_PHRASES = [
    "이 이슈는 나와 직접 관련이 없다",
    "정보가 너무 많음",
    "오늘 내 선택 기준이 됩니다",
    "나와 관련 있는지",
    "공식 안내를 확인한다",
    "공식 확인처를 확인한다",
    "행동 필요한지 모름",
    "내 생활과 관련있는지 모름",
    "지금 행동이 필요한지 모름",
]

# 뉴스 패턴 라벨 / AI 패턴 라벨 (Phase A: AI는 가이드형 라벨로 분기)
_REQUIRED_MARKERS_NEWS = [
    "핵심 관점",
    "흔한 착각",
    "30초 판단표",
    "바로 할 행동",
]
_REQUIRED_MARKERS_AI = [
    "결론부터 말하면",
    "자주 하는 오해와 실제",
    "상황별 추천",
    "지금 바로 해보기",
]

_FAQ_MARKERS = ["빠른 확인 답변", "자주 묻는 질문", "피해 대응 전 많이 묻는 질문", "신청 전 확인 질문", "많이 묻는 질문"]

_THREE_PATTERNS = [
    ("세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", "tax_refund_hometax_check"),
    ("넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지", "viral_ott_reaction_decode"),
    ("직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유", "ai_work_time_savings"),
]


def _render_article_candidate_html(
    *,
    topic: str = "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지",
    content_type: str = "viral_issue_decode",
    topic_group: str = "ott_platform",
) -> str:
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService

    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    pattern_match = ps.match_pattern(topic=topic, content_type=content_type, topic_group=topic_group)
    slot_result = sf.fill_slots(pattern_id=str(pattern_match.get("pattern_id")), topic=topic)
    return svc.render_article_candidate_html(pattern_match, slot_result, selected_title=topic)


class TestGoldenArticlePreviewService(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = GoldenArticlePreviewService()

    # ------------------------------------------------------------------ #
    # 작업 C — 3개 패턴 ready_for_review=True                              #
    # ------------------------------------------------------------------ #

    def test_tax_refund_ready_for_review(self) -> None:
        result = self.svc.build_preview(
            topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        )
        self.assertTrue(result["matched"], "matched should be True")
        self.assertTrue(
            result["ready_for_review"],
            f"ready_for_review=False issues={result['blocking_issues']}",
        )

    def test_viral_ott_ready_for_review(self) -> None:
        result = self.svc.build_preview(
            topic="넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지"
        )
        self.assertTrue(result["matched"])
        self.assertTrue(
            result["ready_for_review"],
            f"ready_for_review=False issues={result['blocking_issues']}",
        )

    def test_ai_work_ready_for_review(self) -> None:
        result = self.svc.build_preview(
            topic="직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"
        )
        self.assertTrue(result["matched"])
        self.assertTrue(
            result["ready_for_review"],
            f"ready_for_review=False issues={result['blocking_issues']}",
        )

    # ------------------------------------------------------------------ #
    # 작업 D — unmatched topic                                             #
    # ------------------------------------------------------------------ #

    def test_unmatched_topic_not_ready(self) -> None:
        result = self.svc.build_preview(topic="배달료 논란")
        self.assertFalse(result["matched"])
        self.assertFalse(result["ready_for_review"])
        bi = result["blocking_issues"]
        self.assertTrue(
            any("pattern_not_matched" in i or "low_pattern_confidence" in i for i in bi),
            f"blocking_issues should mention pattern_not_matched or low_pattern_confidence: {bi}",
        )

    def test_unmatched_html_is_minimal(self) -> None:
        result = self.svc.build_preview(topic="배달료 논란")
        html = result["preview_html"]
        self.assertIn("배달료 논란", html)
        # 슬롯 기반 섹션이 없어야 함
        self.assertNotIn("yomi-judgment-box", html)
        self.assertNotIn("misconception-box", html)

    # ------------------------------------------------------------------ #
    # 작업 E — banned phrase 없음                                          #
    # ------------------------------------------------------------------ #

    def test_no_banned_phrases_in_preview_html(self) -> None:
        for topic, _ in _THREE_PATTERNS:
            with self.subTest(topic=topic):
                result = self.svc.build_preview(topic=topic)
                html = result["preview_html"]
                for phrase in _BANNED_PHRASES:
                    self.assertNotIn(
                        phrase, html,
                        f"[{topic}] banned phrase found: '{phrase}'",
                    )

    # ------------------------------------------------------------------ #
    # 작업 C 상세 — 각 preview_html에 필수 마커 포함                        #
    # ------------------------------------------------------------------ #

    def test_required_markers_in_preview_html(self) -> None:
        for topic, pattern_id in _THREE_PATTERNS:
            with self.subTest(topic=topic):
                result = self.svc.build_preview(topic=topic)
                html = result["preview_html"]
                markers = (
                    _REQUIRED_MARKERS_AI
                    if str(pattern_id).startswith("ai_")
                    else _REQUIRED_MARKERS_NEWS
                )
                for marker in markers:
                    self.assertIn(
                        marker, html,
                        f"[{topic}] required marker missing: '{marker}'",
                    )
                self.assertTrue(
                    any(marker in html for marker in _FAQ_MARKERS),
                    f"[{topic}] FAQ marker missing",
                )

    def test_viral_preview_uses_search_phrase_heading_not_duplicate_faq_heading(self) -> None:
        html = _render_article_candidate_html()

        self.assertIn("빠른 확인 답변", html)
        self.assertIn("관련 검색어", html)
        self.assertNotIn("관련 검색 질문", html)
        self.assertNotIn("신청 전 많이 묻는 질문", html)
        self.assertNotIn("함께 확인할 질문", html)
        self.assertIn("출처와 확인 기준", html)

    def test_people_also_ask_questions_do_not_repeat_intent_questions(self) -> None:
        html = _render_article_candidate_html()
        intent_questions = {
            re.sub(r"[^0-9A-Za-z가-힣]+", "", q.lower())
            for q in re.findall(r'class="intent-qa-item"><h3>Q\. (.*?)</h3>', html)
        }
        paa_questions = {
            re.sub(r"[^0-9A-Za-z가-힣]+", "", q.lower())
            for q in re.findall(r'class="paa-item">(.*?)</li>', html)
        }

        self.assertGreaterEqual(len(paa_questions), 5)
        self.assertFalse(intent_questions & paa_questions)

    def test_money_article_paa_does_not_use_viral_reaction_fallback(self) -> None:
        html = _render_article_candidate_html(
            topic="무료배송인데 결제금액이 커질 때 확인할 것",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        paa_items = re.findall(r'class="paa-item">(.*?)</li>', html)

        self.assertGreaterEqual(len(paa_items), 5)
        self.assertFalse([item for item in paa_items if item.endswith(("가요", "나요", "하나요", "되나요", "인가요", "하는지", "되는지", "인지", "한지")) or "?" in item])
        self.assertIn("무료배송 결제금액 비교 기준", html)
        self.assertIn("쿠폰 적용 후 최종금액 비교", html)
        self.assertIn("최소주문금액 미달 조건", html)
        self.assertNotIn("반응이 갈린 이유", html)
        self.assertNotIn("보기 전에 확인할 핵심 포인트", html)

    # ------------------------------------------------------------------ #
    # 2026-07-16 회귀 — 실제 검색 인용 URL이 official_sources.py의 빈 매핑을 대체 #
    # ------------------------------------------------------------------ #

    def test_ai_pattern_without_llm_citations_has_no_source_links(self) -> None:
        # ai_work_time_savings는 official_sources.py에 빈 튜플로 매핑돼 있어
        # (한국 정부기관 URL이 있을 수 없는 AI 뉴스이므로) 실제 인용 URL이 없으면
        # SOURCE_TRUST_BLOCK에 링크가 생기지 않는 것이 맞다(조작 링크 금지).
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService

        ps = GoldenPatternService()
        sf = SlotFillerService()
        topic = "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"
        pattern_match = ps.match_pattern(topic=topic, content_type="ai_work_tip", topic_group="ai_work")
        slot_result = sf.fill_slots(pattern_id=str(pattern_match.get("pattern_id")), topic=topic)

        html = self.svc.render_article_candidate_html(pattern_match, slot_result, selected_title=topic)

        source_block = html.split('id="SOURCE_TRUST_BLOCK"')[1].split("</section>")[0]
        self.assertNotIn("<a href=", source_block)

    def test_ai_pattern_with_llm_citations_gets_real_source_links(self) -> None:
        # ai_slot_enricher가 Naver/Exa에서 실제로 얻은 인용 URL을
        # slots["_llm_source_citations"]에 담아 넘기면, official_sources.py의
        # 빈 매핑 대신 그 실제 링크가 SOURCE_TRUST_BLOCK에 렌더링돼야 한다.
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService

        ps = GoldenPatternService()
        sf = SlotFillerService()
        topic = "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"
        pattern_match = ps.match_pattern(topic=topic, content_type="ai_work_tip", topic_group="ai_work")
        slot_result = sf.fill_slots(pattern_id=str(pattern_match.get("pattern_id")), topic=topic)
        slot_result["slots"]["_llm_source_citations"] = [
            {"name": "관련 보도 A", "url": "https://news.example.com/a"},
            {"name": "관련 보도 B", "url": "https://news.example.com/b"},
        ]

        html = self.svc.render_article_candidate_html(pattern_match, slot_result, selected_title=topic)

        source_block = html.split('id="SOURCE_TRUST_BLOCK"')[1].split("</section>")[0]
        self.assertIn('href="https://news.example.com/a"', source_block)
        self.assertIn('href="https://news.example.com/b"', source_block)

    def test_llm_citations_with_bad_scheme_are_ignored(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService

        ps = GoldenPatternService()
        sf = SlotFillerService()
        topic = "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유"
        pattern_match = ps.match_pattern(topic=topic, content_type="ai_work_tip", topic_group="ai_work")
        slot_result = sf.fill_slots(pattern_id=str(pattern_match.get("pattern_id")), topic=topic)
        slot_result["slots"]["_llm_source_citations"] = [
            {"name": "잘못된 스킴", "url": "javascript:alert(1)"},
            {"name": "", "url": "https://news.example.com/no-name"},
        ]

        html = self.svc.render_article_candidate_html(pattern_match, slot_result, selected_title=topic)

        source_block = html.split('id="SOURCE_TRUST_BLOCK"')[1].split("</section>")[0]
        self.assertNotIn("<a href=", source_block)

    # ------------------------------------------------------------------ #
    # 작업 F — 빈 슬롯은 섹션 미출력                                        #
    # ------------------------------------------------------------------ #

    def test_empty_slot_section_not_rendered(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService

        ps = GoldenPatternService()
        pattern_match = ps.match_pattern(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")

        # hook_opening을 의도적으로 비움
        slot_result = {
            "topic": "테스트",
            "slot_fill_rate": 0.5,
            "missing_required_slots": ["hook_opening"],
            "slots": {
                "hook_opening": "",
                "yomi_judgment": "요미의 판단 테스트 내용입니다.",
                "misconceptions": [],
                "real_criterion": "",
                "quick_decision_table": [],
                "actions": [],
                "faq": [],
                "hashtags": [],
                "internal_links": [],
            },
        }
        html = self.svc.render_html(pattern_match, slot_result)
        # hook_opening 섹션은 없어야 함 (CSS class selector와 구별하기 위해 section 태그로 검사)
        self.assertNotIn('<section class="preview-hook"', html)
        # yomi_judgment는 있어야 함
        self.assertIn('<section class="yomi-judgment-box"', html)

    # ------------------------------------------------------------------ #
    # 작업 E — validate_preview_html 정상 동작                             #
    # ------------------------------------------------------------------ #

    def test_validate_preview_html_clean(self) -> None:
        result = self.svc.build_preview(
            topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        )
        validation = self.svc.validate_preview_html(result["preview_html"])
        self.assertTrue(validation["valid"], f"issues={validation['issues']}")
        self.assertEqual(validation["issues"], [])

    def test_validate_preview_html_detects_banned_phrase(self) -> None:
        dirty_html = '<h1>테스트</h1><p>이 이슈는 나와 직접 관련이 없다</p>'
        validation = self.svc.validate_preview_html(dirty_html)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("banned_default_phrase" in i for i in validation["issues"]))

    def test_validate_preview_html_missing_h1(self) -> None:
        html = '<p>내용만 있고 h1 없음</p>'
        validation = self.svc.validate_preview_html(html)
        self.assertFalse(validation["valid"])
        self.assertIn("missing_h1", validation["issues"])

    def test_validate_preview_html_warnings_for_missing_sections(self) -> None:
        html = '<h1>제목만 있음</h1>'
        validation = self.svc.validate_preview_html(html)
        # h1은 있으니 issues 없어야 함
        self.assertTrue(validation["valid"])
        # 섹션이 없으니 warnings에 항목이 있어야 함
        self.assertGreater(len(validation["warnings"]), 0)

    # ------------------------------------------------------------------ #
    # 반환 구조 검증                                                        #
    # ------------------------------------------------------------------ #

    def test_build_preview_result_structure(self) -> None:
        result = self.svc.build_preview(
            topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        )
        required_keys = [
            "matched", "pattern_match", "slot_result", "preview_html",
            "slot_fill_rate", "missing_required_slots",
            "ready_for_review", "blocking_issues", "warnings",
        ]
        for k in required_keys:
            self.assertIn(k, result, f"key '{k}' missing from build_preview result")

    def test_fill_rate_in_result(self) -> None:
        for topic, _ in _THREE_PATTERNS:
            with self.subTest(topic=topic):
                result = self.svc.build_preview(topic=topic)
                self.assertGreaterEqual(result["slot_fill_rate"], _MIN_FILL_RATE := 0.8)

    def test_unmatched_slot_fill_rate_zero(self) -> None:
        result = self.svc.build_preview(topic="배달료 논란")
        self.assertEqual(result["slot_fill_rate"], 0.0)

    def test_build_preview_with_candidate_raw(self) -> None:
        raw = {"topic_group": "policy_benefit", "content_type": "tax_refund"}
        result = self.svc.build_preview(
            topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
            candidate_raw=raw,
        )
        self.assertTrue(result["ready_for_review"])


if __name__ == "__main__":
    unittest.main()
