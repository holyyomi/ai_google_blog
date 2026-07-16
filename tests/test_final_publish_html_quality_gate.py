"""Final publish HTML — HTML entity artifact 회귀 테스트.

검증 항목:
1. &amp;#숫자  → blocking_issue 'broken_html_entity_double_escape'
2. &#숫자 (세미콜론 없음) → blocking_issue 'broken_html_entity_no_semicolon'
3. &#숫자; (세미콜론 있음) → 정상 entity, blocking 없음
4. _clean_entity_artifacts 디코딩 정확성
5. html_entity_artifact_absent / broken_html_entity_detected 필드 존재
"""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

# ── 최소 mock ScoredNewsCandidate ────────────────────────────────────────────

def _make_candidate(html: str, title: str = "삼성 이슈, 소비자와 투자자가 궁금해할 3가지") -> object:
    """quality_gate.evaluate()가 받는 ScoredNewsCandidate 최소 stub."""
    import types

    raw: dict = {
        "source_type": "google_news_rss",
        "topic_group": "platform_issue",
        "content_angle": {"content_type": "viral_issue_decode"},
        "hook_angle": {"safe_title_keyword": "삼성 파업"},
        "image_prompt": "삼성 파업 이슈 사무실 배경",
        "image_alt_text": "삼성전자 노조 파업 관련 이슈",
        "click_potential_score": 9,
        "total_score": 85,
        "raw_total_score": 85,
        "evergreen_axis": "",
        "is_test_candidate": False,
        "publish_allowed": True,
        "discovery_engine": True,
        "today_buzz_score": 10,
        "viral_safety_score": 80,
    }
    candidate = types.SimpleNamespace(
        topic="삼성전자 노조 총파업",
        category="platform_issue",
        summary="",
        source_hint=None,
        published_at=None,
        url=None,
        raw=raw,
    )
    scored = types.SimpleNamespace(
        candidate=candidate,
        total_score=85,
        reason="test",
    )

    # html을 평가 시 주입할 수 있도록 패치
    scored._test_html = html
    scored._test_title = title
    return scored


def _evaluate(html: str, title: str = "삼성 이슈, 소비자와 투자자가 궁금해할 3가지") -> dict:
    """NewsQualityGate.evaluate()를 실제 시그니처에 맞게 호출한다."""
    from blogspot_automation.services.news_quality_gate import NewsQualityGate

    scored = _make_candidate(html, title)

    gate = NewsQualityGate()
    return gate.evaluate(
        selected=scored,
        selected_title=title,
        html=html,
        labels=["삼성", "파업", "노조", "기업이슈", "소비자", "오늘이슈"],
        hashtags=["#삼성", "#파업", "#기업이슈", "#소비자", "#오늘이슈", "#뉴스"],
        image_prompt="삼성 파업 관련 사무실",
        image_alt_text="삼성전자 노조 파업",
    )


def _min_valid_html(extra: str = "") -> str:
    """blocking 없이 통과하는 최소 HTML 뼈대."""
    return f"""<html><head>
<meta name="description" content="삼성전자 노조 파업 소비자 투자자 궁금증 3가지 정리">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[]}}</script>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BlogPosting","headline":"삼성 이슈"}}</script>
</head><body>
<h1>삼성 이슈, 소비자와 투자자가 궁금해할 3가지</h1>
<section class="hero-summary-box">핵심요약</section>
<section class="target-reader-box">독자</section>
<section class="core-message-box">핵심메시지</section>
<section class="key-fact-cards">팩트카드</section>
<div class="checklist">체크리스트 항목</div>
<div class="warning">주의사항</div>
<section class="faq-card"><h3>Q1 파업이 소비자에게 미치는 영향은?</h3><p>답변 내용입니다 답변 내용입니다 답변 내용입니다.</p></section>
<section class="faq-card"><h3>Q2 투자자는 어떻게 봐야 하나?</h3><p>답변 내용입니다 답변 내용입니다 답변 내용입니다.</p></section>
<section class="faq-card"><h3>Q3 파업 종료 시점은?</h3><p>답변 내용입니다 답변 내용입니다 답변 내용입니다.</p></section>
<section class="yomi-judgment-box">요미 판단</section>
<section class="misconception-box">오해</section>
<section class="quick-decision-table">결정표</section>
<section class="naver-blog-box"><a href="https://blog.naver.com/holyyomi" target="_blank" rel="noopener noreferrer">네이버 블로그</a></section>
<p>이슈 내용입니다. 반응이 갈리고 있습니다. 오늘 발표 이후 소비자 이슈가 됐습니다.</p>
{'<p>' + 'A' * 200 + '</p>'}
{extra}
</body></html>"""


# ── 테스트 클래스 ─────────────────────────────────────────────────────────────

class TestHtmlEntityArtifact(unittest.TestCase):
    """HTML entity artifact가 publish_ready를 차단하는지 검증."""

    def test_double_escaped_entity_blocked(self):
        """&amp;#9989 형태(이중 escape) → blocking_issue 추가."""
        html = _min_valid_html('<p>체크 &amp;#9989 확인완료</p>')
        result = _evaluate(html)
        self.assertIn(
            "broken_html_entity_double_escape",
            result["blocking_issues"],
            "이중 escape entity(&amp;#숫자)는 blocking_issue여야 함",
        )
        self.assertFalse(result["html_entity_artifact_absent"])
        self.assertTrue(result["broken_html_entity_detected"])

    def test_bare_entity_no_semicolon_blocked(self):
        """&#9989 형태(세미콜론 없음) → blocking_issue 추가."""
        html = _min_valid_html('<p>체크 &#9989 확인완료</p>')
        result = _evaluate(html)
        self.assertIn(
            "broken_html_entity_no_semicolon",
            result["blocking_issues"],
            "세미콜론 없는 entity(&#숫자)는 blocking_issue여야 함",
        )
        self.assertFalse(result["html_entity_artifact_absent"])

    def test_bare_entity_numeric_99_blocked(self):
        """&#99 형태(사용자 리포트 케이스) → blocking_issue 추가."""
        html = _min_valid_html('<p>항목 &#99 내용</p>')
        result = _evaluate(html)
        self.assertIn("broken_html_entity_no_semicolon", result["blocking_issues"])

    def test_valid_entity_with_semicolon_not_blocked(self):
        """&#9989; 형태(세미콜론 있는 정상 entity) → blocking_issue 없음."""
        html = _min_valid_html('<p>체크 &#9989; 확인완료</p>')
        result = _evaluate(html)
        self.assertNotIn("broken_html_entity_double_escape", result["blocking_issues"])
        self.assertNotIn("broken_html_entity_no_semicolon", result["blocking_issues"])
        self.assertTrue(result["html_entity_artifact_absent"])
        self.assertFalse(result["broken_html_entity_detected"])

    def test_clean_html_entity_artifact_absent_true(self):
        """entity artifact 없는 정상 HTML → html_entity_artifact_absent=True."""
        html = _min_valid_html('<p>✅ 확인완료 → 다음 단계</p>')
        result = _evaluate(html)
        self.assertTrue(result["html_entity_artifact_absent"])
        self.assertFalse(result["broken_html_entity_detected"])

    def test_result_has_entity_fields(self):
        """evaluate() 결과에 entity QA 필드가 존재해야 함."""
        html = _min_valid_html()
        result = _evaluate(html)
        self.assertIn("html_entity_artifact_absent", result)
        self.assertIn("broken_html_entity_detected", result)


class TestCleanEntityArtifacts(unittest.TestCase):
    """_clean_entity_artifacts 디코딩 정확성 검증."""

    def setUp(self):
        from blogspot_automation.services.llm_content_service import _clean_entity_artifacts
        self.clean = _clean_entity_artifacts

    def test_semicolon_entity_decoded(self):
        """&#9989; → ✅ 로 변환."""
        result = self.clean("<p>&#9989; 완료</p>")
        self.assertIn("✅", result)
        self.assertNotIn("&#9989", result)

    def test_bare_entity_decoded(self):
        """&#9989 (세미콜론 없음) → unicode 문자로 변환."""
        result = self.clean("<p>&#9989 완료</p>")
        self.assertNotIn("&#9989", result)

    def test_double_escape_resolved(self):
        """&amp;#9989; → ✅ 로 변환."""
        result = self.clean("<p>&amp;#9989; 완료</p>")
        self.assertNotIn("&amp;#", result)

    def test_html_tags_preserved(self):
        """HTML 태그 구조는 변경되지 않아야 함."""
        html = '<div class="box"><p>텍스트 &#9989; 내용</p></div>'
        result = self.clean(html)
        self.assertIn('<div class="box">', result)
        self.assertIn('<p>', result)
        self.assertIn('</p>', result)

    def test_normal_text_unchanged(self):
        """일반 텍스트와 한글은 변경되지 않아야 함."""
        html = '<p>정상 텍스트입니다. 가격 7% 인상.</p>'
        result = self.clean(html)
        self.assertEqual(html, result)

    def test_css_numbers_not_affected(self):
        """CSS 숫자값(8px, #f0f0f0 등)은 변경되지 않아야 함."""
        html = '<div style="padding:8px;color:#f0f0f0">내용</div>'
        result = self.clean(html)
        self.assertEqual(html, result)

    def test_hex_entity_with_semicolon_decoded(self):
        """&#x27; (hex, 2026-07-16 실측 관측) → ' 로 변환."""
        result = self.clean("<p>오픈AI는 &#x27;서비스 개선&#x27;을 명시한다</p>")
        self.assertIn("'서비스 개선'", result)
        self.assertNotIn("&#x27", result)

    def test_hex_entity_bare_and_double_escape_decoded(self):
        """&#x27 (세미콜론 없음)·&amp;#x27; (이중 escape) 모두 처리."""
        result = self.clean("<p>따옴표 &#x27 그리고 &amp;#x27; 케이스</p>")
        self.assertNotIn("&#x27", result)
        self.assertNotIn("&amp;#x", result)


class TestHexEntityGate(unittest.TestCase):
    """게이트의 entity 안전망이 hex 표기(&#x27)도 잡는지 검증 (2026-07-16)."""

    def test_bare_hex_entity_blocked(self):
        html = _min_valid_html('<p>따옴표 &#x27 노출</p>')
        result = _evaluate(html)
        self.assertIn("broken_html_entity_no_semicolon", result["blocking_issues"])

    def test_double_escaped_hex_entity_blocked(self):
        html = _min_valid_html('<p>따옴표 &amp;#x27; 노출</p>')
        result = _evaluate(html)
        self.assertIn("broken_html_entity_double_escape", result["blocking_issues"])

    def test_valid_hex_entity_with_semicolon_not_blocked(self):
        html = _min_valid_html('<p>따옴표 &#x27; 정상</p>')
        result = _evaluate(html)
        self.assertNotIn("broken_html_entity_no_semicolon", result["blocking_issues"])
        self.assertNotIn("broken_html_entity_double_escape", result["blocking_issues"])


if __name__ == "__main__":
    unittest.main()
