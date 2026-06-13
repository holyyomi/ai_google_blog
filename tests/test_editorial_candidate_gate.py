from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from blogspot_automation.pipelines.news_pipeline import NewsPipeline


def _make_selected(
    *,
    total_score: int = 80,
    topic: str = "테스트 주제",
    content_type: str = "tax_refund",
    topic_group: str = "policy_benefit",
    source_type: str = "news",
    click_potential_score: int = 10,
    viral_risk_flags: list | None = None,
    viral_safety_score: int = 80,
) -> MagicMock:
    raw: dict = {
        "topic_group": topic_group,
        "content_angle": {"content_type": content_type},
        "source_type": source_type,
        "click_potential_score": click_potential_score,
        "hook_angle": {"safe_title_keyword": "확인"},
        "is_test_candidate": False,
        "publish_allowed": True,
        "viral_risk_flags": viral_risk_flags or [],
        "viral_safety_score": viral_safety_score,
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


def _quality_gate(
    *,
    reader_value_score: int = 80,
    default_phrase_detected: bool = False,
    blocking_issues: list | None = None,
) -> dict:
    return {
        "reader_value_score": reader_value_score,
        "default_phrase_detected": default_phrase_detected,
        "blocking_issues": blocking_issues or [],
        "passed": not (blocking_issues or []),
    }


def _golden_ready(*, fill_rate: float = 1.0, confidence: int = 80) -> dict:
    return {
        "matched": confidence >= 80,
        "ready_for_review": confidence >= 80 and fill_rate >= 0.8,
        "pattern_match": {"pattern_id": "tax_refund_hometax_check", "confidence": confidence},
        "slot_result": {
            "slots": {
                "quick_decision_table": [{"내 상황": "a", "할 일": "b"}],
                "actions": [{"번호": 1, "행동": "행동1", "설명": "설명1"}],
                "faq": [{"Q": "Q1", "A": "A1"}],
                "internal_links": [{"주제": "링크1", "content_type": "tax_refund"}],
            },
        },
        "slot_fill_rate": fill_rate,
        "missing_required_slots": [],
        "blocking_issues": [],
        "warnings": [],
    }


def _golden_unmatched() -> dict:
    return {
        "matched": False,
        "ready_for_review": False,
        "pattern_match": {"pattern_id": None, "confidence": 0},
        "slot_result": {},
        "slot_fill_rate": 0.0,
        "missing_required_slots": [],
        "blocking_issues": ["pattern_not_matched", "low_pattern_confidence:0"],
        "warnings": [],
    }


class TestEditorialCandidateGate(unittest.TestCase):

    # ------------------------------------------------------------------ #
    # _compute_content_candidate_grade                                     #
    # ------------------------------------------------------------------ #

    def test_grade_A_golden_ready_high_click(self) -> None:
        selected = _make_selected(click_potential_score=10)
        gpr = _golden_ready(fill_rate=1.0, confidence=80)
        qg = _quality_gate(reader_value_score=80)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        grade = NewsPipeline._compute_content_candidate_grade(
            editorial_scores=es, golden_preview_result=gpr, publish_quality_gate=qg
        )
        self.assertIn(grade, ("A", "B"), f"grade={grade}")

    def test_grade_B_golden_ready_high_reader_value(self) -> None:
        selected = _make_selected(click_potential_score=5)
        gpr = _golden_ready(fill_rate=1.0, confidence=80)
        qg = _quality_gate(reader_value_score=90)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        grade = NewsPipeline._compute_content_candidate_grade(
            editorial_scores=es, golden_preview_result=gpr, publish_quality_gate=qg
        )
        self.assertIn(grade, ("A", "B"), f"grade={grade} — high reader_value should be B or better")

    def test_grade_C_high_click_golden_not_ready(self) -> None:
        selected = _make_selected(click_potential_score=10)
        gpr = _golden_unmatched()
        gpr["pattern_match"]["confidence"] = 0
        qg = _quality_gate()
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        grade = NewsPipeline._compute_content_candidate_grade(
            editorial_scores=es, golden_preview_result=gpr, publish_quality_gate=qg
        )
        self.assertIn(grade, ("C", "D"), f"grade={grade}")

    def test_grade_D_pattern_not_matched(self) -> None:
        selected = _make_selected(click_potential_score=3)
        gpr = _golden_unmatched()
        qg = _quality_gate(reader_value_score=50)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        grade = NewsPipeline._compute_content_candidate_grade(
            editorial_scores=es, golden_preview_result=gpr, publish_quality_gate=qg
        )
        self.assertEqual(grade, "D", f"grade={grade}")

    def test_grade_D_viral_risk_flag(self) -> None:
        selected = _make_selected(click_potential_score=10)
        gpr = _golden_ready()
        qg = _quality_gate(blocking_issues=["viral_risk_flags_detected:privacy,defamation"])
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        grade = NewsPipeline._compute_content_candidate_grade(
            editorial_scores=es, golden_preview_result=gpr, publish_quality_gate=qg
        )
        self.assertEqual(grade, "D", f"grade={grade}")

    def test_grade_D_default_phrase_detected(self) -> None:
        selected = _make_selected(click_potential_score=10)
        gpr = _golden_ready()
        qg = _quality_gate(default_phrase_detected=True)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        grade = NewsPipeline._compute_content_candidate_grade(
            editorial_scores=es, golden_preview_result=gpr, publish_quality_gate=qg
        )
        self.assertEqual(grade, "D")

    # ------------------------------------------------------------------ #
    # _compute_editorial_scores                                            #
    # ------------------------------------------------------------------ #

    def test_editorial_scores_structure(self) -> None:
        selected = _make_selected(click_potential_score=8)
        gpr = _golden_ready()
        qg = _quality_gate(reader_value_score=80)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        for k in ("traffic_potential_score", "usefulness_score", "evergreen_asset_score",
                  "viral_safety_score", "final_editorial_score"):
            self.assertIn(k, es)

    def test_editorial_scores_bounded(self) -> None:
        selected = _make_selected(click_potential_score=15)
        gpr = _golden_ready()
        qg = _quality_gate()
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        self.assertLessEqual(es["traffic_potential_score"], 40)
        self.assertLessEqual(es["usefulness_score"], 40)
        self.assertLessEqual(es["evergreen_asset_score"], 10)
        self.assertLessEqual(es["viral_safety_score"], 10)
        self.assertLessEqual(es["final_editorial_score"], 100)
        self.assertGreaterEqual(es["final_editorial_score"], 0)

    def test_usefulness_high_when_golden_filled(self) -> None:
        selected = _make_selected(click_potential_score=5)
        gpr = _golden_ready(fill_rate=1.0)
        qg = _quality_gate(reader_value_score=90)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        self.assertGreater(es["usefulness_score"], 20)

    def test_usefulness_low_when_golden_unmatched(self) -> None:
        selected = _make_selected()
        gpr = _golden_unmatched()
        qg = _quality_gate(reader_value_score=50)
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        self.assertLess(es["usefulness_score"], 20)

    def test_evergreen_asset_score_for_evergreen(self) -> None:
        selected = _make_selected(source_type="evergreen_fallback")
        gpr = _golden_ready(fill_rate=1.0)
        qg = _quality_gate()
        es = NewsPipeline._compute_editorial_scores(
            selected=selected, publish_quality_gate=qg, golden_preview_result=gpr
        )
        self.assertGreater(es["evergreen_asset_score"], 0)

    # ------------------------------------------------------------------ #
    # PUBLISH_HOLD_PHASE2                                                  #
    # ------------------------------------------------------------------ #

    def test_publish_hold_phase2_default_true(self) -> None:
        import os
        os.environ.pop("PUBLISH_HOLD_PHASE2", None)
        self.assertTrue(NewsPipeline._is_publish_hold_phase2())

    def test_publish_hold_phase2_explicit_false(self) -> None:
        import os
        os.environ["PUBLISH_HOLD_PHASE2"] = "false"
        self.assertFalse(NewsPipeline._is_publish_hold_phase2())
        os.environ.pop("PUBLISH_HOLD_PHASE2", None)

    def test_publish_hold_phase2_explicit_true(self) -> None:
        import os
        os.environ["PUBLISH_HOLD_PHASE2"] = "true"
        self.assertTrue(NewsPipeline._is_publish_hold_phase2())
        os.environ.pop("PUBLISH_HOLD_PHASE2", None)


class TestNewsAutoPublishGate(unittest.TestCase):
    def _base_result(self, **overrides) -> dict:
        base = {
            "source_type": "news",
            "fallback_candidate": False,
            "article_candidate_generated": True,
            "publish_ready": True,
            "geo_ready": True,
            "sge_ready": True,
        }
        base.update(overrides)
        return base

    def test_auto_publish_false_blocks_even_when_ready(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=False)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(),
            publish_quality_gate={"passed": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("auto_publish_false", gate["blocking_reasons"])

    def test_sge_ready_false_blocks_publish(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(sge_ready=False),
            publish_quality_gate={"passed": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("sge_ready_false", gate["blocking_reasons"])

    def test_article_candidate_required_for_publish(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(article_candidate_generated=False),
            publish_quality_gate={"passed": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("article_candidate_not_generated", gate["blocking_reasons"])

    def test_today_issue_explainer_can_publish_without_golden_article_candidate(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(
                source_type="naver_trending",
                topic_group="today_issue",
                content_angle={"content_type": "today_issue_explainer"},
                trending_engine=True,
                today_buzz_score=9,
                source_count=4,
                article_candidate_generated=False,
                publish_ready=False,
                geo_ready=False,
                sge_ready=False,
            ),
            publish_quality_gate={
                "passed": True,
                "article_focus_score": 72,
                "reader_value_score": 82,
            },
        )

        self.assertTrue(gate["allowed"], gate["blocking_reasons"])
        self.assertTrue(gate["top_issue_direct_publish"])

    def test_evergreen_fallback_not_auto_publishable(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(source_type="evergreen_fallback"),
            publish_quality_gate={"passed": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn(
            "source_type_not_auto_publishable:evergreen_fallback",
            gate["blocking_reasons"],
        )

    def test_daily_evergreen_fallback_can_publish_when_all_gates_ready(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(
                source_type="evergreen_fallback",
                fallback_reason="no_golden_publish_candidate_used_evergreen",
                topic_group="delivery_money",
                content_angle={"content_type": "money_checklist"},
                evergreen_axis="money_life",
                article_candidate_generated=True,
                publish_ready=True,
                geo_ready=True,
                sge_ready=True,
                human_review_required=False,
                near_match=False,
            ),
            publish_quality_gate={"passed": True},
        )

        self.assertTrue(gate["allowed"], gate["blocking_reasons"])
        self.assertTrue(gate["evergreen_daily_fallback"])

    def test_general_life_not_auto_publishable(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(content_angle={"content_type": "general_life"}),
            publish_quality_gate={"passed": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("content_type_not_auto_publishable:general_life", gate["blocking_reasons"])
        self.assertIn("content_type_excluded_from_news:general_life", gate["blocking_reasons"])

    def test_blogspot_growth_axis_not_auto_publishable(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(evergreen_axis="blogspot_growth"),
            publish_quality_gate={"passed": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("evergreen_axis_excluded_from_news:blogspot_growth", gate["blocking_reasons"])

    def test_allowed_news_content_type_passes_gate(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish", auto_publish=True)
        gate = pipeline._evaluate_auto_publish_gate(
            base_result=self._base_result(content_angle={"content_type": "platform_change"}),
            publish_quality_gate={"passed": True},
        )
        self.assertTrue(gate["allowed"], gate["blocking_reasons"])


class TestGeneralLifePolicyLeakBlocks(unittest.TestCase):
    def test_general_life_does_not_match_tax_refund_pattern(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService

        result = GoldenPatternService().match_pattern(
            topic="블로그스팟 내부링크 넣기 전에 볼 기준 신청 전 이것부터",
            content_type="general_life",
            topic_group="general_life",
            summary="환급 지원금 대상 조건 같은 정책형 문구가 섞인 일반 생활 주제",
        )
        self.assertFalse(result["matched"])
        self.assertNotEqual(result["pattern_id"], "tax_refund_hometax_check")

    def test_general_life_title_blocks_policy_phrases(self) -> None:
        from blogspot_automation.services.title_candidate_service import TitleCandidateService

        svc = TitleCandidateService()
        for phrase in ("신청 전", "대상 조건", "환급", "지원금"):
            scored = svc.score_title(
                f"블로그스팟 내부링크 넣기 전에 볼 기준 {phrase} 이것부터",
                content_type="general_life",
                topic_group="general_life",
            )
            self.assertFalse(scored["is_allowed"], phrase)
            self.assertTrue(
                any("general_life_policy_phrase" in issue for issue in scored["blocking_issues"]),
                scored["blocking_issues"],
            )


if __name__ == "__main__":
    unittest.main()
