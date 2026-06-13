from __future__ import annotations

from scripts.audit_ai_blog_live import audit_home_html, extract_recent_post_urls


def test_audit_home_html_blocks_legacy_today_issue_profile_text() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="https://holyyomiai.blogspot.com/">
      <meta name="description" content="AI 기술과 트렌드를 정리합니다">
      <meta property="og:description" content="AI 기술과 트렌드를 정리합니다">
    </head><body>
      <h1>holyyomi AI Insight</h1>
      <p>오늘의 이슈 해부 | 생활 뉴스 핵심 정리</p>
    </body></html>
    """

    result = audit_home_html(html)

    assert "legacy_today_issue_phrase_visible" in result["issues"]


def test_audit_home_html_passes_ai_brand_home() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="https://holyyomiai.blogspot.com/">
      <meta name="description" content="AI 기술과 트렌드를 정리합니다">
      <meta property="og:description" content="AI 기술과 트렌드를 정리합니다">
    </head><body>
      <h1>holyyomi AI Insight</h1>
      <p>AI 기술과 트렌드를 쉽고 명확하게 정리합니다.</p>
    </body></html>
    """

    result = audit_home_html(html)

    assert result["issues"] == []
    assert result["home_meta_description_present"] is True


def test_extract_recent_post_urls_normalizes_mixed_case_blogspot_host() -> None:
    html = """
    <a href="https://holyyomiAI.blogspot.com/2026/01/notebooklm.html">A</a>
    <a href="https://holyyomiai.blogspot.com/2026/01/chatgpt.html">B</a>
    """

    urls = extract_recent_post_urls(html, base="https://holyyomiai.blogspot.com/")

    assert urls == [
        "https://holyyomiai.blogspot.com/2026/01/notebooklm.html",
        "https://holyyomiai.blogspot.com/2026/01/chatgpt.html",
    ]
