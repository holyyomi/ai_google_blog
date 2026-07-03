from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
from blogspot_automation.services.golden_pattern_service import GoldenPatternService
from blogspot_automation.services.news_label_service import NewsLabelService
from blogspot_automation.services.publish_history_service import PublishHistoryService
from blogspot_automation.services.run_artifact_service import RunArtifactService
from blogspot_automation.services.seo_policy import normalize_hashtags, normalize_labels, prepare_blogspot_html
from blogspot_automation.services.title_candidate_service import TitleCandidateService
from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService
from blogspot_automation.services.news_scoring_service import NewsScoringService

logger = logging.getLogger(__name__)

_AI_AXES = {"ai_automation"}
_AI_CONTENT_TYPE = "ai_work_tip"
_AI_TOPIC_GROUP = "ai_work"

# 주제 → (content_type, topic_group) 분류 규칙. 위에서부터 먼저 매칭되는 규칙을 사용한다.
# 더 구체적인 타입(프롬프트/비교/검색/모델/리스크)을 일반 타입보다 앞에 둔다.
_AI_ROUTE_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("프롬프트", "prompt", "지시문", "프롬프트 템플릿", "프롬프트 레시피", "프롬프트 작성", "프롬프트 엔지니어링"),
     "ai_prompt_recipe", "ai_prompt"),
    (("vs", " 대 ", "비교", "차이", "어떤 ai", "무엇이 다를", "뭐가 나아", "요금제 비교", "가격 비교", "어느 것"),
     "ai_comparison", "ai_compare"),
    (("ai 검색", "ai overview", "ai 오버뷰", "sge", "aeo", "생성형 검색", "답변엔진", "제로클릭", "검색 변화", "ai 인용"),
     "ai_search_change", "ai_search"),
    (("모델 업데이트", "ai 업데이트", "새 모델", "신규 모델", "신모델", "모델 출시", "gpt-5", "gpt5", "업그레이드", "버전 공개", "정식 출시"),
     "ai_model_update", "ai_model"),
    (("보안", "개인정보", "저작권", "환각", "hallucination", "리스크", "위험", "유출", "프라이버시", "기밀", "ai 윤리", "ai 규제"),
     "ai_risk_security", "ai_risk"),
    (("블로그", "애드센스", "수익화", "조회수", "rpm", "트래픽", "포스팅 자동화", "수익형"),
     "ai_blog_growth", "ai_blog"),
    (("초보", "입문", "처음", "기초", "왕초보", "시작하는", "첫걸음", "쉬운 ai"),
     "ai_beginner_guide", "ai_beginner"),
    # 도구 '활용법/꿀팁' 주제는 리뷰가 아니라 활용 가이드(프롬프트 포함)로 → tool_review보다 먼저
    (("활용법", "활용 방법", "활용 팁", "고급 활용", "제대로 쓰", "200%", "100% 활용", "꿀팁",
      "자동화하는 법", "자동화 하는 법", "업무에 쓰", "업무 활용"),
     "ai_work_tip", "ai_work"),
    (("리뷰", "후기", "써봤", "사용법", "도구 추천", "툴 추천", "ai 도구", "ai 툴",
      "평가", "쓸 만한", "쓸만한", "따져", "테스트", "체험", "생성 툴", "생성 도구",
      "perplexity", "copilot", "notion ai", "미드저니", "midjourney"),
     "ai_tool_review", "ai_tool"),
)


def _classify_ai_topic(topic: str) -> tuple[str, str]:
    """AI 주제를 content_type/topic_group로 분류한다.

    구체 규칙을 위에서부터 매칭하고, 매칭이 없으면 ai_work_tip/ai_work 기본값을 유지한다.
    """
    haystack = (topic or "").lower()
    for keywords, ct, tg in _AI_ROUTE_RULES:
        if any(kw in haystack for kw in keywords):
            return ct, tg
    return _AI_CONTENT_TYPE, _AI_TOPIC_GROUP

# pattern_id별 16:9 커버 이미지 scene
_AI_IMAGE_SCENES: dict[str, str] = {
    "ai_work_time_savings": (
        "a Korean office worker organizing repeated workflow tasks into a clean digital checklist "
        "on a laptop screen, calm focused mood, modern minimal desk, natural daylight"
    ),
    "ai_tool_comparison": (
        "two laptop screens side by side on a modern desk showing different AI assistant interfaces, "
        "a Korean professional comparing results calmly, clean office setting, natural light"
    ),
    "ai_automation_workflow": (
        "a clean automated workflow diagram with connected process nodes displayed on a monitor, "
        "a Korean office desk with organized documents, calm productive mood, minimal modern style"
    ),
}
_AI_IMAGE_SCENE_DEFAULT = (
    "a Korean office worker using AI productivity tools on a laptop, "
    "calm professional mood, modern minimal desk, natural daylight"
)


def _build_ai_image_prompt(*, pattern_id: str, selected_title: str) -> tuple[str, str]:
    scene = _AI_IMAGE_SCENES.get(pattern_id, _AI_IMAGE_SCENE_DEFAULT)
    prompt = (
        f"Clean realistic editorial blog cover image for a Korean AI productivity blog. "
        f"Topic: {selected_title}. "
        f"Scene: {scene}, 16:9 aspect ratio, "
        f"no text, no readable letters, no logo, no watermark, no UI elements with readable text."
    )
    alt_text = f"{selected_title} 관련 AI 업무 활용 이미지"
    return prompt, alt_text


_AI_TOOL_TOKENS: tuple[str, ...] = (
    "chatgpt", "gpt", "claude", "gemini", "copilot", "perplexity", "midjourney",
    "notion", "n8n", "zapier", "make", "프롬프트", "워크플로", "api",
)


def compute_ai_content_scores(
    *,
    slots: dict[str, Any],
    candidate_html: str,
    content_type: str = "",
    geo_score: int = 0,
) -> dict[str, int]:
    """AI 블로그 주제용 점수 루브릭(0~100)을 후보 신호에서 계산한다.

    뉴스/이슈성 점수 대신 AI 콘텐츠 가치 기준으로 평가한다 (Phase D).
    슬롯/HTML 신호 기반의 결정론적 점수로, 검토·정렬 보조에 사용한다.
    """
    s = slots or {}
    html = candidate_html or ""

    def has(slot: str) -> bool:
        v = s.get(slot)
        if isinstance(v, (list, dict)):
            return bool(v)
        return bool(str(v or "").strip())

    text_blob = " ".join(
        str(v) for v in s.values() if isinstance(v, str)
    ).lower() + " " + html.lower()
    tool_hits = sum(1 for t in _AI_TOOL_TOKENS if t in text_blob)

    faq_n = len(s.get("faq") or []) if isinstance(s.get("faq"), list) else 0

    scores = {
        # 검색 의도 명확도 — hook + intent answer 블록
        "search_intent_clarity": 80 + (10 if has("hook_opening") else 0)
        + (10 if 'id="INTENT_ANSWER_BLOCK"' in html else 0),
        # 실무 적용 가능성 — 따라하는 순서 + 행동 + 프롬프트
        "practical_applicability": 60 + (15 if has("real_criterion") else 0)
        + (10 if has("actions") else 0) + (15 if has("prompt_block") else 0),
        # 저장 가치 — 프롬프트/체크리스트 같이 다시 꺼내 쓰는 자산
        "save_worthiness": 60 + (20 if has("prompt_block") else 0)
        + (20 if has("checklist") else 0),
        # 도구/모델 구체성 — 실제 도구명 언급 수
        "tool_specificity": min(100, 55 + tool_hits * 9),
        # 비교/선택 가치 — 비교/판단 표
        "comparison_value": 60 + (25 if has("quick_decision_table") else 0)
        + (15 if has("misconceptions") else 0),
        # 초보자 이해도 — 오해표 + FAQ
        "beginner_clarity": 60 + (20 if has("misconceptions") else 0)
        + min(20, faq_n * 7),
        # 수익화/광고 가치 — 도구 비교/리뷰 성격일수록 높음
        "monetization_value": min(
            100,
            65 + tool_hits * 5 + (10 if has("quick_decision_table") else 0),
        ),
        # 업데이트 신선도 — 갱신일 블록
        "freshness": 75 + (15 if 'id="UPDATED_DATE_BLOCK"' in html else 0)
        + (10 if content_type == "ai_model_update" else 0),
        # 보안/리스크 필요성 충족 — 위험 알림
        "risk_coverage": 60 + (40 if has("risk_note") else 0),
        # AI 답변엔진 인용 가능성 — citation/overview + geo_score 반영
        "ai_citation_likelihood": min(
            100,
            (10 if 'id="AI_CITATION_SUMMARY"' in html else 0)
            + (10 if 'id="AI_OVERVIEW_TARGET_ANSWER"' in html else 0)
            + int(geo_score or 0) * 0.8,
        ),
    }
    result = {k: int(min(100, max(0, v))) for k, v in scores.items()}
    result["ai_content_score_avg"] = int(sum(result.values()) / len(result))
    return result


class AiTopicPipeline:
    """AI 관련 주제 Blogspot article_candidate 생성 파이프라인.

    1순위: 네이버 블로그 AI 관련 포스트 → Blogspot 재구성
    Fallback: evergreen_topic_service (Naver 포스트 없을 때)

    auto_publish=True + 품질 조건 통과 시 실제 Blogger API 발행.
    """

    def __init__(
        self,
        *,
        artifact_service: RunArtifactService | None = None,
        publish_history_service: PublishHistoryService | None = None,
        dry_run: bool = True,
        auto_publish: bool = False,
        disable_image_generation: bool = True,
        disable_image_upload: bool = True,
        # 테스트용: 외부 소스 호출 없이 주제 강제 지정
        _force_topic: str = "",
        _force_naver_post: Any | None = None,
    ) -> None:
        self.artifact_service = artifact_service or RunArtifactService()
        self.publish_history_service = publish_history_service or PublishHistoryService()
        self.golden_preview_service = GoldenArticlePreviewService()
        self.title_candidate_service = TitleCandidateService()
        self.label_service = NewsLabelService()
        self.scoring_service = NewsScoringService()
        self.evergreen_topic_service = EvergreenTopicService()
        self._ps = GoldenPatternService()
        self.dry_run = dry_run
        self.auto_publish = auto_publish
        self.disable_image_generation = disable_image_generation
        self.disable_image_upload = disable_image_upload
        self._force_topic = _force_topic
        # Deprecated compatibility only. It is treated as a forced topic and is
        # never fetched from, linked to, or marked as a Naver rewrite.
        self._force_naver_post = _force_naver_post

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def run_once(self) -> dict[str, Any]:
        try:
            source_meta, topic, ct, tg = self._resolve_source()
            if not topic:
                return {"status": "skipped", "reason": "no_source_topic"}

            summary = self._build_summary(source_meta)
            raw_candidate = self._build_candidate_raw(source_meta, ct, tg)

            preview, pm_result, pattern_id = self._build_golden_preview(
                topic=topic, ct=ct, tg=tg,
                summary=summary, raw_candidate=raw_candidate,
            )
            if not preview:
                return {"status": "skipped", "reason": "no_golden_matched_ai_candidate",
                        "source_type": source_meta.get("source_type", "unknown")}

            title_result, selected_title, selected_title_ctr = self._build_title(
                topic=topic, ct=ct, tg=tg, pattern_id=pattern_id,
                raw_candidate=raw_candidate,
            )

            # LLM 주제 특화 본문 보강 (실패 시 템플릿 그대로 — 발행 안전)
            self._enrich_preview_slots(
                preview=preview, topic=topic, content_type=ct, selected_title=selected_title,
            )
            # LLM이 더 자연스러운 제목을 만들었으면 채택
            _llm_title = ((preview.get("slot_result") or {}).get("slots") or {}).get("_llm_title")
            if _llm_title:
                logger.info("AiTopicPipeline: LLM 제목 채택 — %s", _llm_title)
                selected_title = _llm_title

            cover_image_url = self._resolve_cover_image_url(
                title=selected_title, topic=topic, content_type=ct, topic_group=tg,
            )

            internal_link_pairs = self._build_internal_link_pairs(
                title=selected_title, topic=topic, content_type=ct,
            )

            _can_gen, candidate_html = self._render_candidate(
                preview=preview, selected_title=selected_title,
                cover_image_url=cover_image_url,
                internal_link_pairs=internal_link_pairs,
            )

            blogspot_labels, hashtags = self._build_labels(
                pattern_id=pattern_id, ct=ct, tg=tg,
                topic=topic, selected_title=selected_title,
            )

            preview = self._attach_preview_fields(
                preview=preview,
                title_result=title_result,
                selected_title=selected_title,
                candidate_html=candidate_html,
                can_gen=_can_gen,
                blogspot_labels=blogspot_labels,
                hashtags=hashtags,
                ct=ct, tg=tg,
            )

            image_prompt, image_alt_text = _build_ai_image_prompt(
                pattern_id=pattern_id, selected_title=selected_title
            )

            run_path = self._make_run_path()
            self._save_artifacts(
                run_path=run_path,
                preview=preview,
                title_result=title_result,
                topic=topic,
                pattern_id=pattern_id,
                ct=ct, tg=tg,
                source_meta=source_meta,
                selected_title=selected_title,
                selected_title_ctr=selected_title_ctr,
                pm_result=pm_result,
                raw_candidate=raw_candidate,
                blogspot_labels=blogspot_labels,
                hashtags=hashtags,
                image_prompt=image_prompt,
                image_alt_text=image_alt_text,
                can_gen=_can_gen,
            )

            _cand_meta = self._load_cand_meta(run_path)
            _geo_ready  = bool(_cand_meta.get("geo_ready"))
            _pub_ready  = bool(_cand_meta.get("publish_ready"))
            _meta_valid = bool(_cand_meta.get("candidate_meta_description_valid"))
            _cit_valid  = bool(_cand_meta.get("geo_ai_citation_summary_valid"))

            # soft 품질 게이트: hard_block만 발행 중지, soft_warning은 로그/기록만
            from blogspot_automation.services.ai_quality_gate import evaluate_ai_publish_quality
            _quality = evaluate_ai_publish_quality(candidate_html, content_type=ct)
            if _quality["soft_warnings"]:
                logger.info("AiTopicPipeline: quality soft_warnings=%s", _quality["soft_warnings"])
            if _quality["hard_blocks"]:
                logger.warning("AiTopicPipeline: quality hard_blocks=%s", _quality["hard_blocks"])

            # 실제 발행 시도 (auto_publish + 품질 조건)
            publish_attempted = False
            publish_succeeded = False
            blogger_url = ""
            skip_reason = ""

            _evergreen_allowed = (
                os.getenv("ALLOW_EVERGREEN_AUTO_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"}
                or os.getenv("FORCE_EVERGREEN_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}
            )
            if self.dry_run:
                skip_reason = "dry_run=true"
            elif not self.auto_publish:
                skip_reason = "auto_publish=false"
            elif (
                str(source_meta.get("source_type") or "") == "evergreen_fallback"
                and not _evergreen_allowed
            ):
                # 범용 evergreen 글 자동발행 금지 (2026-07-02) — 최신 AI 이슈 강제
                skip_reason = "evergreen_auto_publish_disabled"
            elif not _can_gen:
                skip_reason = "article_candidate_generated=false"
            elif not _geo_ready:
                skip_reason = "geo_ready=false"
            elif not _meta_valid:
                skip_reason = "candidate_meta_description_valid=false"
            elif not _cit_valid:
                skip_reason = "geo_ai_citation_summary_valid=false"
            elif not _quality["passed"]:
                skip_reason = "quality_hard_block:" + ",".join(_quality["hard_blocks"])
            else:
                publish_attempted = True
                _slots_for_footer = (preview.get("slot_result") or {}).get("slots") or {}
                blogger_url, publish_succeeded = self._attempt_blogger_publish(
                    title=selected_title,
                    candidate_html=candidate_html,
                    labels=blogspot_labels,
                    cand_meta=_cand_meta,
                    run_path=run_path,
                    content_type=ct,
                    internal_links=_slots_for_footer.get("internal_links") or [],
                    hashtags=_slots_for_footer.get("hashtags") or hashtags,
                    internal_link_pairs=internal_link_pairs,
                )

            if self.dry_run:
                status = "dry_run_saved"
            elif publish_attempted and publish_succeeded:
                status = "published"
            elif publish_attempted and not publish_succeeded:
                status = "publish_failed"
            else:
                status = "held_for_review"

            logger.info("AiTopicPipeline: done → %s (status=%s)", run_path, status)

            return {
                "status": status,
                "artifact_dir": str(run_path),
                "selected_topic": topic,
                "selected_title": selected_title,
                "golden_pattern_id": pattern_id,
                "golden_pattern_confidence": int(pm_result.get("confidence", 0)),
                "article_candidate_generated": _can_gen,
                "geo_score": _cand_meta.get("geo_score", 0),
                "geo_ready": _geo_ready,
                "publish_ready": _pub_ready,
                "publish_allowed_in_phase2": False,
                "human_review_required": True,
                "source_type": source_meta.get("source_type", "unknown"),
                "source_url": source_meta.get("source_url", ""),
                "source_title": source_meta.get("source_title", ""),
                "already_rewritten": False,
                "blogspot_labels": blogspot_labels,
                "publish_attempted": publish_attempted,
                "publish_succeeded": publish_succeeded,
                "blogger_url": blogger_url,
                "skip_reason": skip_reason,
            }

        except Exception as exc:
            logger.error("AiTopicPipeline failed: %s", exc)
            return {"status": "failed", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _resolve_source(
        self,
    ) -> tuple[dict[str, Any], str, str, str]:
        """소스(fresh AI/news topic or evergreen)와 topic/ct/tg를 결정한다."""
        # 테스트용 강제 지정
        if self._force_naver_post:
            forced_title = str(getattr(self._force_naver_post, "title", "") or "").strip()
            meta = {
                "source_type": "forced_topic",
                "source_url": "",
                "source_title": forced_title,
                "source_summary": "",
                "source_published_at": "",
                "already_rewritten": False,
            }
            _ct, _tg = _classify_ai_topic(forced_title)
            return meta, forced_title, _ct, _tg
        if self._force_topic:
            meta = {
                "source_type": "forced_topic",
                "source_url": "",
                "source_title": self._force_topic,
                "source_summary": "",
                "source_published_at": "",
                "already_rewritten": False,
            }
            _ct, _tg = _classify_ai_topic(self._force_topic)
            return meta, self._force_topic, _ct, _tg

        # 1순위: Fresh AI/news discovery
        # Fallback: evergreen_topic_service
        logger.info("AiTopicPipeline: fresh AI/news source unavailable; evergreen fallback 사용")
        fallback_topic, fallback_ct, fallback_tg = self._evergreen_fallback()
        if not fallback_topic:
            return {}, "", "", ""

        meta = {
            "source_type": "evergreen_fallback",
            "source_url": "",
            "source_title": fallback_topic,
            "source_summary": "",
            "source_published_at": "",
            "already_rewritten": False,
        }
        return meta, fallback_topic, fallback_ct, fallback_tg

    def _evergreen_fallback(self) -> tuple[str, str, str]:
        candidates = self.evergreen_topic_service.collect_candidates()
        ai_candidates = [
            c for c in candidates
            if (c.raw or {}).get("evergreen_axis") in _AI_AXES
        ]
        if not ai_candidates:
            return "", "", ""
        scored = self.scoring_service.score_candidates(ai_candidates)
        for item in scored:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            r = self._ps.match_pattern(
                topic=item.candidate.topic or "", content_type=ct, topic_group=tg
            )
            if r["matched"] or r.get("near_match"):
                return item.candidate.topic or "", ct, tg
        return "", "", ""

    @staticmethod
    def _build_summary(source_meta: dict) -> str:
        return source_meta.get("source_summary", "")

    @staticmethod
    def _build_candidate_raw(
        source_meta: dict,
        ct: str,
        tg: str,
    ) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "content_angle": {"content_type": ct, "topic_group": tg},
            "topic_group": tg,
            "source_type": source_meta.get("source_type", "unknown"),
            "source_url": source_meta.get("source_url", ""),
            "source_title": source_meta.get("source_title", ""),
            "source_summary": source_meta.get("source_summary", ""),
            "source_published_at": source_meta.get("source_published_at", ""),
            "already_rewritten": False,
        }
        return raw

    def _build_golden_preview(
        self,
        *,
        topic: str,
        ct: str,
        tg: str,
        summary: str,
        raw_candidate: dict,
    ) -> tuple[dict | None, dict, str]:
        """golden preview 빌드 + 패턴 매칭 결과 반환.

        키워드 매칭이 실패해도, 분류기(_classify_ai_topic)가 정한 content_type이
        패턴과 1:1 매핑되면 그 패턴으로 강제 빌드한다 (도구명 등으로 매칭이 약한 AI
        주제가 발행에서 탈락하지 않도록).
        """
        pm_result = self._ps.match_pattern(
            topic=topic, content_type=ct, topic_group=tg
        )
        forced_pattern_id = ""
        if not (pm_result.get("matched") or pm_result.get("near_match")):
            # 분류기 content_type/topic_group으로 패턴 추천 → 강제 폴백
            forced_pattern_id = self._ps.suggest_pattern_id_by_hint(
                topic, content_type=ct, topic_group=tg
            ) or ""
            if not forced_pattern_id:
                logger.warning("AiTopicPipeline: 패턴 매칭 실패 — topic=%s", topic[:40])
                return None, pm_result, ""
            logger.info("AiTopicPipeline: 키워드 매칭 약함 → 분류 패턴 강제 적용 (%s)", forced_pattern_id)

        preview = self.golden_preview_service.build_preview(
            topic=topic,
            content_type=ct,
            topic_group=tg,
            summary=summary,
            candidate_raw=raw_candidate,
            forced_pattern_id=forced_pattern_id,
        )
        if forced_pattern_id:
            pm_result = preview.get("pattern_match") or pm_result
        pattern_id = str(pm_result.get("pattern_id") or forced_pattern_id)
        preview["_editorial_scores"] = {
            "traffic_potential_score": 24,
            "usefulness_score": 30,
            "evergreen_asset_score": 8,
            "viral_safety_score": 10,
            "final_editorial_score": 72,
        }
        preview["_content_candidate_grade"] = "B"
        return preview, pm_result, pattern_id

    def _build_title(
        self, *, topic: str, ct: str, tg: str, pattern_id: str, raw_candidate: dict
    ) -> tuple[dict, str, int]:
        tr = self.title_candidate_service.generate_candidates(
            topic=topic, content_type=ct, topic_group=tg,
            pattern_id=pattern_id, candidate_raw=raw_candidate,
        )
        best = tr.get("best_title") or {}
        selected_title = best.get("title", topic)
        ctr = int(best.get("ctr_score") or 0)
        return tr, selected_title, ctr

    def _render_candidate(
        self, *, preview: dict, selected_title: str, cover_image_url: str = "",
        internal_link_pairs: list | None = None,
    ) -> tuple[bool, str]:
        pm = preview.get("pattern_match") or {}
        sr = preview.get("slot_result") or {}
        _can_gen = bool(preview.get("matched") or preview.get("near_match"))
        candidate_html = ""
        if _can_gen and pm:
            try:
                candidate_html = self.golden_preview_service.render_article_candidate_html(
                    pm, sr, selected_title=selected_title,
                    cover_image_url=cover_image_url,
                    internal_link_pairs=internal_link_pairs,
                )
            except Exception as e:
                logger.warning("render_article_candidate_html failed: %s", e)
                _can_gen = False
        return _can_gen, candidate_html

    def _enrich_preview_slots(
        self, *, preview: dict, topic: str, content_type: str, selected_title: str
    ) -> None:
        """preview의 slot_result.slots를 LLM 주제 특화 본문으로 교체(제자리 수정).

        실패/비활성 시 원본 유지 — 발행은 항상 진행 가능.
        """
        try:
            sr = preview.get("slot_result") or {}
            slots = sr.get("slots") or {}
            if not slots:
                return
            from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
            enriched = enrich_slots_with_llm(
                slots=slots, topic=topic, content_type=content_type,
                selected_title=selected_title,
            )
            sr["slots"] = enriched
            preview["slot_result"] = sr
        except Exception as exc:
            logger.warning("AiTopicPipeline: slot enrich 실패(템플릿 폴백): %s", exc)

    def _build_internal_link_pairs(
        self, *, title: str, topic: str, content_type: str
    ) -> list[tuple[str, str]]:
        """발행 이력에서 실제 발행된 Blogspot 글 (제목, URL) 내부링크를 만든다.

        이력이 없으면 빈 목록 → 렌더러가 카테고리 라벨 링크로 폴백한다.
        """
        try:
            from blogspot_automation.services.seo_policy import build_internal_links_from_history
            records = self.publish_history_service.recent_records(limit=120, published_only=True)
            pairs = build_internal_links_from_history(
                records,
                current_title=title,
                current_topic=topic,
                current_content_type=content_type,
                limit=3,
            )
            return list(pairs)
        except Exception as exc:
            logger.warning("internal link 생성 실패(비치명): %s", exc)
            return []

    def _resolve_cover_image_url(
        self, *, title: str, topic: str, content_type: str, topic_group: str
    ) -> str:
        """이미지 생성/업로드가 활성화된 경우 CoverImageService로 ImgBB 영구 URL을 만든다.

        생성/업로드 비활성이거나 키가 없으면 ""(비치명) — 렌더러가 CSS 히어로로 폴백.
        """
        if self.disable_image_generation or self.disable_image_upload:
            return ""
        try:
            from blogspot_automation.services.cover_image_service import CoverImageService
            svc = CoverImageService()
            if not svc.enabled():
                logger.info("CoverImageService disabled (키 누락) → 이미지 없이 진행")
                return ""
            url = svc.build_cover_image_url(title=title or topic, topic=topic)
            if url:
                logger.info("AiTopicPipeline: cover image ready → %s", url)
            return url or ""
        except Exception as exc:
            logger.warning("cover image 생성 실패(비치명): %s", exc)
            return ""

    def _build_labels(
        self, *, pattern_id: str, ct: str, tg: str, topic: str, selected_title: str
    ) -> tuple[list, list]:
        labels = self.label_service.build_blogspot_labels(
            pattern_id=pattern_id, content_type=ct, topic_group=tg
        )
        hashtags = self.label_service.build_hashtags(
            selected_topic=topic, selected_title=selected_title,
            topic_group=tg, content_type=ct,
        )
        return normalize_labels(labels), normalize_hashtags(hashtags)

    @staticmethod
    def _attach_preview_fields(
        *,
        preview: dict,
        title_result: dict,
        selected_title: str,
        candidate_html: str,
        can_gen: bool,
        blogspot_labels: list,
        hashtags: list,
        ct: str,
        tg: str,
    ) -> dict:
        preview["_can_generate_candidate"] = can_gen
        preview["_article_candidate_html"] = candidate_html
        preview["_title_result"] = title_result
        preview["_selected_title"] = selected_title
        preview["_stale_candidate"] = False
        preview["_scoring_stale_penalty"] = False
        preview["_blogspot_labels"] = blogspot_labels
        preview["_hashtags"] = hashtags
        preview["_content_type"] = ct
        preview["_topic_group"] = tg
        return preview

    def _make_run_path(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        runs_dir = Path(getattr(self.artifact_service, "runs_dir", "runs"))
        run_path = runs_dir / f"news_{ts}"
        run_path.mkdir(parents=True, exist_ok=True)
        return run_path

    def _save_artifacts(
        self,
        *,
        run_path: Path,
        preview: dict,
        title_result: dict,
        topic: str,
        pattern_id: str,
        ct: str,
        tg: str,
        source_meta: dict,
        selected_title: str,
        selected_title_ctr: int,
        pm_result: dict,
        raw_candidate: dict,
        blogspot_labels: list,
        hashtags: list,
        image_prompt: str,
        image_alt_text: str,
        can_gen: bool,
    ) -> None:
        editorial_scores = preview.get("_editorial_scores") or {}

        # selected_topic.json (source 메타 포함)
        RunArtifactService._write_json(run_path / "selected_topic.json", {
            "topic": topic,
            "pattern_id": pattern_id,
            "content_type": ct,
            "topic_group": tg,
            "source": "ai_pipeline",
            **source_meta,
        })

        # golden preview artifacts
        self.artifact_service.save_golden_preview_artifacts(run_path, preview)

        # title candidate artifacts
        if title_result:
            self.artifact_service.save_title_candidate_artifacts(run_path, title_result)

        # article_candidate_meta에서 GEO 정보 읽기
        _cand_meta = self._load_cand_meta(run_path)
        _geo_score    = int(_cand_meta.get("geo_score") or 0)
        _geo_ready    = bool(_cand_meta.get("geo_ready"))
        _publish_ready = bool(_cand_meta.get("publish_ready"))

        status = "dry_run_saved" if self.dry_run else "held_for_review"
        _phase_hold = os.getenv("PUBLISH_HOLD_PHASE2", "true").strip().lower() in {"1", "true", "yes"}

        # run_meta.json
        run_meta: dict[str, Any] = {
            "pipeline": "ai_pipeline",
            "mode": "dry_run" if self.dry_run else "publish",
            "dry_run": self.dry_run,
            "status": status,
            "selected_topic": topic,
            "selected_topic_group": tg,
            "selected_content_angle": {"content_type": ct, "topic_group": tg},
            "golden_preview_generated": bool(preview),
            "golden_preview_ready_for_review": bool(preview.get("ready_for_review")),
            "golden_pattern_id": pattern_id,
            "golden_pattern_confidence": int(pm_result.get("confidence", 0)),
            "golden_slot_fill_rate": float(preview.get("slot_fill_rate", 0.0)),
            "golden_blocking_issues": list(preview.get("blocking_issues") or []),
            "golden_warnings": list(preview.get("warnings") or []),
            "article_candidate_generated": can_gen,
            "selected_title": selected_title,
            "selected_title_ctr_score": selected_title_ctr,
            "geo_score": _geo_score,
            "geo_ready": _geo_ready,
            "publish_ready": _publish_ready,
            "publish_allowed_in_phase2": False,
            "human_review_required": True,
            "blogspot_labels": blogspot_labels,
            "content_hashtags": hashtags,
            "image_prompt": image_prompt,
            "image_alt_text": image_alt_text,
            "content_candidate_grade": "B",
            "final_editorial_score": editorial_scores.get("final_editorial_score", 72),
            "traffic_potential_score": editorial_scores.get("traffic_potential_score", 24),
            "usefulness_score": editorial_scores.get("usefulness_score", 30),
            "phase_hold": _phase_hold,
            "auto_publish": self.auto_publish,
            "disable_image_generation": self.disable_image_generation,
            "disable_image_upload": self.disable_image_upload,
            "run_at": datetime.now().isoformat(),
            # 소스 메타
            **{f"source_{k}": v for k, v in {
                "type": source_meta.get("source_type", "unknown"),
                "url": source_meta.get("source_url", ""),
                "title": source_meta.get("source_title", ""),
                "summary": source_meta.get("source_summary", ""),
                "published_at": source_meta.get("source_published_at", ""),
            }.items()},
        }
        RunArtifactService._write_json(run_path / "run_meta.json", run_meta)

        # scoring.json
        scoring: dict[str, Any] = {
            "pipeline": "ai_pipeline",
            "topic": topic,
            "source_type": source_meta.get("source_type", "unknown"),
            "source_title": source_meta.get("source_title", ""),
            "golden_pattern_id": pattern_id,
            "pattern_confidence": int(pm_result.get("confidence", 0)),
            "content_candidate_grade": "B",
            "final_editorial_score": editorial_scores.get("final_editorial_score", 72),
            "traffic_potential_score": editorial_scores.get("traffic_potential_score", 24),
            "usefulness_score": editorial_scores.get("usefulness_score", 30),
            "evergreen_asset_score": editorial_scores.get("evergreen_asset_score", 8),
            "viral_safety_score": editorial_scores.get("viral_safety_score", 10),
            "ai_topic_score": int(raw_candidate.get("topic_engine_score") or 75),
            "search_intent_score": int(raw_candidate.get("topic_search_intent_score") or 15),
            "monetization_score": int(raw_candidate.get("topic_monetization_score") or 12),
            "safety_score": int(raw_candidate.get("topic_safety_score") or 15),
            "slot_fill_rate": float(preview.get("slot_fill_rate", 0.0)),
            "geo_score": _geo_score,
            "geo_ready": _geo_ready,
            "publish_ready": _publish_ready,
            "publish_allowed_in_phase2": False,
            "human_review_required": True,
            "selected_title": selected_title,
            "selected_title_ctr_score": selected_title_ctr,
            "stale_penalty_applied": False,
            "ai_content_scores": compute_ai_content_scores(
                slots=(preview.get("slot_result") or {}).get("slots") or {},
                candidate_html=str(preview.get("_article_candidate_html") or ""),
                content_type=ct,
                geo_score=_geo_score,
            ),
            "blocking_issues": list(preview.get("blocking_issues") or []),
            "reason": (
                f"source={source_meta.get('source_type','unknown')} "
                f"golden_matched={bool(pm_result.get('matched'))} "
                f"pattern={pattern_id} "
                f"conf={pm_result.get('confidence', 0)} "
                f"slot_fill={preview.get('slot_fill_rate', 0):.2f} "
                f"geo={_geo_score}"
            ),
        }
        RunArtifactService._write_json(run_path / "scoring.json", scoring)

        # image_prompt.txt
        if image_prompt.strip():
            (run_path / "image_prompt.txt").write_text(image_prompt.strip(), encoding="utf-8")

        # publish_history 기록
        self._record_history(
            topic=topic,
            selected_title=selected_title,
            pattern_id=pattern_id,
            ct=ct, tg=tg,
            source_meta=source_meta,
            can_gen=can_gen,
            geo_score=_geo_score,
            publish_ready=_publish_ready,
            status=status,
            run_path=run_path,
            raw_candidate=raw_candidate,
        )

    def _record_history(
        self, *, topic: str, selected_title: str, pattern_id: str,
        ct: str, tg: str, source_meta: dict, can_gen: bool,
        geo_score: int, publish_ready: bool, status: str,
        run_path: Path, raw_candidate: dict,
    ) -> None:
        record: dict[str, Any] = {
            "pipeline": "ai_pipeline",
            "run_at": datetime.now().isoformat(),
            "date": datetime.now().date().isoformat(),
            "topic": topic,
            "selected_title": selected_title,
            "golden_pattern_id": pattern_id,
            "content_type": ct,
            "topic_group": tg,
            "evergreen_axis": str(raw_candidate.get("evergreen_axis") or "ai_automation"),
            "source_type": source_meta.get("source_type", "unknown"),
            "source_url": source_meta.get("source_url", ""),
            "source_title": source_meta.get("source_title", ""),
            "status": status,
            "publish_ready": publish_ready,
            "article_candidate_generated": can_gen,
            "geo_score": geo_score,
            "artifact_dir": str(run_path),
        }
        try:
            self.publish_history_service.append_record(record)
            logger.info("AiTopicPipeline: publish_history recorded (source=%s)", record["source_type"])
        except Exception as _he:
            logger.warning("AiTopicPipeline: publish_history record failed: %s", _he)

    def _attempt_blogger_publish(
        self,
        *,
        title: str,
        candidate_html: str,
        labels: list,
        cand_meta: dict,
        run_path: Path,
        content_type: str = "",
        internal_links: list | None = None,
        hashtags: list | None = None,
        internal_link_pairs: list | None = None,
    ) -> tuple[str, bool]:
        """Blogger API에 발행 시도. (url, succeeded) 반환."""
        import json as _json
        try:
            from blogspot_automation.config import Settings
            from blogspot_automation.publishing.client import BloggerClient
            from blogspot_automation.services.golden_article_preview_service import append_ai_footer_html

            settings = Settings.from_env()
            client = BloggerClient(settings)
            meta_description = str(cand_meta.get("candidate_meta_description") or title[:120])
            # prepare가 internal-links/hashtag를 strip하므로 그 뒤에 다시 붙인다.
            _publish_html = prepare_blogspot_html(candidate_html, strip_document=True)
            _publish_html = append_ai_footer_html(
                _publish_html,
                internal_links=internal_links or [],
                hashtags=hashtags or [],
                content_type=content_type,
                internal_link_pairs=internal_link_pairs or [],
            )
            # 독자 우선 레이아웃: GEO/SEO 블록을 본문 뒤로 재배치 (블록 존재는 유지)
            from blogspot_automation.services.reader_first_layout_service import reorder_for_reader_first
            _publish_html = reorder_for_reader_first(_publish_html)
            result = client.publish_post(
                title=title,
                article_html=_publish_html,
                labels=normalize_labels(labels or []),
                meta_description=meta_description,
                is_draft=False,
            )
            blogger_url = str(result.get("url") or "")
            logger.info("AiTopicPipeline: Blogger publish succeeded → %s", blogger_url)

            # 색인 즉시 요청 (Bing·Naver IndexNow) — 신규 글 색인 가속, 비치명
            if blogger_url:
                try:
                    from blogspot_automation.services.indexnow_client import submit_urls
                    _idx = submit_urls([blogger_url])
                    logger.info("AiTopicPipeline: indexnow ping → %s", _idx.get("status"))
                except Exception as _ie:
                    logger.warning("AiTopicPipeline: indexnow ping 실패(비치명): %s", _ie)

            # run_meta 업데이트
            run_meta_path = run_path / "run_meta.json"
            if run_meta_path.exists():
                try:
                    rm = _json.loads(run_meta_path.read_text(encoding="utf-8"))
                    rm["publish_attempted"] = True
                    rm["publish_succeeded"] = True
                    rm["blogger_url"] = blogger_url
                    rm["blogger_post_id"] = str(result.get("id") or "")
                    rm["status"] = "published"
                    RunArtifactService._write_json(run_meta_path, rm)
                except Exception:
                    pass

            return blogger_url, True

        except Exception as exc:
            logger.error("AiTopicPipeline: Blogger publish failed: %s", exc)

            run_meta_path = run_path / "run_meta.json"
            if run_meta_path.exists():
                try:
                    import json as _j
                    rm = _j.loads(run_meta_path.read_text(encoding="utf-8"))
                    rm["publish_attempted"] = True
                    rm["publish_succeeded"] = False
                    rm["publish_error"] = str(exc)
                    rm["status"] = "publish_failed"
                    RunArtifactService._write_json(run_meta_path, rm)
                except Exception:
                    pass

            return "", False

    @staticmethod
    def _load_cand_meta(run_path: Path) -> dict[str, Any]:
        import json as _json
        p = run_path / "article_candidate_meta.json"
        if p.exists():
            try:
                return _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

