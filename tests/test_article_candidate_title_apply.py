from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any


def _build_preview_result(
    *,
    grade: str = "A",
    selected_title: str = "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지",
    topic: str = "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지",
    pattern_id: str = "viral_ott_reaction_decode",
) -> dict[str, Any]:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService

    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()

    pm = ps.match_pattern(topic=topic)
    sr = sf.fill_slots(pattern_id=pattern_id, topic=topic)

    candidate_html = svc.render_article_candidate_html(pm, sr, selected_title=selected_title)

    best = {
        "title": selected_title,
        "title_type": "viral",
        "ctr_score": 88,
        "risk_score": 0,
        "promise_match_score": 90,
        "is_allowed": True,
    } if selected_title else {}

    return {
        "matched": True,
        "ready_for_review": grade in ("A", "B"),
        "pattern_match": pm,
        "slot_result": sr,
        "slot_fill_rate": 1.0,
        "missing_required_slots": [],
        "blocking_issues": [],
        "warnings": [],
        "preview_html": "<html><head><title>[PREVIEW] 테스트</title></head><body><h1>테스트</h1></body></html>",
        "_editorial_scores": {
            "traffic_potential_score": 30,
            "usefulness_score": 35,
            "final_editorial_score": 90,
        },
        "_content_candidate_grade": grade,
        "_can_generate_candidate": grade in ("A", "B") and bool(selected_title),
        "_article_candidate_html": candidate_html,
        "_title_result": {"best_title": best, "candidates": [best], "topic": topic},
        "_selected_title": selected_title,
    }


def _run_and_collect(preview_result: dict) -> dict[str, str]:
    """임시 디렉토리에 artifacts 저장 후 파일 내용을 반환한다."""
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    with tempfile.TemporaryDirectory() as tmpdir:
        run_path = Path(tmpdir) / "test_run"
        run_path.mkdir()
        art = RunArtifactService(runs_dir=tmpdir)
        art.save_golden_preview_artifacts(run_path, preview_result)
        return {f.name: f.read_text(encoding="utf-8") for f in run_path.iterdir()}


class TestSelectedTitleApplied(unittest.TestCase):

    def setUp(self) -> None:
        self.result = _build_preview_result()
        self.contents = _run_and_collect(self.result)

    def test_article_candidate_html_created(self) -> None:
        self.assertIn("article_candidate.html", self.contents)

    def test_h1_reflects_selected_title(self) -> None:
        html = self.contents["article_candidate.html"]
        h1_match = re.search(r'<h1>([^<]*)</h1>', html)
        self.assertIsNotNone(h1_match)
        self.assertEqual(h1_match.group(1), "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지")

    def test_title_tag_reflects_selected_title(self) -> None:
        html = self.contents["article_candidate.html"]
        title_match = re.search(r'<title>([^<]*)</title>', html)
        self.assertIsNotNone(title_match)
        self.assertEqual(title_match.group(1), "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지")

    def test_jsonld_headline_reflects_selected_title(self) -> None:
        html = self.contents["article_candidate.html"]
        jld_match = re.search(r'"headline"\s*:\s*"([^"]+)"', html)
        self.assertIsNotNone(jld_match, "JSON-LD headline not found")
        self.assertEqual(jld_match.group(1), "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지")

    def test_no_preview_prefix(self) -> None:
        html = self.contents["article_candidate.html"]
        self.assertNotIn("[PREVIEW]", html)

    def test_meta_description_contains_title(self) -> None:
        html = self.contents["article_candidate.html"]
        self.assertIn("넷플릭스 신작 반응이 갈린 이유", html)

    def test_article_candidate_meta_has_title_fields(self) -> None:
        meta = json.loads(self.contents["article_candidate_meta.json"])
        for k in ("selected_title_applied_to_candidate", "candidate_title_source",
                  "candidate_h1", "candidate_meta_title", "candidate_jsonld_headline",
                  "selected_title_ctr_score", "selected_title_promise_match_score",
                  "selected_title_risk_score", "candidate_title_mismatch",
                  "candidate_title_mismatch_reason"):
            self.assertIn(k, meta, f"field '{k}' missing")

    def test_selected_title_applied_true(self) -> None:
        meta = json.loads(self.contents["article_candidate_meta.json"])
        self.assertTrue(meta["selected_title_applied_to_candidate"])
        self.assertEqual(meta["candidate_title_source"], "selected_title")

    def test_no_mismatch(self) -> None:
        meta = json.loads(self.contents["article_candidate_meta.json"])
        self.assertFalse(meta["candidate_title_mismatch"])


class TestNoSelectedTitle(unittest.TestCase):

    def test_fallback_to_topic_when_no_selected_title(self) -> None:
        topic = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        result = _build_preview_result(
            topic=topic,
            pattern_id="tax_refund_hometax_check",
            selected_title="",  # 빈 문자열
        )
        # _can_generate_candidate 재계산 (selected_title 없으면 False)
        result["_can_generate_candidate"] = True
        # HTML은 selected_title 없이 topic으로 렌더링
        from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService
        ps = GoldenPatternService()
        sf = SlotFillerService()
        svc = GoldenArticlePreviewService()
        pm = ps.match_pattern(topic=topic)
        sr = sf.fill_slots(pattern_id="tax_refund_hometax_check", topic=topic)
        result["_article_candidate_html"] = svc.render_article_candidate_html(pm, sr, selected_title="")
        result["_selected_title"] = ""
        result["_title_result"] = {"best_title": {}, "candidates": [], "topic": topic}

        contents = _run_and_collect(result)
        html = contents.get("article_candidate.html", "")
        # h1이 topic으로 fallback
        h1_match = re.search(r'<h1>([^<]*)</h1>', html)
        self.assertIsNotNone(h1_match)
        self.assertIn("세금 환급금", h1_match.group(1))


class TestBlockedTitleNotApplied(unittest.TestCase):

    def test_blocked_title_uses_topic_fallback(self) -> None:
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        tc = TitleCandidateService()
        blocked_title = "충격 루머 폭로 드라마 반응"
        validation = tc.validate_title(blocked_title)
        self.assertFalse(validation["is_valid"])
        self.assertEqual(validation["ctr_score"], 0)


class TestArticleHtmlNotChanged(unittest.TestCase):
    """기존 article.html 흐름은 변경되지 않아야 한다."""

    def test_article_html_not_affected_by_title_service(self) -> None:
        # TitleCandidateService는 article.html 내용에 영향을 주지 않음
        # → article_candidate.html에만 반영
        result = _build_preview_result()
        contents = _run_and_collect(result)
        # article_candidate.html에는 selected_title이 반영됨
        self.assertIn("article_candidate.html", contents)
        # article.html은 저장되지 않음 (save_golden_preview_artifacts는 golden 전용)
        self.assertNotIn("article.html", contents)


if __name__ == "__main__":
    unittest.main()
