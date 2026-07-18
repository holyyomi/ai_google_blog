from __future__ import annotations

import re

from blogspot_automation.services.answer_engine_policy import (
    _demote_excess_question_headings,
    _heading_text_is_question,
)
from blogspot_automation.services.final_html_audit_service import (
    _heading_text_is_question as audit_is_question,
)


def test_question_detection_excludes_statement_ending_in_yo() -> None:
    # '필요/중요/내용'처럼 '요'로 끝나는 서술형은 질문이 아니다.
    assert not _heading_text_is_question("직접 확인 필요")
    assert not _heading_text_is_question("핵심 내용 정리")
    # 실제 질문은 인정.
    assert _heading_text_is_question("왜 지금 주목받나요?")
    assert _heading_text_is_question("어떤 영향이 있나요")
    assert _heading_text_is_question("무엇을 확인하나")
    # audit과 answer_engine 탐지가 동일 규약이어야 한다.
    for t in ["직접 확인 필요", "왜 지금 주목받나요?", "일시적 유행인가요?"]:
        assert _heading_text_is_question(t) == audit_is_question(t)


def _count_q_headings(html: str) -> int:
    heads = re.findall(r"<h[123]\b[^>]*>(.*?)</h[123]>", html, flags=re.IGNORECASE | re.DOTALL)
    return sum(1 for h in heads if _heading_text_is_question(re.sub(r"<[^>]+>", " ", h)))


def test_demotes_loose_body_questions_when_they_alone_exceed_budget() -> None:
    """본문 자체 질문형 h2가 max_count를 넘으면 초과분만 <p>로 강등한다."""
    html = (
        '<article class="yomi-clean-post">'
        "<h2>왜 지금 주목받나요?</h2><p>본문.</p>"
        "<h2>나는 해당될까?</h2><p>본문.</p>"
        "<h2>어떤 영향이 있나요?</h2><p>본문.</p>"
        "<h2>무엇이 달라지나요?</h2><p>본문.</p>"
        "<h2>언제 적용되나요?</h2><p>본문.</p>"
        "<h2>비용은 얼마인가요?</h2><p>본문.</p>"
        "</article>"
    )
    assert _count_q_headings(html) == 6

    out = _demote_excess_question_headings(html, max_count=5)

    assert _count_q_headings(out) == 5
    assert "yomi-subhead" in out


def test_intent_answer_block_questions_exempt_from_budget_regardless_of_count() -> None:
    """INTENT_ANSWER_BLOCK은 본문 저자가 쓴 게 아니라 시스템이 붙이는 합성
    AEO Q&A라, 본문 질문형 헤딩 예산(max_count)과 무관하게 개수 집계·강등
    양쪽에서 완전히 제외된다.

    2026-07-18 실측 사고: 영어 전환 후 모든 서술형 글이 본문 자체 FAQ 3개 +
    이 블록의 합성 질문 3개를 동시에 갖는 것이 표준 형태가 됐다(둘만 합쳐도
    6개로 max_count=5를 넘는다). TL;DR 위치 버그(has_author_answer_sections)를
    고치자 이 블록이 문서 앞쪽으로 올 수 있게 됐고, 예전처럼 '문서 순서상
    앞의 것'을 강등 후보로 고르는 로직과 맞물려 이 블록의 질문이 강등되며
    FAQ 답 추출이 깨졌다(faq_answer_too_short). 이제는 이 블록의 질문이
    본문에 몇 개가 있든, 심지어 본문 질문이 전혀 없어도 예산 계산에
    아무 영향을 주지 않아야 한다.
    """
    html = (
        '<article class="yomi-clean-post">'
        '<section id="INTENT_ANSWER_BLOCK" class="yomi-faq">'
        '<article class="intent-qa-item"><h3>왜 관심이 커졌나요?</h3><p>답.</p></article>'
        '<article class="intent-qa-item"><h3>무엇을 확인하나요?</h3><p>답.</p></article>'
        '<article class="intent-qa-item"><h3>일시적 유행인가요?</h3><p>답.</p></article>'
        "</section>"
        '<section class="faq faq-block">'
        '<div class="faq-card"><h3>비용이 드나요?</h3><p>답.</p></div>'
        '<div class="faq-card"><h3>무료 한도는 얼마인가요?</h3><p>답.</p></div>'
        '<div class="faq-card"><h3>취소는 어떻게 하나요?</h3><p>답.</p></div>'
        "</section>"
        "</article>"
    )
    # 외부에서 보면 6개(intent 3 + faq-card 3) 전부 여전히 <h3>다 — 아무것도
    # 강등되지 않는다. 둘 다 "구조화된" 것으로 보호되고, intent는 예산 집계
    # 자체에서 제외되므로 애초에 초과로 판단되지 않는다.
    out = _demote_excess_question_headings(html, max_count=5)
    assert out == html
    assert out.count("<h3>") == 6


def test_no_change_when_within_budget() -> None:
    html = "<h2>먼저 볼 핵심</h2><h2>왜 지금인가요?</h2><h3>무엇을 보나요?</h3>"
    assert _demote_excess_question_headings(html, max_count=5) == html
