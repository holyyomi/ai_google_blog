from __future__ import annotations

import re

from blogspot_automation.services.trending_article_service import TrendingArticleService


def _faq_article_count(html: str) -> int:
    section = re.search(
        r'<section\b[^>]*class=["\'][^"\']*yomi-faq[^"\']*["\'][^>]*>.*?</section>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not section:
        return 0
    return len(re.findall(r"<article\b", section.group(0), flags=re.IGNORECASE))


def test_caps_faq_items_to_two() -> None:
    faq = "".join(
        f"<article><h3>질문{i}인가요?</h3><p>답변{i} 충분히 긴 문장으로 작성합니다.</p></article>"
        for i in range(5)
    )
    html = f'<article class="yomi-clean-post"><section class="yomi-faq">{faq}</section></article>'

    out = TrendingArticleService._cap_yomi_faq_items(html, max_items=2)

    assert _faq_article_count(out) == 2
    assert "질문0" in out and "질문1" in out
    assert "질문2" not in out and "질문4" not in out


def test_keeps_faq_when_within_budget() -> None:
    faq = "".join(
        f"<article><h3>질문{i}인가요?</h3><p>답변{i} 입니다.</p></article>" for i in range(2)
    )
    html = f'<section class="yomi-faq">{faq}</section>'
    out = TrendingArticleService._cap_yomi_faq_items(html, max_items=2)
    assert _faq_article_count(out) == 2


def test_passthrough_without_faq_section() -> None:
    html = "<article class='yomi-clean-post'><p>본문만 있습니다.</p></article>"
    assert TrendingArticleService._cap_yomi_faq_items(html) == html
