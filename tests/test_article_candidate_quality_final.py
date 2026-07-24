from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _render_candidate(
    *,
    topic: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    pattern_id: str = "tax_refund_hometax_check",
    selected_title: str = "",
    content_type: str = "tax_refund",
    topic_group: str = "policy_benefit",
) -> str:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService
    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    pm = ps.match_pattern(topic=topic, content_type=content_type, topic_group=topic_group)
    sr = sf.fill_slots(pattern_id=pattern_id, topic=topic)
    return svc.render_article_candidate_html(pm, sr, selected_title=selected_title or topic)


def _make_preview_and_save(
    *,
    topic: str = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
    pattern_id: str = "tax_refund_hometax_check",
    selected_title: str = "",
    content_type: str = "tax_refund",
    topic_group: str = "policy_benefit",
    grade: str = "A",
    stale: bool = False,
) -> dict:
    from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
    from blogspot_automation.services.golden_pattern_service import GoldenPatternService
    from blogspot_automation.services.slot_filler_service import SlotFillerService
    from blogspot_automation.services.run_artifact_service import RunArtifactService
    ps = GoldenPatternService()
    sf = SlotFillerService()
    svc = GoldenArticlePreviewService()
    pm = ps.match_pattern(topic=topic, content_type=content_type, topic_group=topic_group)
    sr = sf.fill_slots(pattern_id=pattern_id, topic=topic)
    st = selected_title or topic
    html = svc.render_article_candidate_html(pm, sr, selected_title=st)
    best = {"title": st, "ctr_score": 85, "risk_score": 0, "promise_match_score": 88, "is_allowed": True}
    preview = {
        "matched": True,
        "near_match": False,
        "ready_for_review": grade in ("A", "B"),
        "pattern_match": pm,
        "slot_result": sr,
        "slot_fill_rate": 1.0,
        "missing_required_slots": [],
        "blocking_issues": [],
        "warnings": [],
        "_editorial_scores": {"traffic_potential_score": 30, "usefulness_score": 35, "final_editorial_score": 90},
        "_content_candidate_grade": grade,
        "_can_generate_candidate": grade in ("A", "B"),
        "_article_candidate_html": html,
        "_title_result": {"best_title": best},
        "_selected_title": st,
        "_blogspot_labels": ["세금환급", "홈택스", "생활정보"],
        "_hashtags": ["#세금환급", "#환급금조회", "#홈택스", "#손택스", "#국세환급금", "#환급계좌", "#생활정보", "#체크리스트"],
        "_content_type": content_type,
        "_topic_group": topic_group,
        "_stale_candidate": stale,
    }
    preview["_hashtags"] = preview["_hashtags"][:3]
    with tempfile.TemporaryDirectory() as tmp:
        run_path = Path(tmp) / "run"
        run_path.mkdir()
        RunArtifactService(runs_dir=tmp).save_golden_preview_artifacts(run_path, preview)
        return {f.name: json.loads(f.read_text(encoding="utf-8")) if f.suffix == ".json" else f.read_text(encoding="utf-8")
                for f in run_path.iterdir()}


# ------------------------------------------------------------------ #
# Tests
# ------------------------------------------------------------------ #

class TestAiCitationSummary(unittest.TestCase):
    """작업 A: AI_CITATION_SUMMARY 품질"""

    def setUp(self) -> None:
        self.html = _render_candidate()

    def test_ai_citation_present(self) -> None:
        self.assertIn('id="AI_CITATION_SUMMARY"', self.html)

    def test_no_internal_label_in_summary(self) -> None:
        m = re.search(r'id="AI_CITATION_SUMMARY".*?</section>', self.html, re.DOTALL)
        self.assertIsNotNone(m)
        block = m.group()
        self.assertNotIn("요미 판단:", block)
        self.assertNotIn("요미의 판단:", block)

    def test_no_broken_sentence_fragments(self) -> None:
        m = re.search(r'id="AI_CITATION_SUMMARY".*?</p>', self.html, re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group())
            # 단어가 잘린 경우: "높 요미", "않 1단계" 같은 패턴 금지
            self.assertNotRegex(text, r'[가-힣] [가-힣]{2,4} 판단')
            self.assertNotRegex(text, r'[가-힣] \d+단계')

    def test_summary_under_500_chars(self) -> None:
        m = re.search(r'<p>(.*?)</p>', re.search(
            r'id="AI_CITATION_SUMMARY".*?</section>', self.html, re.DOTALL
        ).group(), re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group(1))
            self.assertLessEqual(len(text), 500)

    def test_official_note_in_tax_summary(self) -> None:
        # tax_refund 글에서 공식 확인 문구 포함
        html = _render_candidate(content_type="tax_refund")
        m = re.search(r'id="AI_CITATION_SUMMARY".*?</section>', html, re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group())
            self.assertIn("공식", text)


class TestMetaDescription(unittest.TestCase):
    """작업 C: meta description 품질"""

    def setUp(self) -> None:
        self.html = _render_candidate()
        m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']', self.html)
        self.desc = m.group(1) if m else ""

    def test_meta_description_present(self) -> None:
        self.assertIn('<meta name="description"', self.html)

    def test_meta_description_min_80_chars(self) -> None:
        self.assertGreaterEqual(len(self.desc), 80, f"desc too short: {len(self.desc)} chars: {self.desc!r}")

    def test_meta_description_max_160_chars(self) -> None:
        self.assertLessEqual(len(self.desc), 160)

    def test_meta_description_no_broken_sentence(self) -> None:
        # 문장이 잘리지 않아야 함 (중간에 "다 " + 다른 문장 없음 체크)
        self.assertNotIn("요미 판단:", self.desc)
        self.assertNotIn("요미의 판단:", self.desc)


class TestGeoScoreQualityBased(unittest.TestCase):
    """작업 B: GEO score 품질 기반"""

    def test_meta_desc_invalid_caps_geo_score(self) -> None:
        # meta_description_valid=false이면 geo_score <= 80
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        if not meta.get("candidate_meta_description_valid", True):
            self.assertLessEqual(meta.get("geo_score", 0), 80)

    def test_geo_ready_requires_meta_desc_valid(self) -> None:
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        if not meta.get("candidate_meta_description_valid", True):
            self.assertFalse(meta.get("geo_ready", False))

    def test_geo_ready_requires_title_applied(self) -> None:
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        if not meta.get("selected_title_applied_to_candidate", True):
            self.assertFalse(meta.get("geo_ready", False))

    def test_full_quality_candidate_geo_score_valid(self) -> None:
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        if meta.get("candidate_meta_description_valid"):
            self.assertGreaterEqual(meta.get("geo_score", 0), 60)


class TestStaleSourceHandling(unittest.TestCase):
    """작업 E: stale 후보 처리"""

    def test_stale_publish_ready_false(self) -> None:
        contents = _make_preview_and_save(stale=True)
        meta = contents.get("article_candidate_meta.json", {})
        self.assertFalse(meta.get("publish_ready", True))

    def test_stale_fields_present(self) -> None:
        contents = _make_preview_and_save(stale=True)
        meta = contents.get("article_candidate_meta.json", {})
        self.assertTrue(meta.get("stale_source_warning"))
        self.assertTrue(meta.get("publish_blocked_by_stale_source"))
        self.assertFalse(meta.get("fresh_source_ok", True))
        self.assertFalse(meta.get("official_source_ok", True))

    def test_fresh_candidate_has_publish_ready_field(self) -> None:
        contents = _make_preview_and_save(stale=False)
        meta = contents.get("article_candidate_meta.json", {})
        self.assertIn("publish_ready", meta)

    def test_stale_pre_publish_checklist(self) -> None:
        contents = _make_preview_and_save(stale=True)
        meta = contents.get("article_candidate_meta.json", {})
        checklist = meta.get("pre_publish_checklist", {})
        self.assertFalse(checklist.get("fresh_source_ok", True))
        self.assertFalse(checklist.get("official_source_ok", True))


class TestHumanReviewRequired(unittest.TestCase):
    """작업 F: human_review_required is risk-based."""

    def test_article_candidate_meta_human_review_false_for_clean_candidate(self) -> None:
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        self.assertFalse(meta.get("human_review_required"))

    def test_pre_publish_checklist_human_review_false_for_clean_candidate(self) -> None:
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        checklist = meta.get("pre_publish_checklist", {})
        self.assertFalse(checklist.get("human_review_required"))

    def test_publish_allowed_for_clean_candidate(self) -> None:
        contents = _make_preview_and_save()
        meta = contents.get("article_candidate_meta.json", {})
        self.assertTrue(meta.get("publish_allowed_in_phase2"))
        checklist = meta.get("pre_publish_checklist", {})
        self.assertTrue(checklist.get("publish_allowed_in_phase2"))


class TestTitleSpecificity(unittest.TestCase):
    """작업 D: selected_title 구체성"""

    def test_specificity_score_field_exists(self) -> None:
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        result = svc.generate_candidates(
            topic="종합소득세 환급금 지연 때 먼저 확인할 것",
            content_type="tax_refund",
            topic_group="policy_benefit",
            pattern_id="tax_refund_hometax_check",
        )
        self.assertIn("selected_title_specificity_score", result)
        self.assertIn("selected_title_keyword_coverage", result)

    def test_select_best_title_with_keywords(self) -> None:
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        candidates = [
            {"title": "세금 환급금 확인법", "is_allowed": True, "ctr_score": 70, "risk_score": 0, "promise_match_score": 80},
            {"title": "종합소득세 환급금 조회 전 홈택스에서 먼저 볼 3가지", "is_allowed": True, "ctr_score": 65, "risk_score": 0, "promise_match_score": 80},
        ]
        best = svc.select_best_title(candidates, topic_keywords=["종합소득세", "환급금"])
        # specificity 높은 제목 우선
        self.assertIn("종합소득세", best.get("title", ""))


class TestWorkflowSchedules(unittest.TestCase):
    """작업 G: workflow 스케줄"""

    def test_news_workflow_is_manual_only(self) -> None:
        # 운영 방침(2026-07-03): AI 주제 하루 1회 자동 발행은 ai_blog.yml 하나만.
        # news_blog.yml은 수동(workflow_dispatch) 전용이어야 한다.
        import pathlib
        path = pathlib.Path(".github/workflows/news_blog.yml")
        if not path.exists():
            self.skipTest("news_blog.yml not found")
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("cron:", content, "news_blog.yml must not have a schedule trigger")
        self.assertIn("workflow_dispatch:", content)

    def test_ai_workflow_no_schedule_trigger(self) -> None:
        # 운영 방침(2026-07-24): ai_blog.yml은 schedule 트리거를 갖지 않는다 —
        # 유일한 자동 발행 경로는 Cloud Run Job(ai-blog-pipeline, 12:50 UTC 하루
        # 1회, Cloud Scheduler "ai-blog-evening"). GHA와 Cloud Run이 각자 스케줄을
        # 갖고 핸드셰이크로 중복을 막던 이전 설계가 GHA 지연으로 슬롯당 2건 중복
        # 발행 사고를 냈다(2026-07-20~21 실측) — schedule 자체를 없애 구조적으로
        # 재발을 막는다. news_blog.yml과 동일한 불변조건.
        import pathlib
        path = pathlib.Path(".github/workflows/ai_blog.yml")
        if not path.exists():
            self.skipTest("ai_blog.yml not found")
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("cron:", content, "ai_blog.yml must not have a schedule trigger")
        self.assertIn("workflow_dispatch:", content)

    def test_news_workflow_operational_guards(self) -> None:
        import pathlib
        path = pathlib.Path(".github/workflows/news_blog.yml")
        if not path.exists():
            self.skipTest("news_blog.yml not found")
        content = path.read_text(encoding="utf-8")
        self.assertIn("actions/checkout@v4", content)
        self.assertIn("actions/setup-python@v5", content)
        self.assertNotIn("continue-on-error: true", content)
        self.assertIn('NEWS_MAX_PUBLISH_ATTEMPTS: "12"', content)
        self.assertIn('MIN_TOPIC_SCORE: "75"', content)
        self.assertIn('TOPIC_CANDIDATE_LIMIT: "120"', content)
        self.assertIn('TITLE_CANDIDATE_COUNT: "10"', content)
        self.assertIn('NEWS_NAVER_MAX_REQUESTS: "36"', content)
        self.assertIn('NEWS_NAVER_DISPLAY: "10"', content)
        self.assertIn('git pull --rebase --autostash origin "${{ github.ref_name }}"', content)

    def test_ai_workflow_manual_dispatch(self) -> None:
        # 1단계: ai_blog.yml은 수동 dispatch 전용(스케줄 미설정). 검증 후 cron 추가 예정.
        import pathlib
        path = pathlib.Path(".github/workflows/ai_blog.yml")
        if not path.exists():
            self.skipTest("ai_blog.yml not found")
        content = path.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", content)
        self.assertIn("cli_ai.py", content)

    def test_ai_workflow_default_dry_run(self) -> None:
        import pathlib
        path = pathlib.Path(".github/workflows/ai_blog.yml")
        if not path.exists():
            self.skipTest("ai_blog.yml not found")
        content = path.read_text(encoding="utf-8")
        self.assertIn("default: 'dry_run'", content)


class TestAiPipeline(unittest.TestCase):
    """작업 H: AI pipeline 품질 엔진"""

    def test_ai_pipeline_runs(self) -> None:
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
        from blogspot_automation.services.publish_history_service import PublishHistoryService
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = AiTopicPipeline(
                dry_run=True,
                publish_history_service=PublishHistoryService(history_path=Path(tmp) / "publish_history.json"),
            )
            result = pipeline.run_once()
            self.assertIn(result.get("status"), ("dry_run_saved", "skipped", "failed", "held_for_review"))

    def test_ai_pipeline_generates_candidate(self) -> None:
        from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            from blogspot_automation.services.publish_history_service import PublishHistoryService
            from blogspot_automation.services.run_artifact_service import RunArtifactService
            pipeline = AiTopicPipeline(
                artifact_service=RunArtifactService(runs_dir=tmp),
                publish_history_service=PublishHistoryService(history_path=Path(tmp) / "publish_history.json"),
                dry_run=True,
            )
            result = pipeline.run_once()
            if result.get("status") == "dry_run_saved":
                artifact_dir = result.get("artifact_dir", "")
                self.assertTrue(Path(artifact_dir).exists())
                files = list(Path(artifact_dir).iterdir())
                names = {f.name for f in files}
                self.assertIn("selected_topic.json", names)


class TestCompletionPatch2(unittest.TestCase):
    """Completion Patch 2 — 작업 H 신규 테스트 10개"""

    def _get_citation_text(self, html: str) -> str:
        m = re.search(r'id="AI_CITATION_SUMMARY".*?<p>(.*?)</p>', html, re.DOTALL)
        if not m:
            return ""
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()

    def test_tax_refund_citation_summary_3_to_5_sentences(self) -> None:
        """tax_refund AI_CITATION_SUMMARY는 3~5문장 자연문."""
        html = _render_candidate(content_type="tax_refund", pattern_id="tax_refund_hometax_check")
        text = self._get_citation_text(html)
        self.assertTrue(text, "AI_CITATION_SUMMARY 텍스트가 없음")
        sentences = [s.strip() for s in re.split(r'(?<=[다요]\.)\s+', text) if s.strip()]
        self.assertGreaterEqual(len(sentences), 3, f"문장 수 부족: {len(sentences)}\ntext={text!r}")
        self.assertLessEqual(len(sentences), 5, f"문장 수 초과: {len(sentences)}\ntext={text!r}")

    def test_no_yomi_judgment_label_in_citation(self) -> None:
        """AI_CITATION_SUMMARY에 '요미 판단:' 없음."""
        html = _render_candidate()
        text = self._get_citation_text(html)
        self.assertNotIn("요미 판단:", text)
        self.assertNotIn("요미의 판단:", text)

    def test_no_step_label_in_citation(self) -> None:
        """AI_CITATION_SUMMARY에 '1단계:' 없음."""
        html = _render_candidate()
        text = self._get_citation_text(html)
        self.assertNotRegex(text, r'\d+단계\s*:')

    def test_broken_phrase_detected_as_invalid(self) -> None:
        """깨진 문구 '시작했기 확인할 항목' 발견 시 validate_ai_citation_summary=invalid."""
        from blogspot_automation.services.golden_article_preview_service import validate_ai_citation_summary
        broken = "환급 유형을 구분하지 않은 채로 조회를 시작했기 확인할 항목이 늘어납니다."
        result = validate_ai_citation_summary(broken)
        self.assertFalse(result["valid"])
        self.assertTrue(any("broken_pattern" in issue for issue in result["issues"]))

    def test_broken_meta_description_detected_as_invalid(self) -> None:
        """meta description에 깨진 문구 있으면 validate_meta_description=invalid."""
        from blogspot_automation.services.golden_article_preview_service import validate_meta_description
        broken = "시작했기 확인할 항목과 환급 계좌 등록 방법을 정리했습니다."
        result = validate_meta_description(broken)
        self.assertFalse(result["valid"])

    def test_stale_penalty_applied_makes_publish_ready_false(self) -> None:
        """stale_penalty_applied=True면 article_candidate_meta.publish_ready=False."""
        contents = _make_preview_and_save(stale=True)
        meta = contents.get("article_candidate_meta.json", {})
        self.assertFalse(meta.get("publish_ready", True),
                         f"stale 후보인데 publish_ready=True: {meta.get('publish_ready')}")

    def test_stale_penalty_applied_makes_fresh_source_ok_false(self) -> None:
        """stale_penalty_applied=True면 fresh_source_ok=False."""
        contents = _make_preview_and_save(stale=True)
        meta = contents.get("article_candidate_meta.json", {})
        self.assertFalse(meta.get("fresh_source_ok", True))

    def test_golden_preview_meta_human_review_false_for_clean_candidate(self) -> None:
        """clean golden_preview_meta does not require human review."""
        contents = _make_preview_and_save()
        gpm = contents.get("golden_preview_meta.json", {})
        self.assertFalse(gpm.get("human_review_required"),
                        f"golden_preview_meta human_review_required={gpm.get('human_review_required')}")

    def test_tax_refund_title_contains_search_keyword(self) -> None:
        """tax_refund selected_title은 '종합소득세' 또는 '홈택스' 또는 '환급금' 포함."""
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        result = svc.generate_candidates(
            topic="종합소득세 환급금 조회 전 먼저 확인할 것",
            content_type="tax_refund",
            topic_group="policy_benefit",
            pattern_id="tax_refund_hometax_check",
        )
        best = result.get("best_title", {})
        title = best.get("title", "")
        self.assertTrue(
            any(kw in title for kw in ("종합소득세", "홈택스", "환급금")),
            f"핵심 키워드 없는 제목 선택됨: {title!r}",
        )

    def test_overhype_title_has_lower_ctr_score(self) -> None:
        """과장 제목 '0원으로 보입니다'는 tax_refund에서 정상 제목보다 낮은 ctr_score."""
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        svc = TitleCandidateService()
        overhype = svc.score_title(
            "국세환급금·종합소득세 환급, 메뉴를 헷갈리면 0원으로 보입니다",
            pattern_id="tax_refund_hometax_check",
        )
        normal = svc.score_title(
            "종합소득세 환급금 조회 전 홈택스에서 먼저 볼 3가지",
            pattern_id="tax_refund_hometax_check",
        )
        self.assertLess(
            overhype["ctr_score"],
            normal["ctr_score"],
            f"과장 제목 ctr={overhype['ctr_score']} >= 정상 제목 ctr={normal['ctr_score']}",
        )


if __name__ == "__main__":
    unittest.main()
