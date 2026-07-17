from __future__ import annotations

import logging
from html import escape
import os
import re
from typing import Any

from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.golden_pattern_service import GoldenPatternService
from blogspot_automation.services.official_sources import (
    get_official_sources_for_pattern,
    render_official_sources_html,
)
from blogspot_automation.services.seo_policy import (
    BLOGSPOT_HOME_URL,
    append_hashtags_block,
    append_internal_links_block,
    prepare_blogspot_html,
)
from blogspot_automation.services.slot_filler_service import SlotFillerService

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 80
_MIN_FILL_RATE = 0.8

_HOWTO_ELIGIBLE_PATTERNS: frozenset[str] = frozenset(
    {
        "tax_refund_hometax_check",
        "policy_deadline_support",
        "ai_work_time_savings",
        "ai_tool_comparison",
        "ai_automation_workflow",
        "ai_prompt_recipe",
        "ai_tool_review",
        "delivery_money_checklist",
    }
)

# AI 블로그 전용 content_type 집합 (Phase A~B). 이 집합이거나 pattern_id가 "ai_"로
# 시작하면 뉴스 이슈형 대신 AI 가이드형 섹션 라벨/프레이밍을 사용한다.
_AI_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "ai_work_tip",
        "ai_tool_review",
        "ai_workflow_guide",
        "ai_prompt_recipe",
        "ai_model_update",
        "ai_search_change",
        "ai_blog_growth",
        "ai_comparison",
        "ai_risk_security",
        "ai_beginner_guide",
    }
)


def _is_ai_family(pattern_id: str = "", content_type: str = "") -> bool:
    """AI 블로그 패밀리 여부 판별. CSS 클래스/섹션 ID는 동일하게 유지하되,
    사람이 보는 섹션 제목·프레이밍만 AI 가이드형으로 바꾸기 위한 분기."""
    return str(pattern_id or "").startswith("ai_") or str(content_type or "") in _AI_CONTENT_TYPES


# AI 글마다 매번 같지 않게 색감을 바꾸기 위한 테마 (article 클래스로 적용).
# 뉴스 글에는 테마 클래스가 붙지 않으므로 영향 없음.
_AI_THEMES: tuple[str, ...] = (
    "theme-teal", "theme-violet", "theme-blue", "theme-emerald",
    "theme-rose", "theme-indigo", "theme-sky", "theme-amber",
)


def _pick_ai_theme(topic: str, pattern_id: str = "") -> str:
    """주제 문자열 해시로 테마를 결정 — 같은 주제는 항상 같은 색, 주제별로는 다양."""
    import hashlib as _hl
    seed = f"{topic}|{pattern_id}".encode("utf-8", errors="ignore")
    idx = int(_hl.sha1(seed).hexdigest(), 16) % len(_AI_THEMES)
    return _AI_THEMES[idx]


# content_type → 블로그스팟 라벨(내부링크 검색 페이지용 한국어 라벨)
_AI_LABEL_FOR_CT: dict[str, str] = {
    "ai_work_tip": "AI활용",
    "ai_prompt_recipe": "프롬프트",
    "ai_tool_review": "AI도구",
    "ai_model_update": "AI모델",
    "ai_search_change": "AI검색",
    "ai_blog_growth": "AI블로그",
    "ai_comparison": "AI비교",
    "ai_risk_security": "AI보안",
    "ai_beginner_guide": "AI입문",
}


# content_type → 본문 상단 히어로 배너용 (카테고리 라벨, 이모지)
_AI_HERO_META: dict[str, tuple[str, str]] = {
    "ai_work_tip": ("AI 업무 활용", "⚡"),
    "ai_prompt_recipe": ("프롬프트 레시피", "📝"),
    "ai_tool_review": ("AI 도구 리뷰", "🧩"),
    "ai_model_update": ("AI 모델 업데이트", "🚀"),
    "ai_search_change": ("AI 검색 변화", "🔎"),
    "ai_blog_growth": ("AI 블로그 성장", "📈"),
    "ai_comparison": ("AI 비교 분석", "⚖️"),
    "ai_risk_security": ("AI 리스크·보안", "🛡️"),
    "ai_beginner_guide": ("AI 입문 가이드", "🎓"),
}


# 섹션 라벨: (slot_key) -> {"ai": ..., "news": ...}
# 클래스명은 바꾸지 않으므로 게이트(geo_score)에 영향 없음 — 표시 텍스트만 분기.
def _section_label(slot_key: str, ai: bool) -> str:
    _LABELS: dict[str, tuple[str, str]] = {
        # slot_key: (ai_label, news_label)
        "yomi_judgment": ("결론부터 말하면", "핵심 관점"),
        "real_criterion": ("📋 따라 하는 순서", "공식 기준 / 단계별 확인"),
        "actions": ("✅ 지금 바로 해보기", "바로 할 행동"),
    }
    pair = _LABELS.get(slot_key)
    if not pair:
        return ""
    return pair[0] if ai else pair[1]

_BANNED_DEFAULT_PHRASES: tuple[str, ...] = (
    "이 이슈는 나와 직접 관련이 없다",
    "정보가 너무 많음",
    "오늘 내 선택 기준이 됩니다",
    "나와 관련 있는지",
    "공식 안내를 확인한다",
    "공식 확인처를 확인한다",
    "행동 필요한지 모름",
    "내 생활과 관련있는지 모름",
    "지금 행동이 필요한지 모름",
    "비용·시간·선택 조건 중 직접 바뀌는 항목을 먼저 봐야 합니다",
)

_PREVIEW_CSS = """
  body { font-family: 'Noto Sans KR', sans-serif; background: #f8f9fa; margin: 0; padding: 16px; }
  .golden-preview { max-width: 780px; margin: 0 auto; background: #fff; border-radius: 10px; padding: 32px; }
  h1 { font-size: 1.5rem; border-bottom: 3px solid #2563eb; padding-bottom: 8px; margin-bottom: 24px; }
  .section-label { font-size: 0.78rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
  .preview-hook { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 14px 18px; margin-bottom: 20px; border-radius: 0 6px 6px 0; }
  .yomi-judgment-box { background: #fef9c3; border-left: 4px solid #f59e0b; padding: 14px 18px; margin-bottom: 20px; border-radius: 0 6px 6px 0; }
  .misconception-box { margin-bottom: 20px; }
  .misconception-box table { width: 100%; border-collapse: collapse; }
  .misconception-box th { background: #e5e7eb; padding: 8px 12px; text-align: left; font-size: 0.85rem; }
  .misconception-box td { padding: 8px 12px; border-bottom: 1px solid #e5e7eb; font-size: 0.9rem; vertical-align: top; }
  .misconception-box tr:nth-child(odd) td { background: #f9fafb; }
  .real-criterion { background: #f0fdf4; border: 1px solid #bbf7d0; padding: 14px 18px; margin-bottom: 20px; border-radius: 6px; white-space: pre-line; }
  .quick-decision-table { margin-bottom: 20px; }
  .quick-decision-table table { width: 100%; border-collapse: collapse; }
  .quick-decision-table th { background: #1e3a5f; color: #fff; padding: 8px 12px; text-align: left; font-size: 0.85rem; }
  .quick-decision-table td { padding: 8px 12px; border-bottom: 1px solid #e5e7eb; font-size: 0.9rem; vertical-align: top; }
  .quick-decision-table tr:nth-child(odd) td { background: #f9fafb; }
  .actions-box { margin-bottom: 20px; }
  .actions-box ol { padding-left: 20px; }
  .actions-box li { margin-bottom: 10px; font-size: 0.9rem; }
  .actions-box strong { color: #1d4ed8; }
  .faq-block { margin-bottom: 20px; }
  .faq-card { border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px 16px; margin-bottom: 10px; }
  .faq-card h3 { margin: 0 0 6px; font-size: 0.95rem; color: #111827; }
  .faq-card p { margin: 0; font-size: 0.88rem; color: #374151; }
  .hashtag-box { background: #f0f4ff; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; }
  .hashtag-box p { margin: 0; color: #2563eb; font-size: 0.88rem; }
  .internal-links { margin-bottom: 20px; }
  .internal-links ul { padding-left: 18px; }
  .internal-links li { margin-bottom: 6px; font-size: 0.88rem; color: #374151; }
  .preview-meta { font-size: 0.78rem; color: #9ca3af; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; }
  .issue-context-box { background: #f0fdf4; border-left: 4px solid #2563eb; padding: 14px 18px; margin-bottom: 20px; border-radius: 0 6px 6px 0; }
  .issue-context-box h2 { font-size: 1rem; margin: 0 0 8px; color: #1e3a5f; }
  .intent-answer-box { background: #fefce8; padding: 14px 18px; margin-bottom: 20px; border-radius: 6px; }
  .intent-answer-box h2 { font-size: 1rem; margin: 0 0 12px; color: #92400e; }
  .intent-qa-item { background: #fff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px 16px; margin-bottom: 10px; }
  .intent-qa-item h3 { margin: 0 0 6px; font-size: 0.95rem; color: #111827; }
  .intent-qa-item p { margin: 0; font-size: 0.88rem; color: #374151; }
  .source-trust-box { background: #f3f4f6; padding: 12px 16px; margin-top: 24px; border-radius: 6px; font-style: italic; font-size: 0.85rem; color: #6b7280; }
  .ai-overview-box { background: #eff6ff; border-left: 4px solid #1d4ed8; padding: 16px 20px; margin-bottom: 20px; border-radius: 0 8px 8px 0; }
  .ai-overview-box h2 { font-size: 1rem; margin: 0 0 8px; color: #1e3a5f; }
  .ai-overview-box p { margin: 0; font-size: 0.9rem; color: #1e3a5f; line-height: 1.6; }
  .paa-block { background: #f9fafb; border: 1px solid #e5e7eb; padding: 14px 18px; margin-bottom: 20px; border-radius: 6px; }
  .paa-block h2 { font-size: 1rem; margin: 0 0 10px; color: #374151; }
  .paa-block ul { margin: 0; padding-left: 18px; }
  .paa-block li { margin-bottom: 6px; font-size: 0.88rem; color: #374151; }
  .confirmed-needed-box { margin-bottom: 20px; }
  .confirmed-needed-box h2 { font-size: 1rem; margin: 0 0 10px; color: #374151; }
  .confirmed-section { background: #f0fdf4; border-left: 4px solid #22c55e; padding: 12px 16px; margin-bottom: 10px; border-radius: 0 6px 6px 0; }
  .confirmed-section h3 { font-size: 0.9rem; margin: 0 0 6px; color: #166534; }
  .check-needed-section { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 0 6px 6px 0; }
  .check-needed-section h3 { font-size: 0.9rem; margin: 0 0 6px; color: #92400e; }
  .confirmed-section ul, .check-needed-section ul { margin: 0; padding-left: 16px; }
  .confirmed-section li, .check-needed-section li { margin-bottom: 4px; font-size: 0.87rem; }
  .prompt-recipe-box { margin-bottom: 20px; }
  .prompt-card { border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
  .prompt-card-label { margin: 0; padding: 8px 14px; background: #0f766e; color: #fff; font-size: 0.82rem; font-weight: 700; }
  .prompt-code { margin: 0; padding: 14px 16px; background: #f1f5f9; color: #0f172a; font-family: 'D2Coding','Consolas',monospace; font-size: 0.88rem; line-height: 1.7; white-space: pre-wrap; word-break: break-word; overflow-x: auto; border-top: 1px solid #e2e8f0; }
  .quality-checklist { background: #f0fdf4; border: 1px solid #bbf7d0; padding: 14px 18px; margin-bottom: 20px; border-radius: 6px; }
  .quality-checklist ul { margin: 0; padding-left: 0; list-style: none; }
  .quality-checklist li { padding: 6px 0 6px 28px; position: relative; font-size: 0.9rem; }
  .quality-checklist li:before { content: "☑"; position: absolute; left: 4px; color: #16a34a; font-weight: 800; }
  .risk-note { background: #fff7ed; border: 1px solid #fed7aa; border-left: 4px solid #f97316; padding: 14px 18px; margin-bottom: 20px; border-radius: 0 6px 6px 0; }
  .risk-note ul { margin: 0; padding-left: 18px; }
  .risk-note li { margin-bottom: 6px; font-size: 0.9rem; color: #7c2d12; }
  .risk-note p { margin: 0; font-size: 0.9rem; color: #7c2d12; }
  .tool-summary { background: #eef2ff; border-left: 4px solid #6366f1; padding: 14px 18px; margin-bottom: 20px; border-radius: 0 6px 6px 0; }
  .tool-summary p[itemprop="description"] { margin: 0; font-size: 0.95rem; color: #312e81; }
  .who-for-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .who-for-rec, .who-for-non { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; }
  .who-for-rec { background: #f0fdf4; border-color: #bbf7d0; }
  .who-for-non { background: #fef2f2; border-color: #fecaca; }
  .who-for-rec h3, .who-for-non h3 { margin: 0 0 8px; font-size: 0.92rem; }
  .who-for ul { margin: 0; padding-left: 18px; }
  .who-for li { margin-bottom: 5px; font-size: 0.88rem; }
  .pricing-table table { width: 100%; border-collapse: collapse; }
  .pricing-table caption { text-align: left; font-size: 0.82rem; color: #6b7280; margin-bottom: 6px; }
  .pricing-table th { background: #312e81; color: #fff; padding: 8px 10px; text-align: left; font-size: 0.84rem; }
  .pricing-table td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; font-size: 0.86rem; vertical-align: top; }
  .verdict-box { background: #f0f7ff; border: 2px solid #2563eb; padding: 16px 20px; margin-bottom: 20px; border-radius: 8px; }
  .verdict-box p { margin: 0 0 6px; font-size: 0.92rem; }
  .verdict-rating { color: #f59e0b; font-size: 1.1rem; font-weight: 800; }
  .use-cases { margin-bottom: 20px; }
  .use-case-card { border: 1px solid #e5e7eb; border-left: 4px solid #6366f1; border-radius: 0 8px 8px 0; padding: 12px 16px; margin-bottom: 10px; background: #fafaff; }
  .use-case-when { margin: 0 0 4px; font-weight: 700; color: #312e81; font-size: 0.9rem; }
  .use-case-how { margin: 0; font-size: 0.88rem; color: #374151; }
"""


class GoldenArticlePreviewService:
    """골든 패턴 + 슬롯 결과를 이용해 사람이 검토 가능한 preview HTML을 생성한다.

    기존 article.html 생성 파이프라인과 독립적으로 동작하며,
    패턴 매칭·슬롯 채움·HTML 렌더링·검증을 한 번에 수행한다.
    """

    def __init__(
        self,
        pattern_service: GoldenPatternService | None = None,
        slot_filler: SlotFillerService | None = None,
    ) -> None:
        self._ps = pattern_service or GoldenPatternService()
        self._sf = slot_filler or SlotFillerService(pattern_service=self._ps)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def build_preview(
        self,
        topic: str,
        summary: str = "",
        content_type: str = "",
        topic_group: str = "",
        candidate_raw: dict | None = None,
        forced_pattern_id: str = "",
    ) -> dict[str, Any]:
        """topic으로 패턴 매칭 → 슬롯 채우기 → HTML 렌더링 → 검증까지 한 번에 수행.

        forced_pattern_id가 주어지면 키워드 매칭을 건너뛰고 해당 패턴으로 빌드한다.
        (AI 파이프라인이 분류기로 패턴을 이미 확정한 경우 — 도구명 등으로 키워드
        매칭이 약해도 발행이 막히지 않게 한다.)

        Returns:
            matched, pattern_match, slot_result, preview_html,
            slot_fill_rate, missing_required_slots,
            ready_for_review, blocking_issues, warnings
        """
        blocking_issues: list[str] = []
        warnings: list[str] = []

        if forced_pattern_id and self._ps.get_pattern(forced_pattern_id):
            _p = self._ps.get_pattern(forced_pattern_id) or {}
            pattern_match = {
                "matched": True,
                "near_match": False,
                "pattern_id": forced_pattern_id,
                "pattern_title": _p.get("title", ""),
                "confidence": 80,
                "content_type": _p.get("content_type", content_type),
                "topic_group": _p.get("topic_group", topic_group),
                "content_type_match": True,
                "topic_group_match": True,
                "forced": True,
            }
            warnings.append("forced_pattern_id")
        else:
            pattern_match = self._ps.match_pattern(
                topic=topic,
                summary=summary,
                content_type=content_type,
                topic_group=topic_group,
            )

        if not pattern_match["matched"]:
            if pattern_match.get("near_match"):
                # near_match: confidence 75~79 + ct_match + tg_match + no neg_hits
                # → 슬롯 채움까지 진행하되 human_review_required=True로 처리
                logger.info(
                    "%s | near_match confidence=%d for topic: %s",
                    __name__,
                    pattern_match["confidence"],
                    topic,
                )
                warnings.append(f"near_match_confidence:{pattern_match['confidence']}")
                # Fall through — don't return early
            else:
                logger.info("%s | pattern not matched for topic: %s", __name__, topic)
                blocking_issues.append("pattern_not_matched")
                blocking_issues.append(
                    f"low_pattern_confidence:{pattern_match['confidence']}"
                )
                return {
                    "matched": False,
                    "near_match": False,
                    "pattern_match": pattern_match,
                    "slot_result": {},
                    "preview_html": _unmatched_html(topic),
                    "slot_fill_rate": 0.0,
                    "missing_required_slots": [],
                    "ready_for_review": False,
                    "blocking_issues": blocking_issues,
                    "warnings": warnings,
                }

        pattern_id: str = pattern_match.get("pattern_id") or ""
        if not pattern_id:
            blocking_issues.append("pattern_not_matched")
            return {
                "matched": False,
                "near_match": False,
                "pattern_match": pattern_match,
                "slot_result": {},
                "preview_html": _unmatched_html(topic),
                "slot_fill_rate": 0.0,
                "missing_required_slots": [],
                "ready_for_review": False,
                "blocking_issues": blocking_issues,
                "warnings": warnings,
            }
        slot_result = self._sf.fill_slots(
            pattern_id=pattern_id,
            topic=topic,
            candidate_raw=candidate_raw,
        )

        fill_rate: float = slot_result.get("slot_fill_rate", 0.0)
        missing: list[str] = slot_result.get("missing_required_slots", [])

        if fill_rate < _MIN_FILL_RATE:
            blocking_issues.append(
                f"slot_fill_rate_below_{int(_MIN_FILL_RATE * 100)}:{fill_rate:.2f}"
            )
        if missing:
            warnings.append(f"missing_slots:{','.join(missing)}")

        preview_html = self.render_html(pattern_match, slot_result)
        validation = self.validate_preview_html(preview_html)

        for issue in validation.get("issues", []):
            blocking_issues.append(issue)
        for warn in validation.get("warnings", []):
            warnings.append(warn)

        _is_near_match = bool(pattern_match.get("near_match"))
        ready = (
            pattern_match["confidence"] >= _MIN_CONFIDENCE
            and fill_rate >= _MIN_FILL_RATE
            and not blocking_issues
            and not _is_near_match  # near_match는 항상 human_review 필요
        )

        logger.info(
            "%s | pattern=%s fill=%.2f ready=%s near_match=%s issues=%s",
            __name__, pattern_id, fill_rate, ready, _is_near_match, blocking_issues,
        )

        # reader_intent_questions 생성 (lazy import)
        _reader_intent_questions: list[str] = []
        try:
            from blogspot_automation.services.geo_intent_service import GeoIntentService as _GIS_bp
            _gis_bp = _GIS_bp()
            _p_data_bp = self._ps.get_pattern(pattern_id) if pattern_id else {}
            _ct_bp = str((_p_data_bp or {}).get("content_type") or "")
            _tg_bp = str((_p_data_bp or {}).get("topic_group") or "")
            _reader_intent_questions = _gis_bp.generate_reader_intent_questions(
                topic=topic,
                content_type=_ct_bp,
                topic_group=_tg_bp,
                slots=slot_result.get("slots") or {},
            )
        except Exception as _riq_exc:
            logger.warning("reader_intent_questions generation failed: %s", _riq_exc)

        return {
            "matched": True,
            "near_match": _is_near_match,
            "pattern_match": pattern_match,
            "slot_result": slot_result,
            "preview_html": preview_html,
            "slot_fill_rate": fill_rate,
            "missing_required_slots": missing,
            "ready_for_review": ready,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "reader_intent_questions": _reader_intent_questions,
        }

    def render_html(
        self, pattern_match: dict, slot_result: dict
    ) -> str:
        """슬롯 결과를 사람이 검토 가능한 HTML fragment로 변환한다.

        - 슬롯이 비어 있으면 해당 섹션을 출력하지 않는다.
        - banned default phrase는 절대 출력하지 않는다.
        """
        topic = escape(str(slot_result.get("topic", "")))
        pattern_title = escape(str(pattern_match.get("pattern_title", "")))
        pattern_id = escape(str(pattern_match.get("pattern_id", "")))
        confidence = int(pattern_match.get("confidence", 0))
        fill_rate = float(slot_result.get("slot_fill_rate", 0.0))
        slots: dict[str, Any] = slot_result.get("slots", {})

        # AI 패밀리 판별 (라벨/프레이밍만 분기, 클래스명은 동일 유지)
        _pid_raw = str(pattern_match.get("pattern_id", ""))
        _p_data_rh = self._ps.get_pattern(_pid_raw) if _pid_raw else {}
        _ct_rh = str((_p_data_rh or {}).get("content_type") or "")
        ai_family = _is_ai_family(_pid_raw, _ct_rh)
        _theme_class = f" {_pick_ai_theme(str(slot_result.get('topic', '')), _pid_raw)}" if ai_family else ""

        sections: list[str] = []

        # hook_opening
        hook = _str_slot(slots.get("hook_opening"))
        if hook:
            sections.append(
                f'    <section class="preview-hook">\n'
                f'      <p>{escape(hook)}</p>\n'
                f'    </section>'
            )

        # tool_summary (AI 도구 1줄 요약 — SoftwareApplication 마이크로데이터)
        tool_summary = _str_slot(slots.get("tool_summary"))
        if tool_summary:
            sections.append(
                f'    <section class="tool-summary" itemscope itemtype="https://schema.org/SoftwareApplication">\n'
                f'      <p class="section-label">🧩 한 줄 요약</p>\n'
                f'      <p itemprop="description">{escape(tool_summary)}</p>\n'
                f'      <meta itemprop="applicationCategory" content="AIApplication">\n'
                f'    </section>'
            )

        # yomi_judgment
        yomi = _str_slot(slots.get("yomi_judgment"))
        if yomi:
            if ai_family:
                # AI 글에서는 내부 마커 '요미 판단:' 접두어를 노출하지 않는다
                yomi = re.sub(r'^\s*요미\s*(?:의)?\s*판단\s*[:：]\s*', '', yomi)
            sections.append(
                f'    <section class="yomi-judgment-box">\n'
                f'      <p class="section-label">{escape(_section_label("yomi_judgment", ai_family))}</p>\n'
                f'      <p>{escape(yomi)}</p>\n'
                f'    </section>'
            )

        # who_for (이런 사람에게 맞다 / 패스 — 2열)
        who_for = slots.get("who_for")
        if isinstance(who_for, dict) and (who_for.get("추천") or who_for.get("비추")):
            rec = _list_slot(who_for.get("추천"))
            non = _list_slot(who_for.get("비추"))
            rec_li = "\n".join(f'          <li>{escape(str(x))}</li>' for x in rec if str(x).strip())
            non_li = "\n".join(f'          <li>{escape(str(x))}</li>' for x in non if str(x).strip())
            sections.append(
                f'    <section class="who-for">\n'
                f'      <p class="section-label">🎯 이런 사람에게 맞다 / 패스</p>\n'
                f'      <div class="who-for-cols">\n'
                f'        <div class="who-for-rec">\n'
                f'          <h3>✅ 추천 대상</h3>\n'
                f'          <ul>\n{rec_li}\n          </ul>\n'
                f'        </div>\n'
                f'        <div class="who-for-non">\n'
                f'          <h3>❌ 비추 대상</h3>\n'
                f'          <ul>\n{non_li}\n          </ul>\n'
                f'        </div>\n'
                f'      </div>\n'
                f'    </section>'
            )

        # prompt_block — ai_prompt_recipe 전용(패턴 자체가 프롬프트 템플릿 모음).
        # 다른 content_type에 일괄 적용하면 주제와 무관한 범용 프롬프트가 끼어들어
        # 오히려 저장 가치를 해치므로 렌더링하지 않는다.
        if _ct_rh == "ai_prompt_recipe":
            prompt_block = _list_slot(slots.get("prompt_block"))
            if prompt_block:
                cards = []
                for item in prompt_block:
                    if not isinstance(item, dict):
                        continue
                    label = escape(str(item.get("label", "프롬프트")))
                    prompt_text = escape(str(item.get("prompt", "")))
                    if not prompt_text.strip():
                        continue
                    cards.append(
                        f'      <div class="prompt-card">\n'
                        f'        <p class="prompt-card-label">{label}</p>\n'
                        f'        <pre class="prompt-code">{prompt_text}</pre>\n'
                        f'      </div>'
                    )
                if cards:
                    sections.append(
                        f'    <section class="prompt-recipe-box">\n'
                        f'      <p class="section-label">📝 복사해서 쓰는 프롬프트</p>\n'
                        + "\n".join(cards) + "\n"
                        f'    </section>'
                    )

        # misconceptions
        misconceptions = _list_slot(slots.get("misconceptions"))
        if misconceptions:
            rows = "\n".join(
                f'          <tr><td>{escape(str(item.get("착각", "")))}</td>'
                f'<td>{escape(str(item.get("실제", "")))}</td></tr>'
                for item in misconceptions
                if isinstance(item, dict)
            )
            if rows:
                _mis_label = "🤔 자주 하는 오해와 실제" if ai_family else "🔁 흔한 착각 vs 실제 기준"
                _mis_th_left = "자주 하는 오해" if ai_family else "흔한 착각"
                _mis_th_right = "실제" if ai_family else "실제 기준"
                sections.append(
                    f'    <section class="misconception-box">\n'
                    f'      <p class="section-label">{_mis_label}</p>\n'
                    f'      <table>\n'
                    f'        <thead><tr><th>{_mis_th_left}</th><th>{_mis_th_right}</th></tr></thead>\n'
                    f'        <tbody>\n{rows}\n        </tbody>\n'
                    f'      </table>\n'
                    f'    </section>'
                )

        # real_criterion
        real = _str_slot(slots.get("real_criterion"))
        if real:
            sections.append(
                f'    <section class="real-criterion">\n'
                f'      <p class="section-label">{escape(_section_label("real_criterion", ai_family))}</p>\n'
                f'      <p>{escape(real)}</p>\n'
                f'    </section>'
            )

        # pricing_table (무료/유료 경계 비교표)
        pricing = _list_slot(slots.get("pricing_table"))
        if pricing:
            prows = "\n".join(
                f'          <tr>'
                f'<td>{escape(str(item.get("플랜", "")))}</td>'
                f'<td>{escape(str(item.get("가격", "")))}</td>'
                f'<td>{escape(str(item.get("핵심 기능", item.get("핵심기능", ""))))}</td>'
                f'<td>{escape(str(item.get("한계", "")))}</td>'
                f'</tr>'
                for item in pricing
                if isinstance(item, dict)
            )
            if prows:
                sections.append(
                    f'    <section class="pricing-table">\n'
                    f'      <p class="section-label">💳 무료 / 유료 경계</p>\n'
                    f'      <table>\n'
                    f'        <caption>플랜별 가격과 한계 비교</caption>\n'
                    f'        <thead><tr><th>플랜</th><th>가격</th><th>핵심 기능</th><th>한계</th></tr></thead>\n'
                    f'        <tbody>\n{prows}\n        </tbody>\n'
                    f'      </table>\n'
                    f'    </section>'
                )

        # quick_decision_table
        qdt = _list_slot(slots.get("quick_decision_table"))
        if qdt:
            rows = "\n".join(
                f'          <tr>'
                f'<td>{escape(str(item.get("내 상황", item.get("내 반응", ""))))}</td>'
                f'<td>{escape(str(item.get("할 일") or item.get("즉시 할 일") or item.get("확인할 조건") or item.get("확인할 것") or item.get("먼저 할 것") or item.get("의미", "")))}</td>'
                f'</tr>'
                for item in qdt
                if isinstance(item, dict)
            )
            if rows:
                _qdt_label = "🧭 상황별 추천" if ai_family else "⚡ 30초 판단표"
                _qdt_th_right = "추천 방법" if ai_family else "먼저 할 것"
                sections.append(
                    f'    <section class="quick-decision-table">\n'
                    f'      <p class="section-label">{_qdt_label}</p>\n'
                    f'      <table>\n'
                    f'        <thead><tr><th>내 상황</th><th>{_qdt_th_right}</th></tr></thead>\n'
                    f'        <tbody>\n{rows}\n        </tbody>\n'
                    f'      </table>\n'
                    f'    </section>'
                )

        # use_cases 섹션은 quick_decision_table(상황별 추천)과 중복되어 제거함(분량 축소).
        # 활용 깊이는 real_criterion(따라 하는 순서)·prompt_block·faq가 담당한다.

        # actions
        actions = _list_slot(slots.get("actions"))
        if actions:
            items_html = "\n".join(
                f'        <li><strong>{escape(str(item.get("행동", "")))}</strong> — '
                f'{escape(str(item.get("설명", "")))}</li>'
                for item in actions
                if isinstance(item, dict) and item.get("행동")
            )
            if items_html:
                sections.append(
                    f'    <section class="actions-box">\n'
                    f'      <p class="section-label">{escape(_section_label("actions", ai_family))}</p>\n'
                    f'      <ol>\n{items_html}\n      </ol>\n'
                    f'    </section>'
                )

        # checklist (결과물 품질 체크리스트 — 체크박스형 리스트)
        checklist = _list_slot(slots.get("checklist"))
        if checklist:
            items_html = "\n".join(
                f'        <li>{escape(str(c))}</li>'
                for c in checklist
                if str(c).strip()
            )
            if items_html:
                sections.append(
                    f'    <section class="quality-checklist">\n'
                    f'      <p class="section-label">✅ 결과물 품질 체크리스트</p>\n'
                    f'      <ul>\n{items_html}\n      </ul>\n'
                    f'    </section>'
                )

        # verdict (최종 판정 + 별점)
        verdict = slots.get("verdict")
        if isinstance(verdict, dict) and _str_slot(verdict.get("결론")):
            try:
                stars_n = int(verdict.get("별점") or 0)
            except (TypeError, ValueError):
                stars_n = 0
            stars_n = max(0, min(5, stars_n))
            star_str = ("★" * stars_n) + ("☆" * (5 - stars_n))
            rating_html = (
                f'      <p class="verdict-rating">{star_str} ({stars_n}/5)</p>\n'
                if stars_n else ""
            )
            sections.append(
                f'    <section class="verdict-box">\n'
                f'      <p class="section-label">⭐ 최종 판정</p>\n'
                f'      <p><strong>한 줄 결론:</strong> {escape(_str_slot(verdict.get("결론")))}</p>\n'
                f'{rating_html}'
                f'    </section>'
            )

        # risk_note (위험 알림 — 보안/저작권/개인정보/환각 주의)
        risk_items = _list_slot(slots.get("risk_note"))
        risk_text = _str_slot(slots.get("risk_note"))
        if risk_items:
            li = "\n".join(
                f'        <li>{escape(str(c))}</li>' for c in risk_items if str(c).strip()
            )
            if li:
                sections.append(
                    f'    <section class="risk-note">\n'
                    f'      <p class="section-label">⚠️ 쓰기 전 주의할 점</p>\n'
                    f'      <ul>\n{li}\n      </ul>\n'
                    f'    </section>'
                )
        elif risk_text:
            sections.append(
                f'    <section class="risk-note">\n'
                f'      <p class="section-label">⚠️ 쓰기 전 주의할 점</p>\n'
                f'      <p>{escape(risk_text)}</p>\n'
                f'    </section>'
            )

        # faq
        faq = _list_slot(slots.get("faq"))
        if faq:
            cards = "\n".join(
                f'      <div class="faq-card">\n'
                f'        <h3>{escape(str(item.get("Q", "")))}</h3>\n'
                f'        <p>{escape(str(item.get("A", "")))}</p>\n'
                    f'      </div>'
                    for item in faq
                    if isinstance(item, dict) and item.get("Q")
            )
            if cards:
                faq_heading = _faq_heading_for_pattern(pattern_id=str(pattern_id), content_type="")
                sections.append(
                    f'    <section class="faq faq-block">\n'
                    f'      <p class="section-label">{escape(faq_heading)}</p>\n'
                    f'{cards}\n'
                    f'    </section>'
                )

        body = "\n".join(sections) if sections else "    <p>슬롯이 채워지지 않았습니다.</p>"

        _html_lang = "en" if is_english_mode() else "ko"
        return f"""<!DOCTYPE html>
<html lang="{_html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>[PREVIEW] {topic}</title>
  <style>
{_PREVIEW_CSS}
  </style>
</head>
<body>
  <article class="golden-preview{_theme_class}">
    <h1>{topic}</h1>
{body}
    <div class="preview-meta">
      pattern: {pattern_id} · confidence: {confidence} · fill_rate: {fill_rate:.2f}
    </div>
  </article>
</body>
</html>"""

    def render_article_candidate_html(
        self,
        pattern_match: dict,
        slot_result: dict,
        selected_title: str = "",
        cover_image_url: str = "",
        internal_link_pairs: list[tuple[str, str]] | None = None,
    ) -> str:
        """발행 후보용 클린 HTML을 반환한다.

        render_html() 기반으로 debug meta와 [PREVIEW] 접두어를 제거하고,
        selected_title이 있으면 h1·title·meta description·JSON-LD에 반영한다.
        GEO 블록(AI_CITATION_SUMMARY, UPDATED_DATE_BLOCK)을 추가한다.
        """
        import json as _json
        import re as _re
        from datetime import datetime as _dt

        raw = self.render_html(pattern_match, slot_result)
        clean = raw.replace("[PREVIEW] ", "", 1)
        clean = _re.sub(r'\n?\s*\.preview-meta\s*\{[^}]*\}', "", clean)
        clean = _re.sub(
            r'\s*<div class="preview-meta">.*?</div>',
            "",
            clean,
            flags=_re.DOTALL,
        )

        # --- 슬롯 추출 ---
        slots: dict = slot_result.get("slots") or {}
        topic_str = str(slot_result.get("topic") or selected_title or "")
        hook = _str_slot(slots.get("hook_opening")) or topic_str
        yomi = _str_slot(slots.get("yomi_judgment")) or ""
        real = _str_slot(slots.get("real_criterion")) or ""
        faq_list = _list_slot(slots.get("faq"))
        actions_list = _list_slot(slots.get("actions"))
        # slot_result의 pattern_id를 우선 사용 (패턴별 citation/meta 템플릿 선택)
        _slot_pattern_id = str(slot_result.get("pattern_id") or "")
        _pattern_id = _slot_pattern_id or str(pattern_match.get("pattern_id") or "")
        # pattern 실제 content_type 조회 (bonus 전달용 인자와 구분)
        _p_data = self._ps.get_pattern(_pattern_id) if _pattern_id else {}
        _content_type = str((_p_data or {}).get("content_type") or "")
        _ai_family = _is_ai_family(_pattern_id, _content_type)

        # --- meta description 생성 (80~160자, 구조적) ---
        candidate_meta_description = _build_meta_description(
            hook=hook, real=real, actions_list=actions_list,
            topic_str=topic_str, selected_title=selected_title,
            content_type=_content_type, pattern_id=_pattern_id,
        )

        # --- GEO: AI_CITATION_SUMMARY (완전한 문장, 내부 라벨 없음) ---
        # LLM이 만든 주제 특화 인용 요약(_llm_citation_summary)이 있으면 우선 사용 —
        # 규칙 기반 조립은 hook/yomi 문장 재활용이라 일반론에 머문다.
        # 단, LLM 요약이 문장 수 등 유효성 검사를 통과하지 못하면(예: 2문장만 생성)
        # publish_ready가 막히므로 규칙 기반 요약으로 폴백한다.
        today_str = _dt.now().strftime("%Y-%m-%d")
        _llm_summary_text = str(slots.get("_llm_citation_summary") or "").strip()
        if _llm_summary_text and validate_ai_citation_summary(_llm_summary_text)["valid"]:
            _ai_summary_text = _llm_summary_text
        else:
            _ai_summary_text = _build_ai_citation_summary(
                hook=hook, yomi=yomi, real=real,
                faq_list=faq_list, content_type=_content_type,
                pattern_id=_pattern_id,
            )

        ai_citation_block = (
            '\n  <section id="AI_CITATION_SUMMARY">\n'
            '    <p>' + escape(_ai_summary_text) + '</p>\n'
            '  </section>'
        )
        # 작성 기준일은 하단 SOURCE_TRUST_BLOCK 본문에 이미 "(YYYY-MM-DD 기준)"으로
        # 포함된다 — 상단에 같은 날짜를 또 표시하지 않는다(중복 문구 지적 반영).
        # GEO 점수의 날짜 신호 마커(id="UPDATED_DATE_BLOCK")는 하단 출처 문단에 부여한다.
        updated_date_block = ""

        # --- GEO Intent + SGE blocks ---
        _sge_paa: list[str] = []
        _sge_overview_text = ""
        _sge_confirmed: list[str] = []
        _sge_check_needed: list[str] = []
        try:
            from blogspot_automation.services.geo_intent_service import GeoIntentService as _GIS
            _geo_intent = _GIS()
            _p_data_ct = self._ps.get_pattern(_pattern_id) if _pattern_id else {}
            _ct = str((_p_data_ct or {}).get("content_type") or _content_type)
            _tg = str((_p_data_ct or {}).get("topic_group") or "")
            # AI 블로그 전용 content_type은 geo_intent의 AI 브랜치(ai_work_tip)로 정규화 —
            # 전용 분기가 없는 신규 AI 타입이 뉴스형 generic 텍스트로 빠지는 것을 방지.
            if _is_ai_family(_pattern_id, _ct):
                _ct, _tg = "ai_work_tip", "ai_work"
            _iq = _geo_intent.generate_reader_intent_questions(
                topic=topic_str, content_type=_ct, topic_group=_tg, slots=slots,
            )
            _ic = _geo_intent.generate_issue_context(
                topic=topic_str, content_type=_ct, hook=hook,
            )
            _ia = _geo_intent.generate_intent_answers(
                questions=_iq, topic=topic_str, content_type=_ct, slots=slots,
            )
            # SGE 전용 생성
            _sge_overview_text = _geo_intent.generate_ai_overview_target_answer(
                topic=topic_str, content_type=_ct, slots=slots,
            )
            _sge_paa = _geo_intent.generate_people_also_ask(
                questions=_iq, topic=topic_str, content_type=_ct,
            )
            _cvck = _geo_intent.generate_confirmed_vs_check_needed(
                content_type=_ct, topic_group=_tg, slots=slots, topic=topic_str,
            )
            _sge_confirmed = _cvck.get("confirmed", [])
            _sge_check_needed = _cvck.get("check_needed", [])
            # LLM 주제 특화 목록이 있으면 규칙 기반 일반론 대신 사용
            _llm_confirmed = [str(x).strip() for x in (slots.get("_llm_confirmed") or []) if str(x).strip()]
            _llm_check_needed = [str(x).strip() for x in (slots.get("_llm_check_needed") or []) if str(x).strip()]
            if len(_llm_confirmed) >= 2:
                _sge_confirmed = _llm_confirmed
            if len(_llm_check_needed) >= 2:
                _sge_check_needed = _llm_check_needed
            _trust_text = _geo_intent.generate_enhanced_source_trust_block(
                content_type=_ct, topic_group=_tg, pattern_id=_pattern_id,
                today_str=today_str,
            )
        except Exception as _ge_exc:
            logger.warning("geo_intent_service error (fallback): %s", _ge_exc)
            _ic = topic_str
            _ia = []
            _trust_text = "이 글은 공개 정보를 바탕으로 정리했습니다. 최신 정보를 직접 확인하세요."

        # 모델 업데이트/새 도구 등 '이슈형' AI 주제는 '왜 지금 화제인가' 프레이밍 사용
        _ai_issue_type = _pattern_id in {"ai_model_update", "ai_search_change"}
        if _ai_issue_type:
            _overview_heading = "지금 핵심만"
        elif _ai_family:
            _overview_heading = "30초 요약"
        else:
            _overview_heading = "먼저 볼 핵심"
        ai_overview_block = (
            '\n  <section id="AI_OVERVIEW_TARGET_ANSWER" class="ai-overview-box">\n'
            f'    <h2>{escape(_overview_heading)}</h2>\n'
            f'    <p>{_emphasize_first_sentence(escape(_sge_overview_text))}</p>\n'
            '  </section>'
        ) if _sge_overview_text else ""

        # AI_OVERVIEW_TARGET_ANSWER는 hook_opening의 첫 문장을 그대로 재사용해 만들어진다
        # (generate_ai_overview_target_answer 참고) — 그래서 본문 리드(preview-hook)가
        # 몇 문단 뒤에서 같은 문장을 그대로 반복해 "같은 말을 두 번 읽는" 느낌을 준다.
        # 요약 박스가 이미 그 역할을 하므로, 본문 리드 문단은 제거한다(표시용 hook만 삭제,
        # yomi_judgment 이하 실제 본문 섹션은 그대로 유지).
        if ai_overview_block and hook:
            _hook_section = (
                f'    <section class="preview-hook">\n'
                f'      <p>{escape(hook)}</p>\n'
                f'    </section>\n'
            )
            clean = clean.replace(_hook_section, "", 1)

        # LLM이 만든 주제 특화 대상 독자(_llm_target_reader)가 있으면 우선 사용 —
        # 규칙 기반 _ic는 "30~50대 직장인" 식 일반론 + 제목 반복에 머문다.
        _llm_target_reader = str(slots.get("_llm_target_reader") or "").strip()
        if _llm_target_reader:
            _ic = _llm_target_reader
        elif topic_str and topic_str not in str(_ic or ""):
            if _ai_issue_type:
                _ic_prefix = f"{topic_str}, 지금 주목받는 이유입니다."
            elif _ai_family:
                _ic_prefix = f"{topic_str} 핵심 정리입니다."
            else:
                _ic_prefix = f"{topic_str} 관련 이슈입니다."
            _ic = f"{_ic_prefix} {_ic}"

        if _ai_issue_type:
            _context_heading = "지금 왜 화제인가"
        elif _ai_family:
            _context_heading = "이 글이 도움이 되는 사람"
        else:
            _context_heading = "왜 지금 봐야 하나"
        issue_context_block = (
            '\n  <section id="ISSUE_CONTEXT_BLOCK" class="issue-context-box">\n'
            f'    <h2>{escape(_context_heading)}</h2>\n'
            f'    <p>{escape(_ic)}</p>\n'
            '  </section>'
        )

        _qa_items_html = ""
        _intent_question_keys: set[str] = set()
        for _qa in _ia[:3]:
            _intent_question_keys.add(_normalize_question_key(str(_qa.get("Q", ""))))
            _q_esc = escape(str(_qa.get("Q", "")))
            _a_esc = escape(str(_qa.get("A", "")))
            _qa_items_html += (
                f'    <div class="intent-qa-item"><h3>Q. {_q_esc}</h3>'
                f'<p>A. {_a_esc}</p></div>\n'
            )
        intent_answer_block = (
            '\n  <section id="INTENT_ANSWER_BLOCK" class="intent-answer-box">\n'
            f'    <h2>{escape(_faq_heading_for_pattern(pattern_id=_pattern_id, content_type=_content_type))}</h2>\n'
            + _qa_items_html +
            '  </section>'
        )

        # PEOPLE_ALSO_ASK_BLOCK
        # LLM이 만든 실제 검색어 스타일 키워드(_llm_paa)가 있으면 그것을 우선 사용 —
        # 규칙 기반 질문→검색어 변환은 조사가 어색해지는 경우가 잦다.
        _paa_html = ""
        _paa_phrases: list[str] = []
        _paa_seen: set[str] = set()
        for _kw in list(slots.get("_llm_paa") or []):
            _kw_text = str(_kw or "").strip()
            _kw_key = _normalize_question_key(_kw_text)
            if not _kw_text or not _kw_key or _is_near_duplicate_question_key(_kw_key, _paa_seen):
                continue
            _paa_seen.add(_kw_key)
            _paa_phrases.append(_kw_text)
            if len(_paa_phrases) >= 5:
                break
        for _question in list(_sge_paa) + _paa_fallback_questions(topic_str, _content_type):
            if len(_paa_phrases) >= 5:
                break
            _question_text = str(_question or "").strip()
            _question_key = _normalize_question_key(_question_text)
            if not _question_text or not _question_key:
                continue
            if (
                _is_near_duplicate_question_key(_question_key, _intent_question_keys)
                or _is_near_duplicate_question_key(_question_key, _paa_seen)
            ):
                continue
            _paa_seen.add(_question_key)
            _paa_phrases.append(_search_phrase_from_question(_question_text))
        if _paa_phrases:
            _paa_items = "\n".join(
                f'      <li class="paa-item">{escape(str(q))}</li>'
                for q in _paa_phrases[:5]
            )
            _paa_html = (
                '\n  <section id="PEOPLE_ALSO_ASK_BLOCK" class="paa-block">\n'
                '    <h2>관련 검색어</h2>\n'
                f'    <ul>\n{_paa_items}\n    </ul>\n'
                '  </section>'
            )

        # CONFIRMED_VS_CHECK_NEEDED_BLOCK
        _cvck_html = ""
        if _sge_confirmed or _sge_check_needed:
            _conf_items = "\n".join(
                f'        <li>{escape(str(c))}</li>' for c in _sge_confirmed
            )
            _chk_items = "\n".join(
                f'        <li>{escape(str(c))}</li>' for c in _sge_check_needed
            )
            _cvck_heading = "검증된 점과 직접 확인할 점" if _ai_family else "확인된 내용과 직접 확인할 내용"
            _confirmed_subheading = "✓ 검증된 사실" if _ai_family else "✓ 확인된 내용"
            _cvck_html = (
                '\n  <section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">\n'
                f'    <h2>{escape(_cvck_heading)}</h2>\n'
                '    <div class="confirmed-section">\n'
                f'      <h3>{escape(_confirmed_subheading)}</h3>\n'
                f'      <ul>\n{_conf_items}\n      </ul>\n'
                '    </div>\n'
                '    <div class="check-needed-section">\n'
                '      <h3>⚠️ 직접 확인 필요</h3>\n'
                f'      <ul>\n{_chk_items}\n      </ul>\n'
                '    </div>\n'
                '  </section>'
            )

        # 실제 검색(Naver/Exa)에서 가져온 인용 URL이 있으면 정적 공식기관 매핑보다
        # 우선 사용한다 — AI 뉴스처럼 official_sources.py에 고정 매핑이 없는
        # pattern_id(ai_work_time_savings 등은 빈 튜플)도 실제 근거 링크를 얻는다
        # (2026-07-16, official_source_links_below_2 게이트 실측 차단 대응).
        # 조작 URL이 섞이지 않도록 http(s) 스킴과 name 존재만 다시 검증한다.
        _real_source_citations = [
            {"name": str(c.get("name", "")).strip(), "url": str(c.get("url", "")).strip()}
            for c in (slots.get("_llm_source_citations") or [])
            if isinstance(c, dict)
            and str(c.get("url", "")).strip().lower().startswith(("http://", "https://"))
            and str(c.get("name", "")).strip()
        ][:4]
        _official_sources_html = render_official_sources_html(
            _real_source_citations or get_official_sources_for_pattern(_pattern_id)
        )
        # 날짜 신호 마커(id="UPDATED_DATE_BLOCK")를 출처 문단에 부여 — 상단 별도
        # 날짜 블록을 없앤 뒤에도 GEO 점수의 updated-date 체크가 유지되게 한다.
        source_trust_block = (
            '\n  <section id="SOURCE_TRUST_BLOCK" class="source-trust-box">\n'
            f'    <h2>{escape(_source_trust_heading_for_pattern(pattern_id=_pattern_id, content_type=_content_type))}</h2>\n'
            f'    <p id="UPDATED_DATE_BLOCK">{escape(_trust_text)}</p>'
            f'{_official_sources_html}\n'
            '  </section>'
        )

        # </h1> 직후에 삽입 순서:
        # AI_OVERVIEW → AI_CITATION → UPDATED_DATE → ISSUE_CONTEXT → INTENT_ANSWER → PAA
        # 히어로 시각 요소: 공개 이미지 URL이 있으면 실제 커버 사진, 없으면 CSS 히어로 배너.
        _visual_block = ""
        if _ai_family:
            _cover_url = (cover_image_url or "").strip()
            if not _cover_url:
                try:
                    from blogspot_automation.services.cover_image_policy import cover_image_url_from_env
                    _cover_url = cover_image_url_from_env(
                        content_type=_content_type,
                        topic_group=str((_p_data or {}).get("topic_group") or ""),
                        variant_seed=topic_str,
                    )
                except Exception:
                    _cover_url = ""
            _visual_title = (selected_title or "").strip() or topic_str
            if _cover_url:
                _alt = escape(f"{_visual_title} 대표 이미지", quote=True)
                _visual_block = (
                    '\n  <figure class="ai-cover-image" data-yomi-block="cover-image" data-yomi-cover-kind="ai">'
                    f'<img src="{escape(_cover_url, quote=True)}" alt="{_alt}" '
                    'loading="eager" decoding="async" width="1200" height="675"/></figure>'
                )
            else:
                _visual_block = _hero_banner_html(
                    content_type=_content_type, topic=_visual_title,
                    theme_class=_pick_ai_theme(topic_str, _pattern_id),
                )

        _after_h1 = (
            _visual_block
            + ai_overview_block
            + ai_citation_block
            + updated_date_block
            + issue_context_block
            + intent_answer_block
            + _paa_html
        )
        import re as _re2
        clean = _re2.sub(r'</h1>', '</h1>' + _after_h1, clean, count=1)

        # </body> 직전에 CONFIRMED_VS_CHECK_NEEDED + SOURCE_TRUST + NAVER_CTA 삽입
        clean = clean.replace(
            '</body>',
            _cvck_html + source_trust_block + '\n</body>',
            1,
        )

        # FAQPage JSON-LD용 FAQ 목록 미리 추출
        valid_faqs = [
            item for item in faq_list
            if isinstance(item, dict)
            and str(item.get("Q", "")).strip()
            and str(item.get("A", "")).strip()
        ]

        # --- selected_title 반영 ---
        st = (selected_title or "").strip()
        meta_desc_esc = escape(candidate_meta_description)
        title_for_og = escape(st) if st else escape(topic_str)
        og_meta_tags = (
            f'  <meta name="description" content="{meta_desc_esc}">\n'
            f'  <meta property="og:type" content="article">\n'
            f'  <meta property="og:title" content="{title_for_og}">\n'
            f'  <meta property="og:description" content="{meta_desc_esc}">\n'
            f'  <meta name="twitter:card" content="summary_large_image">\n'
            f'  <meta name="twitter:title" content="{title_for_og}">\n'
            f'  <meta name="twitter:description" content="{meta_desc_esc}">\n'
        )
        if st:
            st_esc = escape(st)
            clean = _re.sub(r'<title>[^<]*</title>', f'<title>{st_esc}</title>', clean)
            clean = _re.sub(r'<h1>([^<]*)</h1>', f'<h1>{st_esc}</h1>', clean, count=1)
            clean = _re.sub(
                r'<meta\s+name=["\']description["\'][^>]*>\s*',
                '',
                clean,
                flags=_re.IGNORECASE,
            )
            clean = _re.sub(
                r'<meta\s+(?:name|property)=["\'](?:og:[^"\']+|twitter:[^"\']+)["\'][^>]*>\s*',
                '',
                clean,
                flags=_re.IGNORECASE,
            )
            clean = clean.replace('</head>', og_meta_tags + '</head>', 1)
            if '"headline"' in clean:
                clean = _re.sub(
                    r'"headline"\s*:\s*"[^"]*"',
                    f'"headline": "{st}"',
                    clean,
                    count=1,
                )
                clean = clean.replace('"@type": "Article"', '"@type": "BlogPosting"', 1)
            else:
                ld = {
                    "@context": "https://schema.org",
                    "@type": "BlogPosting",
                    "headline": st,
                    "description": candidate_meta_description,
                    "datePublished": today_str,
                    "dateModified": today_str,
                    "author": {"@type": "Person", "name": os.getenv("BLOG_AUTHOR_NAME", "holyyomi AI")},
                    "publisher": {
                        "@type": "Organization",
                        "name": os.getenv("BLOG_BRAND_NAME", "holyyomi AI"),
                        "url": BLOGSPOT_HOME_URL.rstrip("/"),
                    },
                    "mainEntityOfPage": {
                        "@type": "WebPage",
                        "@id": BLOGSPOT_HOME_URL.rstrip("/"),
                    },
                    "speakable": {
                        "@type": "SpeakableSpecification",
                        "cssSelector": [
                            "#AI_OVERVIEW_TARGET_ANSWER p",
                            ".real-criterion p",
                        ],
                    },
                    "inLanguage": "ko-KR",
                }
                ld_script = (
                    f'  <script type="application/ld+json">'
                    f'{_json.dumps(ld, ensure_ascii=False)}'
                    f'</script>\n'
                )
                clean = clean.replace('</head>', ld_script + '</head>', 1)
        else:
            clean = _re.sub(
                r'<meta\s+name=["\']description["\'][^>]*>\s*',
                '',
                clean,
                flags=_re.IGNORECASE,
            )
            clean = _re.sub(
                r'<meta\s+(?:name|property)=["\'](?:og:[^"\']+|twitter:[^"\']+)["\'][^>]*>\s*',
                '',
                clean,
                flags=_re.IGNORECASE,
            )
            clean = clean.replace('</head>', og_meta_tags + '</head>', 1)

        # --- FAQPage JSON-LD ---
        if valid_faqs:
            faq_ld = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": str(item["Q"]).strip(),
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": str(item["A"]).strip(),
                        },
                    }
                    for item in valid_faqs[:5]
                ],
            }
            faq_script = (
                f'  <script type="application/ld+json">'
                f'{_json.dumps(faq_ld, ensure_ascii=False)}'
                f'</script>\n'
            )
            clean = clean.replace('</head>', faq_script + '</head>', 1)

        # --- BreadcrumbList JSON-LD (홈 → 카테고리 → 글) ---
        if _ai_family:
            from urllib.parse import quote as _quote_bc
            _bc_label = _AI_LABEL_FOR_CT.get(_content_type, "AI활용")
            _home = BLOGSPOT_HOME_URL.rstrip("/")
            breadcrumb_ld = {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "홈", "item": _home},
                    {
                        "@type": "ListItem", "position": 2, "name": _bc_label,
                        "item": f"{_home}/search/label/{_quote_bc(_bc_label)}",
                    },
                    {"@type": "ListItem", "position": 3, "name": st or topic_str},
                ],
            }
            bc_script = (
                f'  <script type="application/ld+json">'
                f'{_json.dumps(breadcrumb_ld, ensure_ascii=False)}'
                f'</script>\n'
            )
            clean = clean.replace('</head>', bc_script + '</head>', 1)

        if _pattern_id in _HOWTO_ELIGIBLE_PATTERNS:
            howto_steps: list[dict[str, Any]] = []
            for idx, action in enumerate((actions_list or [])[:5]):
                if isinstance(action, dict):
                    # 슬롯 빌더는 행동/설명 키를 쓴다 (title/description 아님)
                    name = str(
                        action.get("행동") or action.get("title") or action.get("step") or ""
                    ).strip()
                    text = str(
                        action.get("설명")
                        or action.get("description")
                        or action.get("desc")
                        or action.get("행동")
                        or action.get("title")
                        or ""
                    ).strip()
                else:
                    raw = str(action).strip()
                    name = raw[:60]
                    text = raw
                if not text:
                    continue
                howto_steps.append(
                    {
                        "@type": "HowToStep",
                        "position": idx + 1,
                        "name": name or f"단계 {idx + 1}",
                        "text": text,
                    }
                )
            if len(howto_steps) >= 2:
                howto_ld = {
                    "@context": "https://schema.org",
                    "@type": "HowTo",
                    "name": st or topic_str,
                    "description": candidate_meta_description,
                    "totalTime": "PT5M",
                    "step": howto_steps,
                }
                howto_script = (
                    f'  <script type="application/ld+json">'
                    f'{_json.dumps(howto_ld, ensure_ascii=False)}'
                    f'</script>\n'
                )
                clean = clean.replace('</head>', howto_script + '</head>', 1)

        # SoftwareApplication + Review JSON-LD (ai_tool_review 전용 — master_guide Category A)
        if _pattern_id == "ai_tool_review":
            _verdict = slots.get("verdict") if isinstance(slots.get("verdict"), dict) else {}
            _tool_name = st or topic_str
            _sw_app = {
                "@type": "SoftwareApplication",
                "name": _tool_name,
                "applicationCategory": "AIApplication",
                "operatingSystem": "Web",
            }
            try:
                _rating = int(_verdict.get("별점") or 0)
            except (TypeError, ValueError):
                _rating = 0
            if 1 <= _rating <= 5:
                review_ld = {
                    "@context": "https://schema.org",
                    "@type": "Review",
                    "itemReviewed": _sw_app,
                    "reviewRating": {
                        "@type": "Rating",
                        "ratingValue": str(_rating),
                        "bestRating": "5",
                        "worstRating": "1",
                    },
                    "author": {
                        "@type": "Person",
                        "name": os.getenv("BLOG_AUTHOR_NAME", "holyyomi AI"),
                    },
                    "reviewBody": str(_verdict.get("결론") or candidate_meta_description),
                    "datePublished": today_str,
                }
            else:
                review_ld = {"@context": "https://schema.org", **_sw_app}
            review_script = (
                f'  <script type="application/ld+json">'
                f'{_json.dumps(review_ld, ensure_ascii=False)}'
                f'</script>\n'
            )
            clean = clean.replace('</head>', review_script + '</head>', 1)

        if _ia:
            clean = _re.sub(
                r'\n?\s*<section[^>]*class="faq[^"]*"[^>]*>.*?</section>',
                '',
                clean,
                count=1,
                flags=_re.DOTALL,
            )

        clean = _decorate_section_headings(clean)
        # 목차(ai-toc)는 GEO/SGE 점수 어디에도 반영되지 않고, 결론 바로 다음에 끼어들어
        # 본문 흐름만 끊는다는 지적을 반영해 제거했다.

        # prepare_blogspot_html은 정책상 공식기관 호스트가 아닌 외부 <a href>를
        # 전부 벗겨낸다(LLM이 본문에 임의로 지어낸 링크 방지용 안전장치) — 그래서
        # SOURCE_TRUST_BLOCK에 방금 넣은 실제 인용 URL(Naver/Exa)도 그대로 두면
        # 벗겨져 official_source_links_below_2 게이트가 다시 막힌다. 여기서 만든
        # _real_source_citations는 실제 API 응답에서 그대로 가져온 것만 통과했으므로
        # (조작 URL 아님) 정확히 그 URL만 예외로 허용한다.
        clean = prepare_blogspot_html(
            clean,
            extra_allowed_urls=tuple(c["url"] for c in _real_source_citations),
        )
        # 내부링크 + 해시태그는 prepare의 strip 이후에 붙여야 살아남는다 (AI 글만)
        if _ai_family:
            clean = append_ai_footer_html(
                clean,
                internal_links=_list_slot(slots.get("internal_links")),
                hashtags=_list_slot(slots.get("hashtags")),
                content_type=_content_type,
                internal_link_pairs=internal_link_pairs,
            )
        return clean

    @staticmethod
    def validate_preview_html(html: str) -> dict[str, Any]:
        """preview HTML의 품질 기준을 검사한다.

        Returns:
            {"valid": bool, "issues": list[str], "warnings": list[str]}
        """
        return _validate_preview_html_impl(html)


_HEADING_EMOJI_MAP: dict[str, str] = {
    "먼저 볼 핵심": "🔥",
    "왜 지금 봐야 하나": "⚡",
    "빠른 확인 답변": "❓",
    "피해 대응 전 많이 묻는 질문": "❓",
    "신청 전 확인 질문": "❓",
    "많이 묻는 질문": "❓",
    "함께 확인할 질문": "💬",
    "관련 검색어": "🔎",
    "핵심 관점": "💡",
    "흔한 착각 vs 실제 기준": "⚖️",
    "공식 기준 / 단계별 확인": "📋",
    "30초 판단표": "⏱️",
    "바로 할 행동": "✅",
    "확인된 내용과 직접 확인할 내용": "🔍",
    "공식 공고와 문의처": "📞",
    "출처와 확인 기준": "📞",
    "오늘의 핵심": "🔥",
    "AI 인용 요약": "🤖",
    "오늘 업데이트": "📅",
    # AI 가이드형 섹션 제목
    "30초 요약": "⚡",
    "지금 핵심만": "⚡",
    "이 글이 도움이 되는 사람": "🎯",
    "지금 왜 화제인가": "🔥",
    "검증된 점과 직접 확인할 점": "🔍",
    "자주 묻는 질문": "❓",
}


_AI_LABEL_POOL: tuple[str, ...] = (
    "AI활용", "AI도구", "프롬프트", "AI비교", "AI입문", "AI모델", "AI검색", "AI보안", "AI블로그",
)


def ai_internal_link_pairs(internal_links: list, *, content_type: str = "") -> list[tuple[str, str]]:
    """internal_links 슬롯 → (앵커, 라벨검색 URL) 튜플 목록. 내 블로그 라벨 페이지로 연결.

    같은 content_type이 반복돼 URL이 겹치면 다른 카테고리 라벨로 회전시켜
    서로 다른 내부 페이지로 연결되게 한다(최소 2개 이상 확보).
    """
    from urllib.parse import quote as _quote
    pairs: list[tuple[str, str]] = []
    base = BLOGSPOT_HOME_URL.rstrip("/")
    used: set[str] = set()
    pool_i = 0

    def _url(label: str) -> str:
        return f"{base}/search/label/{_quote(label)}"

    for item in internal_links or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("주제", "")).strip()
        if not subject:
            continue
        lct = str(item.get("content_type", "")).strip() or content_type
        label = _AI_LABEL_FOR_CT.get(lct, "AI활용")
        url = _url(label)
        if url in used:  # 라벨 충돌 → 다른 카테고리로 회전
            while pool_i < len(_AI_LABEL_POOL) and _url(_AI_LABEL_POOL[pool_i]) in used:
                pool_i += 1
            if pool_i < len(_AI_LABEL_POOL):
                url = _url(_AI_LABEL_POOL[pool_i])
                pool_i += 1
        if url in used:
            continue
        used.add(url)
        pairs.append((subject, url))
    return pairs


def append_ai_footer_html(
    html: str,
    *,
    internal_links: list | None = None,
    hashtags: list | None = None,
    content_type: str = "",
    internal_link_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """발행 직전(마지막 strip 이후) HTML에 내부링크 + 해시태그 푸터를 붙인다.

    prepare_blogspot_html이 internal-links/hashtag 섹션을 strip하므로, 반드시
    최종 단계에서 호출해야 살아남는다 (뉴스 발행 서비스와 동일한 패턴).

    internal_link_pairs(실제 발행된 글 (제목,URL))가 있으면 우선 사용하고,
    부족분은 라벨 검색 링크로 보충한다.
    """
    out = html or ""
    real_pairs = [
        (str(t), str(u)) for t, u in (internal_link_pairs or [])
        if str(t).strip() and str(u).strip()
    ]
    label_pairs = ai_internal_link_pairs(internal_links or [], content_type=content_type)
    seen_urls = {u for _, u in real_pairs}
    combined = real_pairs + [lp for lp in label_pairs if lp[1] not in seen_urls]
    if combined:
        out = append_internal_links_block(out, links=combined[:3])
    tags = [str(t) for t in (hashtags or []) if str(t).strip()]
    if tags:
        out = append_hashtags_block(out, hashtags=tags)
    return out


def _inject_toc_html(html: str) -> str:
    """본문 콘텐츠 섹션(section-label 보유)에 id를 부여하고 목차(TOC)를 삽입한다.
    AEO/가독성 향상. 섹션이 4개 미만이면 생략."""
    pat = re.compile(
        r'<section class="(?P<cls>[^"]*)">\s*<p class="section-label">(?P<label>[^<]*)</p>'
    )
    entries: list[tuple[str, str]] = []
    counter = {"i": 0}

    def _repl(m: "re.Match[str]") -> str:
        counter["i"] += 1
        anchor = f"sec-{counter['i']}"
        cls = m.group("cls")
        label = m.group("label").strip()
        clean_label = re.sub(r'^[^가-힣A-Za-z0-9]+', '', label).strip() or label
        entries.append((anchor, clean_label))
        return f'<section id="{anchor}" class="{cls}">\n      <p class="section-label">{m.group("label")}</p>'

    new_html = pat.sub(_repl, html)
    if len(entries) < 4:
        return html
    items = "".join(f'<li><a href="#{a}">{escape(lbl)}</a></li>' for a, lbl in entries)
    toc = (
        '\n  <nav class="ai-toc" aria-label="목차">\n'
        '    <p class="ai-toc-title">목차</p>\n'
        f'    <ol>{items}</ol>\n'
        '  </nav>'
    )
    # 본문 첫 콘텐츠 섹션(리드/훅) 앞에 삽입
    m_first = re.search(r'<section class="preview-hook">', new_html)
    if m_first:
        return new_html[:m_first.start()] + toc + "\n" + new_html[m_first.start():]
    # 폴백: PAA 블록 뒤
    return re.sub(r'(</section>)(\s*<section class=")', r'\1' + toc + r'\2', new_html, count=1)


def _hero_banner_html(*, content_type: str = "", topic: str = "", theme_class: str = "") -> str:
    """이미지가 없을 때도 모든 AI 글 상단에 들어가는 CSS 히어로 배너.
    카테고리 배지 + 이모지 + 주제를 테마 색으로 보여준다 (외부 이미지 의존 없음)."""
    label, emoji = _AI_HERO_META.get(content_type, ("AI 인사이트", "🤖"))
    topic_short = (topic or "").strip()
    if len(topic_short) > 70:
        topic_short = topic_short[:69] + "…"
    return (
        f'\n  <div class="ai-hero {escape(theme_class)}">\n'
        f'    <span class="ai-hero-icon">{emoji}</span>\n'
        f'    <span class="ai-hero-badge">{escape(label)}</span>\n'
        f'    <span class="ai-hero-title">{escape(topic_short)}</span>\n'
        f'  </div>'
    )


def _faq_heading_for_pattern(*, pattern_id: str = "", content_type: str = "") -> str:
    if _is_ai_family(pattern_id, content_type):
        return "자주 묻는 질문"
    if pattern_id == "consumer_warning_refund" or content_type == "consumer_warning":
        return "피해 대응 전 많이 묻는 질문"
    if pattern_id in {"policy_deadline_support", "tax_refund_hometax_check"} or content_type in {
        "policy_deadline",
        "policy_benefit",
        "tax_refund",
    }:
        return "신청 전 확인 질문"
    return "빠른 확인 답변"


def _source_trust_heading_for_pattern(*, pattern_id: str = "", content_type: str = "") -> str:
    if pattern_id in {"policy_deadline_support", "tax_refund_hometax_check"} or content_type in {
        "policy_deadline",
        "policy_benefit",
        "tax_refund",
    }:
        return "공식 공고와 문의처"
    return "출처와 확인 기준"


def _normalize_question_key(text: str) -> str:
    key = re.sub(r"[^0-9A-Za-z가-힣]+", "", (text or "").lower())
    replacements = {
        "어떻게확인하나요": "확인",
        "어떻게확인하나": "확인",
        "어디에서확인하나요": "확인",
        "어디서확인하나요": "확인",
        "무엇을기준으로비교해야하나요": "비교기준",
        "무엇을기준으로비교하나요": "비교기준",
        "무엇인가요": "",
        "무엇인가": "",
    }
    for source, target in replacements.items():
        key = key.replace(source, target)
    key = re.sub(r"(인가요|인가|하나요|하나|나요|습니까|까요|까|요)$", "", key)
    return key


def _search_phrase_from_question(question: str) -> str:
    text = " ".join((question or "").split()).strip()
    text = re.sub(r"[?？]+$", "", text)
    if "무료배송" in text and "결제금액" in text and ("비교" in text or "기준" in text):
        return "무료배송 결제금액 비교 기준"
    if "쿠폰" in text and ("저렴" in text or "최종" in text):
        return "쿠폰 적용 후 최종금액 비교"
    if "최소주문금액" in text and "미달" in text:
        return "최소주문금액 미달 조건"
    if "앱별" in text and "결제금액" in text:
        return "앱별 결제금액 차이"
    text = text.replace("무엇을 기준으로 비교해야", "비교 기준")
    text = text.replace("무엇을 기준으로 비교", "비교 기준")
    replacements = (
        ("무엇인가요", ""),
        ("무엇인가", ""),
        ("한가요", "한지"),
        ("되나요", "되는지"),
        ("있나요", "있는지"),
        ("없나요", "없는지"),
        ("하나요", "하는지"),
        ("인가요", "인지"),
        ("일까요", "일지"),
        ("왜", ""),
        ("어떻게", ""),
        ("나요", ""),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(r"(은|는)\s+비교 기준\s+하는지$", r" 비교 기준", text)
    text = re.sub(r"(하는지|되는지|인지|한지)$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,·-")
    return text or "관련 확인 포인트"


def _is_near_duplicate_question_key(key: str, seen_keys: set[str]) -> bool:
    if key in seen_keys:
        return True
    for seen in seen_keys:
        if min(len(key), len(seen)) >= 10 and (key in seen or seen in key):
            return True
    return False


def _paa_fallback_questions(topic: str, content_type: str) -> list[str]:
    core = " ".join((topic or "이 이슈").split()).strip()
    if content_type in {"policy_deadline", "policy_benefit", "tax_refund"}:
        return [
            f"{core} 대상 조건은 어디에서 확인하나요?",
            f"{core} 신청 전에 준비할 정보는 무엇인가요?",
            f"{core} 공식 안내에서 바뀐 내용은 무엇인가요?",
            f"{core} 마감일이나 처리 일정은 어떻게 확인하나요?",
            f"{core} 관련 문의처는 어디인가요?",
        ]
    if content_type == "consumer_warning":
        return [
            f"{core} 피해 여부는 어떻게 확인하나요?",
            f"{core} 관련 증거는 무엇을 남겨야 하나요?",
            f"{core} 고객센터 답변은 어떻게 기록하나요?",
            f"{core} 추가 피해를 막으려면 무엇을 확인하나요?",
            f"{core} 신고나 문의는 어디에서 하나요?",
        ]
    if content_type in {"money_checklist", "delivery_money"}:
        return [
            f"{core} 최종 결제금액은 어떻게 비교하나요?",
            f"{core} 쿠폰 적용 조건은 어디에서 확인하나요?",
            f"{core} 최소주문금액 미달 때 비용은 어떻게 달라지나요?",
            f"{core} 앱별 가격 차이는 어떻게 확인하나요?",
            f"{core} 주문 전 체크리스트는 무엇인가요?",
        ]
    return [
        f"{core} 반응이 갈린 이유는 무엇인가요?",
        f"{core} 보기 전에 확인할 핵심 포인트는 무엇인가요?",
        f"{core} 관련해서 공식 확인이 필요한 내용은 무엇인가요?",
        f"{core} 이후 이어질 변수는 무엇인가요?",
        f"{core} 비슷한 사례와 다른 점은 무엇인가요?",
    ]


_SENTENCE_END_CHARS = ".!?。"


def _emphasize_first_sentence(escaped_text: str) -> str:
    text = (escaped_text or "").strip()
    if not text:
        return ""
    cut = -1
    for i, ch in enumerate(text):
        if ch in _SENTENCE_END_CHARS:
            cut = i + 1
            break
    if cut <= 0 or cut > 240:
        return escaped_text
    first = text[:cut]
    rest = text[cut:].lstrip()
    if not first or len(first) < 10:
        return escaped_text
    if rest:
        return f"<strong>{first}</strong> {rest}"
    return f"<strong>{first}</strong>"


def _decorate_section_headings(html: str) -> str:
    if not html:
        return html
    decorated = html
    for heading, emoji in _HEADING_EMOJI_MAP.items():
        pattern = re.compile(
            rf'(<h2\b[^>]*>)\s*(?!{re.escape(emoji)})(?!\S+\s+{re.escape(heading)})({re.escape(heading)})\s*(</h2>)',
            flags=re.IGNORECASE,
        )
        decorated = pattern.sub(rf'\1{emoji} \2\3', decorated)
    return decorated


def _validate_preview_html_impl(html: str) -> dict[str, Any]:
    """preview HTML의 품질 기준을 검사한다."""
    issues: list[str] = []
    warnings: list[str] = []

    for phrase in _BANNED_DEFAULT_PHRASES:
        if phrase in html:
            issues.append(f"banned_default_phrase:{phrase[:40]}")

    if "<h1" not in html.lower():
        issues.append("missing_h1")

    # 뉴스/AI 양쪽 라벨 또는 CSS 클래스 중 하나라도 있으면 통과 (클래스는 게이트 기준)
    required_markers: dict[str, tuple[str, ...]] = {
        "missing_yomi_judgment": ("핵심 관점", "결론부터 말하면", 'class="yomi-judgment-box"'),
        "missing_misconception": ("흔한 착각", "자주 하는 오해", 'class="misconception-box"'),
        "missing_quick_decision_table": ("30초 판단표", "상황별 추천", 'class="quick-decision-table"'),
        "missing_faq": (
            "빠른 확인 답변", "자주 묻는 질문", "피해 대응 전 많이 묻는 질문",
            "신청 전 확인 질문", "많이 묻는 질문", 'class="faq',
        ),
    }
    for issue_key, markers in required_markers.items():
        if not any(marker in html for marker in markers):
            warnings.append(issue_key)

    return {
        "valid": not issues,
        "issues": issues,
        "warnings": warnings,
    }


# ------------------------------------------------------------------ #
# Module-level helpers                                                #
# ------------------------------------------------------------------ #

def _str_slot(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _list_slot(value: Any) -> list:
    if isinstance(value, list) and value:
        return value
    return []


def _content_type_badge(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    ct = str(item.get("content_type", "")).strip()
    if not ct:
        return ""
    return f' <span style="font-size:0.75rem;color:#6b7280;">({escape(ct)})</span>'


def _extract_clean_sentence(text: str, max_len: int = 130) -> str:
    """텍스트에서 내부 라벨을 제거한 후 첫 완전한 문장을 추출한다."""
    import re as _re_s
    if not text:
        return ""
    text = " ".join(text.split())  # 공백 정규화
    # 내부 라벨 제거: "요미 판단:", "요미의 판단:", "단계:", 번호, 불릿
    text = _re_s.sub(r'^[가-힣A-Za-z]{2,8}\s*(의\s*)?판단\s*:\s*', '', text)
    text = _re_s.sub(r'^\d+\s*단계\s*[:\-]\s*', '', text)
    text = _re_s.sub(r'^\d+\.\s+', '', text)
    text = _re_s.sub(r'^[-·•]\s+', '', text)
    text = text.strip()
    if not text:
        return ""
    # 완전한 문장 종결 찾기 — "다. ", "요. ", "니다. " 패턴
    for sep in ("다. ", "요. ", "니다. ", "습니다. "):
        pos = text.find(sep)
        if 8 < pos <= max_len - 1:
            return text[:pos + 1].strip()  # "다" or "요" 포함 (sep[0])
    # 문장 끝에 마침표 (공백 없이)
    for sep in ("습니다.", "니다.", "다.", "요."):
        pos = text.find(sep)
        if 8 < pos + len(sep) <= max_len + 5:
            return text[:pos + len(sep)].strip()
    # 구분자 없으면 첫 줄 or 최대 길이
    first_line = text.split("\n")[0].strip()
    candidate = first_line if first_line else text
    return candidate[:max_len]


_PATTERN_CITATION_SUMMARIES: dict[str, str] = {
    "tax_refund_hometax_check": (
        "종합소득세·세금 환급금 조회 전에는 환급 유형과 조회 경로를 먼저 구분해야 한다. "
        "국세환급금, 종합소득세 환급, 연말정산 환급, 지방세 환급은 확인 메뉴가 다를 수 있다. "
        "홈택스·손택스에서는 환급 대상 여부, 신고 내역, 환급 계좌, 보완 요청 여부를 함께 확인해야 한다. "
        "세금 환급 정보는 개인 신고 상태에 따라 달라질 수 있으므로 최종 기준은 국세청·홈택스 공식 화면이다."
    ),
    "ai_work_time_savings": (
        "ChatGPT나 AI 도구로 업무 시간을 줄이려면 작업 전체가 아니라 반복되는 단계를 먼저 분리해야 한다. "
        "초안 작성, 요약, 분류, 체크리스트화, 보고서 정리처럼 반복 규칙이 있는 업무가 자동화에 적합하다. "
        "검수 기준 없이 AI를 쓰면 오히려 수정 시간이 늘어날 수 있다. "
        "따라서 프롬프트보다 먼저 입력 자료, 결과물 기준, 검수 루프를 정해야 한다."
    ),
    "ai_tool_comparison": (
        "AI 도구를 비교할 때는 가격보다 반복 업무에서의 실제 응답 정확도를 먼저 확인해야 한다. "
        "같은 프롬프트에도 도구마다 출력 형식과 길이가 달라 검수 시간이 달라질 수 있다. "
        "무료 플랜의 제한 항목과 유료 전환 기준을 먼저 파악해야 불필요한 비용을 줄일 수 있다. "
        "도구 선택 기준은 기능 목록이 아니라 실제 사용 워크플로우와의 적합성이다."
    ),
    "ai_automation_workflow": (
        "AI 자동화 워크플로우를 구성하기 전에 반복되는 입력 자료와 출력 기준을 먼저 정의해야 한다. "
        "자동화에 적합한 업무는 규칙이 명확하고 검수 기준이 정해진 반복 작업이다. "
        "검수 루프 없이 자동화하면 오류 누적으로 수정 비용이 증가할 수 있다. "
        "자동화 도구 도입 전 파일럿 테스트로 실제 시간 절감 효과를 확인하는 것이 권장된다."
    ),
    "ai_prompt_recipe": (
        "좋은 프롬프트는 길이가 아니라 구조에서 나온다. 역할 지정, 작업 목적, 입력 자료, 출력 형식, 제약 조건 다섯 가지를 고정하면 결과가 안정된다. "
        "매번 새로 쓰지 말고 잘 나온 프롬프트를 템플릿으로 저장해 값만 바꿔 재사용하는 것이 효율적이다. "
        "출력 형식을 명시하고 '확실하지 않으면 추측하지 말 것'이라는 제약을 더하면 환각을 줄일 수 있다. "
        "다만 프롬프트가 좋아져도 AI 출력은 초안이므로 핵심 사실은 결과물 품질 체크리스트로 직접 검수해야 한다."
    ),
    "ai_tool_review": (
        "AI 도구는 기능 수가 아니라 내 반복 업무에서 검수 시간을 실제로 줄여주는지로 판단해야 한다. "
        "광고성 후기 대신 무료 범위에서 내 업무 한 가지를 직접 시켜 결과물의 검수 시간을 측정하는 것이 정확하다. "
        "무료로 어디까지 되는지, 사용량·고급 모델·파일 처리에서 어디가 막히는지가 유료 전환 판단 기준이다. "
        "요금·기능·무료 한도는 수시로 바뀌므로 공식 가격 페이지에서 직접 확인하고, 민감정보 입력과 사실 검증은 사람이 책임져야 한다."
    ),
    "ai_model_update": (
        "AI 모델 업데이트는 버전 숫자가 아니라 내 반복 업무에서 체감되는 변화로 판단해야 한다. "
        "벤치마크와 데모는 참고치이며, 글쓰기·요약처럼 이미 잘 되던 작업은 차이가 작을 수 있다. "
        "추론·코딩·긴 문서 처리처럼 한계가 있던 영역에서 변화가 크므로 내 핵심 업무로 직접 비교하는 것이 정확하다. "
        "공식 발표에서 확인된 사실과 추측을 구분하고, 달라진 요금·사용량 제한도 함께 확인해야 한다."
    ),
    "ai_search_change": (
        "AEO·GEO·SGE는 AI 답변에 내 글이 소스로 인용되도록 하는 최적화를 가리킨다. "
        "기존 SEO가 끝난 것이 아니라 명확한 사실, 구조화된 정보, 신뢰 신호가 더 중요해진 것이다. "
        "질문에 첫 문장으로 직접 답하고 정의 박스·표·번호 목록으로 구조화하면 인용 확률이 높아진다. "
        "업데이트 날짜, 작성자 정보, 공식 출처 링크 같은 신뢰 신호를 함께 더하는 것이 효과적이다."
    ),
    "ai_blog_growth": (
        "AI 블로그의 성패는 발행량이 아니라 검색 의도를 충족하는 깊이에서 갈린다. "
        "AI 초안을 그대로 올리면 비슷한 글이 양산돼 검색에서 밀리므로 경험·데이터·관점을 더해야 한다. "
        "발행 전 품질 체크리스트로 사실·구조·중복을 거르는 검수 루프가 핵심이다. "
        "구매·비교 의도 키워드 글의 비중을 높이면 광고 단가(RPM)를 개선할 수 있다."
    ),
    "ai_comparison": (
        "AI 도구·모델 비교에 절대 승자는 없으며, 글쓰기에 강한 도구와 코딩·분석에 강한 도구가 다르다. "
        "기능 목록이 아니라 같은 업무를 두 도구에 시켜 결과 품질과 검수 시간을 비교하는 것이 정확하다. "
        "무료로 어디까지 되는지, 유료 전환 시 무엇이 풀리는지의 경계가 실제 선택 기준이다. "
        "요금·성능 정보는 수시로 바뀌므로 공식 가격 페이지에서 직접 확인해야 한다."
    ),
    "ai_risk_security": (
        "AI 리스크는 사용 금지가 아니라 안전하게 쓰는 규칙으로 관리하는 것이 현실적이다. "
        "민감정보(기밀·개인정보)는 입력하지 않고, 결과의 핵심 사실은 원문으로 직접 검증해야 한다. "
        "환각은 기술로 완전히 막을 수 없으므로 사람의 검수 단계가 필수이며, 생성물은 저작권·표절 확인이 필요하다. "
        "회사 AI 사용 정책과 도구의 데이터 처리 옵션(학습 제외·기업용 보안)을 먼저 확인하는 것이 안전하다."
    ),
    "ai_beginner_guide": (
        "AI를 처음 시작할 때는 도구를 늘리기보다 무료 도구 하나로 내 작은 업무부터 맡겨 보는 것이 빠르다. "
        "AI는 완성본을 주는 도구가 아니라 80점 초안을 빠르게 주는 도구라는 점을 기억해야 한다. "
        "요청에 역할·목적·형식을 적으면 결과 품질이 올라가고, 무료 버전으로도 요약·번역·초안 작성은 충분하다. "
        "결과는 그대로 쓰지 말고 핵심 사실을 확인한 뒤 내 말투로 다듬고, 민감 정보는 입력하지 않아야 한다."
    ),
    "viral_ott_reaction_decode": (
        "반응이 갈리는 이슈는 확인된 사실, 이용자 기대, 커뮤니티 해석을 분리해서 봐야 한다. "
        "화제성이 높아도 공식 확인 범위와 추측성 반응은 같은 무게로 볼 수 없다. "
        "구독, 결제, 일정, 소비 결정처럼 독자 행동에 직접 연결되는 변화가 있는지 따로 확인해야 한다. "
        "루머나 사생활성 주장보다 원문 안내와 신뢰할 수 있는 보도 기준으로 맥락을 정리하는 것이 안전하다."
    ),
    "delivery_money_checklist": (
        "배달앱 주문 전 배달비 조건, 쿠폰 적용 기준, 최소주문금액을 순서대로 확인하면 결제 후 예상 초과를 줄일 수 있다. "
        "배달비 무료는 최소주문금액 충족 시 적용되며, 쿠폰마다 적용 가능 조건이 다르다. "
        "앱별로 동일 가게의 최종 결제금액이 다를 수 있으므로 2개 이상 앱 비교가 도움이 된다. "
        "배달앱 정책은 수시로 바뀔 수 있으므로 주문 시점의 앱 화면에서 조건을 직접 확인해야 한다."
    ),
    "platform_change_service_update": (
        "플랫폼 서비스 변경 공지가 떴다면 적용 일자 전에 내 계정·결제·기기 상태를 순서대로 점검해야 한다. "
        "변경 대상 여부, 자동결제 처리, 기존 사용자 예외 조건은 운영사 공식 안내에서 직접 확인해야 한다. "
        "약관 변경에 따라 취소·환불 기준이 함께 바뀔 수 있으므로 변경 일자 전 확인이 필요하다. "
        "공식 공지 외 출처는 사실 확인이 필요하며, 변경 일자 전 필요한 조치를 미리 마치는 것이 안전하다."
    ),
    "consumer_warning_refund": (
        "소비자 피해 상황에서는 고객센터 전화보다 결제 화면, 주문번호, 상담 기록 캡처를 먼저 남겨야 한다. "
        "환불·보상은 신청과 증빙이 필요한 경우가 많아 증거 확보가 늦으면 처리 결과가 달라질 수 있다. "
        "운영사 채널은 텍스트 기록이 남는 채팅·이메일을 우선 사용하고, 통화는 메모로 보완하는 것이 안전하다. "
        "운영사 1차 대응이 부족하면 한국소비자원 1372, 개인정보침해 신고센터 118 등 공식 기관 단계로 진행할 수 있다."
    ),
    "policy_deadline_support": (
        "정부·지자체 지원금은 신청 대상과 소득 기준, 신청 기간을 직접 확인하지 않으면 받을 수 있는 지원을 놓치기 쉽다. "
        "지원금마다 대상 조건과 필요 서류가 다르므로 공식 공지의 자격 요건을 먼저 확인해야 한다. "
        "신청 경로는 정부24·복지로·지자체 누리집·주민센터 등으로 안내된 공식 채널을 사용해야 한다. "
        "지급 방식과 사용처는 사업별로 다르므로 신청 전 안내 페이지에서 함께 확인하는 것이 안전하다."
    ),
    "corporate_issue_decode": (
        "기업 이슈는 공식 발표·공시와 외부 추측을 구분해서 보는 것이 안전하다. "
        "오늘 발표된 내용은 공식 채널과 복수 매체 교차 확인이 가능한 사실 위주로 정리할 수 있다. "
        "소비자·이용자에게 즉시 미치는 영향은 서비스·결제·계정 관련 안내가 따로 나올 때 확정된다. "
        "투자 관련 판단은 공시 시스템과 후속 IR 발표를 기준으로 별도 확인하는 것이 권장된다."
    ),
}

_BROKEN_CITATION_PATTERNS: tuple[str, ...] = (
    "시작했기 확인할 항목",
    "높다 환급금",
    "복잡하지 않다 환급",
    "요미 판단:",
    "1단계:",
    "2단계:",
    "3단계:",
    "section-label",
)

_SENTENCE_ENDERS: tuple[str, ...] = ("다.", "요.", "습니다.", "입니다.")


def validate_ai_citation_summary(text: str) -> dict:
    """AI_CITATION_SUMMARY 유효성 검사.

    Returns: {"valid": bool, "issues": list[str]}
    """
    import re as _re
    issues: list[str] = []

    for pattern in _BROKEN_CITATION_PATTERNS:
        if pattern in text:
            issues.append(f"broken_pattern:{pattern[:30]}")

    if _re.search(r'요미\s*(의\s*)?판단\s*:', text):
        issues.append("internal_label:yomi_judgment")
    if _re.search(r'\d+단계\s*:', text):
        issues.append("internal_label:step_label")

    # 문장 수: 마침표+공백 또는 마침표 끝으로 분리
    raw_sentences = [s.strip() for s in _re.split(r'(?<=[다요]\.)\s+', text) if s.strip()]
    if len(raw_sentences) < 3:
        issues.append(f"sentence_count_below_3:{len(raw_sentences)}")
    elif len(raw_sentences) > 5:
        issues.append(f"sentence_count_above_5:{len(raw_sentences)}")

    if len(text) > 500:
        issues.append(f"over_500_chars:{len(text)}")

    for sent in raw_sentences[:5]:
        if not any(sent.endswith(e) for e in _SENTENCE_ENDERS):
            issues.append(f"sentence_no_proper_ender:{sent[-15:]!r}")
            break

    return {"valid": not issues, "issues": issues}


def _build_ai_citation_summary(
    *,
    hook: str,
    yomi: str,
    real: str,
    faq_list: list,
    content_type: str = "",
    pattern_id: str = "",
) -> str:
    """AI 인용 요약 3~5문장을 완결된 자연문으로 생성한다.

    pattern_id별 고정 요약을 우선 사용하고, 없으면 슬롯 추출로 생성한다.
    """
    if pattern_id and pattern_id in _PATTERN_CITATION_SUMMARIES:
        return _PATTERN_CITATION_SUMMARIES[pattern_id]

    sentences: list[str] = []

    if hook:
        s = _extract_clean_sentence(hook)
        if s and s not in sentences:
            sentences.append(s)

    if yomi and len(sentences) < 3:
        s = _extract_clean_sentence(yomi)
        if s and s not in sentences:
            sentences.append(s)

    if real and len(sentences) < 4:
        first_line = real.split("\n")[0].strip()
        s = _extract_clean_sentence(first_line) if first_line else _extract_clean_sentence(real)
        if s and s not in sentences:
            sentences.append(s)

    if len(sentences) < 5 and content_type in ("tax_refund", "policy_deadline"):
        official = "세금·지원금·환급 정보는 관련 기관의 공식 안내 기준을 직접 확인하시기 바랍니다."
        if official not in sentences:
            sentences.append(official)

    if faq_list and len(sentences) < 5:
        for item in faq_list[:2]:
            if not isinstance(item, dict):
                continue
            a_text = str(item.get("A", "")).strip()
            if len(a_text) > 15:
                s = _extract_clean_sentence(a_text)
                if s and s not in sentences:
                    sentences.append(s)
                    break

    result = " ".join(sentences[:5])
    return result[:500] if len(result) > 500 else result


_PATTERN_DATE_DISCLAIMERS: dict[str, str] = {
    "tax_refund_hometax_check": "세금·정책 정보는 공식 안내에 따라 달라질 수 있습니다.",
    "viral_ott_reaction_decode": "이슈 관련 정보는 공식 안내와 후속 보도에 따라 달라질 수 있습니다.",
    "ai_work_time_savings": "AI 도구 기능과 요금은 서비스 정책에 따라 달라질 수 있습니다.",
    "ai_tool_comparison": "AI 도구 기능과 요금은 서비스 정책에 따라 달라질 수 있습니다.",
    "ai_automation_workflow": "AI 도구 기능과 요금은 서비스 정책에 따라 달라질 수 있습니다.",
    "ai_prompt_recipe": "AI 모델 동작과 출력은 버전·설정에 따라 달라질 수 있으므로 결과는 직접 검수하세요.",
    "ai_tool_review": "AI 도구의 요금·기능·무료 한도는 서비스 정책에 따라 바뀔 수 있으므로 공식 페이지를 확인하세요.",
    "ai_model_update": "AI 모델의 사양·요금·제공 범위는 공식 발표와 후속 업데이트에 따라 달라질 수 있습니다.",
    "ai_search_change": "AI 검색·답변엔진의 동작과 노출 기준은 플랫폼 정책에 따라 수시로 바뀔 수 있습니다.",
    "ai_blog_growth": "검색 알고리즘·애드센스 정책은 변경될 수 있으며 수익은 보장되지 않습니다.",
    "ai_comparison": "AI 도구·모델의 요금·성능은 서비스 정책에 따라 바뀌므로 공식 페이지에서 확인하세요.",
    "ai_risk_security": "AI 보안·저작권·데이터 정책은 서비스 약관과 법령에 따라 달라질 수 있습니다.",
    "ai_beginner_guide": "AI 도구의 기능·요금은 서비스 정책에 따라 달라질 수 있으므로 결과는 직접 확인하세요.",
    "delivery_money_checklist": "배달앱 배달비·쿠폰·최소주문금액 조건은 앱 정책에 따라 달라질 수 있습니다.",
    "platform_change_service_update": "플랫폼 서비스·약관·요금제는 운영사 정책에 따라 변경될 수 있습니다.",
    "consumer_warning_refund": "환불·소비자 보호 절차는 운영사 약관과 관련 법령에 따라 달라질 수 있습니다.",
    "policy_deadline_support": "정부·지자체 지원금은 사업 공고와 예산에 따라 변경될 수 있습니다.",
    "corporate_issue_decode": "기업 발표·공시 내용은 공식 채널과 후속 IR 발표에 따라 갱신될 수 있습니다.",
}

_PATTERN_META_TEMPLATES: dict[str, str] = {
    "tax_refund_hometax_check": (
        "홈택스·손택스에서 세금 환급금 조회 전 먼저 확인할 환급 유형, 계좌 등록, 신고 내역, "
        "보완 요청 체크리스트를 정리했습니다. 세금·환급 정보는 공식 안내에 따라 달라질 수 있습니다."
    ),
    "ai_work_time_savings": (
        "ChatGPT·AI 도구를 써도 업무 시간이 줄지 않는 이유와, 반복 단계 분리·검수 기준 설정으로 "
        "실제 시간을 줄이는 방법을 직장인 기준으로 정리했습니다."
    ),
    "ai_tool_comparison": (
        "ChatGPT·Claude 등 AI 도구 비교 전 확인할 응답 정확도, 무료 플랜 제한, "
        "유료 전환 기준, 실제 워크플로우 적합성 체크리스트를 정리했습니다."
    ),
    "ai_automation_workflow": (
        "AI 자동화 워크플로우 구성 전 반복 업무 분류, 검수 루프 설계, 파일럿 테스트 방법을 "
        "단계별로 정리했습니다. 도구 선택보다 자동화 프로세스 정의가 먼저입니다."
    ),
    "ai_prompt_recipe": (
        "복사해서 바로 쓰는 AI 프롬프트 템플릿과 보고서·요약 변형 예시, 결과물 품질 체크리스트를 "
        "정리했습니다. 역할·목적·출력 형식·제약을 고정해 결과를 안정시키는 방법입니다."
    ),
    "ai_tool_review": (
        "AI 도구를 직접 써보고 판단하는 기준과 추천·비추 대상, 무료/유료 경계, 최종 판정을 "
        "정리했습니다. 기능 목록이 아니라 내 반복 업무의 검수 시간으로 도구를 고르는 방법입니다."
    ),
    "ai_model_update": (
        "새 AI 모델 업데이트에서 무엇이 바뀌었는지, 확인된 사실과 과장된 기대를 구분하고 "
        "누가 영향을 받는지, 내 업무로 직접 비교하는 방법을 정리했습니다."
    ),
    "ai_search_change": (
        "AI 검색(AEO·GEO·SGE) 변화에서 내 블로그 글이 AI 답변에 인용되려면 무엇을 바꿔야 하는지 "
        "용어 정리부터 실전 단계까지 정리했습니다."
    ),
    "ai_blog_growth": (
        "AI 블로그에서 조회수를 망치는 글 구조를 피하고, 검수 루프를 갖춘 자동화로 "
        "검색 노출과 수익을 높이는 운영 기준을 정리했습니다."
    ),
    "ai_comparison": (
        "AI 도구·모델·요금제 비교에서 무료/유료 경계, 상황별 추천, 최종 판단 기준을 "
        "비교표로 정리했습니다. 절대 승자가 아니라 내 업무에 맞는 선택 기준입니다."
    ),
    "ai_risk_security": (
        "AI 사용 시 개인정보·보안·저작권·환각 리스크를 안전하게 관리하는 구체적 규칙과 "
        "입력 전 점검·결과 검증 단계를 정리했습니다."
    ),
    "ai_beginner_guide": (
        "AI를 처음 쓰는 초보자를 위해 용어를 쉽게 풀고, 무료로 시작하는 순서와 "
        "첫 시도 점검표를 정리했습니다."
    ),
    "viral_ott_reaction_decode": (
        "반응이 갈리는 이슈에서 확인된 사실, 이용자 영향, 커뮤니티 해석, 루머 구분 기준을 "
        "공식 안내와 신뢰 가능한 보도 중심으로 정리했습니다."
    ),
    "delivery_money_checklist": (
        "배달의민족·쿠팡이츠 등 배달앱 주문 전 배달비 조건, 쿠폰 적용 기준, "
        "최소주문금액을 확인해 최종 결제금액을 미리 파악하는 체크리스트를 정리했습니다."
    ),
    "platform_change_service_update": (
        "플랫폼 서비스 변경 공지가 떴을 때 내 계정·결제·기기 상태에서 변경 일자 전 점검할 "
        "체크리스트를 정리했습니다. 약관과 취소·환불 기준 변경도 함께 확인이 필요합니다."
    ),
    "consumer_warning_refund": (
        "환불·결제 오류·개인정보 유출 같은 소비자 피해 상황에서 증거 보존 순서와 운영사·소비자원 "
        "단계별 대응 방법, 필요한 기록 항목을 체크리스트로 정리했습니다."
    ),
    "policy_deadline_support": (
        "정부·지자체 지원금 신청 전 대상 조건, 소득 기준, 필요 서류, 신청 경로를 "
        "단계별로 확인할 수 있는 체크리스트를 정리했습니다. 마감 전 신청이 필요합니다."
    ),
    "corporate_issue_decode": (
        "기업 발표·공시 이슈에서 공식 입장과 외부 추측을 구분하고 소비자·투자자·"
        "이용자가 직접 확인할 채널과 후속 발표 추적 기준을 정리했습니다."
    ),
}

_BROKEN_META_PATTERNS: tuple[str, ...] = (
    "시작했기 확인할 항목",
    "높다 환급금",
    "복잡하지 않다 환급",
    "요미 판단:",
    "요미의 판단:",
    "1단계:",
    "2단계:",
)


def validate_meta_description(text: str) -> dict:
    """meta description 유효성 검사.

    Returns: {"valid": bool, "issues": list[str]}
    """
    import re as _re
    issues: list[str] = []
    if len(text) < 80:
        issues.append(f"too_short:{len(text)}")
    if len(text) > 160:
        issues.append(f"too_long:{len(text)}")
    for pattern in _BROKEN_META_PATTERNS:
        if pattern in text:
            issues.append(f"broken_pattern:{pattern[:30]}")
    # 연속 동일 단어만 금지 (예: "환급 환급", "조회 조회")
    words = _re.split(r'\s+', text)
    for i in range(len(words) - 1):
        if len(words[i]) >= 3 and words[i] == words[i + 1]:
            issues.append(f"consecutive_duplicate_word:{words[i]}")
            break
    return {"valid": not issues, "issues": issues}


def _build_meta_description(
    *,
    hook: str,
    real: str,
    actions_list: list,
    topic_str: str,
    selected_title: str = "",
    content_type: str = "",
    pattern_id: str = "",
) -> str:
    """80~160자 meta description을 생성한다.

    pattern_id별 고정 템플릿을 우선 사용하고, 없으면 슬롯 조합으로 생성한다.
    """
    if is_english_mode():
        return _build_meta_description_en(
            hook=hook, real=real, topic_str=topic_str, selected_title=selected_title
        )
    keyword = (selected_title or topic_str)[:50]

    if pattern_id == "policy_deadline_support":
        subject = re.sub(
            r"(신청방법과 대상 조건|신청방법|대상 조건|신청 전 먼저 볼 \d+가지|먼저 볼 \d+가지|정리)",
            "",
            (selected_title or topic_str or "").strip(),
        )
        subject = re.sub(r"\s+", " ", subject).strip(" ,")
        if subject and subject not in {"지원금", "정부 지원금", "지자체 지원금"}:
            desc = (
                f"{subject} 신청 전 대상 조건, 지원 금액, 신청 기간, 필요 서류, 공식 확인처를 "
                "한 번에 점검하는 체크리스트입니다."
            )
            if 80 <= len(desc) <= 160:
                return desc.strip()

    if pattern_id and pattern_id in _PATTERN_META_TEMPLATES:
        desc = _PATTERN_META_TEMPLATES[pattern_id]
        if 80 <= len(desc) <= 160:
            return desc.strip()

    check_items: list[str] = []
    for item in (actions_list or [])[:4]:
        if isinstance(item, dict):
            action = str(item.get("행동", "")).strip()
            if action and len(action) <= 16:
                check_items.append(action)

    hook_sent = _extract_clean_sentence(hook, max_len=80) if hook else ""
    real_line = ""
    if real:
        rl = real.split("\n")[0].strip()
        real_line = _extract_clean_sentence(rl, max_len=60) if rl else ""
    items_str = "·".join(check_items[:3]) if check_items else ""

    if hook_sent and items_str:
        desc = f"{hook_sent} 확인할 항목: {items_str} 등 핵심 체크리스트를 정리했습니다."
    elif hook_sent:
        desc = hook_sent
        if len(desc) < 80 and real_line:
            desc = (desc + " " + real_line).strip()
        if len(desc) < 80 and items_str:
            desc = (desc + " 확인 항목: " + items_str + "을 순서대로 정리했습니다.").strip()
    elif items_str:
        desc = f"{keyword}를 확인하기 위해 {items_str} 등 핵심 항목을 정리했습니다."
    elif real_line:
        desc = real_line
    else:
        tail = "의 핵심 확인 항목과 순서, 독자가 놓치기 쉬운 주의점을 단계별로 정리했습니다."
        desc = keyword + tail

    if content_type in ("tax_refund", "policy_deadline") and len(desc) < 120:
        note = " 세금·환급 정보는 공식 안내에 따라 달라질 수 있습니다."
        if note not in desc:
            desc = desc + note

    if len(desc) > 160:
        cut = desc[:157]
        for sep in ("다. ", "요. ", ". "):
            pos = cut.rfind(sep)
            if pos > 80:
                desc = cut[:pos + 1].strip()
                break
        else:
            desc = cut + "..."

    if len(desc) < 80:
        tail = "의 핵심 확인 항목과 순서, 독자가 놓치기 쉬운 주의점을 단계별로 정리했습니다."
        desc = keyword + tail

    return desc.strip()


def _build_meta_description_en(*, hook: str, real: str, topic_str: str, selected_title: str) -> str:
    """영어 모드 meta description — 80~160자 계약 동일, '. ' 경계에서만 절단."""
    keyword = " ".join((selected_title or topic_str or "this AI update").split()).strip()[:70]
    filler = "Key facts, pricing, and what to check before you use it — updated with sources."
    first = ""
    for source in (hook, (real or "").split("\n")[0]):
        text = " ".join((source or "").split())
        match = re.match(r".+?[.!?](?=\s|$)", text)
        candidate = (match.group(0) if match else text).strip()
        if 30 <= len(candidate) <= 110 and candidate.endswith((".", "!", "?")):
            first = candidate
            break
    desc = f"{first} {filler}".strip() if first else f"{keyword}: {filler}"
    if len(desc) > 160:
        cut = desc[:157]
        pos = cut.rfind(". ")
        if pos > 80:
            desc = cut[: pos + 1].strip()
        else:
            desc = cut.rsplit(" ", 1)[0].rstrip(" ,;—-") + "."
    if len(desc) < 80:
        desc = f"{desc} {filler}".strip()[:160]
    return desc.strip()


def _unmatched_html(topic: str) -> str:
    _html_lang = "en" if is_english_mode() else "ko"
    return (
        f'<!DOCTYPE html><html lang="{_html_lang}"><head><meta charset="utf-8">'
        f'<title>[PREVIEW — NO MATCH] {escape(topic)}</title></head>'
        f'<body><p>패턴 매칭 실패: <strong>{escape(topic)}</strong> — '
        f'등록된 패턴과 일치하지 않아 preview를 생성할 수 없습니다.</p></body></html>'
    )
