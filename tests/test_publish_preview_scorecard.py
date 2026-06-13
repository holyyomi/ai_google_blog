from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from blogspot_automation.services.publish_preview_scorecard import build_publish_preview_scorecard
from blogspot_automation.services.run_artifact_service import RunArtifactService


class PublishPreviewScorecardTests(unittest.TestCase):
    def test_build_scorecard_passes_when_clean_publish_checks_pass(self) -> None:
        scorecard = build_publish_preview_scorecard(_passing_quality_gate())

        self.assertEqual(scorecard["status"], "pass")
        self.assertEqual(scorecard["score"], 100)
        self.assertEqual(scorecard["passed_checks"], scorecard["total_checks"])

    def test_build_scorecard_fails_when_gate_has_blocking_issue(self) -> None:
        quality_gate = _passing_quality_gate()
        quality_gate["passed"] = False
        quality_gate["blocking_issues"] = ["inline_style_attributes_present"]

        scorecard = build_publish_preview_scorecard(quality_gate)

        self.assertEqual(scorecard["status"], "fail")
        self.assertLess(scorecard["score"], 80)
        self.assertIn("inline_style_attributes_present", scorecard["blocking_issues"])

    def test_run_artifact_service_writes_scorecard_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scorecard = build_publish_preview_scorecard(_passing_quality_gate())
            service = RunArtifactService(runs_dir=Path(temp_dir))

            run_path = service.save_status_result(
                status_payload={
                    "status": "trending_held_for_review",
                    "publish_quality_gate": {
                        "publish_preview_scorecard": scorecard,
                    },
                }
            )

            scorecard_json = run_path / "publish_preview_scorecard.json"
            scorecard_markdown = run_path / "publish_preview_scorecard.md"
            self.assertTrue(scorecard_json.exists())
            self.assertTrue(scorecard_markdown.exists())
            saved = json.loads(scorecard_json.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "pass")
            self.assertIn("Publish Preview Scorecard", scorecard_markdown.read_text(encoding="utf-8"))

    def test_run_artifact_service_writes_scorecard_files_for_dry_run_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scorecard = build_publish_preview_scorecard(_passing_quality_gate())
            service = RunArtifactService(runs_dir=Path(temp_dir))

            run_path = service.save_dry_run_result(
                html="<article>draft</article>",
                selected_topic={"topic": "test"},
                title_candidates=[],
                scoring={},
                run_meta={
                    "publish_quality_gate": {
                        "publish_preview_scorecard": scorecard,
                    },
                },
            )

            self.assertTrue((run_path / "publish_preview_scorecard.json").exists())
            self.assertTrue((run_path / "publish_preview_scorecard.md").exists())


def _passing_quality_gate() -> dict[str, object]:
    return {
        "passed": True,
        "blocking_issues": [],
        "warnings": [],
        "final_html_audit": {
            "metrics": {
                "yomi_clean_layout": {
                    "present": True,
                    "lede_count": 1,
                    "adaptive_module_count": 2,
                    "inline_style_count": 0,
                    "details_count": 0,
                }
            }
        },
        "answer_engine_coverage": {
            "ai_overview_target_answer_present": True,
            "issue_context_present": True,
            "intent_answer_present": True,
            "people_also_ask_present": True,
            "source_trust_block_present": True,
            "blogposting_json_ld_present": True,
        },
        "faq_count": 3,
        "reader_value_score": 65,
        "article_focus_score": 60,
        "external_anchor_count": 0,
    }


if __name__ == "__main__":
    unittest.main()
