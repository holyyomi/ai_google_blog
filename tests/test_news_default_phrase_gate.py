from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from blogspot_automation.services.news_quality_gate import NewsQualityGate


def _make_selected(
    *,
    total_score: int = 80,
    topic: str = "테스트 주제",
    content_type: str = "tax_refund",
    topic_group: str = "policy_benefit",
    source_type: str = "news",
    click_potential_score: int = 10,
    hook_angle: dict | None = None,
    safe_title_keyword: str = "확인",
) -> MagicMock:
    raw = {
        "topic_group": topic_group,
        "content_angle": {"content_type": content_type},
        "source_type": source_type,
        "click_potential_score": click_potential_score,
        "hook_angle": hook_angle or {"safe_title_keyword": safe_title_keyword},
        "is_test_candidate": False,
        "publish_allowed": True,
    }
    candidate = MagicMock()
    candidate.topic = topic
    candidate.category = "생활"
    candidate.summary = "테스트 요약"
    candidate.raw = raw
    selected = MagicMock()
    selected.total_score = total_score
    selected.candidate = candidate
    selected.reason = "테스트"
    return selected


_MINIMAL_VALID_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>홈택스 세금 환급 확인하세요</title>
  <meta name="description" content="세금 환급 조회 방법 정리">
  <script type="application/ld+json">{"@context":"https://schema.org","@type":"Article","headline":"테스트"}</script>
  <script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[]}</script>
</head>
<body>
  <article>
    <h1>홈택스 세금 환급 확인하세요</h1>
    <p class="meta">유형: tax_refund</p>
    <section class="hero-summary-box"><p>요약</p></section>
    <section class="target-reader-box"><p>대상</p></section>
    <section class="core-message-box"><p>핵심</p></section>
    <section class="yomi-judgment-box"><p>요미의 판단 내용</p></section>
    <section class="misconception-box"><p>착각 내용</p></section>
    <section class="quick-decision-table"><p>판단표</p></section>
    <section class="key-fact-cards"><p>팩트카드</p></section>
    <section class="warning"><p>주의 사항</p></section>
    <section class="checklist"><p>체크리스트 내용</p></section>
    <section class="action-guide-box"><p>홈택스·손택스에서 환급 대상 여부를 조회한다.</p></section>
    <section class="faq faq-block">
      <h2>자주 묻는 질문</h2>
      <div class="faq-card">
        <h3>환급계좌 등록 방법은?</h3>
        <p>홈택스 로그인 후 마이홈택스에서 환급계좌 신청/해지 메뉴로 이동하여 본인 계좌를 등록합니다.</p>
      </div>
      <div class="faq-card">
        <h3>환급금이 입금이 안 되는 이유는?</h3>
        <p>계좌 미등록, 주소 불일치, 처리 중 대기 상태 등이 원인일 수 있으므로 홈택스에서 확인해야 합니다.</p>
      </div>
      <div class="faq-card">
        <h3>소멸시효가 있나요?</h3>
        <p>국세환급금 소멸시효는 5년이며 5년 내 청구하지 않으면 소멸합니다.</p>
      </div>
    </section>
    <section class="naver-blog-box">
      <a href="https://blog.naver.com/holyyomi" target="_blank" rel="noopener noreferrer">블로그</a>
    </section>
    <p>환급 조회 홈택스 손택스 환급금 예시 체크리스트 환급 계좌 구체 상황 예시 환급 유형 구분
    종합소득세 연말정산 국세환급금 오늘 바로 할 일</p>
    <p>세금 환급 국세환급금 홈택스 환급금 조회 환급계좌 미수령 환급금</p>
  </article>
</body>
</html>"""

_TAX_LABELS = ["세금환급", "홈택스", "국세환급금", "환급계좌", "종합소득세", "연말정산"]
_TAX_HASHTAGS = ["#세금환급", "#홈택스", "#국세환급금", "#환급계좌등록", "#종합소득세환급", "#연말정산환급"]


class TestDefaultPhraseGate(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = NewsQualityGate()

    def _evaluate(
        self,
        html: str,
        content_type: str = "tax_refund",
        topic_group: str = "policy_benefit",
        labels: list[str] | None = None,
        hashtags: list[str] | None = None,
    ) -> dict:
        selected = _make_selected(
            content_type=content_type,
            topic_group=topic_group,
        )
        return self.gate.evaluate(
            selected=selected,
            selected_title="홈택스 세금 환급 확인하세요",
            html=html,
            image_prompt="A clean infographic about tax refund process, no text, no logo, no watermark",
            image_alt_text="세금 환급 절차 안내 인포그래픽",
            labels=labels or _TAX_LABELS,
            hashtags=hashtags or _TAX_HASHTAGS,
            dry_run=True,
        )

    # ------------------------------------------------------------------ #
    # 핵심 테스트 4개 (작업 D 명세 기준)                                     #
    # ------------------------------------------------------------------ #

    def test_banned_phrase_direct_relation_blocks(self) -> None:
        """'이 이슈는 나와 직접 관련이 없다' 포함 → blocking."""
        html = _MINIMAL_VALID_HTML.replace(
            "오늘 바로 할 일",
            "이 이슈는 나와 직접 관련이 없다",
        )
        result = self._evaluate(html)
        self.assertTrue(result["default_phrase_detected"])
        self.assertTrue(any("banned_default_phrase_detected" in issue for issue in result["blocking_issues"]))
        self.assertTrue(any("이 이슈는 나와 직접 관련이 없다" in hit for hit in result["default_phrase_hits"]))

    def test_banned_phrase_too_much_info_blocks(self) -> None:
        """'정보가 너무 많음' 포함 → blocking."""
        html = _MINIMAL_VALID_HTML.replace(
            "오늘 바로 할 일",
            "정보가 너무 많음",
        )
        result = self._evaluate(html)
        self.assertTrue(result["default_phrase_detected"])
        self.assertTrue(any("banned_default_phrase_detected" in issue for issue in result["blocking_issues"]))

    def test_clean_tax_refund_html_not_blocked_by_phrase(self) -> None:
        """정상 tax_refund 샘플 문구 → default_phrase_detected=False."""
        result = self._evaluate(_MINIMAL_VALID_HTML)
        self.assertFalse(result["default_phrase_detected"], msg=f"hits={result['default_phrase_hits']}")
        self.assertNotIn(True, [
            "banned_default_phrase_detected" in issue
            for issue in result["blocking_issues"]
        ])

    def test_official_check_order_section_not_blocked(self) -> None:
        """'공식 확인 순서'라는 섹션명 단독 포함 → blocking 아님."""
        html = _MINIMAL_VALID_HTML.replace(
            "오늘 바로 할 일",
            "공식 확인 순서",
        )
        result = self._evaluate(html)
        self.assertFalse(result["default_phrase_detected"], msg=f"hits={result['default_phrase_hits']}")

    # ------------------------------------------------------------------ #
    # 추가 케이스                                                           #
    # ------------------------------------------------------------------ #

    def test_multiple_banned_phrases_all_detected(self) -> None:
        """여러 banned phrase 동시 포함 → 모두 hits에 포함."""
        html = _MINIMAL_VALID_HTML.replace(
            "오늘 바로 할 일",
            "정보가 너무 많음 / 나와 관련 있는지 모름",
        )
        result = self._evaluate(html)
        self.assertTrue(result["default_phrase_detected"])
        self.assertGreaterEqual(len(result["default_phrase_hits"]), 1)

    def test_default_phrase_detected_field_exists(self) -> None:
        """반환 dict에 default_phrase_detected, default_phrase_hits 필드 존재."""
        result = self._evaluate(_MINIMAL_VALID_HTML)
        self.assertIn("default_phrase_detected", result)
        self.assertIn("default_phrase_hits", result)
        self.assertIsInstance(result["default_phrase_detected"], bool)
        self.assertIsInstance(result["default_phrase_hits"], list)

    def test_banned_choice_criteria_blocks(self) -> None:
        """'오늘 내 선택 기준이 됩니다' 포함 → blocking."""
        html = _MINIMAL_VALID_HTML.replace(
            "오늘 바로 할 일",
            "오늘 내 선택 기준이 됩니다",
        )
        result = self._evaluate(html)
        self.assertTrue(result["default_phrase_detected"])

    def test_empty_phrase_hits_when_clean(self) -> None:
        """banned phrase 없을 때 default_phrase_hits는 빈 리스트."""
        result = self._evaluate(_MINIMAL_VALID_HTML)
        self.assertEqual(result["default_phrase_hits"], [])


class TestDefaultBoxSuppression(unittest.TestCase):
    """contrarian_content_service 박스 억제 로직 단위 테스트."""

    def setUp(self) -> None:
        from blogspot_automation.services.contrarian_content_service import ContrarianContentService
        self.svc = ContrarianContentService()

    def test_yomi_judgment_unknown_type_empty(self) -> None:
        result = self.svc._yomi_judgment_box_html("general_life", "임의 주제")
        self.assertEqual(result, "")

    def test_yomi_judgment_unknown_type_default_empty(self) -> None:
        result = self.svc._yomi_judgment_box_html("unknown_xyz", "임의 주제")
        self.assertEqual(result, "")

    def test_yomi_judgment_known_type_not_empty(self) -> None:
        result = self.svc._yomi_judgment_box_html("tax_refund", "홈택스 환급")
        self.assertIn("yomi-judgment-box", result)
        self.assertNotEqual(result, "")

    def test_misconception_unknown_type_empty(self) -> None:
        result = self.svc._misconception_box_html("general_life", "임의 주제")
        self.assertEqual(result, "")

    def test_misconception_known_type_not_empty(self) -> None:
        result = self.svc._misconception_box_html("tax_refund", "홈택스 환급")
        self.assertIn("misconception-box", result)
        self.assertNotEqual(result, "")

    def test_quick_decision_unknown_type_empty(self) -> None:
        result = self.svc._quick_decision_table_html("general_life", "임의 주제")
        self.assertEqual(result, "")

    def test_quick_decision_known_type_not_empty(self) -> None:
        result = self.svc._quick_decision_table_html("tax_refund", "홈택스 환급")
        self.assertIn("quick-decision-table", result)
        self.assertNotEqual(result, "")

    def test_action_guide_unknown_type_empty(self) -> None:
        result = self.svc._action_guide_html("general_life")
        self.assertEqual(result, "")

    def test_action_guide_known_type_not_empty(self) -> None:
        result = self.svc._action_guide_html("tax_refund")
        self.assertIn("action-guide-box", result)
        self.assertNotEqual(result, "")

    def test_no_banned_phrases_in_known_type_boxes(self) -> None:
        banned = [
            "이 이슈는 나와 직접 관련이 없다",
            "정보가 너무 많음",
            "오늘 내 선택 기준이 됩니다",
            "나와 관련 있는지",
            "공식 안내를 확인한다",
            "내 생활과 관련있는지 모름",
            "지금 행동이 필요한지 모름",
        ]
        for ct in ("tax_refund", "ai_work_tip", "viral_issue_decode", "policy_deadline"):
            boxes = (
                self.svc._yomi_judgment_box_html(ct, "테스트 주제")
                + self.svc._misconception_box_html(ct, "테스트 주제")
                + self.svc._quick_decision_table_html(ct, "테스트 주제")
                + self.svc._action_guide_html(ct)
            )
            for phrase in banned:
                self.assertNotIn(phrase, boxes, f"[{ct}] banned phrase: '{phrase}'")


if __name__ == "__main__":
    unittest.main()
