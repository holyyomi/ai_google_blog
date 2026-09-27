"""2026-09-26 라이브 글 사고 회귀 방지.

1. 내부링크 목록이 FAQ 1번과 2번 사이에 박혔다(첫 </article> = 중첩 faq-item).
2. 별자리 운세 글·무관한 글이 "2026" 같은 토큰 하나로 내부링크에 붙었다.
3. GEO 블록 소제목("Start here")이 FAQ 질문으로 되풀이됐다.
"""
from blogspot_automation.services import seo_policy
from blogspot_automation.services.answer_engine_policy import _section_derived_intent_pool
from blogspot_automation.services.seo_policy import (
    ASTROLOGY_TITLE_RE,
    append_internal_links_block,
    build_internal_links_from_history,
)


def test_links_block_goes_after_nested_faq_items(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    html = (
        "<article><h1>T</h1><section class='faq'>"
        "<article class='faq-item'><h3>Q1</h3><p>A1</p></article>"
        "<article class='faq-item'><h3>Q2</h3><p>A2</p></article>"
        "</section></article>"
    )
    out = append_internal_links_block(html, links=[("Gemini API quota", "https://holyyomiai.blogspot.com/2026/09/x.html")])
    assert out.index("yomi-internal-links") > out.index("Q2")


def _rec(title, url, topic=""):
    return {"title": title, "url": url, "published": True, "status": "published",
            "selected_topic": topic or title, "run_at": "2026-09-20T00:00:00"}


def test_unrelated_and_astrology_posts_are_not_linked(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setattr(seo_policy, "_liveness_check_enabled", lambda: False)
    monkeypatch.setattr(seo_policy, "_record_title_is_safe_for_internal_link", lambda r, title: True)
    records = [
        _rec("Gemini Shani Horoscope Today, 19th September 2026", "https://holyyomiai.blogspot.com/2026/09/gemini-shani-horoscope.html"),
        _rec("Copilot How to Use Agents: Project Delta Digest 2026", "https://holyyomiai.blogspot.com/2026/09/copilot-agents.html"),
        _rec("Gemini API Rate Limit 429 Error Fix", "https://holyyomiai.blogspot.com/2026/09/gemini-api-429.html"),
    ]
    links = build_internal_links_from_history(
        records, current_title="Gemini Free API Limits 2026: 250 Requests per Day", limit=3
    )
    urls = [u for _, u in links]
    assert urls == ["https://holyyomiai.blogspot.com/2026/09/gemini-api-429.html"]


def test_astrology_regex_ignores_ai_gemini():
    assert ASTROLOGY_TITLE_RE.search("Gemini Shani Horoscope Today")
    assert not ASTROLOGY_TITLE_RE.search("Gemini 3 Pro pricing and limits")


def test_system_block_heading_not_turned_into_faq():
    body = "x " * 40
    html = (
        f"<article><h2>Start here</h2><p>{body} free tier gives 250 requests per day.</p>"
        f"<h2>The change, step back</h2><p>{body} knowing what changed decides.</p>"
        f"<h2>How authentication changes your quota</h2><p>{body} the credential decides the tier.</p></article>"
    )
    qs = [qa["Q"] for qa in _section_derived_intent_pool(html)]
    assert not any("Start here" in q or "step back" in q for q in qs)
    assert any("authentication" in q for q in qs)
