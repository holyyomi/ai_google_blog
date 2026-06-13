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


def test_demotes_loose_body_questions_keeps_structured_blocks() -> None:
    html = (
        '<article class="yomi-clean-post">'
        "<h2>왜 지금 주목받나요?</h2><p>본문.</p>"
        "<h2>나는 해당될까?</h2><p>본문.</p>"
        "<h2>어떤 영향이 있나요?</h2><p>본문.</p>"
        '<section id="INTENT_ANSWER_BLOCK" class="yomi-faq">'
        '<article class="intent-qa-item"><h3>왜 관심이 커졌나요?</h3><p>답.</p></article>'
        '<article class="intent-qa-item"><h3>무엇을 확인하나요?</h3><p>답.</p></article>'
        '<article class="intent-qa-item"><h3>일시적 유행인가요?</h3><p>답.</p></article>'
        "</section>"
        "</article>"
    )
    assert _count_q_headings(html) == 6

    out = _demote_excess_question_headings(html, max_count=5)

    assert _count_q_headings(out) == 5
    # 구조화된 intent-qa-item 질문은 모두 보존.
    assert out.count('class="intent-qa-item"') == 3
    assert "왜 관심이 커졌나요?" in out and "일시적 유행인가요?" in out
    # 느슨한 본문 질문 1개가 강등됨.
    assert "yomi-subhead" in out


def test_no_change_when_within_budget() -> None:
    html = "<h2>먼저 볼 핵심</h2><h2>왜 지금인가요?</h2><h3>무엇을 보나요?</h3>"
    assert _demote_excess_question_headings(html, max_count=5) == html
