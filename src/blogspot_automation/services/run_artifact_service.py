from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

from blogspot_automation.config import Settings
from blogspot_automation.services.publish_preview_scorecard import render_publish_preview_scorecard_markdown
from blogspot_automation.services.seo_policy import MAX_BLOGSPOT_LABELS, MAX_CONTENT_HASHTAGS

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _ai_blog_auto_publish_enabled() -> bool:
    return _env_flag("AI_BLOG_MODE") and _env_flag("AI_BLOG_AUTO_PUBLISH")

_ALWAYS_REVIEW_PATTERN_IDS = frozenset(
    {
        "ai_work_time_savings",
        "ai_tool_comparison",
        "ai_automation_workflow",
    }
)


class RunArtifactService:
    def __init__(self, *, runs_dir: str | Path | None = None, settings: Settings | None = None) -> None:
        if runs_dir is not None:
            self.runs_dir = Path(runs_dir)
        elif settings is not None:
            self.runs_dir = Path(settings.runs_dir)
        else:
            self.runs_dir = Path("runs")

    def save_dry_run_result(
        self,
        *,
        html: str,
        selected_topic: dict[str, Any],
        title_candidates: list[dict[str, Any]],
        scoring: dict[str, Any],
        run_meta: dict[str, Any],
        image_prompt: str = "",
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_path = self.runs_dir / f"news_{timestamp}"

        try:
            run_path.mkdir(parents=True, exist_ok=True)
            (run_path / "article.html").write_text(html, encoding="utf-8")
            self._write_json(run_path / "selected_topic.json", selected_topic)
            self._write_json(run_path / "title_candidates.json", title_candidates)
            self._write_json(run_path / "scoring.json", scoring)
            self._write_json(run_path / "run_meta.json", run_meta)
            self._write_publish_preview_scorecard(run_path, run_meta)
            if image_prompt.strip():
                (run_path / "image_prompt.txt").write_text(image_prompt.strip(), encoding="utf-8")
        except Exception as exc:
            logger.error("DRY_RUN 결과 저장 실패: %s", exc)
            raise RuntimeError(f"Failed to save dry run artifacts: {exc}") from exc

        return run_path

    def save_status_result(
        self,
        *,
        status_payload: dict[str, Any],
        run_meta: dict[str, Any] | None = None,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_path = self.runs_dir / f"news_{timestamp}"

        try:
            run_path.mkdir(parents=True, exist_ok=True)
            self._write_json(run_path / "status.json", status_payload)
            self._write_json(run_path / "run_meta.json", run_meta or status_payload)
            self._write_publish_preview_scorecard(run_path, run_meta or status_payload)
        except Exception as exc:
            logger.error("DRY_RUN status artifact save failed: %s", exc)
            raise RuntimeError(f"Failed to save dry run status artifact: {exc}") from exc

        return run_path

    def update_publish_artifacts(
        self,
        run_path: Path | str,
        *,
        html: str | None = None,
        publish_quality_gate: dict[str, Any] | None = None,
        run_meta_updates: dict[str, Any] | None = None,
        scoring_updates: dict[str, Any] | None = None,
    ) -> None:
        """Rewrite final publish artifacts after the pipeline changes publish HTML."""
        path = Path(run_path)
        try:
            if html is not None:
                (path / "article.html").write_text(html, encoding="utf-8")

            run_meta = self._read_json_dict(path / "run_meta.json")
            if publish_quality_gate is not None:
                run_meta["publish_quality_gate"] = publish_quality_gate
            if run_meta_updates:
                run_meta.update(run_meta_updates)
            if run_meta:
                self._write_json(path / "run_meta.json", run_meta)
                self._write_publish_preview_scorecard(path, run_meta)

            scoring = self._read_json_dict(path / "scoring.json")
            if publish_quality_gate is not None:
                scoring["publish_quality_gate"] = publish_quality_gate
            if scoring_updates:
                scoring.update(scoring_updates)
            if scoring:
                self._write_json(path / "scoring.json", scoring)
        except Exception as exc:
            logger.warning("publish artifact update failed: %s", exc)

    def save_golden_preview_artifacts(
        self,
        run_path: Path,
        preview_result: dict[str, Any],
    ) -> None:
        """golden preview 관련 artifact를 run_path 폴더에 저장한다."""
        try:
            pm = preview_result.get("pattern_match") or {}
            sr = preview_result.get("slot_result") or {}

            # pattern_match.json — 항상 저장
            self._write_json(run_path / "pattern_match.json", pm)

            # slot_result.json — matched=true일 때만 의미 있음
            if preview_result.get("matched") and sr:
                self._write_json(run_path / "slot_result.json", sr)

            # golden_preview.html — matched=true일 때만 저장
            html = str(preview_result.get("preview_html") or "")
            if preview_result.get("matched") and html.strip():
                (run_path / "golden_preview.html").write_text(html, encoding="utf-8")

            # golden_preview_meta.json — 항상 저장
            es: dict[str, Any] = preview_result.get("_editorial_scores") or {}
            grade: str = str(preview_result.get("_content_candidate_grade") or "")
            ready = preview_result.get("ready_for_review", False)
            blocking = preview_result.get("blocking_issues", [])
            _is_nm = bool(preview_result.get("near_match"))
            _pattern_id = str(pm.get("pattern_id") or "")
            _always_review_pattern = (
                _pattern_id in _ALWAYS_REVIEW_PATTERN_IDS
                and not _ai_blog_auto_publish_enabled()
            )
            human_review_required = (
                _is_nm
                or bool(blocking)
                or not bool(ready)
                or grade not in ("A", "B")
                or _always_review_pattern
            )
            meta: dict[str, Any] = {
                "matched": preview_result.get("matched", False),
                "near_match": _is_nm,
                "ready_for_review": ready,
                "pattern_id": pm.get("pattern_id") or "",
                "pattern_confidence": pm.get("confidence", 0),
                "pattern_ct_match": pm.get("content_type_match", False),
                "pattern_tg_match": pm.get("topic_group_match", False),
                "slot_fill_rate": preview_result.get("slot_fill_rate", 0.0),
                "missing_required_slots": preview_result.get("missing_required_slots", []),
                "blocking_issues": blocking,
                "warnings": preview_result.get("warnings", []),
                # Editorial Scoring
                "content_candidate_grade": grade,
                "traffic_potential_score": es.get("traffic_potential_score", 0),
                "usefulness_score": es.get("usefulness_score", 0),
                "evergreen_asset_score": es.get("evergreen_asset_score", 0),
                "viral_safety_score": es.get("viral_safety_score", 0),
                "final_editorial_score": es.get("final_editorial_score", 0),
                # Human review guidance
                "is_publish_candidate": (ready or _is_nm) and not blocking,
                "why_candidate": (
                    "near_match(ct+tg)+slot_fill>=0.8+human_review_required"
                    if _is_nm else
                    "golden_preview_ready + slot_fill>=0.8 + confidence>=80"
                ) if ((ready or _is_nm) and not blocking) else "",
                "why_hold": ", ".join(blocking) if blocking else (
                    "pattern_not_matched" if not preview_result.get("matched") else
                    (f"near_match_confidence:{pm.get('confidence',0)}" if _is_nm else "")
                ),
                "human_review_required": human_review_required,
            }
            self._write_json(run_path / "golden_preview_meta.json", meta)

            logger.info(
                "golden preview artifacts saved → %s (matched=%s ready=%s)",
                run_path,
                meta["matched"],
                meta["ready_for_review"],
            )

            # article_candidate.html + article_candidate_meta.json
            if preview_result.get("_can_generate_candidate"):
                candidate_html = str(preview_result.get("_article_candidate_html") or "")
                if candidate_html.strip():
                    (run_path / "article_candidate.html").write_text(candidate_html, encoding="utf-8")

                    fill_rate = preview_result.get("slot_fill_rate", 0.0)
                    confidence = pm.get("confidence", 0)
                    tr = preview_result.get("_title_result") or {}
                    best = tr.get("best_title") or {}
                    selected_title = str(preview_result.get("_selected_title") or best.get("title") or "")

                    # h1·title 추출 및 mismatch 검사
                    import re as _re_cand
                    h1_match = _re_cand.search(r'<h1>([^<]*)</h1>', candidate_html)
                    actual_h1 = h1_match.group(1) if h1_match else ""
                    title_match = _re_cand.search(r'<title>([^<]*)</title>', candidate_html)
                    actual_title = title_match.group(1) if title_match else ""
                    jld_match = _re_cand.search(r'"headline"\s*:\s*"([^"]+)"', candidate_html)
                    actual_jld = jld_match.group(1) if jld_match else ""

                    # HTML entity decode (e.g. &quot; → ") so comparison with selected_title works
                    import html as _html_mod
                    actual_h1 = _html_mod.unescape(actual_h1) if actual_h1 else actual_h1
                    actual_title = _html_mod.unescape(actual_title) if actual_title else actual_title
                    actual_jld = _html_mod.unescape(actual_jld) if actual_jld else actual_jld

                    title_applied = bool(selected_title and actual_h1 == selected_title)
                    mismatch = bool(selected_title and actual_h1 and actual_h1 != selected_title)
                    mismatch_reason = (
                        f"h1='{actual_h1[:40]}' != selected_title='{selected_title[:40]}'"
                        if mismatch else ""
                    )

                    # meta description 추출
                    _mdesc_m = _re_cand.search(
                        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']',
                        candidate_html,
                    )
                    candidate_meta_description = _mdesc_m.group(1) if _mdesc_m else ""
                    meta_desc_length = len(candidate_meta_description)
                    meta_desc_valid = 120 <= meta_desc_length <= 160

                    # JSON-LD 추가 필드
                    _jdesc_m = _re_cand.search(r'"description"\s*:\s*"([^"]+)"', candidate_html)
                    actual_jld_desc = _jdesc_m.group(1) if _jdesc_m else ""
                    jld_valid = bool(actual_jld and actual_jld_desc)
                    jld_warnings: list[str] = []
                    if not actual_jld:
                        jld_warnings.append("missing_headline")
                    if not actual_jld_desc:
                        jld_warnings.append("missing_description")

                    # 첫 200자 핵심 답변 검사
                    _body_m = _re_cand.search(r'<body[^>]*>(.*)', candidate_html, _re_cand.DOTALL)
                    _body_text = _body_m.group(1) if _body_m else candidate_html
                    _body_plain = _re_cand.sub(r'<[^>]+>', '', _body_text)
                    _body_plain = ' '.join(_body_plain.split())
                    first_200 = _body_plain[:200]
                    _fillers = ["요즘 많은 사람이", "궁금해합니다", "알아보겠습니다", "살펴보겠습니다"]
                    geo_first_200_ok = bool(first_200.strip()) and not any(f in first_200 for f in _fillers)
                    geo_first_200_issue = "" if geo_first_200_ok else "filler_or_empty_opening"

                    # AI_CITATION_SUMMARY 텍스트 추출 및 유효성 검사
                    import re as _re_geo
                    from blogspot_automation.services.golden_article_preview_service import (
                        validate_ai_citation_summary as _val_aic,
                        validate_meta_description as _val_meta,
                    )
                    _aic_block_m = _re_geo.search(
                        r'id="AI_CITATION_SUMMARY".*?<p>(.*?)</p>',
                        candidate_html,
                        _re_geo.DOTALL,
                    )
                    _aic_text = _re_geo.sub(r'<[^>]+>', '', _aic_block_m.group(1)) if _aic_block_m else ""
                    _aic_validation = _val_aic(_aic_text)
                    geo_ai_citation_summary_valid = _aic_validation["valid"]

                    # meta description 유효성 강화 검사 (80~160자 + 깨진 문장 없음)
                    _meta_validation = _val_meta(candidate_meta_description)
                    meta_desc_valid = (
                        80 <= meta_desc_length <= 160
                        and _meta_validation["valid"]
                    )

                    # GEO 요소 존재 확인
                    geo_ai_citation = 'id="AI_CITATION_SUMMARY"' in candidate_html
                    geo_updated_date = 'id="UPDATED_DATE_BLOCK"' in candidate_html
                    geo_faq_present = 'class="faq' in candidate_html
                    geo_jsonld_present = '"@context"' in candidate_html
                    geo_links_present = 'class="internal-links"' in candidate_html
                    geo_table_present = any(x in candidate_html for x in [
                        'class="quick-decision-table"', 'class="misconception-box"',
                    ])
                    geo_checklist_present = 'class="actions-box"' in candidate_html
                    geo_definition_present = 'class="real-criterion"' in candidate_html
                    geo_judgment_present = 'class="yomi-judgment-box"' in candidate_html

                    # New GEO intent elements
                    geo_issue_context_present = 'id="ISSUE_CONTEXT_BLOCK"' in candidate_html
                    geo_intent_answer_present = 'id="INTENT_ANSWER_BLOCK"' in candidate_html
                    geo_source_trust_present = 'id="SOURCE_TRUST_BLOCK"' in candidate_html
                    geo_intent_qa_count = len(_re_cand.findall(r'class="intent-qa-item"', candidate_html))
                    geo_intent_questions_ok = geo_intent_answer_present and geo_intent_qa_count >= 3

                    # SGE / AI Overviews elements
                    sge_ai_overview_present = 'id="AI_OVERVIEW_TARGET_ANSWER"' in candidate_html
                    sge_paa_present = 'id="PEOPLE_ALSO_ASK_BLOCK"' in candidate_html
                    sge_paa_count = len(_re_cand.findall(r'class="paa-item"', candidate_html))
                    sge_confirmed_vs_check_present = 'id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"' in candidate_html

                    # GEO 점수 계산 (100점 기준)
                    geo_score_raw = (
                        (10 if geo_first_200_ok else 0) +
                        (15 if geo_intent_answer_present and geo_intent_qa_count >= 3 else 0) +
                        (10 if geo_issue_context_present else 0) +
                        (5 if geo_source_trust_present else 0) +
                        (10 if geo_ai_citation else 0) +
                        (5 if geo_definition_present else 0) +
                        (5 if geo_table_present else 0) +
                        (5 if geo_faq_present else 0) +
                        (10 if geo_updated_date else 0) +
                        (5 if geo_links_present else 0) +
                        (5 if geo_jsonld_present else 0) +
                        (5 if geo_judgment_present else 0) +
                        (5 if geo_checklist_present else 0)
                    )
                    # GEO 품질 기반 cap: meta_description 또는 AI_CITATION 문제시 최대치 제한
                    _geo_cap = 100
                    if not meta_desc_valid:
                        _geo_cap = min(_geo_cap, 80)
                    if not geo_ai_citation or not geo_ai_citation_summary_valid:
                        _geo_cap = min(_geo_cap, 70)
                    if not title_applied:
                        _geo_cap = min(_geo_cap, 80)
                    if not geo_intent_answer_present or geo_intent_qa_count < 3:
                        _geo_cap = min(_geo_cap, 75)
                    geo_score = min(geo_score_raw, _geo_cap)
                    geo_ready = (
                        geo_score >= 80
                        and meta_desc_valid
                        and title_applied
                        and not mismatch
                        and geo_intent_answer_present
                        and geo_intent_qa_count >= 3
                    )
                    geo_needs_revision = (not geo_ready) and geo_score >= 60
                    geo_hold = geo_score < 60

                    # blogspot_labels (2~3개)
                    _blogspot_labels: list[str] = list(preview_result.get("_blogspot_labels") or [])
                    blogspot_label_count = len(_blogspot_labels)
                    blogspot_labels_valid = 2 <= blogspot_label_count <= MAX_BLOGSPOT_LABELS

                    # content_hashtags (0~3개)
                    _raw_hashtags: list[str] = list(preview_result.get("_hashtags") or [])
                    content_hashtag_count = len(_raw_hashtags)
                    content_hashtags_valid = content_hashtag_count <= MAX_CONTENT_HASHTAGS

                    # FAQPage JSON-LD 감지
                    faq_ld_match = _re_cand.search(
                        r'"@type"\s*:\s*"FAQPage"', candidate_html
                    )
                    faq_jsonld_present = faq_ld_match is not None
                    # FAQ 항목 수
                    faq_q_count = len(_re_cand.findall(r'"@type"\s*:\s*"Question"', candidate_html))
                    faq_jsonld_valid = faq_jsonld_present and faq_q_count > 0
                    faq_jsonld_warnings: list[str] = []
                    if not faq_jsonld_present:
                        faq_jsonld_warnings.append("faq_jsonld_missing")
                    elif faq_q_count == 0:
                        faq_jsonld_warnings.append("faq_jsonld_no_questions")

                    # SGE / AI Overviews 점수 (100점 기준)
                    sge_score_raw = (
                        (20 if sge_ai_overview_present else 0) +
                        (15 if sge_paa_present and sge_paa_count >= 5 else (8 if sge_paa_count >= 3 else 0)) +
                        (20 if geo_intent_answer_present and geo_intent_qa_count >= 3 else 0) +
                        (15 if geo_issue_context_present else 0) +
                        (10 if sge_confirmed_vs_check_present else 0) +
                        (10 if geo_source_trust_present else 0) +
                        (10 if faq_jsonld_valid else 0)
                    )
                    sge_score = min(sge_score_raw, 100)
                    sge_ready = (
                        sge_ai_overview_present
                        and sge_paa_count >= 5
                        and geo_intent_qa_count >= 3
                        and geo_issue_context_present
                        and geo_source_trust_present
                        and meta_desc_valid
                        and faq_jsonld_valid
                    )

                    # JSON-LD 안정성 추가 검사
                    _jld_type_m = _re_cand.search(r'"@type"\s*:\s*"([^"]+)"', candidate_html)
                    jsonld_type = _jld_type_m.group(1) if _jld_type_m else ""
                    jsonld_hl_match = bool(actual_jld and actual_jld == selected_title)
                    jsonld_desc_match = bool(
                        actual_jld_desc
                        and candidate_meta_description
                        and actual_jld_desc[:80] == candidate_meta_description[:80]
                    )
                    _date_present = bool(
                        _re_cand.search(r'"datePublished"|"dateModified"', candidate_html)
                    )
                    _author_present = '"author"' in candidate_html
                    _image_present = '"image"' in candidate_html
                    extended_jld_warnings: list[str] = list(jld_warnings)
                    if not jsonld_hl_match and actual_jld:
                        extended_jld_warnings.append("headline_title_mismatch")
                    if not jsonld_desc_match and actual_jld_desc:
                        extended_jld_warnings.append("description_meta_mismatch")
                    if not _date_present:
                        extended_jld_warnings.append("date_missing")
                    if not _author_present:
                        extended_jld_warnings.append("author_missing")
                    if not _image_present:
                        extended_jld_warnings.append("image_missing")

                    # metadata_warnings 종합
                    metadata_warnings: list[str] = []
                    if blogspot_label_count > MAX_BLOGSPOT_LABELS:
                        metadata_warnings.append(f"blogspot_labels_exceeds_{MAX_BLOGSPOT_LABELS}:{blogspot_label_count}")
                    if content_hashtag_count > MAX_CONTENT_HASHTAGS:
                        metadata_warnings.append(f"hashtags_exceeds_{MAX_CONTENT_HASHTAGS}:{content_hashtag_count}")
                    if actual_jld and actual_jld != selected_title:
                        metadata_warnings.append("jsonld_headline_title_mismatch")
                    if not candidate_meta_description:
                        metadata_warnings.append("meta_description_missing")
                    if not _image_present:
                        metadata_warnings.append("image_missing")
                    if not faq_jsonld_present and geo_faq_present:
                        metadata_warnings.append("faq_in_body_but_no_faq_jsonld")

                    # stale source 여부:
                    # _stale_candidate, blocking_issues, _scoring_stale_penalty 세 경로 모두 체크
                    _preview_labels = list(preview_result.get("_labels") or [])
                    _is_stale = (
                        bool(preview_result.get("_stale_candidate"))
                        or bool(preview_result.get("_scoring_stale_penalty"))
                        or any(
                            "stale_policy" in str(b) or "stale_penalty" in str(b)
                            for b in (preview_result.get("blocking_issues") or [])
                        )
                    )
                    _fresh_source_ok = not _is_stale
                    _official_source_ok = not _is_stale

                    _article_pattern_id = str(pm.get("pattern_id") or "")
                    _article_always_review_pattern = (
                        _article_pattern_id in _ALWAYS_REVIEW_PATTERN_IDS
                        and not _ai_blog_auto_publish_enabled()
                    )
                    article_human_review_required = (
                        bool(preview_result.get("near_match"))
                        or bool(preview_result.get("blocking_issues") or [])
                        or not bool(preview_result.get("ready_for_review"))
                        or grade not in ("A", "B")
                        or _article_always_review_pattern
                    )

                    # traffic/usefulness 하한선 — 저관심·저트래픽 주제 자동발행 차단
                    # editorial traffic_potential_score/usefulness_score는 0-40 스케일.
                    _min_traffic = _env_int("NEWS_MIN_TRAFFIC_POTENTIAL_SCORE", 20)
                    _min_usefulness = _env_int("NEWS_MIN_USEFULNESS_SCORE", 22)
                    _traffic_score = int(es.get("traffic_potential_score", 0) or 0)
                    _usefulness_value = int(es.get("usefulness_score", 0) or 0)
                    _traffic_floor_ok = (
                        _traffic_score >= _min_traffic and _usefulness_value >= _min_usefulness
                    )

                    # pre_publish_checklist (강화 + stale + human_review)
                    _blocking = list(preview_result.get("blocking_issues") or [])
                    _default_clean = not any("banned_default_phrase" in b for b in _blocking)
                    _risk_clean = not any("viral_risk" in b for b in _blocking)
                    pre_publish_checklist: dict[str, Any] = {
                        "traffic_floor_ok": _traffic_floor_ok,
                        "title_ok": title_applied,
                        "meta_description_ok": meta_desc_valid,
                        "ai_citation_summary_ok": geo_ai_citation_summary_valid,
                        "jsonld_ok": jld_valid,
                        "faq_jsonld_ok": faq_jsonld_present,
                        "blogspot_labels_ok": blogspot_labels_valid,
                        "content_hashtags_ok": content_hashtags_valid,
                        "golden_pattern_matched": bool(preview_result.get("matched")),
                        "slot_fill_rate_ok": float(preview_result.get("slot_fill_rate", 0.0)) >= 0.8,
                        "default_phrase_clean": _default_clean,
                        "risk_clean": _risk_clean,
                        "fresh_source_ok": _fresh_source_ok,
                        "official_source_ok": _official_source_ok,
                        "geo_score_ok": geo_ready,
                        "sge_ready": sge_ready,
                        "human_review_required": article_human_review_required,
                        "publish_allowed_in_phase2": not article_human_review_required,
                    }

                    # publish_ready 조건: 모든 필수 항목 통과 + stale 없음 + citation valid
                    _required_pass = (
                        title_applied
                        and meta_desc_valid
                        and geo_ai_citation_summary_valid
                        and jld_valid
                        and faq_jsonld_valid
                        and blogspot_labels_valid
                        and content_hashtags_valid
                        and _fresh_source_ok
                        and geo_ready
                        and sge_ready
                        and _default_clean
                        and _risk_clean
                        and grade in ("A", "B")
                        and _traffic_floor_ok
                    )
                    publish_ready = _required_pass and not _is_stale and not article_human_review_required

                    cand_meta: dict[str, Any] = {
                        "article_candidate_generated": True,
                        "article_candidate_source": "golden_preview",
                        "near_match": bool(preview_result.get("near_match")),
                        "golden_pattern_id": pm.get("pattern_id") or "",
                        "golden_pattern_confidence": confidence,
                        "golden_slot_fill_rate": fill_rate,
                        "content_candidate_grade": grade,
                        "final_editorial_score": es.get("final_editorial_score", 0),
                        "traffic_potential_score": es.get("traffic_potential_score", 0),
                        "usefulness_score": es.get("usefulness_score", 0),
                        "why_candidate": (
                            f"grade={grade} + golden_matched + "
                            f"slot_fill={fill_rate:.2f} + confidence={confidence}"
                        ),
                        "why_hold": (
                            ""
                            if _traffic_floor_ok
                            else f"traffic_floor:traffic={_traffic_score}<{_min_traffic}_or_usefulness={_usefulness_value}<{_min_usefulness}"
                        ),
                        "human_review_required": article_human_review_required,
                        "publish_allowed_in_phase2": not article_human_review_required,
                        # selected_title 반영 필드
                        "selected_title_applied_to_candidate": title_applied,
                        "candidate_title_source": "selected_title" if title_applied else "topic",
                        "candidate_h1": actual_h1,
                        "candidate_meta_title": actual_title,
                        "candidate_jsonld_headline": actual_jld,
                        "selected_title_ctr_score": int(best.get("ctr_score") or 0),
                        "selected_title_promise_match_score": int(best.get("promise_match_score") or 0),
                        "selected_title_risk_score": int(best.get("risk_score") or 0),
                        "candidate_title_mismatch": mismatch,
                        "candidate_title_mismatch_reason": mismatch_reason,
                        # meta description
                        "candidate_meta_description": candidate_meta_description,
                        "candidate_meta_description_length": meta_desc_length,
                        "candidate_meta_description_valid": meta_desc_valid,
                        # JSON-LD
                        "candidate_jsonld_description": actual_jld_desc,
                        "candidate_jsonld_valid": jld_valid,
                        "candidate_jsonld_warnings": jld_warnings,
                        # GEO 첫 200자
                        "first_200_chars": first_200,
                        "geo_first_200_chars_answer_present": geo_first_200_ok,
                        "geo_first_200_chars_issue": geo_first_200_issue,
                        # GEO 요소 존재
                        "geo_ai_citation_summary_present": geo_ai_citation,
                        "geo_ai_citation_summary_valid": geo_ai_citation_summary_valid,
                        "geo_ai_citation_summary_issues": _aic_validation.get("issues", []),
                        "geo_updated_date_present": geo_updated_date,
                        "geo_definition_or_context_present": geo_definition_present,
                        "geo_table_or_decision_matrix_present": geo_table_present,
                        "geo_checklist_present": geo_checklist_present,
                        "geo_faq_present": geo_faq_present,
                        "geo_internal_links_present": geo_links_present,
                        "geo_jsonld_present": geo_jsonld_present,
                        "geo_personal_judgment_present": geo_judgment_present,
                        # GEO Intent Engine
                        "geo_issue_context_present": geo_issue_context_present,
                        "geo_intent_answer_present": geo_intent_answer_present,
                        "geo_source_trust_present": geo_source_trust_present,
                        "geo_intent_qa_count": geo_intent_qa_count,
                        "reader_intent_questions_present": geo_intent_questions_ok,
                        # GEO 점수
                        "geo_score": geo_score,
                        # SGE / AI Overviews
                        "sge_score": sge_score,
                        "sge_ready": sge_ready,
                        "ai_overview_target_answer_present": sge_ai_overview_present,
                        "people_also_ask_count": sge_paa_count,
                        "confirmed_vs_check_needed_present": sge_confirmed_vs_check_present,
                        "source_trust_block_present": geo_source_trust_present,
                        "geo_score_raw": geo_score_raw,
                        "geo_ready": geo_ready,
                        "geo_needs_revision": geo_needs_revision,
                        "geo_hold": geo_hold,
                        # stale source
                        "stale_source_warning": _is_stale,
                        "fresh_source_ok": _fresh_source_ok,
                        "official_source_ok": _official_source_ok,
                        "official_source_required": _is_stale,
                        "fresh_source_replacement_required": _is_stale,
                        "publish_blocked_by_stale_source": _is_stale,
                        # publish_ready (자동 발행 허용 조건 종합)
                        "publish_ready": publish_ready,
                        "human_review_required": article_human_review_required,
                        # Blogspot 라벨 (2~3개)
                        "blogspot_labels": _blogspot_labels,
                        "blogspot_label_count": blogspot_label_count,
                        "blogspot_labels_valid": blogspot_labels_valid,
                        # 본문 해시태그 (0~3개)
                        "content_hashtags": _raw_hashtags,
                        "content_hashtag_count": content_hashtag_count,
                        "content_hashtags_valid": content_hashtags_valid,
                        # FAQ JSON-LD
                        "faq_jsonld_present": faq_jsonld_present,
                        "faq_count": faq_q_count,
                        "faq_jsonld_valid": faq_jsonld_valid,
                        "faq_jsonld_warnings": faq_jsonld_warnings,
                        # JSON-LD 안정성
                        "jsonld_type": jsonld_type,
                        "jsonld_headline_matches_title": jsonld_hl_match,
                        "jsonld_description_matches_meta": jsonld_desc_match,
                        "jsonld_date_present": _date_present,
                        "jsonld_author_present": _author_present,
                        "jsonld_image_present": _image_present,
                        "jsonld_warnings": extended_jld_warnings,
                        # metadata warnings
                        "metadata_warnings": metadata_warnings,
                        # pre_publish_checklist
                        "pre_publish_checklist": pre_publish_checklist,
                        # stale replacement 필드 (교체 발생 시만 non-empty)
                        **{k: v for k, v in (preview_result.get("_replacement_meta") or {}).items()},
                    }
                    self._write_json(run_path / "article_candidate_meta.json", cand_meta)
                    logger.info(
                        "article_candidate saved → %s (grade=%s title_applied=%s near_match=%s)",
                        run_path,
                        grade,
                        title_applied,
                        bool(preview_result.get("near_match")),
                    )
            else:
                # article_candidate 미생성 시 hold report 저장
                try:
                    _pm_r = preview_result.get("pattern_match") or {}
                    _bl_r = list(preview_result.get("blocking_issues") or [])
                    _hold_report: dict[str, Any] = {
                        "article_candidate_generated": False,
                        "publish_attempted": False,
                        "hold_reason": _bl_r or ["_can_generate_candidate=False"],
                        "pattern_id": _pm_r.get("pattern_id") or "",
                        "pattern_confidence": _pm_r.get("confidence", 0),
                        "near_match": bool(preview_result.get("near_match")),
                        "content_type_match": _pm_r.get("content_type_match", False),
                        "topic_group_match": _pm_r.get("topic_group_match", False),
                        "matched": preview_result.get("matched", False),
                        "ready_for_review": preview_result.get("ready_for_review", False),
                        "slot_fill_rate": preview_result.get("slot_fill_rate", 0.0),
                        "content_candidate_grade": str(preview_result.get("_content_candidate_grade") or ""),
                        "warnings": list(preview_result.get("warnings") or []),
                        "title_result_present": bool(preview_result.get("_title_result")),
                        "selected_title": str((
                            (preview_result.get("_title_result") or {}).get("best_title") or {}
                        ).get("title") or ""),
                        "candidate_html_present": bool(str(preview_result.get("_article_candidate_html") or "").strip()),
                    }
                    self._write_json(run_path / "candidate_hold_report.json", _hold_report)
                    logger.info(
                        "candidate_hold_report saved → %s (confidence=%d near_match=%s grade=%s)",
                        run_path,
                        _hold_report["pattern_confidence"],
                        _hold_report["near_match"],
                        _hold_report["content_candidate_grade"],
                    )
                except Exception as _hr_exc:
                    logger.warning("candidate_hold_report save failed: %s", _hr_exc)
        except Exception as exc:
            logger.warning("golden preview artifact save failed: %s", exc)

    def save_title_candidate_artifacts(
        self,
        run_path: Path,
        title_result: dict[str, Any],
    ) -> None:
        """title_candidates.json, selected_title.json을 run_path에 저장한다."""
        try:
            self._write_json(run_path / "title_candidates.json", title_result)
            best = title_result.get("best_title") or {}
            if best:
                self._write_json(run_path / "selected_title.json", best)
            logger.info(
                "title candidate artifacts saved → %s (best=%s ctr=%s)",
                run_path,
                best.get("title", "")[:40],
                best.get("ctr_score", 0),
            )
        except Exception as exc:
            logger.warning("title candidate artifact save failed: %s", exc)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_publish_preview_scorecard(self, run_path: Path, payload: dict[str, Any]) -> None:
        quality_gate = payload.get("publish_quality_gate") if isinstance(payload, dict) else None
        if not isinstance(quality_gate, dict):
            return
        scorecard = quality_gate.get("publish_preview_scorecard")
        if not isinstance(scorecard, dict):
            return
        self._write_json(run_path / "publish_preview_scorecard.json", scorecard)
        (run_path / "publish_preview_scorecard.md").write_text(
            render_publish_preview_scorecard_markdown(scorecard),
            encoding="utf-8",
        )
