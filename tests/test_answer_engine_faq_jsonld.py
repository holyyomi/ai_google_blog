from __future__ import annotations

import json
import re

from blogspot_automation.services.answer_engine_policy import (
    _normalize_llm_faq_pairs,
    ensure_answer_engine_optimized_html,
)

_BODY = (
    '<article class="yomi-clean-post">'
    '<span class="yomi-kicker">2026.06.10 기준 오늘 이슈</span>'
    '<section class="yomi-lede"><p>핵심 답변 문단입니다. 오늘 이슈의 결론을 먼저 제시합니다.</p></section>'
    '<div class="yomi-thesis"><p>관점 비교 모듈.</p></div>'
    '<ul class="yomi-list"><li data-step="1">확인 순서.</li></ul>'
    "</article>"
)

_LLM_FAQ = [
    {"question": "장마 정의 개편은 언제부터 적용되나요?", "answer": "기상학계 논의 결과에 따라 이르면 내년 장마철부터 새 기준이 적용될 수 있다는 보도가 나왔습니다. 확정 시점은 기상청 공식 발표를 봐야 합니다."},
    {"question": "비가 안 와도 장마철로 분류되는 이유는 무엇인가요?", "answer": "정체전선의 위치와 수증기 유입량 기준으로 장마를 정의하자는 제안 때문입니다. 강수량만으로는 최근 기후 패턴을 설명하기 어렵다는 판단입니다."},
    {"question": "새 장마 정의가 일상에 주는 영향은 무엇인가요?", "answer": "장마 예보 기간과 침수 대비 안내 시점이 달라질 수 있습니다. 보험·농작물 관리 기준일에도 연쇄 영향이 가능합니다."},
]


def _extract_faq_jsonld(html: str) -> dict:
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, flags=re.DOTALL):
        payload = json.loads(m.group(1))
        if payload.get("@type") == "FAQPage":
            return payload
    return {}


def test_faq_jsonld_prefers_llm_faq_items() -> None:
    html = ensure_answer_engine_optimized_html(
        _BODY,
        title="비 안 와도 장마철? 기상학계, 장마 정의 새로 손본다",
        topic="장마 정의 개편",
        content_type="today_issue_explainer",
        topic_group="today_issue",
        faq_items=_LLM_FAQ,
    )
    payload = _extract_faq_jsonld(html)
    names = [e["name"] for e in payload.get("mainEntity", [])]
    # LLM의 이슈 특정적 질문이 구조화 데이터에 들어가야 한다 (템플릿 질문 아님).
    assert "장마 정의 개편은 언제부터 적용되나요?" in names
    assert all("핵심 내용은 무엇인가요" not in n for n in names)


def test_faq_jsonld_falls_back_to_template_when_faq_items_invalid() -> None:
    html = ensure_answer_engine_optimized_html(
        _BODY,
        title="비 안 와도 장마철? 기상학계, 장마 정의 새로 손본다",
        topic="장마 정의 개편",
        content_type="today_issue_explainer",
        topic_group="today_issue",
        faq_items=[{"question": "짧음", "answer": "x"}],  # 전부 필터됨
    )
    payload = _extract_faq_jsonld(html)
    # 폴백이라도 FAQPage 구조화 데이터는 반드시 존재해야 한다.
    assert payload.get("@type") == "FAQPage"
    assert len(payload.get("mainEntity", [])) >= 1


def test_normalize_llm_faq_pairs_filters_and_dedupes() -> None:
    items = [
        {"question": "장마 정의 개편은 언제부터 적용되나요?", "answer": "이르면 내년 장마철부터 적용될 수 있다는 보도가 나왔습니다."},
        {"question": "장마 정의 개편은 언제부터 적용되나요?", "answer": "중복 질문이므로 제거되어야 합니다. 동일 키 중복."},
        {"question": "짧", "answer": "질문이 너무 짧아 제거되어야 합니다."},
        {"question": "답변이 너무 짧은 경우는 어떻게 되나요?", "answer": "짧음"},
        "not-a-dict",
    ]
    pairs = _normalize_llm_faq_pairs(items)  # type: ignore[arg-type]
    assert len(pairs) == 1
    assert pairs[0]["Q"] == "장마 정의 개편은 언제부터 적용되나요?"


def test_normalize_llm_faq_pairs_caps_at_five() -> None:
    items = [
        {"question": f"질문 항목 번호 {i}는 무엇인가요?", "answer": f"답변 {i}입니다. 충분히 긴 답변 텍스트를 제공합니다."}
        for i in range(8)
    ]
    assert len(_normalize_llm_faq_pairs(items)) == 5
