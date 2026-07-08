from __future__ import annotations

import json
import pathlib
import re
import tempfile
import unittest
from pathlib import Path


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _build_candidate(
    *,
    topic: str,
    pattern_id: str,
    content_type: str = "ai_work_tip",
    topic_group: str = "ai_work",
    grade: str = "B",
) -> dict:
    """지정 패턴으로 article_candidate 생성 후 artifact dict 반환."""
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    from blogspot_automation.services.title_candidate_service import TitleCandidateService

    ps  = GoldenPatternService()
    sf  = SlotFillerService()
    svc = GoldenArticlePreviewService()
    tc  = TitleCandidateService()

    pm = ps.match_pattern(topic=topic, content_type=content_type, topic_group=topic_group)
    sr = sf.fill_slots(pattern_id=pattern_id, topic=topic)

    tr = tc.generate_candidates(
        topic=topic, content_type=content_type,
        topic_group=topic_group, pattern_id=pattern_id,
    )
    selected_title = (tr.get("best_title") or {}).get("title", topic)
    html = svc.render_article_candidate_html(pm, sr, selected_title=selected_title)

    best = tr.get("best_title") or {"title": selected_title, "ctr_score": 80, "risk_score": 0, "promise_match_score": 80, "is_allowed": True}
    preview = {
        "matched": bool(pm.get("matched") or pm.get("near_match")),
        "near_match": bool(pm.get("near_match")),
        "ready_for_review": grade in ("A", "B"),
        "pattern_match": pm,
        "slot_result": sr,
        "slot_fill_rate": sr.get("slot_fill_rate", 0.0),
        "missing_required_slots": sr.get("missing_required_slots", []),
        "blocking_issues": [],
        "warnings": [],
        "_editorial_scores": {"traffic_potential_score": 24, "usefulness_score": 30, "final_editorial_score": 72},
        "_content_candidate_grade": grade,
        "_can_generate_candidate": grade in ("A", "B"),
        "_article_candidate_html": html,
        "_title_result": tr,
        "_selected_title": selected_title,
        "_blogspot_labels": ["AI활용", "직장인AI", "생산성"],
        "_hashtags": [
            "#AI활용", "#업무자동화", "#ChatGPT활용",
            "#직장인AI", "#생산성향상", "#프롬프트작성", "#업무효율",
        ],
        "_content_type": content_type,
        "_topic_group": topic_group,
        "_stale_candidate": False,
        "_scoring_stale_penalty": False,
    }

    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "run"
        rp.mkdir()
        RunArtifactService(runs_dir=tmp).save_golden_preview_artifacts(rp, preview)
        return {
            f.name: (
                json.loads(f.read_text(encoding="utf-8"))
                if f.suffix == ".json"
                else f.read_text(encoding="utf-8")
            )
            for f in rp.iterdir()
        }


# ------------------------------------------------------------------ #
# 3패턴 공통 검증 mixin
# ------------------------------------------------------------------ #

class _AiPatternChecks:
    """ai_work_time_savings / ai_tool_comparison / ai_automation_workflow 공통 검사."""

    topic: str
    pattern_id: str
    _contents: dict
    _meta: dict
    _gpm: dict
    _html: str

    def setUp(self):  # type: ignore[override]
        self._contents = _build_candidate(topic=self.topic, pattern_id=self.pattern_id)
        self._meta = self._contents.get("article_candidate_meta.json", {})
        self._gpm  = self._contents.get("golden_preview_meta.json", {})
        self._html = self._contents.get("article_candidate.html", "")

    def _citation_text(self) -> str:
        m = re.search(r'id="AI_CITATION_SUMMARY".*?<p>(.*?)</p>', self._html, re.DOTALL)
        return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ""

    # 1. article_candidate 생성
    def test_article_candidate_generated(self):
        self.assertIn("article_candidate.html", self._contents, "article_candidate.html 없음")
        self.assertTrue(self._meta.get("article_candidate_generated"), "article_candidate_generated=False")

    # 4. AI_CITATION_SUMMARY 자연문
    def test_ai_citation_summary_natural(self):
        text = self._citation_text()
        self.assertTrue(text, "AI_CITATION_SUMMARY 없음")
        self.assertNotIn("요미 판단:", text)
        self.assertNotRegex(text, r'\d+단계\s*:')
        self.assertNotIn("section-label", text)

    # 5. meta description valid
    def test_meta_description_valid(self):
        self.assertTrue(
            self._meta.get("candidate_meta_description_valid"),
            f"meta_desc invalid: {self._meta.get('candidate_meta_description')!r}",
        )

    # 7. geo_ready
    def test_geo_ready(self):
        self.assertTrue(self._meta.get("geo_ready"), f"geo_ready=False geo_score={self._meta.get('geo_score')}")

    # 8. human_review_required
    def test_human_review_required_true(self):
        self.assertTrue(self._meta.get("human_review_required"))
        self.assertTrue(self._gpm.get("human_review_required"))

    # 9. publish_allowed_in_phase2=false
    def test_publish_not_allowed_in_phase2(self):
        self.assertFalse(self._meta.get("publish_allowed_in_phase2"))
        checklist = self._meta.get("pre_publish_checklist", {})
        self.assertFalse(checklist.get("publish_allowed_in_phase2"))


# ------------------------------------------------------------------ #
# 패턴별 테스트 클래스
# ------------------------------------------------------------------ #

class TestAiWorkTimeSavings(_AiPatternChecks, unittest.TestCase):
    topic      = "직장인이 ChatGPT로 업무 시간을 줄이는 방법"
    pattern_id = "ai_work_time_savings"

    # 6. selected_title 핵심 키워드 포함
    def test_selected_title_has_ai_keyword(self):
        title = self._meta.get("candidate_h1", "") or self._meta.get("candidate_meta_title", "")
        html_h1 = re.search(r'<h1>([^<]*)</h1>', self._html)
        t = html_h1.group(1) if html_h1 else title
        self.assertTrue(
            any(kw in t for kw in ("ChatGPT", "AI", "업무", "시간", "자동화")),
            f"핵심 키워드 없음: {t!r}",
        )


class TestAiToolComparison(_AiPatternChecks, unittest.TestCase):
    topic      = "AI 도구 비교 ChatGPT vs Claude 업무용 선택 기준"
    pattern_id = "ai_tool_comparison"

    # 6. selected_title 핵심 키워드
    def test_selected_title_has_ai_keyword(self):
        html_h1 = re.search(r'<h1>([^<]*)</h1>', self._html)
        t = html_h1.group(1) if html_h1 else ""
        self.assertTrue(
            any(kw in t for kw in ("AI", "ChatGPT", "Claude", "비교", "도구", "업무")),
            f"핵심 키워드 없음: {t!r}",
        )

    def test_slot_fill_rate_above_80(self):
        rate = self._meta.get("golden_slot_fill_rate", 0.0)
        self.assertGreaterEqual(rate, 0.8, f"fill_rate={rate:.2f}")


class TestAiAutomationWorkflow(_AiPatternChecks, unittest.TestCase):
    topic      = "업무 자동화 워크플로우 설계 방법"
    pattern_id = "ai_automation_workflow"

    # 6. selected_title 핵심 키워드
    def test_selected_title_has_ai_keyword(self):
        html_h1 = re.search(r'<h1>([^<]*)</h1>', self._html)
        t = html_h1.group(1) if html_h1 else ""
        self.assertTrue(
            any(kw in t for kw in ("자동화", "워크플로우", "반복", "AI", "업무")),
            f"핵심 키워드 없음: {t!r}",
        )

    def test_slot_fill_rate_above_80(self):
        rate = self._meta.get("golden_slot_fill_rate", 0.0)
        self.assertGreaterEqual(rate, 0.8, f"fill_rate={rate:.2f}")


# ------------------------------------------------------------------ #
# AI 제목 품질 (작업 B)
# ------------------------------------------------------------------ #

class TestAiTitleQuality(unittest.TestCase):

    def _score(self, title: str, pid: str) -> dict:
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        return TitleCandidateService().score_title(title, pattern_id=pid)

    def test_ai_work_title_has_required_signal(self):
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        res = svc.generate_candidates(
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            content_type="ai_work_tip", topic_group="ai_work",
            pattern_id="ai_work_time_savings",
        )
        best = res.get("best_title", {})
        t = best.get("title", "")
        self.assertTrue(
            any(kw in t for kw in ("ChatGPT", "AI", "업무 시간", "반복 업무", "프롬프트", "검수")),
            f"핵심 신호 없음: {t!r}",
        )

    def test_overhype_ai_title_lower_score(self):
        normal   = self._score("ChatGPT로 업무 시간이 안 줄어드는 진짜 이유", "ai_work_time_savings")
        overhype = self._score("AI 쓰면 인생이 바뀐다, 끝판왕 활용법", "ai_work_time_savings")
        self.assertLess(overhype["ctr_score"], normal["ctr_score"])

    def test_tool_comparison_title_has_comparison_signal(self):
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        res = svc.generate_candidates(
            topic="AI 도구 비교 ChatGPT vs Claude 업무용 선택 기준",
            content_type="ai_work_tip", topic_group="ai_work",
            pattern_id="ai_tool_comparison",
        )
        best = res.get("best_title", {})
        t = best.get("title", "")
        self.assertTrue(
            any(kw in t for kw in ("AI", "ChatGPT", "Claude", "비교", "도구", "업무")),
            f"비교 신호 없음: {t!r}",
        )

    def test_automation_title_has_workflow_signal(self):
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        res = svc.generate_candidates(
            topic="업무 자동화 워크플로우 설계 방법",
            content_type="ai_work_tip", topic_group="ai_work",
            pattern_id="ai_automation_workflow",
        )
        best = res.get("best_title", {})
        t = best.get("title", "")
        self.assertTrue(
            any(kw in t for kw in ("자동화", "워크플로우", "반복", "AI")),
            f"워크플로우 신호 없음: {t!r}",
        )


# ------------------------------------------------------------------ #
# ai_blog.yml 검증 (1단계: 수동 dry-run 전용)
# ------------------------------------------------------------------ #

class TestAiBlogYml(unittest.TestCase):

    @classmethod
    def _yml_content(cls) -> str:
        path = pathlib.Path(".github/workflows/ai_blog.yml")
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def test_workflow_dispatch_present(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        self.assertIn("workflow_dispatch", content)

    def test_runs_cli_ai(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        self.assertIn("cli_ai.py", content)
        self.assertIn("NEWS_MODE: \"news\"", content)
        self.assertIn("AI_BLOG_MODE: \"true\"", content)

    def test_default_is_dry_run(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        # 수동(dispatch) 기본은 dry_run (실수로 실제 발행되지 않도록)
        self.assertIn("default: 'dry_run'", content)

    def test_schedule_publishes_daily(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        # 매일 아침 자동 발행 cron + schedule이면 publish(dry_run=false).
        # DRY_RUN 표현식은 schedule 또는 수동 publish/publish_draft면 'false'.
        self.assertIn("cron:", content)
        self.assertIn("github.event_name == 'schedule'", content)
        self.assertIn("&& 'false' || 'true'", content)  # DRY_RUN: 발행 경로면 false

    def test_manual_publish_draft_mode(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        # 수동 리허설은 Blogger 초안으로만(라이브 오염 0). 스케줄만 라이브.
        self.assertIn("publish_draft", content)
        self.assertIn("NEWS_PUBLISH_AS_DRAFT", content)
        # 초안 플래그는 수동 publish_draft일 때만 true
        self.assertIn("github.event.inputs.publish_mode == 'publish_draft' && 'true' || 'false'", content)

    def test_persists_dedup_state(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        # 중복 방지 상태를 저장소에 커밋해야 매일 다른 주제가 나옴
        self.assertIn("data/publish_history.json", content)
        self.assertNotIn("naver_ai_rewritten.json", content)
        self.assertIn("git push", content)

    def test_llm_and_image_keys_injected(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        for marker in ("ENABLE_AI_LLM_ENRICH", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "IMGBB_API_KEY", "CLOUDFLARE_API_TOKEN"):
            self.assertIn(marker, content, f"키 주입 누락: {marker}")
        # 운영 방침(2026-07-03): Gemini는 더 이상 사용하지 않음
        self.assertNotIn("GOOGLE_AI_API_KEY", content)

    def test_artifact_upload_present(self):
        content = self._yml_content()
        if not content:
            self.skipTest("ai_blog.yml not found")
        self.assertIn("upload-artifact", content)


if __name__ == "__main__":
    unittest.main()
