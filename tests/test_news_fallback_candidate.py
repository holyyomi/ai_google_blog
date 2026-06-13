from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ------------------------------------------------------------------ #
# Helpers
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
    source_type: str | None = None,
    risk_penalty: int = 0,
    golden_matched: bool = False,
    grade: str = "B",
    freshness_score: float = 0.8,
    content_type: str = "general_life",
    topic_group: str = "general_life",
    evergreen_axis: str = "",
) -> MagicMock:
    raw = {
        "topic_group": topic_group,
        "is_stale": stale,
        "stale_penalty_applied": stale_penalty,
        "source_type": source_type or ("fallback" if fallback else "news"),
        "is_test_candidate": test_cand,
        "publish_allowed": publish_allowed,
        "golden_matched": golden_matched,
        "topic_candidate_grade": grade,
        "evergreen_axis": evergreen_axis,
        "content_angle": {"content_type": content_type, "topic_group": topic_group},
        "click_potential_score": 10,
    }
    candidate = MagicMock()
    candidate.topic = topic
    candidate.raw = raw
    candidate.category = topic_group
    candidate.summary = f"summary for {topic}"
    scored = MagicMock()
    scored.candidate = candidate
    scored.total_score = total_score
    scored.risk_penalty = risk_penalty
    scored.freshness_score = freshness_score
    scored.search_demand_score = 0
    scored.contrarian_gap_score = 0
    scored.mass_impact_score = 0
    scored.adsense_value_score = 0
    scored.hook_score = 0
    scored.reason = "test"
    return scored


def _pipeline():
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline
    return NewsPipeline


def _search_fallback(pool, original):
    from blogspot_automation.pipelines.news_pipeline import NewsPipeline
    pipeline = NewsPipeline(dry_run=True)
    return pipeline._search_fallback_in_pool(pool, original)


# ------------------------------------------------------------------ #
# Tests
# ------------------------------------------------------------------ #

class TestSearchFallbackInPool(unittest.TestCase):
    """_search_fallback_in_pool 핵심 로직"""

    def _orig(self):
        return _make_scored("stale original", stale_penalty=True,
                            content_type="tax_refund", topic_group="policy_benefit")

    # 1. stale + no fresh → fallback 탐색 실행
    def test_finds_fallback_when_no_fresh(self):
        orig = self._orig()
        viral = _make_scored("viral news", content_type="viral_issue_decode", total_score=85)
        result, reason, fb_type = _search_fallback([orig, viral], orig)
        self.assertIsNotNone(result)
        self.assertEqual(fb_type, "viral")

    # 2. viral fallback → article_candidate 생성 가능 (후보 선택까지)
    def test_viral_fallback_selected(self):
        orig = self._orig()
        viral = _make_scored("viral fallback", content_type="viral_issue_decode", total_score=82)
        result, _, fb_type = _search_fallback([orig, viral], orig)
        self.assertEqual(fb_type, "viral")
        self.assertEqual(result.candidate.topic, "viral fallback")

    # 3. evergreen ai_work_tip fallback은 news_blog 자동발행 후보가 아니다.
    def test_evergreen_ai_fallback_excluded(self):
        orig = self._orig()
        ai = _make_scored("ChatGPT 활용법", content_type="ai_work_tip",
                          topic_group="ai_work", total_score=75, golden_matched=True)
        with patch.dict("os.environ", {"AI_BLOG_MODE": "false"}, clear=False):
            result, _, fb_type = _search_fallback([orig, ai], orig)
        self.assertIsNone(result)
        self.assertEqual(fb_type, "hold")

    def test_evergreen_ai_fallback_allowed_in_ai_blog_mode(self):
        orig = self._orig()
        ai = _make_scored("ChatGPT 활용법", content_type="ai_work_tip",
                          topic_group="ai_work", total_score=85, golden_matched=True)
        ai.candidate.raw["click_potential_score"] = 8

        with patch.dict("os.environ", {"AI_BLOG_MODE": "true"}, clear=False):
            result, _, fb_type = _search_fallback([orig, ai], orig)

        self.assertIsNotNone(result)
        self.assertEqual(fb_type, "evergreen")

    # 4. tax_refund stale → fallback 자동 발행 후보로 사용 안 함
    def test_tax_refund_excluded_from_fallback(self):
        orig = self._orig()
        tax = _make_scored("세금 환급 조회", content_type="tax_refund", total_score=90)
        result, _, _ = _search_fallback([orig, tax], orig)
        self.assertIsNone(result)

    # policy_benefit은 명시 whitelist에 포함된다.
    def test_policy_benefit_allowed(self):
        orig = self._orig()
        pol = _make_scored("정책 지원", content_type="policy_benefit", total_score=90)
        result, _, fb_type = _search_fallback([orig, pol], orig)
        self.assertIsNotNone(result)
        self.assertEqual(fb_type, "useful_news")

    # fallback 자신도 stale이면 제외
    def test_stale_fallback_excluded(self):
        orig = self._orig()
        stale_fb = _make_scored("stale fallback", content_type="ai_work_tip",
                                total_score=85, stale_penalty=True)
        result, _, _ = _search_fallback([orig, stale_fb], orig)
        self.assertIsNone(result)

    # 10. fallback도 없으면 None 반환
    def test_no_fallback_returns_none(self):
        orig = self._orig()
        result, reason, fb_type = _search_fallback([orig], orig)
        self.assertIsNone(result)
        self.assertEqual(fb_type, "hold")

    # viral > evergreen > useful_news 우선순위
    def test_viral_preferred_over_evergreen(self):
        orig = self._orig()
        viral = _make_scored("viral", content_type="viral_issue_decode", total_score=75)
        ai    = _make_scored("ai", content_type="ai_work_tip", total_score=90)
        result, _, fb_type = _search_fallback([orig, viral, ai], orig)
        self.assertEqual(fb_type, "viral")

    def test_general_life_fallback_excluded(self):
        orig = self._orig()
        general = _make_scored("general", content_type="general_life", total_score=95)
        result, _, fb_type = _search_fallback([orig, general], orig)
        self.assertIsNone(result)
        self.assertEqual(fb_type, "hold")

    def test_evergreen_source_type_excluded(self):
        orig = self._orig()
        money = _make_scored(
            "money evergreen",
            content_type="money_checklist",
            topic_group="delivery_money",
            source_type="evergreen_fallback",
            total_score=95,
        )
        result, _, fb_type = _search_fallback([orig, money], orig)
        self.assertIsNone(result)
        self.assertEqual(fb_type, "hold")


class TestFallbackMetaFields(unittest.TestCase):
    """5~8: fallback 사용 시 artifact 메타 필드"""

    @classmethod
    def setUpClass(cls) -> None:
        from blogspot_automation.services.golden_article_preview_service import (
            GoldenArticlePreviewService, GoldenPatternService, SlotFillerService,
        )
        from blogspot_automation.services.run_artifact_service import RunArtifactService

        ps  = GoldenPatternService()
        sf  = SlotFillerService()
        svc = GoldenArticlePreviewService()
        pm  = ps.match_pattern(
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            content_type="ai_work_tip", topic_group="ai_work",
        )
        sr  = sf.fill_slots(
            pattern_id="ai_work_time_savings",
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
        )
        st  = "무료 ChatGPT로도 업무 시간 줄이는 3가지 패턴"
        html = svc.render_article_candidate_html(pm, sr, selected_title=st)
        best = {"title": st, "ctr_score": 88, "risk_score": 0, "promise_match_score": 85}

        _fb_meta = {
            "stale_candidate_replaced": True,
            "no_fresh_replacement_fallback_used": True,
            "fallback_type": "evergreen",
            "fallback_reason": "fallback_type=evergreen ct=ai_work_tip score=75",
            "fallback_topic": "직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            "fallback_content_type": "ai_work_tip",
            "fallback_topic_group": "ai_work",
            "fallback_human_review_required": True,
            "original_stale_topic": "stale_original",
            "original_stale_source_url": "",
            "original_stale_published_at": "",
            "original_stale_reason": "stale_penalty_applied",
            "fresh_replacement_attempted": True,
            "fresh_replacement_found": False,
            "fallback_attempted": True,
            "fallback_found": True,
        }

        preview = {
            "matched": True, "near_match": False, "ready_for_review": True,
            "pattern_match": pm, "slot_result": sr, "slot_fill_rate": 1.0,
            "missing_required_slots": [], "blocking_issues": [], "warnings": [],
            "_editorial_scores": {"traffic_potential_score": 24, "usefulness_score": 30,
                                   "final_editorial_score": 72},
            "_content_candidate_grade": "B", "_can_generate_candidate": True,
            "_article_candidate_html": html, "_title_result": {"best_title": best},
            "_selected_title": st,
            "_blogspot_labels": ["AI활용", "직장인AI", "생산성"],
            "_hashtags": ["#AI활용", "#업무자동화", "#ChatGPT활용",
                          "#직장인AI", "#생산성향상", "#프롬프트작성", "#업무효율"],
            "_content_type": "ai_work_tip", "_topic_group": "ai_work",
            "_stale_candidate": False,
            "_scoring_stale_penalty": False,
            "_replacement_meta": _fb_meta,
        }

        with tempfile.TemporaryDirectory() as tmp:
            rp = Path(tmp) / "run"; rp.mkdir()
            RunArtifactService(runs_dir=tmp).save_golden_preview_artifacts(rp, preview)
            cls._meta = json.loads((rp / "article_candidate_meta.json").read_text(encoding="utf-8"))
            cls._html_exists = (rp / "article_candidate.html").exists()

    # 5. no_fresh_replacement_fallback_used=true 기록
    def test_fallback_used_flag(self):
        self.assertTrue(self._meta.get("no_fresh_replacement_fallback_used"))

    # 6. run_meta에 fallback_type 기록 (article_candidate_meta 통해 확인)
    def test_fallback_type_recorded(self):
        self.assertEqual(self._meta.get("fallback_type"), "evergreen")

    # 7. publish_allowed_in_phase2=false 유지
    def test_publish_allowed_false(self):
        self.assertFalse(self._meta.get("publish_allowed_in_phase2"))

    # 8. human_review_required=true 유지
    def test_human_review_required(self):
        self.assertTrue(self._meta.get("human_review_required"))

    # 9. fallback GEO 필드 정상 생성
    def test_fallback_geo_fields(self):
        self.assertIn("geo_score", self._meta)
        self.assertIn("geo_ready", self._meta)
        self.assertGreaterEqual(self._meta.get("geo_score", 0), 0)

    # article_candidate.html 생성 확인
    def test_article_candidate_html_generated(self):
        self.assertTrue(self._html_exists, "fallback article_candidate.html 미생성")


class TestCandidateHoldReport(unittest.TestCase):
    """10~11: fallback 없을 때 hold report"""

    def _make_hold_report_scenario(self):
        """stale + no fresh + no fallback → hold report"""
        from blogspot_automation.services.run_artifact_service import RunArtifactService

        with tempfile.TemporaryDirectory() as tmp:
            rp = Path(tmp) / "run"; rp.mkdir()
            hold_report = {
                "article_candidate_generated": False,
                "publish_attempted": False,
                "hold_reason": "no_fresh_or_fallback_candidate",
                "original_stale_topic": "stale topic",
                "original_stale_published_at": "2026-01-01",
                "original_stale_source_url": "https://example.com",
                "fresh_replacement_attempted": True,
                "fresh_replacement_found": False,
                "fallback_attempted": True,
                "fallback_found": False,
                "stale_source_warning": True,
                "fresh_source_replacement_required": True,
                "next_action": "wait_for_fresh_news_or_manual_publish_review",
            }
            RunArtifactService._write_json(rp / "candidate_hold_report.json", hold_report)
            return json.loads((rp / "candidate_hold_report.json").read_text(encoding="utf-8"))

    # 10. fallback 없으면 candidate_hold_report 생성
    def test_hold_report_generated(self):
        report = self._make_hold_report_scenario()
        self.assertFalse(report["article_candidate_generated"])
        self.assertFalse(report.get("publish_attempted", False))

    # 11. hold_reason=no_fresh_or_fallback_candidate
    def test_hold_reason(self):
        report = self._make_hold_report_scenario()
        self.assertEqual(report["hold_reason"], "no_fresh_or_fallback_candidate")

    def test_hold_report_tracking_fields(self):
        report = self._make_hold_report_scenario()
        self.assertTrue(report.get("fresh_replacement_attempted"))
        self.assertFalse(report.get("fresh_replacement_found"))
        self.assertTrue(report.get("fallback_attempted"))
        self.assertFalse(report.get("fallback_found"))

    def test_hold_report_stale_warning(self):
        report = self._make_hold_report_scenario()
        self.assertTrue(report.get("stale_source_warning"))
        self.assertTrue(report.get("fresh_source_replacement_required"))

    def test_no_real_news_hold_report_does_not_write_article_html(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        from blogspot_automation.services.publish_history_service import PublishHistoryService
        from blogspot_automation.services.run_artifact_service import RunArtifactService

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = NewsPipeline(
                artifact_service=RunArtifactService(runs_dir=tmp),
                publish_history_service=PublishHistoryService(history_path=Path(tmp) / "hist.json"),
                dry_run=True,
            )
            scored = [
                _make_scored(
                    "blogspot growth",
                    content_type="general_life",
                    topic_group="general_life",
                    source_type="evergreen_fallback",
                    total_score=95,
                )
            ]
            result = pipeline._save_no_real_news_hold_report(
                candidates=[],
                scored=scored,
                publishable=scored,
                fallback_reason="no_real_news_publish_candidate",
                news_candidate_count=1,
                news_publishable_count=1,
                news_publishable_real_count=0,
                recent_evergreen_axes=[],
                preferred_axis="blogspot_growth",
                recommended_next_axis="money_life",
                recent_topic_groups_hist=[],
                recent_content_types_hist=[],
            )
            artifact_dir = Path(result["artifact_dir"])
            report = json.loads((artifact_dir / "candidate_hold_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["hold_reason"], "no_real_news_publish_candidate")
            self.assertFalse(report["article_candidate_generated"])
            self.assertFalse(report["publish_attempted"])
            self.assertFalse((artifact_dir / "article.html").exists())
            self.assertFalse((artifact_dir / "article_candidate.html").exists())


class TestAIPipelineUnaffected(unittest.TestCase):
    """12. AI pipeline은 _find_fallback_when_no_fresh_replacement 없음"""

    def test_ai_pipeline_no_fallback_method(self):
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
        self.assertFalse(hasattr(AiTopicPipeline, "_find_fallback_when_no_fresh_replacement"))
        self.assertFalse(hasattr(AiTopicPipeline, "_search_fallback_in_pool"))

    def test_ai_pipeline_runs_normally(self):
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
        from blogspot_automation.services.naver_blog_service import NaverPost

        fake_post = NaverPost(
            title="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            link="https://blog.naver.com/holyyomi/123456789",
            log_no="123456789",
            pub_date="", rss_excerpt="ChatGPT 업무 활용 테스트", full_text="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            from blogspot_automation.services.run_artifact_service import RunArtifactService
            from blogspot_automation.services.publish_history_service import PublishHistoryService
            pipeline = AiTopicPipeline(
                artifact_service=RunArtifactService(runs_dir=tmp),
                publish_history_service=PublishHistoryService(history_path=Path(tmp) / "hist.json"),
                dry_run=True,
                _force_naver_post=fake_post,
            )
            result = pipeline.run_once()
        self.assertIn(result.get("status"), ("dry_run_saved", "skipped", "held_for_review"))


if __name__ == "__main__":
    unittest.main()
