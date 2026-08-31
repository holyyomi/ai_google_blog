"""Create/update the "All Articles" index page for holyyomi AI Insight.

Why: sitemap.xml, the Atom feed, the homepage recent-posts list, and even the
sidebar Archive widget all only surface a rolling window of the most recent
~35 posts (confirmed 2026-08-31 via tools/indexability_audit.py + direct GSC
inspection: Search Console's Page indexing report only knows about 36-37
URLs even though 51 live posts exist back to 2026-07-03). Once a post ages
out of that window it has zero remaining internal discovery path, since this
blog's internal-link policy only links between recently-published posts.

This page is a plain internal-link index, not an XML sitemap — it complies
with the "no external links, internal-only" policy. It is meant to be linked
from the homepage/nav so both crawlers and human readers have a durable path
back to every live post, not just the last ~5 weeks of them.

Mirrors the existing create_about_page.py / create_english_static_pages.py
pattern (Blogger Pages API, refresh-token auth from .env).

DRAFT-ONLY BY DEFAULT: prints a preview unless you pass --publish.
If a page with this title already exists, --publish PATCHes it in place
instead of creating a duplicate.

Run (dry preview):
  PYTHONPATH=src python scripts/create_all_articles_page.py

Run (actually create/update on Blogger):
  PYTHONPATH=src python scripts/create_all_articles_page.py --publish
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE  # noqa: E402

PAGE_TITLE = "All Articles"
LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "publish_history.json"

# Confirmed dead (HTTP 404) via a full tools/indexability_audit.py sweep of all
# 51 "published: true" ledger URLs on 2026-08-31 — 17 of 51 (33%) came back 404,
# concentrated in the early "ai-work-automation-productivity-*" generic-slug
# batch (2026-07-03 to 2026-07-18ish). Excluded so this index never links to a
# broken page. This is itself a separate bug worth investigating (likely the
# same post-publish self-delete path documented in docs/INDEXABILITY_RUNBOOK.md
# section A) — re-verify before reuse, don't assume this list stays complete.
KNOWN_DEAD = {
    "https://holyyomiai.blogspot.com/2026/07/why-ai-gives-wrong-answers-chatgpt-news.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-assistant-pricing-compared-chatgpt.html",
    "https://holyyomiai.blogspot.com/2026/07/etsy-ai-tools-keepr-ops-vs-news-06414e.html",
    "https://holyyomiai.blogspot.com/2026/07/gpt-wordpress-rce-discovery-broker.html",
    "https://holyyomiai.blogspot.com/2026/07/best-ai-tools-real-estate-agents-news.html",
    "https://holyyomiai.blogspot.com/2026/07/grok-build-open-sourced-after-repo-news_01329126671.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-de90cc.html",
    "https://holyyomiai.blogspot.com/2026/07/ceo-ai-work-government-automation.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-galaxy.html",
    "https://holyyomiai.blogspot.com/2026/07/chatgpt-claude-gemini-ai-work.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-e86e02.html",
    "https://holyyomiai.blogspot.com/2026/07/api-caio-ai-work-automation.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-d7e6b.html",
    "https://holyyomiai.blogspot.com/2026/07/chatgpt-ai-work-automation-productivity_0981020487.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-worker.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-worker_01472287632.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-f34f.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-c6ee.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-poll_01708274305.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-bd4ac0.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-adebc.html",
    "https://holyyomiai.blogspot.com/2026/07/ai-work-automation-productivity-update.html",
}


def _load_live_posts() -> list[tuple[str, str, str]]:
    """Returns (date, title, url) for every distinct live post, newest first."""
    with open(LEDGER_PATH, encoding="utf-8") as f:
        data = json.load(f)
    seen: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for entry in data:
        if entry.get("published") is not True:
            continue
        url = entry.get("url")
        if not url or url in KNOWN_DEAD or url in seen:
            continue
        seen.add(url)
        title = (entry.get("title") or entry.get("selected_title") or url.rsplit("/", 1)[-1]).strip()
        rows.append((entry.get("date", ""), title, url))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def _month_label(date_str: str) -> str:
    try:
        year, month, _ = date_str.split("-")
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        return f"{months[int(month) - 1]} {year}"
    except Exception:
        return "Undated"


def _build_html(rows: list[tuple[str, str, str]]) -> str:
    by_month: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in rows:
        by_month[_month_label(row[0])].append(row)

    sections = []
    for month, items in by_month.items():
        links = "\n".join(
            f'<li><a href="{url}">{_escape(title)}</a> <span class="yomi-muted">({date})</span></li>'
            for date, title, url in items
        )
        sections.append(f"<h2>{month}</h2>\n<ul class=\"yomi-list\">\n{links}\n</ul>")

    body = (
        '<section class="yomi-lede"><p>Every article published on holyyomi AI Insight, '
        "newest first. Use this page to find older comparisons, pricing breakdowns, "
        "and how-to guides that may have scrolled off the homepage.</p></section>\n"
        + "\n".join(sections)
    )
    stripped_style = re.sub(r"/\*.*?\*/", "", YOMI_CLEAN_ARTICLE_STYLE, flags=re.DOTALL)
    stripped_style = re.sub(r"\n{2,}", "\n", stripped_style)
    return stripped_style + '\n<article class="yomi-clean-post">' + body + "</article>"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip().lstrip("﻿"), value.strip().strip('"').strip("'"))


def _access_token(*, client_id: str, client_secret: str, refresh_token: str) -> str:
    token_req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(token_req, timeout=30) as response:
        return str(json.loads(response.read())["access_token"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish", action="store_true",
        help="Actually create/update the page on Blogger. Without this flag, only prints a preview.",
    )
    args = parser.parse_args()

    rows = _load_live_posts()
    html = _build_html(rows)

    if not args.publish:
        print(f"DRY PREVIEW (no --publish flag) — {len(rows)} live posts would be listed on '{PAGE_TITLE}' ({len(html)} chars)\n")
        for date, title, url in rows[:5]:
            print(f"  {date}  {title}  -> {url}")
        print(f"  ... and {max(0, len(rows) - 5)} more")
        print("\nRe-run with --publish to actually create/update this on Blogger.")
        return

    _load_env()
    client_id = os.getenv("BLOGGER_CLIENT_ID", "")
    client_secret = os.getenv("BLOGGER_CLIENT_SECRET", "")
    refresh_token = os.getenv("BLOGGER_REFRESH_TOKEN", "")
    blog_id = os.getenv("BLOGGER_BLOG_ID", "")
    assert all([client_id, client_secret, refresh_token, blog_id]), "Blogger credentials are missing."

    token = _access_token(client_id=client_id, client_secret=client_secret, refresh_token=refresh_token)
    list_req = urllib.request.Request(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(list_req, timeout=30) as response:
        existing = {
            str(page.get("title", "")).strip(): page.get("id")
            for page in (json.loads(response.read()).get("items") or [])
        }

    payload = json.dumps({"kind": "blogger#page", "title": PAGE_TITLE, "content": html}).encode("utf-8")
    if PAGE_TITLE in existing:
        page_id = existing[PAGE_TITLE]
        req = urllib.request.Request(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages/{page_id}",
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read())
        print(f"UPDATED: {PAGE_TITLE} ({len(rows)} posts) -> {data.get('url')}")
    else:
        req = urllib.request.Request(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read())
        print(f"CREATED: {PAGE_TITLE} ({len(rows)} posts) -> {data.get('url')}")


if __name__ == "__main__":
    main()
