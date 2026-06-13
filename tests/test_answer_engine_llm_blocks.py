from __future__ import annotations

import re

from blogspot_automation.services.answer_engine_policy import ensure_answer_engine_optimized_html
from blogspot_automation.services.geo_intent_service import GeoIntentService

_BODY = (
    '<article class="yomi-clean-post">'
    '<span class="yomi-kicker">2026.06.10 기준 오늘 이슈</span>'
    '<section class="yomi-lede"><p>핵심 답변 문단입니다. 오늘 이슈의 결론을 먼저 제시합니다.</p></section>'
    '<div class="yomi-thesis"><p>관점 비교 모듈.</p></div>'
    '<ul class="yomi-list"><li data-step="1">확인 순서.</li></ul>'
    "</article>"
)

_LLM_FAQ = [
    {"question": "장마 정의 개편은 언제부터 적용되나요?", "answer": "기상학계 논의에 따라 이르면 내년부터 적용 가능성이 보도됐습니다. 확정은 기상청 발표를 봐야 합니다."},
    {"question": "비가 안 와도 장마철로 분류되는 이유는 무엇인가요?", "answer": "정체전선 위치와 수증기 유입량 기준 제안 때문입니다. 강수량만으로는 설명이 어렵다는 판단입니다."},
    {"question": "새 장마 정의가 일상에 주는 영향은 무엇인가요?", "answer": "장마 예보 기간과 침수 대비 안내 시점이 달라질 수 있습니다. 보험 기준일에도 영향이 가능합니다."},
]


def _render(**kwargs) -> str:
    return ensure_answer_engine_optimized_html(
        _BODY,
        title="비 안 와도 장마철? 기상학계, 장마 정의 새로 손본다",
        topic="장마 정의 개편",
        content_type="today_issue_explainer",
        topic_group="today_issue",
        **kwargs,
    )


def test_intent_block_uses_llm_faq_when_available() -> None:
    html = _render(faq_items=_LLM_FAQ)
    intent = re.search(r'<section id="INTENT_ANSWER_BLOCK".*?</section>', html, flags=re.DOTALL)
    assert intent is not None
    # 이슈 특정적 LLM 질문이 visible 블록에 쓰였는지 (템플릿 질문 아님)
    assert "장마 정의 개편은 언제부터 적용되나요?" in intent.group(0)
    assert "지금 확인된 내용은 무엇인가요" not in intent.group(0)


def test_intent_block_falls_back_to_template_without_faq_items() -> None:
    html = _render()
    intent = re.search(r'<section id="INTENT_ANSWER_BLOCK".*?</section>', html, flags=re.DOTALL)
    assert intent is not None
    assert "intent-qa-item" in intent.group(0)


def test_confirmed_block_uses_llm_facts_when_available() -> None:
    html = _render(
        faq_items=_LLM_FAQ,
        confirmed_facts=[
            "기상학회가 장마 정의 개편 논의를 공식화했다.",
            "복수 매체가 정체전선 기준 제안을 보도했다.",
        ],
        check_needed=["새 정의의 적용 시점은 기상청 발표를 확인해야 한다."],
    )
    block = re.search(r'<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK".*?</section>', html, flags=re.DOTALL)
    assert block is not None
    assert "기상학회가 장마 정의 개편 논의를 공식화했다." in block.group(0)
    assert "새 정의의 적용 시점은 기상청 발표를 확인해야 한다." in block.group(0)


def test_confirmed_block_falls_back_when_llm_facts_partial() -> None:
    # confirmed만 있고 check_needed가 없으면 템플릿 유지 (반쪽 데이터 방지)
    html = _render(confirmed_facts=["기상학회가 장마 정의 개편 논의를 공식화했다."], check_needed=[])
    block = re.search(r'<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK".*?</section>', html, flags=re.DOTALL)
    assert block is not None
    assert "기상학회가 장마 정의 개편 논의를 공식화했다." not in block.group(0)


def test_source_trust_today_issue_varies_by_seed() -> None:
    svc = GeoIntentService()
    texts = {
        svc.generate_enhanced_source_trust_block(
            "today_issue_explainer", "today_issue", "", "2026-06-10", seed=seed,
        )
        for seed in ("손흥민 이적", "장마 정의 개편", "넷플릭스 요금제", "전세사기 특별법", "BTS 컴백")
    }
    # 5개 토픽이면 최소 2가지 이상 변주가 나와야 한다.
    assert len(texts) >= 2


def test_body_faq_relocated_to_tail() -> None:
    # FAQ가 본문 중간에 끼면 글 끝(확인된 것 블록 앞)으로 이동해야 한다
    body = (
        '<article class="yomi-clean-post">'
        '<span class="yomi-kicker">2026.06.11 기준 오늘 이슈</span>'
        '<section class="yomi-lede"><p>핵심 답변 문단입니다.</p></section>'
        '<h2>전개 섹션</h2><p>본문 전개.</p>'
        '<section class="yomi-faq"><h2>자주 묻는 질문</h2>'
        "<article><h3>질문 하나는 무엇인가요?</h3><p>답변입니다.</p></article></section>"
        "<h2>결론 섹션, 이것만 보면 됩니다</h2><p>마무리 판단.</p>"
        '<div class="yomi-thesis"><p>모듈.</p></div>'
        "</article>"
    )
    html = ensure_answer_engine_optimized_html(
        body,
        title="테스트 제목",
        topic="테스트 주제",
        content_type="today_issue_explainer",
        topic_group="today_issue",
    )
    faq_pos = html.find("자주 묻는 질문")
    conclusion_pos = html.find("결론 섹션, 이것만 보면 됩니다")
    confirmed_pos = html.find('id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"')
    assert faq_pos > conclusion_pos > 0, "FAQ가 본문(결론) 뒤로 이동해야 함"
    assert 0 < faq_pos < confirmed_pos, "FAQ는 확인된 것 블록 앞에 위치해야 함"
