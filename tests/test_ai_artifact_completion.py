from __future__ import annotations

import json
import pathlib
import re
import tempfile
import unittest
from pathlib import Path


# ------------------------------------------------------------------ #
# Helper: AI pipeline 단일 dry_run 실행 후 artifact dict 반환
# ------------------------------------------------------------------ #

def _run_ai_pipeline(*, dry_run: bool = True, force_topic: str = "") -> dict:
    from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    from blogspot_automation.services.publish_history_service import PublishHistoryService

    with tempfile.TemporaryDirectory() as tmp:
        hist_path = Path(tmp) / "publish_history.json"
        pipeline = AiTopicPipeline(
            artifact_service=RunArtifactService(runs_dir=tmp),
            publish_history_service=PublishHistoryService(history_path=hist_path),
            dry_run=dry_run,
            _force_topic=force_topic,
        )
        result = pipeline.run_once()
        artifact_dir = result.get("artifact_dir", "")

        files: dict = {}
        if artifact_dir and Path(artifact_dir).exists():
            for f in Path(artifact_dir).iterdir():
                if f.suffix == ".json":
                    files[f.name] = json.loads(f.read_text(encoding="utf-8"))
                else:
                    files[f.name] = f.read_text(encoding="utf-8")

        history: list = []
        if hist_path.exists():
            history = json.loads(hist_path.read_text(encoding="utf-8"))

        return {
            "result": result,
            "files": files,
            "history": history,
            "artifact_dir": artifact_dir,
        }


class TestAiArtifactFiles(unittest.TestCase):
    """작업 A/B/C: AI artifact 파일 생성 검증"""

    @classmethod
    def setUpClass(cls) -> None:
        data = _run_ai_pipeline(force_topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법")
        cls._result = data["result"]
        cls._files  = data["files"]
        cls._history = data["history"]

    # 1. run_meta.json 생성
    def test_run_meta_generated(self) -> None:
        self.assertIn("run_meta.json", self._files,
                      f"run_meta.json 없음. files={list(self._files)}")

    # 2. scoring.json 생성
    def test_scoring_generated(self) -> None:
        self.assertIn("scoring.json", self._files,
                      f"scoring.json 없음. files={list(self._files)}")

    # 3. image_prompt.txt 생성
    def test_image_prompt_generated(self) -> None:
        self.assertIn("image_prompt.txt", self._files,
                      f"image_prompt.txt 없음. files={list(self._files)}")

    def test_image_prompt_no_text_instruction(self) -> None:
        txt = self._files.get("image_prompt.txt", "")
        self.assertIn("no text", txt)
        self.assertIn("16:9", txt)

    # 4. run_meta.publish_allowed_in_phase2=false
    def test_run_meta_publish_allowed_false(self) -> None:
        meta = self._files.get("run_meta.json", {})
        self.assertFalse(meta.get("publish_allowed_in_phase2"),
                         f"publish_allowed_in_phase2={meta.get('publish_allowed_in_phase2')}")

    # 5. run_meta.human_review_required=true
    def test_run_meta_human_review_true(self) -> None:
        meta = self._files.get("run_meta.json", {})
        self.assertTrue(meta.get("human_review_required"),
                        f"human_review_required={meta.get('human_review_required')}")

    def test_run_meta_pipeline_field(self) -> None:
        meta = self._files.get("run_meta.json", {})
        self.assertEqual(meta.get("pipeline"), "ai_pipeline")

    def test_run_meta_required_fields(self) -> None:
        meta = self._files.get("run_meta.json", {})
        required = [
            "pipeline", "mode", "dry_run", "selected_topic_group", "selected_content_angle",
            "golden_preview_generated", "golden_pattern_id", "golden_pattern_confidence",
            "golden_slot_fill_rate", "article_candidate_generated", "selected_title",
            "selected_title_ctr_score", "geo_score", "geo_ready", "publish_ready",
            "publish_allowed_in_phase2", "human_review_required", "blogspot_labels",
            "content_hashtags", "status",
        ]
        missing = [k for k in required if k not in meta]
        self.assertFalse(missing, f"run_meta.json 누락 필드: {missing}")

    def test_scoring_required_fields(self) -> None:
        sc = self._files.get("scoring.json", {})
        required = [
            "golden_pattern_id", "pattern_confidence", "content_candidate_grade",
            "final_editorial_score", "geo_score", "publish_ready",
            "publish_allowed_in_phase2", "human_review_required", "reason",
        ]
        missing = [k for k in required if k not in sc]
        self.assertFalse(missing, f"scoring.json 누락 필드: {missing}")

    def test_scoring_pipeline_field(self) -> None:
        sc = self._files.get("scoring.json", {})
        self.assertEqual(sc.get("pipeline"), "ai_pipeline")


class TestAiPublishHistory(unittest.TestCase):
    """작업 D: PublishHistoryService 연동 검증"""

    @classmethod
    def setUpClass(cls) -> None:
        data = _run_ai_pipeline(force_topic="무료 ChatGPT로 업무 시간 줄이는 3가지 패턴")
        cls._result  = data["result"]
        cls._history = data["history"]

    # 6. publish_history에 ai_pipeline 기록
    def test_history_has_ai_pipeline_record(self) -> None:
        ai_records = [r for r in self._history if r.get("pipeline") == "ai_pipeline"]
        self.assertGreater(len(ai_records), 0,
                           "publish_history에 ai_pipeline 레코드 없음")

    def test_history_record_has_required_fields(self) -> None:
        ai_records = [r for r in self._history if r.get("pipeline") == "ai_pipeline"]
        if not ai_records:
            self.skipTest("ai_pipeline record not found")
        rec = ai_records[-1]
        for field in ["topic", "selected_title", "golden_pattern_id",
                      "content_type", "topic_group", "status",
                      "article_candidate_generated", "run_at"]:
            self.assertIn(field, rec, f"publish_history record 누락 필드: {field}")

    def test_history_record_status(self) -> None:
        ai_records = [r for r in self._history if r.get("pipeline") == "ai_pipeline"]
        if not ai_records:
            self.skipTest("ai_pipeline record not found")
        rec = ai_records[-1]
        self.assertIn(rec.get("status"), ("dry_run_saved", "held_for_review", "skipped", "failed"))


class TestAiArtifactQuality(unittest.TestCase):
    """article_candidate 품질 유지 확인"""

    @classmethod
    def setUpClass(cls) -> None:
        # 안정적인 force_topic 사용 (외부 소스 결과에 의존하지 않음)
        data = _run_ai_pipeline(force_topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법")
        cls._files  = data["files"]
        cls._result = data["result"]
        cls._meta   = data["files"].get("article_candidate_meta.json", {})

    def test_article_candidate_html_exists(self) -> None:
        self.assertIn("article_candidate.html", self._files)

    def test_geo_score_above_80(self) -> None:
        score = self._meta.get("geo_score", 0)
        self.assertGreaterEqual(score, 80, f"geo_score={score}")

    def test_geo_ready(self) -> None:
        self.assertTrue(self._meta.get("geo_ready"))

    def test_citation_summary_valid(self) -> None:
        self.assertTrue(self._meta.get("geo_ai_citation_summary_valid"),
                        f"issues={self._meta.get('geo_ai_citation_summary_issues')}")

    def test_meta_desc_valid(self) -> None:
        self.assertTrue(self._meta.get("candidate_meta_description_valid"))

    def test_human_review_required(self) -> None:
        self.assertTrue(self._meta.get("human_review_required"))
        gpm = self._files.get("golden_preview_meta.json", {})
        self.assertTrue(gpm.get("human_review_required"))

    def test_publish_not_allowed_in_phase2(self) -> None:
        self.assertFalse(self._meta.get("publish_allowed_in_phase2"))


class TestAiBlogYmlArtifactList(unittest.TestCase):
    """작업 E: ai_blog.yml artifact 목록 확인"""

    @classmethod
    def _yml_content(cls) -> str:
        p = pathlib.Path(".github/workflows/ai_blog.yml")
        return p.read_text(encoding="utf-8") if p.exists() else ""

    # 7. ai_blog.yml artifact에 run_meta/scoring/image_prompt 포함
    def test_upload_artifact_path_includes_runs(self) -> None:
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        self.assertIn("runs/", content)
        self.assertIn("upload-artifact", content)

    def test_artifact_section_covers_all_files(self) -> None:
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        # upload-artifact는 runs/ 전체를 올리므로 run_meta, scoring, image_prompt 모두 포함
        # path: runs/ 설정 확인
        self.assertIn("path: runs/", content)



if __name__ == "__main__":
    unittest.main()
