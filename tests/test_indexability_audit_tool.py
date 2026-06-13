from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import indexability_audit as ia  # noqa: E402


def test_is_weak_slug_detects_numeric_and_blogpost():
    assert ia._is_weak_slug("70")
    assert ia._is_weak_slug("80-10-4")
    assert ia._is_weak_slug("blog-post")
    assert ia._is_weak_slug("blog-post_123")
    assert not ia._is_weak_slug("ps5-today-issue-update-news")


def test_robots_indexable():
    assert ia._robots_indexable("<meta name='robots' content='index,follow'/>")
    assert not ia._robots_indexable("<meta name='robots' content='noindex,follow'/>")
    assert not ia._robots_indexable("<meta name='robots' content='index,nofollow'/>")
    # no robots meta => default indexable
    assert ia._robots_indexable("<head></head>")


def test_canonical_self():
    url = "https://x.blogspot.com/2026/06/a.html"
    assert ia._canonical_self(url, f"<link rel='canonical' href='{url}'/>")
    assert not ia._canonical_self(url, "<link rel='canonical' href='https://x.blogspot.com/'/>")
    assert not ia._canonical_self(url, "<head></head>")


def test_internal_links_same_host_only():
    base = "https://x.blogspot.com"
    body = (
        '<article class="yomi-clean-post">'
        '<a href="/2026/06/b.html">b</a>'
        '<a href="https://x.blogspot.com/2026/06/c.html">c</a>'
        '<a href="https://other.com/d.html">ext</a>'
        "</article>"
    )
    links = ia._internal_links(base, ia._post_body(body))
    assert "https://x.blogspot.com/2026/06/b.html" in links
    assert "https://x.blogspot.com/2026/06/c.html" in links
    assert all("other.com" not in l for l in links)


def test_recent_urls_from_history_dedupes_and_limits(tmp_path):
    hist = tmp_path / "history.json"
    hist.write_text(
        json.dumps(
            [
                {"url": "https://x/a.html"},
                {"url": "https://x/b.html"},
                {"url": "https://x/b.html"},
                {"url": "https://x/c.html"},
            ]
        ),
        encoding="utf-8",
    )
    urls = ia._recent_urls_from_history(hist, 2)
    assert urls == ["https://x/c.html", "https://x/b.html"]
