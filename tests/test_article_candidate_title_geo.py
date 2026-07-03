from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------ #
# fixture helpers
# ------------------------------------------------------------------ #

def _make_candidate_html(
    *,
    topic: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    pattern_id: str = "tax_refund_hometax_check",
    selected_title: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
) -> str:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService
    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    pm = ps.match_pattern(topic=topic)
    sr = sf.fill_slots(pattern_id=pattern_id, topic=topic)
    return svc.render_article_candidate_html(pm, sr, selected_title=selected_title)


def _make_preview_result(
    *,
    selected_title: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    topic: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    pattern_id: str = "tax_refund_hometax_check",
    grade: str = "A",
) -> dict[str, Any]:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService
    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    pm = ps.match_pattern(topic=topic)
    sr = sf.fill_slots(pattern_id=pattern_id, topic=topic)
    html = svc.render_article_candidate_html(pm, sr, selected_title=selected_title)
    best = {
        "title": selected_title,
        "title_type": "evergreen",
        "ctr_score": 85,
        "risk_score": 0,
        "promise_match_score": 88,
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
        "_editorial_scores": {
            "traffic_potential_score": 30,
            "usefulness_score": 35,
            "final_editorial_score": 90,
        },
        "_content_candidate_grade": grade,
        "_can_generate_candidate": grade in ("A", "B"),
        "_article_candidate_html": html,
        "_title_result": {"best_title": best, "candidates": [best], "topic": topic},
        "_selected_title": selected_title,
    }


def _run_save(preview_result: dict) -> dict[str, str]:
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    with tempfile.TemporaryDirectory() as tmpdir:
        run_path = Path(tmpdir) / "test_run"
        run_path.mkdir()
        RunArtifactService(runs_dir=tmpdir).save_golden_preview_artifacts(run_path, preview_result)
        return {f.name: f.read_text(encoding="utf-8") for f in run_path.iterdir()}


# ------------------------------------------------------------------ #
# Test cases
# ------------------------------------------------------------------ #

class TestSelectedTitleInHtml(unittest.TestCase):
    """작업 A: selected_title → h1, title, JSON-LD 반영"""

    def setUp(self) -> None:
        self.title = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        self.html = _make_candidate_html(selected_title=self.title)

    def test_h1_reflects_selected_title(self) -> None:
        m = re.search(r'<h1>([^<]*)</h1>', self.html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), self.title)

    def test_title_tag_reflects_selected_title(self) -> None:
        m = re.search(r'<title>([^<]*)</title>', self.html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), self.title)

    def test_jsonld_headline_reflects_selected_title(self) -> None:
        m = re.search(r'"headline"\s*:\s*"([^"]+)"', self.html)
        self.assertIsNotNone(m, "JSON-LD headline missing")
        self.assertEqual(m.group(1), self.title)

    def test_no_preview_prefix(self) -> None:
        self.assertNotIn("[PREVIEW]", self.html)


class TestMetaDescription(unittest.TestCase):
    """작업 B: meta description 120-160자 생성/검증"""

    def setUp(self) -> None:
        self.html = _make_candidate_html()
        m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']', self.html)
        self.desc = m.group(1) if m else ""

    def test_meta_description_present(self) -> None:
        self.assertIn('<meta name="description"', self.html)

    def test_meta_description_not_empty(self) -> None:
        self.assertTrue(len(self.desc) > 0, "meta description is empty")

    def test_meta_description_recorded_in_meta_json(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        self.assertIn("candidate_meta_description", meta)
        self.assertIn("candidate_meta_description_length", meta)
        self.assertIn("candidate_meta_description_valid", meta)

    def test_meta_description_valid_field_reflects_length(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        length = meta["candidate_meta_description_length"]
        expected_valid = 80 <= length <= 160
        self.assertEqual(meta["candidate_meta_description_valid"], expected_valid)


class TestJsonLdSync(unittest.TestCase):
    """작업 C: JSON-LD 동기화"""

    def setUp(self) -> None:
        self.title = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        self.result = _make_preview_result(selected_title=self.title)
        self.contents = _run_save(self.result)
        self.meta = json.loads(self.contents["article_candidate_meta.json"])

    def test_candidate_jsonld_headline_in_meta(self) -> None:
        self.assertIn("candidate_jsonld_headline", self.meta)

    def test_candidate_jsonld_description_in_meta(self) -> None:
        self.assertIn("candidate_jsonld_description", self.meta)

    def test_candidate_jsonld_valid_in_meta(self) -> None:
        self.assertIn("candidate_jsonld_valid", self.meta)

    def test_candidate_jsonld_warnings_in_meta(self) -> None:
        self.assertIn("candidate_jsonld_warnings", self.meta)


class TestGeoBlocks(unittest.TestCase):
    """작업 D: GEO 블록 존재 확인"""

    def setUp(self) -> None:
        self.html = _make_candidate_html()

    def test_ai_citation_summary_present(self) -> None:
        self.assertIn('id="AI_CITATION_SUMMARY"', self.html)

    def test_updated_date_block_present(self) -> None:
        self.assertIn('id="UPDATED_DATE_BLOCK"', self.html)

    def test_updated_date_contains_date(self) -> None:
        # 작성 기준일은 하단 출처 블록에 1회만 노출된다 (상단 중복 날짜 제거됨).
        m = re.search(r'\(\d{4}-\d{2}-\d{2} 기준\)', self.html)
        self.assertIsNotNone(m, "날짜 형식 (YYYY-MM-DD 기준) 없음")

    def test_geo_ai_citation_recorded_in_meta(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        self.assertIn("geo_ai_citation_summary_present", meta)
        self.assertTrue(meta["geo_ai_citation_summary_present"])

    def test_geo_updated_date_recorded_in_meta(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        self.assertIn("geo_updated_date_present", meta)
        self.assertTrue(meta["geo_updated_date_present"])


class TestGeoScore(unittest.TestCase):
    """작업 F: GEO 점수 계산"""

    def setUp(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        self.meta = json.loads(contents["article_candidate_meta.json"])

    def test_geo_score_present(self) -> None:
        self.assertIn("geo_score", self.meta)

    def test_geo_score_range(self) -> None:
        score = self.meta["geo_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        self.assertEqual(score % 5, 0, "점수는 5 단위여야 함")

    def test_geo_ready_needs_revision_hold_exclusive(self) -> None:
        score = self.meta["geo_score"]
        ready = self.meta["geo_ready"]
        needs_revision = self.meta["geo_needs_revision"]
        hold = self.meta["geo_hold"]
        if score >= 80:
            self.assertTrue(ready)
            self.assertFalse(needs_revision)
            self.assertFalse(hold)
        elif score >= 60:
            self.assertFalse(ready)
            self.assertTrue(needs_revision)
            self.assertFalse(hold)
        else:
            self.assertFalse(ready)
            self.assertFalse(needs_revision)
            self.assertTrue(hold)

    def test_geo_first_200_chars_present(self) -> None:
        self.assertIn("geo_first_200_chars_answer_present", self.meta)
        self.assertIn("first_200_chars", self.meta)


class TestFallbackToTopic(unittest.TestCase):
    """작업 A: selected_title 없으면 topic fallback"""

    def test_no_selected_title_uses_topic_in_h1(self) -> None:
        topic = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        html = _make_candidate_html(topic=topic, selected_title="")
        m = re.search(r'<h1>([^<]*)</h1>', html)
        self.assertIsNotNone(m)
        self.assertIn("세금 환급금", m.group(1))

    def test_no_selected_title_still_has_geo_blocks(self) -> None:
        html = _make_candidate_html(selected_title="")
        self.assertIn('id="AI_CITATION_SUMMARY"', html)
        self.assertIn('id="UPDATED_DATE_BLOCK"', html)

    def test_no_selected_title_still_has_meta_description(self) -> None:
        html = _make_candidate_html(selected_title="")
        self.assertIn('<meta name="description"', html)


class TestPrePublishChecklist(unittest.TestCase):
    """작업 H: pre_publish_checklist"""

    def setUp(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        self.meta = json.loads(contents["article_candidate_meta.json"])

    def test_pre_publish_checklist_present(self) -> None:
        self.assertIn("pre_publish_checklist", self.meta)

    def test_publish_allowed_for_clean_candidate(self) -> None:
        checklist = self.meta["pre_publish_checklist"]
        self.assertTrue(checklist["publish_allowed_in_phase2"])

    def test_human_review_not_required_for_clean_candidate(self) -> None:
        checklist = self.meta["pre_publish_checklist"]
        self.assertFalse(checklist["human_review_required"])

    def test_checklist_required_keys(self) -> None:
        checklist = self.meta["pre_publish_checklist"]
        for key in (
            "title_ok", "meta_description_ok", "jsonld_ok",
            "golden_pattern_matched", "slot_fill_rate_ok",
            "default_phrase_clean", "risk_clean", "geo_score_ok",
        ):
            self.assertIn(key, checklist, f"key '{key}' missing from pre_publish_checklist")


class TestTitleMismatch(unittest.TestCase):
    """작업 I: title mismatch 방지"""

    def test_no_mismatch_when_title_applied(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        self.assertFalse(meta["candidate_title_mismatch"])
        self.assertEqual(meta["candidate_title_mismatch_reason"], "")

    def test_mismatch_detected_on_discrepancy(self) -> None:
        # h1과 selected_title이 다르도록 직접 조작
        result = _make_preview_result(selected_title="제목 A")
        result["_article_candidate_html"] = result["_article_candidate_html"].replace(
            "<h1>제목 A</h1>", "<h1>다른 제목</h1>", 1
        )
        result["_selected_title"] = "제목 A"
        contents = _run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        self.assertTrue(meta["candidate_title_mismatch"])
        self.assertNotEqual(meta["candidate_title_mismatch_reason"], "")


class TestArticleHtmlUntouched(unittest.TestCase):
    """작업 J-10: 기존 article.html 흐름 불변"""

    def test_save_golden_preview_artifacts_does_not_write_article_html(self) -> None:
        result = _make_preview_result()
        contents = _run_save(result)
        self.assertNotIn("article.html", contents)


if __name__ == "__main__":
    unittest.main()
