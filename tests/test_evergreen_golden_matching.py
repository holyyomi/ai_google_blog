from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock


def _make_scored_candidate(
    *,
    topic: str,
    content_type: str = "",
    topic_group: str = "",
    source_type: str = "evergreen_fallback",
    total_score: int = 80,
    search_demand_topic: str = "",
    reader_search_questions: list[str] | None = None,
) -> Any:
    from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
    raw: dict[str, Any] = {
        "source_type": source_type,
        "topic_group": topic_group,
        "content_angle": {"content_type": content_type},
        "search_demand_topic": search_demand_topic or topic,
        "reader_search_questions": reader_search_questions or [],
    }
    nc = NewsCandidate(
        topic=topic,
        category="tech",
        summary="",
        source_hint=source_type,
        published_at=None,
        url=None,
        raw=raw,
    )
    return ScoredNewsCandidate(
        candidate=nc,
        total_score=total_score,
        freshness_score=0,
        search_demand_score=0,
        contrarian_gap_score=0,
        mass_impact_score=0,
        adsense_value_score=0,
        hook_score=0,
        risk_penalty=0,
        reason="test",
    )


class TestGoldenPatternMatchingEvergreen(unittest.TestCase):
    """작업 F: evergreen golden pattern matching 테스트"""

    def setUp(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        self.ps = GoldenPatternService()

    def test_chatgpt_topic_matches_ai_work_time_savings(self) -> None:
        topic = "직장인이 ChatGPT로 업무 시간을 줄이는 방법"
        result = self.ps.match_pattern(
            topic=topic,
            content_type="ai_work_tip",
            topic_group="ai_work",
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["pattern_id"], "ai_work_time_savings")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_chatgpt_topic_only_matches_ai_work(self) -> None:
        topic = "직장인이 ChatGPT로 업무 시간을 줄이는 방법"
        result = self.ps.match_pattern(topic=topic)
        self.assertTrue(result["matched"])
        self.assertEqual(result["pattern_id"], "ai_work_time_savings")

    def test_tax_refund_topic_matches_hometax_check(self) -> None:
        topic = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        result = self.ps.match_pattern(
            topic=topic,
            content_type="tax_refund",
            topic_group="policy_benefit",
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["pattern_id"], "tax_refund_hometax_check")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_tax_refund_topic_only_matches(self) -> None:
        topic = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        result = self.ps.match_pattern(topic=topic)
        self.assertTrue(result["matched"])
        self.assertEqual(result["pattern_id"], "tax_refund_hometax_check")

    def test_money_life_topic_no_golden_match(self) -> None:
        topic = "구독 서비스 자동결제 전 확인할 체크리스트"
        result = self.ps.match_pattern(
            topic=topic,
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        self.assertFalse(result["matched"])

    def test_ai_topic_with_summary_still_matches(self) -> None:
        topic = "AI 업무 자동화 처음 버릴 반복 작업 5가지"
        summary = "직장인이 ChatGPT를 업무에 쓸 때 반복 작업을 줄이는 방법"
        result = self.ps.match_pattern(
            topic=topic,
            content_type="ai_work_tip",
            topic_group="ai_work",
            summary=summary,
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["pattern_id"], "ai_work_time_savings")

    def test_ct_tg_bonus_applied(self) -> None:
        topic = "직장인이 ChatGPT로 업무 시간을 줄이는 방법"
        result_no_ctx = self.ps.match_pattern(topic=topic)
        result_with_ctx = self.ps.match_pattern(
            topic=topic, content_type="ai_work_tip", topic_group="ai_work"
        )
        self.assertGreaterEqual(result_with_ctx["confidence"], result_no_ctx["confidence"])


class TestPreferGoldenMatchedCandidates(unittest.TestCase):
    """_prefer_golden_matched_candidates가 content_type·topic_group을 반영하는지 확인"""

    def _make_pipeline(self) -> Any:
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        return NewsPipeline.__new__(NewsPipeline)

    def setUp(self) -> None:
        from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
        self.pipeline = self._make_pipeline()
        self.pipeline.golden_preview_service = GoldenArticlePreviewService()

    def test_chatgpt_candidate_preferred(self) -> None:
        c = _make_scored_candidate(
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            content_type="ai_work_tip",
            topic_group="ai_work",
        )
        result = self.pipeline._prefer_golden_matched_candidates([c])
        self.assertEqual(len(result), 1)

    def test_money_life_candidate_not_preferred(self) -> None:
        c = _make_scored_candidate(
            topic="구독 서비스 자동결제 전 확인할 체크리스트",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        result = self.pipeline._prefer_golden_matched_candidates([c])
        self.assertEqual(len(result), 0)

    def test_tax_refund_candidate_preferred(self) -> None:
        c = _make_scored_candidate(
            topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
            content_type="tax_refund",
            topic_group="policy_benefit",
        )
        result = self.pipeline._prefer_golden_matched_candidates([c])
        self.assertEqual(len(result), 1)

    def test_mixed_list_returns_only_golden_matched(self) -> None:
        ai = _make_scored_candidate(
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            content_type="ai_work_tip",
            topic_group="ai_work",
        )
        money = _make_scored_candidate(
            topic="구독 서비스 자동결제 전 확인할 체크리스트",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        tax = _make_scored_candidate(
            topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
            content_type="tax_refund",
            topic_group="policy_benefit",
        )
        result = self.pipeline._prefer_golden_matched_candidates([ai, money, tax])
        topics = [r.candidate.topic for r in result]
        self.assertIn("직장인이 ChatGPT로 업무 시간을 줄이는 방법", topics)
        self.assertIn("세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", topics)
        self.assertNotIn("구독 서비스 자동결제 전 확인할 체크리스트", topics)


class TestEvergreenAllCandidatesHaveGoldenMatch(unittest.TestCase):
    """실제 evergreen 후보 전체에서 golden-matched 후보가 항상 존재하는지 확인"""

    def test_at_least_8_golden_matched_from_all_evergreen(self) -> None:
        from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService
        from blogspot_automation.services.news_scoring_service import NewsScoringService
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        svc = EvergreenTopicService()
        candidates = svc.collect_candidates()
        matched = []
        for c in candidates:
            raw = c.raw or {}
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            summary = str(raw.get("search_demand_topic") or "")
            r = ps.match_pattern(topic=c.topic or "", content_type=ct, topic_group=tg, summary=summary)
            if r["matched"]:
                matched.append(c.topic)
        self.assertGreaterEqual(len(matched), 8, f"golden-matched evergreen 후보가 8개 미만: {matched}")

    def test_ai_axis_has_golden_match(self) -> None:
        from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        svc = EvergreenTopicService()
        ai_candidates = [
            c for c in svc.collect_candidates()
            if (c.raw or {}).get("evergreen_axis") == "ai_automation"
        ]
        matched = []
        for c in ai_candidates:
            raw = c.raw or {}
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            r = ps.match_pattern(topic=c.topic or "", content_type=ct, topic_group=tg)
            if r["matched"]:
                matched.append(c.topic)
        self.assertGreater(len(matched), 0, "ai_automation axis에서 golden-matched 후보 없음")

    def test_tax_refund_axis_has_golden_match(self) -> None:
        from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        svc = EvergreenTopicService()
        tax_candidates = [
            c for c in svc.collect_candidates()
            if (c.raw or {}).get("evergreen_axis") == "tax_refund_support"
        ]
        matched = []
        for c in tax_candidates:
            raw = c.raw or {}
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            r = ps.match_pattern(topic=c.topic or "", content_type=ct, topic_group=tg)
            if r["matched"]:
                matched.append(c.topic)
        self.assertGreater(len(matched), 0, "tax_refund_support axis에서 golden-matched 후보 없음")


if __name__ == "__main__":
    unittest.main()
