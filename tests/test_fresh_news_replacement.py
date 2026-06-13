from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ------------------------------------------------------------------ #
# Helpers — ScoredNewsCandidate 모킹                                   #
# ------------------------------------------------------------------ #

def _make_scored(
    topic: str,
    total_score: int = 80,
    *,
    stale: bool = False,
    stale_penalty: bool = False,
    fallback: bool = False,
    test_cand: bool = False,
    publish_allowed: bool = True,
    risk_penalty: int = 0,
    golden_matched: bool = False,
    grade: str = "B",
    freshness_score: float = 0.8,
    topic_group: str = "delivery_money",
    content_type: str = "money_checklist",
) -> MagicMock:
    raw = {
        "topic_group": topic_group,
        "content_angle": {"content_type": content_type, "topic_group": topic_group},
        "click_potential_score": 10,
        "is_stale": stale,
        "stale_penalty_applied": stale_penalty,
        "source_type": "fallback" if fallback else "news",
        "is_test_candidate": test_cand,
        "publish_allowed": publish_allowed,
        "golden_matched": golden_matched,
        "topic_candidate_grade": grade,
    }
    candidate = MagicMock()
    candidate.topic = topic
    candidate.raw = raw
    scored = MagicMock()
    scored.candidate = candidate
    scored.total_score = total_score
    scored.risk_penalty = risk_penalty
    scored.freshness_score = freshness_score
    return scored


def _pipeline_helpers():
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline
    return NewsPipeline


# ------------------------------------------------------------------ #
# Tests                                                               #
# ------------------------------------------------------------------ #

class TestIsStaleCandidate(unittest.TestCase):
    """_is_stale_candidate 판정 기준"""

    def _check(self, **kwargs) -> bool:
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        scored = _make_scored("test topic", **kwargs)
        return NewsPipeline._is_stale_candidate(scored)

    def test_stale_penalty_applied_is_stale(self):
        self.assertTrue(self._check(stale_penalty=True))

    def test_is_stale_flag(self):
        self.assertTrue(self._check(stale=True))

    def test_fresh_candidate_not_stale(self):
        self.assertFalse(self._check(stale=False, stale_penalty=False))

    def test_policy_benefit_with_official_check_needed(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        scored = _make_scored("세금 환급 안내", topic_group="policy_benefit")
        scored.candidate.raw["strategy_score_breakdown"] = {"official_source_check_needed": True}
        self.assertTrue(NewsPipeline._is_stale_candidate(scored))

    def test_general_life_without_check_needed_not_stale(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        scored = _make_scored("일상 주제", topic_group="general_life")
        scored.candidate.raw["strategy_score_breakdown"] = {"official_source_check_needed": True}
        self.assertFalse(NewsPipeline._is_stale_candidate(scored))


class TestFindFreshReplacement(unittest.TestCase):
    """_find_fresh_replacement_candidate 선택 기준"""

    def _find(self, scored_list, original):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        return NewsPipeline._find_fresh_replacement_candidate(scored_list, original)

    # 1. stale 선택 시 fresh replacement 선택
    def test_stale_original_returns_fresh(self):
        original = _make_scored("stale topic", stale_penalty=True)
        fresh    = _make_scored("fresh topic", total_score=82, golden_matched=True)
        result, reason = self._find([original, fresh], original)
        self.assertIsNotNone(result)
        self.assertEqual(result.candidate.topic, "fresh topic")

    # 2. golden_matched fresh가 있으면 article_candidate 생성 가능
    def test_golden_matched_fresh_preferred(self):
        original    = _make_scored("stale topic", stale_penalty=True)
        fresh_norm  = _make_scored("normal fresh", total_score=85, golden_matched=False)
        fresh_gold  = _make_scored("golden fresh", total_score=80, golden_matched=True)
        result, _ = self._find([original, fresh_norm, fresh_gold], original)
        self.assertEqual(result.candidate.topic, "golden fresh")

    # 3. fresh 없으면 None 반환
    def test_no_fresh_returns_none(self):
        original = _make_scored("stale", stale_penalty=True)
        result, reason = self._find([original], original)
        self.assertIsNone(result)
        self.assertIn("no_fresh", reason)

    # 4. stale 후보는 publish_ready=false — 이미 run_artifact에서 처리하므로 직접 테스트
    def test_stale_excluded_from_pool(self):
        original  = _make_scored("stale", stale_penalty=True)
        also_stale = _make_scored("also stale", stale=True, total_score=90)
        result, _ = self._find([original, also_stale], original)
        self.assertIsNone(result)

    # 5. scoring blocking_issues stale → pool 미포함
    def test_scoring_stale_penalty_excluded(self):
        original = _make_scored("original", stale_penalty=True)
        stale2   = _make_scored("stale 2", stale_penalty=True, total_score=90)
        fresh    = _make_scored("fresh", total_score=80)
        result, _ = self._find([original, stale2, fresh], original)
        self.assertEqual(result.candidate.topic, "fresh")

    # 7. fallback_candidate=True이면 제외
    def test_fallback_excluded(self):
        original = _make_scored("stale", stale_penalty=True)
        fallback = _make_scored("fallback topic", fallback=True, total_score=90, golden_matched=True)
        result, _ = self._find([original, fallback], original)
        self.assertIsNone(result)

    # 8. risk_penalty>0이면 제외
    def test_risk_penalty_excluded(self):
        original = _make_scored("stale", stale_penalty=True)
        risky    = _make_scored("risky topic", risk_penalty=20, total_score=90, golden_matched=True)
        result, _ = self._find([original, risky], original)
        self.assertIsNone(result)


class TestStaleReplacementPipelineIntegration(unittest.TestCase):
    """파이프라인 통합: stale 감지 → 교체 or hold"""

    def _run_with_stale(self, *, has_fresh: bool) -> dict:
        """stale 후보를 selected로 만들고 fresh 여부에 따라 파이프라인 실행."""
        from blogspot_automation.services.run_artifact_service import RunArtifactService
        from blogspot_automation.services.publish_history_service import PublishHistoryService
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        # stale scored candidate
        stale_cand = _make_scored("stale news topic", total_score=85, stale_penalty=True,
                                  topic_group="policy_benefit")
        stale_cand.candidate.category = "policy"
        stale_cand.candidate.summary = "stale summary"

        # fresh replacement (선택적)
        fresh_cand = None
        if has_fresh:
            fresh_cand = _make_scored("fresh news topic", total_score=80,
                                      golden_matched=True, grade="A")
            fresh_cand.candidate.category = "news"
            fresh_cand.candidate.summary = "fresh summary"

        scored_list = [stale_cand] + ([fresh_cand] if fresh_cand else [])

        with tempfile.TemporaryDirectory() as tmp:
            hist_path = Path(tmp) / "publish_history.json"
            pipeline = NewsPipeline(
                artifact_service=RunArtifactService(runs_dir=tmp),
                publish_history_service=PublishHistoryService(history_path=hist_path),
                dry_run=True,
            )
            # _find_fresh_replacement_candidate 직접 테스트
            replacement, reason = NewsPipeline._find_fresh_replacement_candidate(
                scored_list, stale_cand
            )
            return {
                "replacement": replacement,
                "reason": reason,
                "has_fresh": has_fresh,
            }

    # 1. stale → fresh replacement 선택
    def test_stale_finds_replacement(self):
        r = self._run_with_stale(has_fresh=True)
        self.assertIsNotNone(r["replacement"])
        self.assertEqual(r["replacement"].candidate.topic, "fresh news topic")

    # 3. fresh 없으면 replacement=None
    def test_no_replacement_returns_none(self):
        r = self._run_with_stale(has_fresh=False)
        self.assertIsNone(r["replacement"])

    # 4. stale 후보는 _is_stale_candidate=True
    def test_stale_detected(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        stale = _make_scored("stale", stale_penalty=True)
        self.assertTrue(NewsPipeline._is_stale_candidate(stale))

    # 5. scoring stale → publish_ready=false (run_artifact_service 연동)
    def test_stale_publish_ready_false_in_artifact(self):
        from blogspot_automation.services.golden_article_preview_service import (
            GoldenArticlePreviewService, GoldenPatternService, SlotFillerService,
        )
        from blogspot_automation.services.run_artifact_service import RunArtifactService

        ps  = GoldenPatternService()
        sf  = SlotFillerService()
        svc = GoldenArticlePreviewService()
        pm  = ps.match_pattern(topic="세금 환급금 조회 방법", content_type="tax_refund", topic_group="policy_benefit")
        sr  = sf.fill_slots(pattern_id="tax_refund_hometax_check", topic="세금 환급금 조회 방법")
        st  = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        html = svc.render_article_candidate_html(pm, sr, selected_title=st)
        best = {"title": st, "ctr_score": 85, "risk_score": 0, "promise_match_score": 88}

        preview = {
            "matched": True, "near_match": False, "ready_for_review": True,
            "pattern_match": pm, "slot_result": sr, "slot_fill_rate": 1.0,
            "missing_required_slots": [], "blocking_issues": [], "warnings": [],
            "_editorial_scores": {"traffic_potential_score": 30, "usefulness_score": 35,
                                   "final_editorial_score": 90},
            "_content_candidate_grade": "A", "_can_generate_candidate": True,
            "_article_candidate_html": html, "_title_result": {"best_title": best},
            "_selected_title": st,
            "_blogspot_labels": ["세금환급", "홈택스", "생활정보"],
            "_hashtags": ["#세금환급","#환급금조회","#홈택스","#손택스",
                          "#국세환급금","#환급계좌","#생활정보","#체크리스트"],
            "_content_type": "tax_refund", "_topic_group": "policy_benefit",
            "_stale_candidate": True,        # stale
            "_scoring_stale_penalty": True,
        }

        with tempfile.TemporaryDirectory() as tmp:
            rp = Path(tmp) / "run"; rp.mkdir()
            RunArtifactService(runs_dir=tmp).save_golden_preview_artifacts(rp, preview)
            meta = json.loads((rp / "article_candidate_meta.json").read_text(encoding="utf-8"))

        self.assertFalse(meta.get("publish_ready"), "stale인데 publish_ready=True")
        self.assertTrue(meta.get("stale_source_warning"))
        self.assertFalse(meta.get("fresh_source_ok"))

    # 6. replacement 발생 시 replacement_meta 포함 확인
    def test_replacement_meta_fields(self):
        from blogspot_automation.services.run_artifact_service import RunArtifactService
        from blogspot_automation.services.golden_article_preview_service import (
            GoldenArticlePreviewService, GoldenPatternService, SlotFillerService,
        )

        ps  = GoldenPatternService()
        sf  = SlotFillerService()
        svc = GoldenArticlePreviewService()
        pm  = ps.match_pattern(topic="세금 환급금 조회 방법", content_type="tax_refund", topic_group="policy_benefit")
        sr  = sf.fill_slots(pattern_id="tax_refund_hometax_check", topic="세금 환급금 조회 방법")
        html = svc.render_article_candidate_html(pm, sr, selected_title="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        best = {"title": "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", "ctr_score": 85}

        _repl_meta = {
            "stale_candidate_replaced": True,
            "original_stale_topic": "stale_topic",
            "original_stale_source_url": "",
            "original_stale_published_at": "",
            "original_stale_reason": "stale_penalty_applied",
            "fresh_replacement_topic": "fresh topic",
            "fresh_replacement_reason": "golden_matched=True grade=A score=82",
            "fresh_replacement_source_url": "",
            "fresh_replacement_published_at": "",
            "fresh_replacement_selected": True,
        }

        preview = {
            "matched": True, "near_match": False, "ready_for_review": True,
            "pattern_match": pm, "slot_result": sr, "slot_fill_rate": 1.0,
            "missing_required_slots": [], "blocking_issues": [], "warnings": [],
            "_editorial_scores": {"traffic_potential_score": 30, "usefulness_score": 35,
                                   "final_editorial_score": 90},
            "_content_candidate_grade": "A", "_can_generate_candidate": True,
            "_article_candidate_html": html, "_title_result": {"best_title": best},
            "_selected_title": best["title"],
            "_blogspot_labels": ["세금환급", "홈택스", "생활정보"],
            "_hashtags": ["#세금환급","#환급금조회","#홈택스","#손택스",
                          "#국세환급금","#환급계좌","#생활정보","#체크리스트"],
            "_content_type": "tax_refund", "_topic_group": "policy_benefit",
            "_stale_candidate": False,
            "_scoring_stale_penalty": False,
            "_replacement_meta": _repl_meta,
        }

        with tempfile.TemporaryDirectory() as tmp:
            rp = Path(tmp) / "run"; rp.mkdir()
            RunArtifactService(runs_dir=tmp).save_golden_preview_artifacts(rp, preview)
            meta = json.loads((rp / "article_candidate_meta.json").read_text(encoding="utf-8"))

        self.assertTrue(meta.get("stale_candidate_replaced"))
        self.assertEqual(meta.get("original_stale_topic"), "stale_topic")
        self.assertEqual(meta.get("fresh_replacement_topic"), "fresh topic")
        self.assertTrue(meta.get("fresh_replacement_selected"))


class TestNoInterferenceRegression(unittest.TestCase):
    """9. fresh 처음 선택 시 replacement 로직 미개입, 10. AI pipeline 미영향"""

    # 9. fresh 처음 선택 → _is_stale_candidate=False
    def test_fresh_first_selection_no_stale(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        fresh = _make_scored("fresh topic", total_score=85, stale=False, stale_penalty=False)
        self.assertFalse(NewsPipeline._is_stale_candidate(fresh))

    # 10. AI pipeline은 _is_stale_candidate 없음 (import 충돌 없음)
    def test_ai_pipeline_unaffected(self):
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
        pipeline = AiTopicPipeline(dry_run=True)
        # _is_stale_candidate가 AiTopicPipeline에 없어야 함
        self.assertFalse(hasattr(AiTopicPipeline, "_is_stale_candidate"))


if __name__ == "__main__":
    unittest.main()
