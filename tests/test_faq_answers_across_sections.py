"""FAQ 답변 추출이 쪼개진 FAQ 섹션을 모두 읽는지(2026-09-27 회귀 방지).

리허설 run 36324354946: 본문 FAQ가 질문 하나짜리 <section class="yomi-faq"> 여러 개로
쪼개져 나왔고, 첫 섹션만 읽던 추출기가 답변 1개로 세어 faq_answer_too_short 로
HN 2,234점 이슈 글을 막았다.
"""
from blogspot_automation.services.news_quality_gate import NewsQualityGate as G

A = "A complete answer that is clearly longer than twenty characters."


def _item(q: str) -> str:
    return f'<article class="faq-item"><h3 class="faq-q">{q}</h3><p class="faq-a">{A}</p></article>'


def test_answers_are_collected_from_split_sections():
    html = (
        f'<section class="yomi-faq">{_item("Q1?")}</section>'
        f'<section class="yomi-faq">{_item("Q2?")}</section>'
        f'<section class="yomi-faq" id="INTENT_ANSWER_BLOCK" data-yomi-engine="aeo">{_item("Q3?")}</section>'
    )
    assert len(G._faq_answers(html)) == 3
    assert G._faq_questions(html) == ["Q1?", "Q2?", "Q3?"]


def test_single_section_still_works():
    html = f'<section class="faq-section">{_item("Q1?")}{_item("Q2?")}{_item("Q3?")}</section>'
    assert len(G._faq_answers(html)) == 3


def test_geo_block_placed_before_body_faq_is_still_skipped():
    # 2026-07-18 사고 재현: id 가 class 앞에 오는 GEO 블록은 FAQ 로 세지 않는다.
    geo = '<section id="INTENT_ANSWER_BLOCK" class="yomi-faq"><h3>Short</h3><p>tiny</p></section>'
    body = f'<section class="faq-section">{_item("Q1?")}{_item("Q2?")}{_item("Q3?")}</section>'
    answers = G._faq_answers(geo + body)
    assert len(answers) == 3 and all(len(a) >= 20 for a in answers)
