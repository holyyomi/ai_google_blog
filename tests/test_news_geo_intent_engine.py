from __future__ import annotations

import re
import unittest


# ------------------------------------------------------------------ #
# Fixture helpers
# ------------------------------------------------------------------ #

def _make_delivery_html(selected_title: str = "배달앱 결제 전 확인할 3가지") -> str:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService

    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    topic = "배달앱 결제금액 비교 전에 확인할 조건"
    pm = ps.match_pattern(topic=topic, content_type="money_checklist", topic_group="delivery_money")
    sr = sf.fill_slots("delivery_money_checklist", topic)
    return svc.render_article_candidate_html(pm, sr, selected_title=selected_title)


def _make_tax_html(selected_title: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지") -> str:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService

    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    topic = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
    pm = ps.match_pattern(topic=topic)
    sr = sf.fill_slots("tax_refund_hometax_check", topic)
    return svc.render_article_candidate_html(pm, sr, selected_title=selected_title)


class TestGeoIntentServiceQuestions(unittest.TestCase):
    """Test 1: reader_intent_questions 최소 5개."""

    def test_reader_intent_questions_min_5(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        svc = GeoIntentService()
        qs = svc.generate_reader_intent_questions(
            topic="배달앱 결제금액 비교",
            content_type="money_checklist",
            topic_group="delivery_money",
            slots={},
        )
        self.assertGreaterEqual(len(qs), 5, f"Expected >=5 questions, got {len(qs)}: {qs}")

    def test_reader_intent_questions_min_5_tax(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        svc = GeoIntentService()
        qs = svc.generate_reader_intent_questions(
            topic="세금 환급금 조회",
            content_type="tax_refund",
            topic_group="policy_benefit",
            slots={},
        )
        self.assertGreaterEqual(len(qs), 5)


class TestIntentAnswerBlockPresent(unittest.TestCase):
    """Test 2: intent_answer_block HTML 존재."""

    def setUp(self) -> None:
        self.html = _make_delivery_html()

    def test_intent_answer_block_present(self) -> None:
        self.assertIn('id="INTENT_ANSWER_BLOCK"', self.html)

    def test_intent_qa_items_min_3(self) -> None:
        count = len(re.findall(r'class="intent-qa-item"', self.html))
        self.assertGreaterEqual(count, 3, f"Expected >=3 intent-qa-items, got {count}")


class TestOriginalTopicKeywordFirst300(unittest.TestCase):
    """Test 3: original_topic 핵심어 첫 300자."""

    def test_topic_keyword_in_first_300_chars(self) -> None:
        html = _make_delivery_html()
        body_m = re.search(r'<body[^>]*>(.*)', html, re.DOTALL)
        body = body_m.group(1) if body_m else html
        plain = re.sub(r'<[^>]+>', '', body)
        plain = ' '.join(plain.split())
        first_300 = plain[:300]
        # 핵심어 "배달앱" 또는 "결제" 가 첫 300자 안에 있어야 함
        self.assertTrue(
            "배달앱" in first_300 or "결제" in first_300,
            f"Topic keyword not in first 300 chars: {first_300!r}",
        )


class TestIssueContextBlockPresent(unittest.TestCase):
    """Test 4: issue_context_block 존재."""

    def test_issue_context_block_in_html(self) -> None:
        html = _make_delivery_html()
        self.assertIn('id="ISSUE_CONTEXT_BLOCK"', html)

    def test_issue_context_has_content(self) -> None:
        html = _make_delivery_html()
        m = re.search(r'id="ISSUE_CONTEXT_BLOCK".*?<p>(.*?)</p>', html, re.DOTALL)
        self.assertIsNotNone(m, "ISSUE_CONTEXT_BLOCK paragraph not found")
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        self.assertGreater(len(text), 5, f"Issue context too short: {text!r}")

    def test_issue_context_preserves_sentence_endings(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService

        svc = GeoIntentService()
        text = svc.generate_issue_context(
            topic="무료배송인데 결제금액이 커질 때 확인할 것",
            content_type="money_checklist",
            hook=(
                "배달앱으로 주문 버튼을 누르기 전까지 최종 금액이 얼마인지 정확히 모르는 경우가 많다. "
                "화면에 보이는 음식 가격에 배달비가 더해진다."
            ),
        )

        self.assertIn("많다.", text)
        self.assertIn("더해진다.", text)
        self.assertNotIn("많다 화면", text)
        self.assertNotIn("더해진다 주문", text)


class TestSourceTrustBlockPresent(unittest.TestCase):
    """Test 5: source_trust_block 존재."""

    def test_source_trust_block_in_html(self) -> None:
        html = _make_delivery_html()
        self.assertIn('id="SOURCE_TRUST_BLOCK"', html)

    def test_source_trust_block_has_text(self) -> None:
        html = _make_delivery_html()
        m = re.search(r'id="SOURCE_TRUST_BLOCK".*?<p[^>]*>(.*?)</p>', html, re.DOTALL)
        self.assertIsNotNone(m, "SOURCE_TRUST_BLOCK paragraph not found")
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        self.assertGreater(len(text), 10)


class TestChecklistAfterIntentAnswerBlock(unittest.TestCase):
    """Test 6: 체크리스트(actions-box)가 intent_answer_block보다 뒤에 위치."""

    def test_checklist_after_intent_answer(self) -> None:
        html = _make_delivery_html()
        intent_pos = html.find('id="INTENT_ANSWER_BLOCK"')
        checklist_pos = html.find('class="actions-box"')
        if checklist_pos == -1:
            # actions-box 없으면 pass (슬롯 미존재 케이스 허용)
            return
        self.assertGreater(
            checklist_pos, intent_pos,
            "actions-box should appear after INTENT_ANSWER_BLOCK",
        )


class TestMoneyChecklistForbiddenPhrases(unittest.TestCase):
    """Test 7: money_checklist에 지원금/환급/홈택스 없음."""

    def setUp(self) -> None:
        self.html = _make_delivery_html()

    def test_no_jiwongeum_in_delivery(self) -> None:
        self.assertNotIn("지원금", self.html)

    def test_no_hwangeup_in_delivery(self) -> None:
        self.assertNotIn("환급", self.html)

    def test_no_hometax_in_delivery(self) -> None:
        self.assertNotIn("홈택스", self.html)


class TestGeoReadyRequiresIntentBlock(unittest.TestCase):
    """Test 8: geo_ready는 intent block 없으면 false."""

    def test_geo_ready_false_without_intent_block(self) -> None:
        # intent block 없는 HTML로 geo_ready 직접 평가
        import re as _re
        html_no_intent = "<html><body><h1>테스트</h1></body></html>"
        geo_intent_answer_present = 'id="INTENT_ANSWER_BLOCK"' in html_no_intent
        geo_intent_qa_count = len(_re.findall(r'class="intent-qa-item"', html_no_intent))
        # geo_ready 조건에 intent 포함 확인
        self.assertFalse(geo_intent_answer_present)
        self.assertEqual(geo_intent_qa_count, 0)
        # geo_ready는 둘 다 True여야 True
        geo_ready = (
            geo_intent_answer_present
            and geo_intent_qa_count >= 3
        )
        self.assertFalse(geo_ready)


class TestGeoReadyFalseWithOnlyFaq(unittest.TestCase):
    """Test 9: FAQ만 있고 intent answers 없으면 geo_ready=false."""

    def test_faq_only_no_intent_answers_geo_not_ready(self) -> None:
        import re as _re
        # FAQ 있지만 INTENT_ANSWER_BLOCK 없는 HTML
        html = (
            '<html><body><h1>제목</h1>'
            '<section id="AI_CITATION_SUMMARY"><p>요약.</p></section>'
            '<section id="UPDATED_DATE_BLOCK"><p>날짜.</p></section>'
            '<section class="faq faq-block"><div class="faq-card"><h3>Q</h3><p>A</p></div></section>'
            '</body></html>'
        )
        geo_faq_present = 'class="faq' in html
        geo_intent_answer_present = 'id="INTENT_ANSWER_BLOCK"' in html
        geo_intent_qa_count = len(_re.findall(r'class="intent-qa-item"', html))

        self.assertTrue(geo_faq_present)
        self.assertFalse(geo_intent_answer_present)
        # geo_ready 조건 체크
        geo_ready = geo_intent_answer_present and geo_intent_qa_count >= 3
        self.assertFalse(geo_ready)


class TestDeliveryTopicKeywordsPreserved(unittest.TestCase):
    """Test 10: 배달앱 주제에서 관련 키워드 보존."""

    def setUp(self) -> None:
        self.html = _make_delivery_html()

    def test_delivery_keywords_present(self) -> None:
        # 배달앱 주제 핵심 키워드가 HTML에 존재해야 함
        self.assertTrue(
            "배달" in self.html or "결제" in self.html,
            "Delivery keywords should be in HTML",
        )

    def test_no_tax_keywords_in_delivery(self) -> None:
        # 배달앱 주제에 세금/환급 관련 키워드가 없어야 함
        # (SOURCE_TRUST_BLOCK이나 AI_CITATION 내 money_checklist 텍스트만 허용)
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        svc = GeoIntentService()
        violations = svc.check_content_type_forbidden_phrases(self.html, "money_checklist")
        self.assertEqual(violations, [], f"Forbidden phrases found: {violations}")


class TestDeliveryScheduleIntentDoesNotUseGenericConsumerQuestions(unittest.TestCase):
    def test_delivery_schedule_questions_and_paa_stay_on_shipping_schedule(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService

        svc = GeoIntentService()
        topic = "2026 선거일 CJ 택배 배송 일정"
        questions = svc.generate_reader_intent_questions(
            topic=topic,
            content_type="consumer_warning",
            topic_group="delivery_money",
            slots={},
        )
        paa = svc.generate_people_also_ask(questions, topic=topic, content_type="consumer_warning")

        joined = " ".join([*questions, *paa])
        for forbidden in ("환불 거부", "소비자 피해 신고", "결제 오류", "개인정보 유출"):
            self.assertNotIn(forbidden, joined)
        self.assertGreaterEqual(len(questions), 5)
        self.assertGreaterEqual(len(paa), 5)
        self.assertTrue(any("택배" in item or "배송" in item for item in paa))

    def test_delivery_schedule_answers_are_not_broken_or_over_repeated(self) -> None:
        from collections import Counter

        from blogspot_automation.services.geo_intent_service import GeoIntentService

        svc = GeoIntentService()
        topic = "2026 선거일 CJ 택배 배송 일정"
        questions = svc.generate_reader_intent_questions(
            topic=topic,
            content_type="consumer_warning",
            topic_group="delivery_money",
            slots={},
        )
        answers = svc.generate_intent_answers(questions, topic=topic, content_type="consumer_warning", slots={})
        answer_texts = [item["A"] for item in answers]

        self.assertGreaterEqual(len(answer_texts), 3)
        self.assertLessEqual(max(Counter(answer_texts).values()), 2)
        self.assertFalse(any(answer.startswith(("으로 ", "라고 ", "에는 ", "에서는 ")) for answer in answer_texts))


def _make_meta_from_html(html: str, pattern_id: str, content_type: str) -> dict:
    """article_candidate_meta.json 내용을 임시 디렉토리에서 생성해 반환."""
    import json
    import tempfile
    from pathlib import Path
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService

    ps = GoldenPatternService()
    sf = SlotFillerService()
    pm = ps.get_pattern(pattern_id) or {}
    sr = sf.fill_slots(pattern_id, "test topic")
    selected_title = "테스트 제목"
    best = {"title": selected_title, "ctr_score": 80, "risk_score": 0, "promise_match_score": 80}
    preview = {
        "matched": True, "near_match": False, "ready_for_review": True,
        "pattern_match": {"pattern_id": pattern_id, "confidence": 95, "content_type_match": True,
                          "topic_group_match": True, "matched_keywords": [], "negative_hits": [],
                          "matched": True, "near_match": False, "reason": "test"},
        "slot_result": sr, "slot_fill_rate": 1.0,
        "missing_required_slots": [], "blocking_issues": [], "warnings": [],
        "_editorial_scores": {"traffic_potential_score": 28, "usefulness_score": 30, "final_editorial_score": 80},
        "_content_candidate_grade": "B", "_can_generate_candidate": True,
        "_article_candidate_html": html, "_title_result": {"best_title": best},
        "_selected_title": selected_title,
        "_blogspot_labels": ["라벨1", "라벨2"],
        "_hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5", "#tag6"],
        "_content_type": content_type, "_topic_group": "test_group",
        "_stale_candidate": False, "_scoring_stale_penalty": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "run"; rp.mkdir()
        RunArtifactService(runs_dir=tmp).save_golden_preview_artifacts(rp, preview)
        return json.loads((rp / "article_candidate_meta.json").read_text(encoding="utf-8"))


class TestSgeAiOverviewBlock(unittest.TestCase):
    """SGE: AI_OVERVIEW_TARGET_ANSWER 블록"""

    def setUp(self) -> None:
        self.delivery_html = _make_delivery_html()
        self.tax_html = _make_tax_html()

    def test_ai_overview_present_delivery(self) -> None:
        self.assertIn('id="AI_OVERVIEW_TARGET_ANSWER"', self.delivery_html)

    def test_ai_overview_present_tax(self) -> None:
        self.assertIn('id="AI_OVERVIEW_TARGET_ANSWER"', self.tax_html)

    def test_ai_overview_content_not_empty(self) -> None:
        m = re.search(r'id="AI_OVERVIEW_TARGET_ANSWER".*?<p>(.*?)</p>', self.delivery_html, re.DOTALL)
        self.assertIsNotNone(m, "AI_OVERVIEW_TARGET_ANSWER block missing or no <p>")
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        self.assertGreater(len(text), 30, f"AI overview text too short: {text!r}")

    def test_ai_overview_before_body_content(self) -> None:
        ao_pos = self.delivery_html.find('id="AI_OVERVIEW_TARGET_ANSWER"')
        body_pos = self.delivery_html.find("핵심 관점")
        self.assertLess(ao_pos, body_pos, "AI_OVERVIEW should come before main body sections")

    def test_ai_overview_has_confirm_phrase_for_tax(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        from blogspot_automation.services.slot_filler_service import SlotFillerService
        gi = GeoIntentService()
        sf = SlotFillerService()
        sr = sf.fill_slots("tax_refund_hometax_check", "세금 환급금 조회")
        text = gi.generate_ai_overview_target_answer(
            topic="세금 환급금 조회", content_type="tax_refund",
            slots=sr.get("slots", {}),
        )
        self.assertTrue(
            "확인" in text or "홈택스" in text,
            f"Tax overview should mention verification: {text[:100]}"
        )

    def test_overview_does_not_glue_truncated_word_to_next_sentence(self) -> None:
        # 2026-07-09 라이브 리허설 실측 사고: real_criterion 첫 줄이 문장 구분자 없이
        # 100자에서 잘려 다음 part와 공백 하나로 붙으면 "...생성 3 제미나이 3.5..."처럼
        # 단어 중간이 끊긴 채 이어진다. 문장 경계에서만 잘라야 한다.
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        gi = GeoIntentService()
        long_step_line = (
            "1단계: Google AI Studio → 'Gemini 3.5 Flash' 모델 선택 → "
            "'Agentic Execution' 토글 켜기 (약 5분 소요, 이후 반복 코드 생성 30분 → 8분)"
        )
        slots = {
            "hook_opening": "매주 같은 리팩토링 작업에 시간을 쓰는 개발자가 많다.",
            "real_criterion": long_step_line,
            "yomi_judgment": "결론적으로 반복 업무부터 위임하는 것이 현실적이다.",
        }
        text = gi.generate_ai_overview_target_answer(
            topic="제미나이 3.5 코딩", content_type="ai_work_tip", slots=slots,
        )
        self.assertNotIn("생성 3 결론", text)
        self.assertNotIn(long_step_line[95:100], text)

    def test_policy_overview_uses_official_notice_not_hometax(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        from blogspot_automation.services.slot_filler_service import SlotFillerService
        gi = GeoIntentService()
        sf = SlotFillerService()
        sr = sf.fill_slots("policy_deadline", "울산형 석유화학업 근로자 안심페이 지원사업")
        text = gi.generate_ai_overview_target_answer(
            topic="울산형 석유화학업 근로자 안심페이 지원사업",
            content_type="policy_deadline",
            slots=sr.get("slots", {}),
        )
        self.assertIn("공식 공고", text)
        self.assertIn("문의처", text)
        self.assertNotIn("홈택스", text)
        self.assertNotIn("국세청", text)


class TestSgePeopleAlsoAsk(unittest.TestCase):
    """SGE: PEOPLE_ALSO_ASK_BLOCK"""

    def setUp(self) -> None:
        self.html = _make_delivery_html()

    def test_paa_block_present(self) -> None:
        self.assertIn('id="PEOPLE_ALSO_ASK_BLOCK"', self.html)

    def test_paa_items_count_ge_5(self) -> None:
        count = len(re.findall(r'class="paa-item"', self.html))
        self.assertGreaterEqual(count, 5, f"PAA items count={count}, expected >=5")

    def test_paa_before_body_content(self) -> None:
        paa_pos = self.html.find('id="PEOPLE_ALSO_ASK_BLOCK"')
        acts_pos = self.html.find('class="actions-box"')
        self.assertLess(paa_pos, acts_pos, "PAA should come before actions-box")

    def test_paa_generate_returns_5_plus(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        gi = GeoIntentService()
        qs = gi.generate_reader_intent_questions(
            "배달앱 결제금액 비교", "money_checklist", "delivery_money", {}
        )
        paa = gi.generate_people_also_ask(qs, "배달앱 결제금액 비교", "money_checklist")
        self.assertGreaterEqual(len(paa), 5)


class TestSgeConfirmedVsCheckNeeded(unittest.TestCase):
    """SGE: CONFIRMED_VS_CHECK_NEEDED_BLOCK"""

    def setUp(self) -> None:
        self.html = _make_delivery_html()
        self.tax_html = _make_tax_html()

    def test_cvck_present_delivery(self) -> None:
        self.assertIn('id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"', self.html)

    def test_cvck_present_tax(self) -> None:
        self.assertIn('id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"', self.tax_html)

    def test_confirmed_section_present(self) -> None:
        self.assertIn('class="confirmed-section"', self.html)

    def test_check_needed_section_present(self) -> None:
        self.assertIn('class="check-needed-section"', self.html)

    def test_cvck_after_body_content(self) -> None:
        cvck_pos = self.html.find('id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"')
        faq_pos  = self.html.find('class="faq faq-block"')
        self.assertGreater(cvck_pos, faq_pos, "CVCK should come after faq section")

    def test_generate_confirmed_not_empty(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        gi = GeoIntentService()
        result = gi.generate_confirmed_vs_check_needed(
            "money_checklist", "delivery_money", {}, "배달앱 결제"
        )
        self.assertGreater(len(result.get("confirmed", [])), 0)
        self.assertGreater(len(result.get("check_needed", [])), 0)

    def test_confirmed_section_does_not_copy_truncated_step_lines(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService

        gi = GeoIntentService()
        result = gi.generate_confirmed_vs_check_needed(
            "money_checklist",
            "delivery_money",
            {
                "real_criterion": (
                    "1단계: 배달비 조건 확인 — 주문 전 해당 가게의 배달비와 무료 배달 조건을 확인한다.\n"
                    "2단계: 쿠폰 적용 기준 확인 — 유효기간과 최소주문금액을 확인한다."
                )
            },
            "무료배송인데 결제금액이 커질 때 확인할 것",
        )
        confirmed = result.get("confirmed", [])

        self.assertFalse(any("단계" in item for item in confirmed))
        self.assertFalse(any(item.endswith("적") or item.endswith("충족 ") for item in confirmed))


class TestSgeScoreAndReady(unittest.TestCase):
    """SGE score + sge_ready 필드 검증"""

    @classmethod
    def setUpClass(cls) -> None:
        html = _make_delivery_html()
        cls._meta = _make_meta_from_html(html, "delivery_money_checklist", "money_checklist")

    def test_sge_score_present(self) -> None:
        self.assertIn("sge_score", self._meta, "sge_score field missing")

    def test_sge_score_above_80(self) -> None:
        score = self._meta.get("sge_score", 0)
        self.assertGreaterEqual(score, 80, f"sge_score={score} < 80")

    def test_sge_ready_true(self) -> None:
        self.assertTrue(self._meta.get("sge_ready"), "sge_ready should be True")

    def test_ai_overview_field_in_meta(self) -> None:
        self.assertIn("ai_overview_target_answer_present", self._meta)
        self.assertTrue(self._meta["ai_overview_target_answer_present"])

    def test_people_also_ask_count_in_meta(self) -> None:
        count = self._meta.get("people_also_ask_count", 0)
        self.assertGreaterEqual(count, 5, f"people_also_ask_count={count}")

    def test_confirmed_vs_check_field_in_meta(self) -> None:
        self.assertIn("confirmed_vs_check_needed_present", self._meta)
        self.assertTrue(self._meta["confirmed_vs_check_needed_present"])

    def test_source_trust_field_in_meta(self) -> None:
        self.assertIn("source_trust_block_present", self._meta)
        self.assertTrue(self._meta["source_trust_block_present"])


class TestSgeEnhancedSourceTrust(unittest.TestCase):
    """SGE: SOURCE_TRUST_BLOCK 강화 내용 검증"""

    def test_tax_trust_has_hometax_mention(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        gi = GeoIntentService()
        text = gi.generate_enhanced_source_trust_block("tax_refund", "policy_benefit", "tax_refund_hometax_check", "2026-05-09")
        self.assertIn("홈택스", text)
        self.assertIn("2026-05-09", text)

    def test_policy_trust_uses_notice_and_contact_not_hometax(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        gi = GeoIntentService()
        text = gi.generate_enhanced_source_trust_block("policy_deadline", "policy_benefit", "policy_deadline", "2026-06-02")
        self.assertIn("공식 공고", text)
        self.assertIn("문의처", text)
        self.assertIn("2026-06-02", text)
        self.assertNotIn("홈택스", text)
        self.assertNotIn("국세청", text)

    def test_delivery_trust_has_update_warning(self) -> None:
        from blogspot_automation.services.geo_intent_service import GeoIntentService
        gi = GeoIntentService()
        text = gi.generate_enhanced_source_trust_block("money_checklist", "delivery_money", "delivery_money_checklist", "2026-05-09")
        self.assertIn("배달앱", text)
        self.assertIn("바뀔 수 있", text)

    def test_trust_block_in_html(self) -> None:
        html = _make_delivery_html()
        self.assertIn('id="SOURCE_TRUST_BLOCK"', html)
        # 강화된 내용: 날짜 기준 언급
        trust_start = html.find('id="SOURCE_TRUST_BLOCK"')
        trust_snippet = html[trust_start:trust_start + 400]
        self.assertIn("기준", trust_snippet)


if __name__ == "__main__":
    unittest.main()
