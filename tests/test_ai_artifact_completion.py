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
        # 안정적인 force_topic 사용 (Naver RSS 결과에 의존하지 않음)
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


class TestNaverSourceIntegration(unittest.TestCase):
    """Naver Blog 소스 파이프라인 통합 검증"""

    @classmethod
    def setUpClass(cls) -> None:
        # _force_naver_post로 실제 RSS 없이 Naver 소스 시뮬레이션
        from blogspot_automation.services.naver_blog_service import NaverPost
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
        from blogspot_automation.services.run_artifact_service import RunArtifactService
        from blogspot_automation.services.publish_history_service import PublishHistoryService

        cls._naver_post = NaverPost(
            title="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            link="https://blog.naver.com/holyyomi/123456789",
            log_no="123456789",
            pub_date="Thu, 07 May 2026 08:00:00 +0900",
            rss_excerpt="ChatGPT를 업무에 활용해도 시간이 줄지 않는 이유와 실제 절감 방법 안내",
            full_text="반복 업무를 먼저 구분하고 ChatGPT를 초안 도구로 활용해야 합니다...",
        )
        with tempfile.TemporaryDirectory() as tmp:
            hist_path = Path(tmp) / "publish_history.json"
            pipeline = AiTopicPipeline(
                artifact_service=RunArtifactService(runs_dir=tmp),
                publish_history_service=PublishHistoryService(history_path=hist_path),
                dry_run=True,
                _force_naver_post=cls._naver_post,
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
            cls._result = result
            cls._files  = files
            cls._history = history

    def test_source_type_naver_blog(self) -> None:
        """result에 source_type=naver_blog 포함."""
        self.assertEqual(self._result.get("source_type"), "naver_blog")

    def test_source_url_present(self) -> None:
        """result에 source_url 포함."""
        url = self._result.get("source_url", "")
        self.assertTrue(url.startswith("https://"), f"source_url={url!r}")

    def test_source_title_matches_naver_post(self) -> None:
        """source_title이 Naver post 제목과 일치."""
        self.assertEqual(self._result.get("source_title"), self._naver_post.title)

    def test_run_meta_has_source_fields(self) -> None:
        """run_meta.json에 source_* 필드 포함."""
        meta = self._files.get("run_meta.json", {})
        for field in ("source_type", "source_url", "source_title",
                       "source_summary", "source_published_at"):
            self.assertIn(field, meta, f"run_meta 누락 필드: {field}")

    def test_run_meta_source_type_naver_blog(self) -> None:
        meta = self._files.get("run_meta.json", {})
        self.assertEqual(meta.get("source_type"), "naver_blog")

    def test_scoring_has_source_fields(self) -> None:
        sc = self._files.get("scoring.json", {})
        self.assertEqual(sc.get("source_type"), "naver_blog")
        self.assertIn("source_title", sc)

    def test_selected_topic_has_source_fields(self) -> None:
        st = self._files.get("selected_topic.json", {})
        self.assertEqual(st.get("source_type"), "naver_blog")
        self.assertEqual(st.get("source_url"), self._naver_post.link)

    def test_history_has_source_type(self) -> None:
        ai_recs = [r for r in self._history if r.get("pipeline") == "ai_pipeline"]
        self.assertGreater(len(ai_recs), 0)
        self.assertEqual(ai_recs[-1].get("source_type"), "naver_blog")

    def test_article_candidate_generated(self) -> None:
        self.assertTrue(self._result.get("article_candidate_generated"))

    def test_geo_ready(self) -> None:
        self.assertTrue(self._result.get("geo_ready"),
                        f"geo_score={self._result.get('geo_score')}")

    def test_human_review_required(self) -> None:
        self.assertTrue(self._result.get("human_review_required"))

    def test_publish_not_allowed_in_phase2(self) -> None:
        self.assertFalse(self._result.get("publish_allowed_in_phase2"))


class TestNaverAiKeywordFilter(unittest.TestCase):
    """naver_blog_service AI 키워드 필터 검증"""

    def _is_ai(self, title: str, excerpt: str = "") -> bool:
        from blogspot_automation.services.naver_blog_service import (
            NaverPost, _is_ai_post, _AI_KEYWORDS,
        )
        post = NaverPost(
            title=title, link="https://x", log_no="1",
            pub_date="", rss_excerpt=excerpt,
        )
        return _is_ai_post(post, _AI_KEYWORDS)

    def test_ai_title_detected(self) -> None:
        self.assertTrue(self._is_ai("ChatGPT로 업무 시간 줄이는 법"))

    def test_non_ai_title_not_detected(self) -> None:
        self.assertFalse(self._is_ai("세금 환급금 조회 방법"))

    def test_ai_in_excerpt_detected(self) -> None:
        self.assertTrue(self._is_ai("업무 효율 높이기", "AI 도구를 활용하면 생산성이 올라갑니다"))

    def test_automation_keyword(self) -> None:
        self.assertTrue(self._is_ai("반복 업무 자동화 전 정해야 할 것"))

    def test_ott_not_ai(self) -> None:
        self.assertFalse(self._is_ai("넷플릭스 반응이 갈린 이유"))


class TestNaverAiRewrittenTracking(unittest.TestCase):
    """already_rewritten 추적 로직 검증"""

    def test_mark_and_check(self) -> None:
        from blogspot_automation.services.naver_blog_service import (
            NaverPost, mark_ai_blogspot_rewritten,
            _load_ai_rewritten, _AI_REWRITTEN_PATH,
        )
        import tempfile, json
        from pathlib import Path
        from unittest.mock import patch

        fake_post = NaverPost(
            title="AI 테스트 포스트",
            link="https://blog.naver.com/holyyomi/999999999",
            log_no="999999999",
            pub_date="", rss_excerpt="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            fake_path = Path(tmp) / "naver_ai_rewritten.json"
            with patch.object(
                __import__("blogspot_automation.services.naver_blog_service",
                            fromlist=["_AI_REWRITTEN_PATH"]),
                "_AI_REWRITTEN_PATH", fake_path,
            ):
                import importlib
                import blogspot_automation.services.naver_blog_service as nbsvc
                orig = nbsvc._AI_REWRITTEN_PATH
                nbsvc._AI_REWRITTEN_PATH = fake_path
                try:
                    nbsvc.mark_ai_blogspot_rewritten(fake_post)
                    loaded = nbsvc._load_ai_rewritten()
                    self.assertIn(fake_post.link, loaded)
                    rec = loaded[fake_post.link]
                    self.assertIn("rewritten_at", rec)
                    self.assertEqual(rec["title"], fake_post.title)
                finally:
                    nbsvc._AI_REWRITTEN_PATH = orig


if __name__ == "__main__":
    unittest.main()
