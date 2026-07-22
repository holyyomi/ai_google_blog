"""헤지 문구 포화 게이트 테스트 (2026-07-22).

2026-07-21 발행 2건 실측: "check the official page"/"not published"류 헤지가
글당 29·36회 등장해 가격비교 글에 정작 가격이 없었다. 생성기 검증기(10회
재생성 유도)와 발행 게이트(최종 HTML 14회 차단)가 이를 잡는지 검증한다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services.llm_content_service import (
    _ContentValidationError,
    _validate_generated_content,
    hedge_phrase_hits_en,
)
from blogspot_automation.services.news_quality_gate import NewsQualityGate


@pytest.fixture(autouse=True)
def _english_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")


def test_hedge_phrase_hits_counts_variants():
    text = (
        "<p>Pricing is not published. Limits are unconfirmed. "
        "Check the official pricing page. Student rates aren't disclosed. "
        "Consult the official docs. Free caps remain unpublished.</p>"
    )
    hits = hedge_phrase_hits_en(text)
    assert len(hits) == 6


def test_hedge_phrase_hits_ignores_normal_prose():
    text = (
        "<p>ChatGPT Plus costs $20 a month as of July 2026 per OpenAI's pricing page. "
        "Claude Pro also costs $20. The free tier covers casual use.</p>"
    )
    assert hedge_phrase_hits_en(text) == []


def test_gate_blocks_hedge_saturated_article():
    hedge = "Pricing is not published — check the official pricing page. "
    result = NewsQualityGate._hedge_saturation("<p>" + hedge * 10 + "</p>")
    assert result["count"] >= 14
    assert result["samples"]


def test_gate_helper_zero_in_korean_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    hedge = "Pricing is not published — check the official pricing page. "
    result = NewsQualityGate._hedge_saturation("<p>" + hedge * 10 + "</p>")
    assert result["count"] == 0


def _valid_en_skeleton(filler: str) -> str:
    """검증기의 다른 결함 검사(길이·태그 균형·반복·FAQ)를 통과하는 최소 EN 본문."""
    base_words = " ".join(
        f"ChatGPT Plus handles workload number {i} well for {i + 2} daily office tasks."
        for i in range(200)
    )
    return (
        "<h2>Pricing and limits</h2>"
        f"<p>{base_words}</p>"
        f"<p>{filler}</p>"
        '<section class="faq-section"><article class="faq-item">'
        '<h3 class="faq-q">Is it worth it?</h3>'
        '<p class="faq-a">Yes when your usage exceeds the free tier every single day.</p>'
        "</article></section>"
    )


def test_validator_rejects_hedge_saturated_output():
    filler = "Exact limits are not published. Check the official pricing page. " * 6
    with pytest.raises(_ContentValidationError, match="헤지"):
        _validate_generated_content(_valid_en_skeleton(filler))


def test_validator_passes_normal_hedge_level():
    filler = "Regional prices vary, so check the official pricing page once before you subscribe."
    _validate_generated_content(_valid_en_skeleton(filler))
