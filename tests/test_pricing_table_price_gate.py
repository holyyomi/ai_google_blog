"""가격축 글 비교표 실측치 게이트 테스트 (2026-07-22).

2026-07-21 발행 실측: "Pricing Compared" 글의 비교표에 가격 컬럼이 아예 없었고,
"Student Pricing" 글의 가격 셀은 전부 "Not published — check official page"였다.
가격을 약속한 제목의 글은 표에 검증된 가격 셀이 최소 2개는 있어야 한다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services.news_quality_gate import NewsQualityGate


@pytest.fixture(autouse=True)
def _english_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")


def _table(cells: list[str]) -> str:
    rows = "".join(f"<tr><td>Tool</td><td>{c}</td></tr>" for c in cells)
    return (
        '<div class="quick-decision-table"><table><thead><tr><th>Tool</th><th>Price</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def test_blocks_pricing_title_with_deferral_only_table():
    html = _table(["Not published — check official page"] * 5)
    result = NewsQualityGate._pricing_table_price_cells(
        html, title="ChatGPT Gemini Copilot Student Pricing 2026", content_type="ai_work_tip"
    )
    assert result["is_pricing_family"] is True
    assert result["table_present"] is True
    assert result["price_cell_count"] == 0


def test_passes_pricing_table_with_real_prices():
    html = _table(["$20/month", "$25 per seat", "Free tier available", "check official page"])
    result = NewsQualityGate._pricing_table_price_cells(
        html, title="AI Assistant Pricing Compared 2026", content_type="ai_work_tip"
    )
    assert result["is_pricing_family"] is True
    assert result["price_cell_count"] >= 3


def test_non_pricing_family_not_checked():
    html = _table(["good for essays", "good for code"])
    result = NewsQualityGate._pricing_table_price_cells(
        html, title="How to fix Claude file upload errors", content_type="ai_work_tip"
    )
    assert result["is_pricing_family"] is False


def test_pricing_family_without_table_is_deferred_to_table_warning():
    result = NewsQualityGate._pricing_table_price_cells(
        "<p>ChatGPT Plus costs $20 as of July 2026.</p>",
        title="ChatGPT pricing guide 2026",
        content_type="ai_work_tip",
    )
    assert result["is_pricing_family"] is True
    assert result["table_present"] is False


def test_korean_mode_skips_check(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    html = _table(["확인 필요"] * 5)
    result = NewsQualityGate._pricing_table_price_cells(
        html, title="ChatGPT pricing 2026", content_type="ai_work_tip"
    )
    assert result["is_pricing_family"] is False
