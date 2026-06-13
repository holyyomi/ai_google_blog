from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------ #
# 공통 fixture                                                         #
# ------------------------------------------------------------------ #

def _make_golden_preview_result(
    *,
    matched: bool = True,
    ready: bool = True,
    fill_rate: float = 1.0,
    confidence: int = 80,
    grade: str = "A",
    blocking: list | None = None,
    final_editorial_score: int = 90,
    traffic: int = 30,
    usefulness: int = 35,
) -> dict[str, Any]:
    slot_result = {
        "topic": "테스트 주제",
        "slot_fill_rate": fill_rate,
        "slots": {
            "hook_opening": "도입 문구입니다.",
            "yomi_judgment": "요미 판단: 테스트 판단 내용입니다.",
            "misconceptions": [{"착각": "착각내용", "실제": "실제내용"}],
            "real_criterion": "실제 기준 내용",
            "quick_decision_table": [{"내 상황": "상황1", "할 일": "행동1"}],
            "actions": [{"번호": 1, "행동": "행동1", "설명": "설명1"}],
            "faq": [{"Q": "Q1", "A": "A1"}],
            "hashtags": ["#해시태그1"],
            "internal_links": [{"주제": "링크1", "content_type": "tax_refund"}],
        },
    }
    es = {
        "traffic_potential_score": traffic,
        "usefulness_score": usefulness,
        "evergreen_asset_score": 8,
        "viral_safety_score": 10,
        "final_editorial_score": final_editorial_score,
    }
    return {
        "matched": matched,
        "ready_for_review": ready,
        "pattern_match": {"pattern_id": "tax_refund_hometax_check", "confidence": confidence},
        "slot_result": slot_result,
        "slot_fill_rate": fill_rate,
        "missing_required_slots": [],
        "blocking_issues": blocking or [],
        "warnings": [],
        "preview_html": "<html><head><title>[PREVIEW] 테스트</title></head><body>"
                        "<h1>테스트</h1>"
                        '<section class="yomi-judgment-box"><p class="section-label">핵심 관점</p>'
                        '<p>요미 판단: 테스트</p></section>'
                        '<div class="preview-meta">pattern: test · confidence: 80 · fill_rate: 1.00</div>'
                        "</body></html>",
        "_editorial_scores": es,
        "_content_candidate_grade": grade,
        "_can_generate_candidate": False,
        "_article_candidate_html": "",
    }


class TestRenderArticleCandidateHtml(unittest.TestCase):
    """GoldenArticlePreviewService.render_article_candidate_html 단위 테스트."""

    def setUp(self) -> None:
        from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
        self.svc = GoldenArticlePreviewService()

    def test_removes_preview_prefix_from_title(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        pm = ps.match_pattern(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        sr = self.svc._sf.fill_slots("tax_refund_hometax_check", "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        html = self.svc.render_article_candidate_html(pm, sr)
        self.assertNotIn("[PREVIEW]", html)
        self.assertIn("<title>", html)

    def test_removes_preview_meta_debug_div(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        pm = ps.match_pattern(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        sr = self.svc._sf.fill_slots("tax_refund_hometax_check", "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        html = self.svc.render_article_candidate_html(pm, sr)
        # div element 제거 확인 (CSS 클래스 선택자 .preview-meta는 무관)
        self.assertNotIn('class="preview-meta"', html)
        self.assertNotIn("confidence:", html)
        self.assertNotIn("fill_rate:", html)

    def test_retains_core_content(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        pm = ps.match_pattern(topic="세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        sr = self.svc._sf.fill_slots("tax_refund_hometax_check", "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지")
        html = self.svc.render_article_candidate_html(pm, sr)
        self.assertIn("<h1>", html)
        self.assertIn("핵심 관점", html)

    def test_quick_decision_table_supports_confirm_key(self) -> None:
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        ps = GoldenPatternService()
        pm = ps.match_pattern(
            topic='게임업계 리밸런싱)③" 서비스 지원 종료 전에 확인할 것',
            content_type="platform_change",
            topic_group="platform_issue",
        )
        sr = {
            "pattern_id": "platform_change_service_update",
            "topic": '게임업계 리밸런싱)③" 서비스 지원 종료 전에 확인할 것',
            "slot_fill_rate": 1.0,
            "slots": {
                "hook_opening": "서비스 지원 종료 전에 계정과 결제를 확인해야 합니다.",
                "yomi_judgment": "요미 판단: 공식 공지에서 적용 대상을 먼저 확인해야 합니다.",
                "misconceptions": [],
                "real_criterion": "1단계: 공식 공지 확인",
                "quick_decision_table": [
                    {
                        "내 상황": "자동결제가 등록되어 있다",
                        "확인할 것": "결제 수단과 해지 가능일을 확인한다",
                    }
                ],
                "actions": [{"행동": "공식 공지 확인", "설명": "적용 대상과 일자를 확인한다"}],
                "faq": [{"Q": "무엇부터 확인하나요?", "A": "공식 공지의 적용 대상부터 확인합니다."}],
            },
        }

        html = self.svc.render_article_candidate_html(pm, sr)

        self.assertIn("<td>결제 수단과 해지 가능일을 확인한다</td>", html)
        self.assertNotIn("<td></td>", html)


class TestArticleCandidateArtifact(unittest.TestCase):
    """save_golden_preview_artifacts article_candidate 저장 테스트."""


    def _preview_with_candidate_html(self, grade: str = "A", blocking: list | None = None) -> dict:
        """article_candidate HTML이 포함된 preview_result 생성."""
        from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
        svc = GoldenArticlePreviewService()
        result = _make_golden_preview_result(grade=grade, blocking=blocking)
        pm = result["pattern_match"]
        sr = result["slot_result"]

        can_generate = (
            result["matched"]
            and result["ready_for_review"]
            and result["slot_fill_rate"] >= 0.8
            and pm.get("confidence", 0) >= 80
            and grade in ("A", "B")
            and not (blocking or [])
        )
        html = ""
        if can_generate:
            html = svc.render_article_candidate_html(pm, sr)
        result["_can_generate_candidate"] = can_generate
        result["_article_candidate_html"] = html
        return result

    # ------------------------------------------------------------------ #
    # 작업 E 테스트 케이스                                                  #
    # ------------------------------------------------------------------ #

    def test_grade_A_generates_candidate(self) -> None:
        result = self._preview_with_candidate_html(grade="A")
        names, contents = self._run_save(result)
        self.assertIn("article_candidate.html", names)
        self.assertIn("article_candidate_meta.json", names)

    def test_grade_B_generates_candidate(self) -> None:
        result = self._preview_with_candidate_html(grade="B")
        names, _ = self._run_save(result)
        self.assertIn("article_candidate.html", names)

    def test_grade_C_no_candidate(self) -> None:
        result = self._preview_with_candidate_html(grade="C")
        names, _ = self._run_save(result)
        self.assertNotIn("article_candidate.html", names)
        self.assertNotIn("article_candidate_meta.json", names)

    def test_grade_D_no_candidate(self) -> None:
        result = self._preview_with_candidate_html(grade="D")
        names, _ = self._run_save(result)
        self.assertNotIn("article_candidate.html", names)

    def test_blocking_issues_prevent_candidate(self) -> None:
        result = self._preview_with_candidate_html(
            grade="A", blocking=["slot_fill_rate_below_80:0.50"]
        )
        names, _ = self._run_save(result)
        self.assertNotIn("article_candidate.html", names)

    def test_article_candidate_meta_fields(self) -> None:
        result = self._preview_with_candidate_html(grade="A")
        names, contents = self._run_save(result)
        self.assertIn("article_candidate_meta.json", names)
        meta = json.loads(contents["article_candidate_meta.json"])
        required_keys = [
            "article_candidate_generated",
            "article_candidate_source",
            "golden_pattern_id",
            "golden_pattern_confidence",
            "golden_slot_fill_rate",
            "content_candidate_grade",
            "final_editorial_score",
            "traffic_potential_score",
            "usefulness_score",
            "why_candidate",
            "why_hold",
            "human_review_required",
            "publish_allowed_in_phase2",
        ]
        for k in required_keys:
            self.assertIn(k, meta, f"field '{k}' missing from article_candidate_meta.json")

    def test_publish_allowed_in_phase2_is_true_for_clean_non_ai_candidate(self) -> None:
        result = self._preview_with_candidate_html(grade="A")
        names, contents = self._run_save(result)
        meta = json.loads(contents["article_candidate_meta.json"])
        self.assertTrue(meta["publish_allowed_in_phase2"])

    def test_article_candidate_html_no_preview_marker(self) -> None:
        result = self._preview_with_candidate_html(grade="A")
        names, contents = self._run_save(result)
        content = contents["article_candidate.html"]
        self.assertNotIn("[PREVIEW]", content)
        self.assertNotIn('class="preview-meta"', content)
        self.assertIn("yomi-clean-post", content)
        self.assertNotIn('class="golden-preview"', content)
        self.assertNotIn('class="ai-overview-box"', content)
        self.assertNotIn('class="paa-block"', content)
        self.assertNotIn('class="internal-links"', content)
        self.assertNotIn('data-yomi-block="internal-links"', content)

    def _run_save(self, preview_result: dict) -> tuple[set[str], dict[str, str]]:
        """임시 디렉토리에 artifacts를 저장하고 (파일명 집합, 파일명→내용 dict)를 반환한다."""
        from blogspot_automation.services.run_artifact_service import RunArtifactService
        with tempfile.TemporaryDirectory() as tmpdir:
            run_path = Path(tmpdir) / "test_run"
            run_path.mkdir()
            art = RunArtifactService(runs_dir=tmpdir)
            art.save_golden_preview_artifacts(run_path, preview_result)
            # tempdir이 닫히기 전에 내용을 읽어 반환
            file_names = {f.name for f in run_path.iterdir()}
            file_contents = {
                f.name: f.read_text(encoding="utf-8")
                for f in run_path.iterdir()
            }
            return file_names, file_contents


if __name__ == "__main__":
    unittest.main()
