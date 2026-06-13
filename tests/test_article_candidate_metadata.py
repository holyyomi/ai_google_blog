from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------ #
# Fixture helpers
# ------------------------------------------------------------------ #

def _make_preview_result(
    *,
    topic: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    pattern_id: str = "tax_refund_hometax_check",
    selected_title: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    grade: str = "A",
    blogspot_labels: list[str] | None = None,
    hashtags: list[str] | None = None,
    content_type: str = "tax_refund",
    topic_group: str = "policy_benefit",
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
    _default_labels = ["AI활용", "업무자동화", "체크리스트"]
    _default_hashtags = [
        "#세금환급", "#환급금조회", "#홈택스", "#손택스",
        "#국세환급금", "#환급계좌", "#AI활용", "#체크리스트",
    ]
    _default_hashtags = _default_hashtags[:3]
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
        "_blogspot_labels": blogspot_labels if blogspot_labels is not None else _default_labels,
        "_hashtags": hashtags if hashtags is not None else _default_hashtags,
        "_content_type": content_type,
        "_topic_group": topic_group,
    }


def _run_save(preview_result: dict) -> dict[str, str]:
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    with tempfile.TemporaryDirectory() as tmpdir:
        run_path = Path(tmpdir) / "test_run"
        run_path.mkdir()
        RunArtifactService(runs_dir=tmpdir).save_golden_preview_artifacts(run_path, preview_result)
        return {f.name: f.read_text(encoding="utf-8") for f in run_path.iterdir()}


def _meta(preview_result: dict | None = None, **kw) -> dict[str, Any]:
    result = preview_result or _make_preview_result(**kw)
    contents = _run_save(result)
    return json.loads(contents["article_candidate_meta.json"])


# ------------------------------------------------------------------ #
# Tests
# ------------------------------------------------------------------ #

class TestBlogspotLabels(unittest.TestCase):
    """작업 A: Blogspot 라벨 2~3개 제한"""

    def test_blogspot_labels_present(self) -> None:
        meta = _meta()
        self.assertIn("blogspot_labels", meta)

    def test_blogspot_labels_2_to_5(self) -> None:
        meta = _meta()
        count = meta["blogspot_label_count"]
        self.assertGreaterEqual(count, 2)
        self.assertLessEqual(count, 5)

    def test_blogspot_labels_valid_true(self) -> None:
        meta = _meta()
        self.assertTrue(meta["blogspot_labels_valid"])

    def test_blogspot_labels_too_many_sets_valid_false(self) -> None:
        result = _make_preview_result(blogspot_labels=["A", "B", "C", "D", "E", "F"])
        meta = _meta(preview_result=result)
        self.assertFalse(meta["blogspot_labels_valid"])
        self.assertIn("blogspot_labels_exceeds_5", " ".join(meta.get("metadata_warnings", [])))

    def test_blogspot_labels_for_ai_pattern(self) -> None:
        from blogspot_automation.services.news_label_service import NewsLabelService
        svc = NewsLabelService()
        labels = svc.build_blogspot_labels(pattern_id="ai_work_time_savings")
        self.assertEqual(len(labels), 3)
        self.assertIn("AI활용", labels)

    def test_blogspot_labels_for_ott_pattern(self) -> None:
        from blogspot_automation.services.news_label_service import NewsLabelService
        svc = NewsLabelService()
        labels = svc.build_blogspot_labels(pattern_id="viral_ott_reaction_decode")
        self.assertEqual(len(labels), 3)
        self.assertIn("AI뉴스해석", labels)

    def test_blogspot_labels_fallback_by_content_type(self) -> None:
        from blogspot_automation.services.news_label_service import NewsLabelService
        svc = NewsLabelService()
        labels = svc.build_blogspot_labels(content_type="money_checklist")
        self.assertLessEqual(len(labels), 3)
        self.assertGreaterEqual(len(labels), 2)

    def test_blogspot_labels_fallback_by_topic_group(self) -> None:
        from blogspot_automation.services.news_label_service import NewsLabelService
        svc = NewsLabelService()
        labels = svc.build_blogspot_labels(topic_group="platform_issue")
        self.assertLessEqual(len(labels), 3)
        self.assertGreaterEqual(len(labels), 2)

    def test_blogspot_labels_for_privacy_security(self) -> None:
        from blogspot_automation.services.news_label_service import NewsLabelService
        svc = NewsLabelService()
        labels = svc.build_blogspot_labels(topic_group="privacy_security")
        self.assertIn("개인정보보호", labels)
        self.assertNotIn("생활비", labels)


class TestContentHashtags(unittest.TestCase):
    """작업 B: 본문 해시태그 분리 및 0~3개 유효성"""

    def test_content_hashtags_present(self) -> None:
        meta = _meta()
        self.assertIn("content_hashtags", meta)

    def test_content_hashtags_at_most_3(self) -> None:
        meta = _meta()
        count = meta["content_hashtag_count"]
        self.assertLessEqual(count, 3)

    def test_content_hashtags_valid_true(self) -> None:
        meta = _meta()
        self.assertTrue(meta["content_hashtags_valid"])

    def test_content_hashtags_empty_is_valid(self) -> None:
        result = _make_preview_result(hashtags=[])
        meta = _meta(preview_result=result)
        self.assertTrue(meta["content_hashtags_valid"])

    def test_content_hashtags_too_many_sets_invalid(self) -> None:
        from blogspot_automation.services.seo_policy import MAX_CONTENT_HASHTAGS
        result = _make_preview_result(hashtags=[f"#{i}" for i in range(MAX_CONTENT_HASHTAGS + 1)])
        meta = _meta(preview_result=result)
        self.assertFalse(meta["content_hashtags_valid"])
        self.assertIn(
            f"hashtags_exceeds_{MAX_CONTENT_HASHTAGS}",
            " ".join(meta.get("metadata_warnings", [])),
        )

    def test_privacy_hashtags_do_not_use_refund_or_money_tags(self) -> None:
        from blogspot_automation.services.news_label_service import NewsLabelService
        svc = NewsLabelService()
        hashtags = svc.build_hashtags(
            selected_topic="티빙 비밀번호 변경 안내 후 확인할 것",
            selected_title="티빙 비밀번호 변경 안내 후 확인할 것",
            topic_group="privacy_security",
            content_type="consumer_warning",
            labels=["개인정보보호", "계정보안", "AI보안"],
        )
        joined = " ".join(hashtags)
        self.assertIn("#개인정보보호", hashtags)
        self.assertNotIn("#환불", hashtags)
        self.assertNotIn("#비용비교", joined)


class TestJsonLdStabilization(unittest.TestCase):
    """작업 C: JSON-LD 안정화"""

    def setUp(self) -> None:
        from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService
        ps = GoldenPatternService()
        sf = SlotFillerService()
        svc = GoldenArticlePreviewService()
        topic = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
        pm = ps.match_pattern(topic=topic)
        sr = sf.fill_slots(pattern_id="tax_refund_hometax_check", topic=topic)
        self.html = svc.render_article_candidate_html(pm, sr, selected_title=topic)

    def test_blogposting_type_in_jsonld(self) -> None:
        self.assertIn('"BlogPosting"', self.html)

    def test_date_published_present(self) -> None:
        self.assertIn('"datePublished"', self.html)

    def test_date_modified_present(self) -> None:
        self.assertIn('"dateModified"', self.html)

    def test_author_present(self) -> None:
        self.assertIn('"author"', self.html)

    def test_main_entity_present(self) -> None:
        self.assertIn('"mainEntityOfPage"', self.html)

    def test_headline_matches_title(self) -> None:
        meta = _meta()
        self.assertTrue(meta["jsonld_headline_matches_title"])

    def test_jsonld_type_blogposting(self) -> None:
        meta = _meta()
        self.assertEqual(meta["jsonld_type"], "BlogPosting")

    def test_jsonld_date_present_in_meta(self) -> None:
        meta = _meta()
        self.assertTrue(meta["jsonld_date_present"])

    def test_jsonld_author_present_in_meta(self) -> None:
        meta = _meta()
        self.assertTrue(meta["jsonld_author_present"])


class TestFaqJsonLd(unittest.TestCase):
    """작업 D: FAQ JSON-LD 후보 생성"""

    def setUp(self) -> None:
        self.meta = _meta()
        result = _make_preview_result()
        contents = _run_save(result)
        self.html = contents.get("article_candidate.html", "")

    def test_faq_jsonld_present_field_in_meta(self) -> None:
        self.assertIn("faq_jsonld_present", self.meta)

    def test_faq_jsonld_schema_in_html(self) -> None:
        self.assertIn('"FAQPage"', self.html)

    def test_faq_count_positive(self) -> None:
        self.assertGreater(self.meta.get("faq_count", 0), 0)

    def test_faq_jsonld_valid_when_present(self) -> None:
        if self.meta["faq_jsonld_present"]:
            self.assertTrue(self.meta["faq_jsonld_valid"])

    def test_faq_question_type_in_html(self) -> None:
        if self.meta["faq_jsonld_present"]:
            self.assertIn('"Question"', self.html)
            self.assertIn('"Answer"', self.html)


class TestPrePublishChecklist(unittest.TestCase):
    """작업 E: pre_publish_checklist 강화"""

    def setUp(self) -> None:
        self.checklist = _meta()["pre_publish_checklist"]

    def test_required_keys_present(self) -> None:
        required = [
            "title_ok", "meta_description_ok", "jsonld_ok", "faq_jsonld_ok",
            "blogspot_labels_ok", "content_hashtags_ok", "golden_pattern_matched",
            "slot_fill_rate_ok", "default_phrase_clean", "risk_clean",
            "geo_score_ok", "human_review_required", "publish_allowed_in_phase2",
        ]
        for k in required:
            self.assertIn(k, self.checklist, f"'{k}' missing from pre_publish_checklist")

    def test_publish_allowed_for_clean_candidate(self) -> None:
        self.assertTrue(self.checklist["publish_allowed_in_phase2"])

    def test_human_review_not_required_for_clean_candidate(self) -> None:
        self.assertFalse(self.checklist["human_review_required"])

    def test_golden_pattern_matched_true(self) -> None:
        self.assertTrue(self.checklist["golden_pattern_matched"])


class TestMetadataWarnings(unittest.TestCase):
    """작업 F: metadata warnings"""

    def test_metadata_warnings_field_present(self) -> None:
        meta = _meta()
        self.assertIn("metadata_warnings", meta)

    def test_excess_labels_triggers_warning(self) -> None:
        result = _make_preview_result(blogspot_labels=["A", "B", "C", "D", "E", "F"])
        meta = _meta(preview_result=result)
        warnings = meta.get("metadata_warnings", [])
        self.assertTrue(any("blogspot_labels_exceeds_5" in w for w in warnings))

    def test_excess_hashtags_triggers_warning(self) -> None:
        from blogspot_automation.services.seo_policy import MAX_CONTENT_HASHTAGS
        result = _make_preview_result(hashtags=[f"#{i}" for i in range(MAX_CONTENT_HASHTAGS + 1)])
        meta = _meta(preview_result=result)
        warnings = meta.get("metadata_warnings", [])
        self.assertTrue(any(f"hashtags_exceeds_{MAX_CONTENT_HASHTAGS}" in w for w in warnings))

    def test_image_missing_warning(self) -> None:
        meta = _meta()
        warnings = meta.get("metadata_warnings", [])
        self.assertIn("image_missing", warnings)

    def test_no_false_warnings_for_valid_candidate(self) -> None:
        meta = _meta()
        warnings = meta.get("metadata_warnings", [])
        from blogspot_automation.services.seo_policy import MAX_CONTENT_HASHTAGS
        dangerous = ["blogspot_labels_exceeds_5", f"hashtags_exceeds_{MAX_CONTENT_HASHTAGS}",
                     "jsonld_headline_title_mismatch", "meta_description_missing"]
        for w in dangerous:
            self.assertNotIn(w, warnings, f"unexpected warning: {w}")


class TestPublishAllowedInPhase2(unittest.TestCase):
    """publish_allowed_in_phase2 reflects final candidate risk."""

    def test_publish_allowed_for_clean_candidate(self) -> None:
        meta = _meta()
        self.assertTrue(meta["publish_allowed_in_phase2"])
        self.assertTrue(meta["pre_publish_checklist"]["publish_allowed_in_phase2"])


if __name__ == "__main__":
    unittest.main()
