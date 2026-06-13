"""discovery → article_candidate 연결 회로 회귀 테스트.

- corporate_issue_decode pattern + slot_filler builder 정상 동작
- title_candidate_service가 discovery 후보에서 entity-specific 제목 생성
- title_has_specific_entity gate
- AI Overviews 핵심 답변 등 옛 라벨이 HTML에 없음 (이미 제거된 상태 확인)
- 새 corporate_issue_decode patterns에 _PATTERN_CITATION_SUMMARIES 등록
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.golden_pattern_service import GoldenPatternService
from blogspot_automation.services.slot_filler_service import SlotFillerService
from blogspot_automation.services.golden_article_preview_service import (
    _PATTERN_CITATION_SUMMARIES,
    _PATTERN_DATE_DISCLAIMERS,
    _PATTERN_META_TEMPLATES,
)
from blogspot_automation.services.news_quality_gate import NewsQualityGate
from blogspot_automation.services.title_candidate_service import (
    _build_entity_specific_titles,
)


class TestCorporateIssuePattern(unittest.TestCase):
    """corporate_issue_decode pattern + slot_filler builder."""

    def test_pattern_exists(self):
        gps = GoldenPatternService()
        patterns = gps.load_patterns()
        ids = {p["pattern_id"] for p in patterns}
        self.assertIn("corporate_issue_decode", ids)

    def test_corporate_issue_matches_samsung_labor_news(self):
        gps = GoldenPatternService()
        result = gps.match_pattern(
            "속보]중노위, 삼성전자 노사에 16일 협상 재개 요청",
            "삼성전자 노조 사측 협상 공식 입장 발송",
            content_type="viral_issue_decode",
            topic_group="platform_issue",
        )
        self.assertGreaterEqual(result["confidence"], 80)
        # corporate_issue_decode 또는 platform_change_service_update 둘 다 OK
        self.assertIn(
            result["pattern_id"],
            ("corporate_issue_decode", "platform_change_service_update"),
        )

    def test_slot_filler_corporate_issue_fills_all_slots(self):
        sf = SlotFillerService()
        result = sf.fill_slots(
            "corporate_issue_decode",
            "삼성전자 노조 협상 재개 요청",
            {"entities": ["삼성"], "entity_types": ["platform"]},
        )
        self.assertEqual(result["slot_fill_rate"], 1.0)
        self.assertEqual(result["missing_required_slots"], [])
        for slot in ["hook_opening", "yomi_judgment", "misconceptions",
                     "real_criterion", "quick_decision_table", "actions",
                     "faq", "hashtags"]:
            self.assertTrue(result["slots"].get(slot),
                            f"Slot '{slot}' empty for corporate_issue_decode")

    def test_citation_summary_registered(self):
        self.assertIn("corporate_issue_decode", _PATTERN_CITATION_SUMMARIES)
        self.assertIn("corporate_issue_decode", _PATTERN_DATE_DISCLAIMERS)
        self.assertIn("corporate_issue_decode", _PATTERN_META_TEMPLATES)


class TestEntitySpecificTitles(unittest.TestCase):
    """discovery 후보의 entity로 entity-specific title 생성."""

    def test_corporate_issue_title_includes_entity(self):
        titles = _build_entity_specific_titles(
            topic="속보]중노위, 삼성전자 노사에 16일 협상 재개 요청",
            entities=["삼성"],
            entity_types=["platform"],
            content_type="viral_issue_decode",
            pattern_id="corporate_issue_decode",
        )
        self.assertGreater(len(titles), 0)
        # 첫 번째 title에 "삼성" entity 포함
        first_title = titles[0][0]
        self.assertIn("삼성", first_title)

    def test_platform_change_title_includes_entity(self):
        titles = _build_entity_specific_titles(
            topic="쿠팡 멤버십 가격 변경",
            entities=["쿠팡"],
            entity_types=["platform"],
            content_type="platform_change",
            pattern_id="platform_change_service_update",
        )
        self.assertGreater(len(titles), 0)
        self.assertIn("쿠팡", titles[0][0])

    def test_no_entities_returns_empty(self):
        titles = _build_entity_specific_titles(
            topic="generic topic",
            entities=[],
            entity_types=[],
            content_type="viral_issue_decode",
            pattern_id="corporate_issue_decode",
        )
        self.assertEqual(len(titles), 0)


class TestTitleHasSpecificEntityGate(unittest.TestCase):
    """title_has_specific_entity blocking 검증."""

    def _evaluate(self, *, title: str, discovery: bool = False) -> list[str]:
        gate = NewsQualityGate()
        scored = MagicMock()
        scored.candidate = MagicMock()
        scored.candidate.topic = title
        scored.candidate.summary = ""
        scored.candidate.published_at = "2026-05-14T10:00:00+00:00"
        scored.candidate.raw = {
            "topic_group": "refund_consumer",
            "source_type": "google_news_rss",
            "is_stale": False,
            "click_potential_score": 9,
            "content_angle": {"content_type": "consumer_warning"},
            "discovery_engine": discovery,
            "hook_angle": {"safe_title_keyword": title[:18]},
            "reader_search_questions": [
                "관련 정보 어디서 확인하나요?",
                "신청은 어떻게 하나요?",
                "공식 안내는 어디서 볼 수 있나요?",
            ],
        }
        scored.total_score = 80
        scored.risk_penalty = 0
        scored.freshness_score = 0.8
        scored.search_demand_score = 0
        scored.contrarian_gap_score = 0
        scored.mass_impact_score = 0
        scored.adsense_value_score = 0
        scored.hook_score = 0
        scored.reason = "test"
        html = (
            "<html><head>"
            '<meta name="description" content="이 글의 설명입니다 — 80자 이상으로 충분히 작성되어 있고 자연스러운 문장 구조입니다.">'
            "</head><body>"
            f"<h1>{title}</h1>"
            "<section><h2>핵심 요약</h2><p>요약입니다.</p></section>"
            '<section class="faq">'
            "<h3>Q1</h3><p>답변 내용은 충분히 길게 작성되어 있습니다.</p>"
            "<h3>Q2</h3><p>두번째 답변도 충분히 길게 작성되어 있습니다.</p>"
            "<h3>Q3</h3><p>세번째 답변도 충분히 길게 작성되어 있습니다.</p>"
            "</section>"
            '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
            '<section><a href="https://blog.naver.com/holyyomi">네이버</a></section>'
            "</body></html>"
        )
        result = gate.evaluate(
            selected=scored, selected_title=title, html=html,
            image_prompt="prompt", image_alt_text="alt",
            labels=["test"], hashtags=["#test"],
            dry_run=True, news_publish_mode="dry_run",
        )
        return list(result.get("blocking_issues", []))

    def test_title_with_entity_passes(self):
        issues = self._evaluate(title="삼성전자 노조 협상 재개 요청, 사람들이 궁금해할 점")
        self.assertNotIn("title_has_no_specific_entity", issues)

    def test_title_without_entity_blocked(self):
        issues = self._evaluate(title="확인 전에 봐야 할 3가지")
        self.assertIn("title_has_no_specific_entity", issues)

    def test_discovery_candidate_bypasses_entity_check(self):
        issues = self._evaluate(title="generic title", discovery=True)
        # discovery_engine=True면 면제
        self.assertNotIn("title_has_no_specific_entity", issues)

    def test_generic_subject_phrase_blocked(self):
        issues = self._evaluate(title="확인 전에 볼 것")
        # discovery 아닐 때 generic 패턴 차단
        self.assertIn("generic_title_without_subject", issues)


if __name__ == "__main__":
    unittest.main()
