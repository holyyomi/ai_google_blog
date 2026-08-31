"""Question-demand mining — the English-language answer to 네이버 지식인.

WHY THIS EXISTS
---------------
Topic selection here has only ever had Google Autocomplete, which tells you a
phrase *exists* but never how many people want it. Autocomplete also returns
nothing at all for many long-tail question phrasings (verified 2026-08-31:
"how to fix gemini api" → empty list), which is exactly the shape of query this
blog is now targeting. Google's People Also Ask — the closest structural match
to 지식인 — is injected client-side and sits behind `Disallow: /search`, so
there is no free compliant way to read it. Paid SERP APIs or headless scraping
are the only options and neither belongs in an unattended daily job.

So this mines the places where people actually ask, and where the asking is
publicly counted:

  1. Discourse vendor forums — real user questions with ABSOLUTE view counts
     and an explicit "nobody answered this" flag. Closest thing to 지식인 for
     this niche. discuss.ai.google.dev alone has ~6,580 topics in gemini-api.
  2. Stack Exchange — the only source returning a hard per-question view count,
     so it can RANK what the others surface. (Measured: the OpenAI 429 quota
     question has 488,097 views.)
  3. GitHub issue search — `total_count` says how many separate repos hit the
     same error. Directly validates a content gap, because for these keywords
     GitHub issues currently outrank every article.

DELIBERATELY NOT WIRED INTO THE PUBLISH PIPELINE
------------------------------------------------
This is a read-only research tool a human runs and reads. It does not touch
news_pipeline, does not inject candidates, and cannot block or alter a publish.
That is on purpose (AGENTS.md 원칙 9: Manual → Semi-auto → Full-auto) — a new
external data source must prove itself before it can affect the daily job.
Promote it only after its output has actually driven a few good posts.

The first real run (2026-08-31) also showed WHY a human filter is required:
the gemini-api forum's weekly top mixes genuine high-demand questions
("Gemini API Image URLs returns 429 RESOURCE_EXHAUSTED", "Tier 3 repeatedly
reverts to Tier 1") with pure grievance threads ("OPEN LETTER TO SUNDAR
PICHAI", "Backend Fraud"). Views alone cannot tell those apart, and a
grievance thread is not a topic this blog should write. Auto-injecting these
as candidates would eventually publish one. Read the titles yourself.

COMPLIANCE NOTES (checked 2026-08-31 — re-check before changing endpoints)
--------------------------------------------------------------------------
- Discourse: `/top.json`, `/c/<slug>/<id>/l/top.json`, `/categories.json` and
  `/t/<id>.json` are all crawlable. `/search.json` IS disallowed by their
  robots.txt (`Disallow: /search`) even though it responds — do not use it.
- Stack Exchange: documented public API, no key required, no robots restriction.
  300 requests/day per IP unauthenticated; `quota_remaining` is echoed and this
  tool prints it.
- GitHub search: 10 requests/minute unauthenticated, 30 with a token.
- Reddit is intentionally absent. Its robots.txt is a blanket `Disallow: /` for
  every user agent, and every JSON path returns 403 regardless of User-Agent
  (retested 2026-08-31). The .rss path responds but is inside the same blanket
  disallow and 429s after one call. See community_topic_service for the
  existing circuit breaker; do not "fix" Reddit by swapping the UA.

Usage:
  python tools/demand_mine.py                     # all sources, default topics
  python tools/demand_mine.py --source stack      # one source
  python tools/demand_mine.py --tag google-gemini --tag openai-api
  python tools/demand_mine.py --json out.json     # machine-readable
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
from typing import Any

import requests

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

UA = {"User-Agent": "holyyomiai-topic-research/1.0 (+https://holyyomiai.blogspot.com)"}
TIMEOUT = 20

# Discourse forums worth mining, as (base_url, category_slug, category_id).
# Verified reachable 2026-08-31. community.anthropic.com does not exist.
DISCOURSE_TARGETS = [
    ("https://discuss.ai.google.dev", "gemini-api", 4),
]
# Forums whose root /top.json is mined without a category filter.
DISCOURSE_ROOTS = [
    "https://community.openai.com",
]

# Stack Overflow tags. NOTE: `gemini-api` does NOT exist as a tag and silently
# returns zero items — the real one is `google-gemini` (verified 2026-08-31).
DEFAULT_SE_TAGS = ["openai-api", "google-gemini", "langchain"]

DEFAULT_GH_QUERIES = [
    'gemini "RESOURCE_EXHAUSTED" in:title is:issue',
    'openrouter 429 in:title is:issue',
    'openrouter "no endpoints" in:title is:issue',
]

# Stack Exchange filter that includes view_count/score/answer_count/link.
_SE_FILTER = "!nNPvSNdWme"


def _get(url: str, **kwargs: Any) -> requests.Response:
    return requests.get(url, headers=UA, timeout=TIMEOUT, **kwargs)


def discourse_top(base: str, cat_slug: str = "", cat_id: int = 0,
                  period: str = "weekly", limit: int = 10) -> list[dict[str, Any]]:
    """Vendor-forum questions with real view counts. Listing endpoints only."""
    if cat_slug:
        url = f"{base}/c/{cat_slug}/{cat_id}/l/top.json"
    else:
        url = f"{base}/top.json"
    try:
        response = _get(url, params={"period": period})
        response.raise_for_status()
        topics = (response.json().get("topic_list") or {}).get("topics") or []
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {base} failed: {exc}", file=sys.stderr)
        return []
    host = base.split("//", 1)[-1]
    rows = []
    for topic in topics[:limit]:
        rows.append({
            "source": f"discourse:{host}" + (f"/{cat_slug}" if cat_slug else ""),
            "title": html.unescape(topic.get("title") or ""),
            "views": topic.get("views"),
            "replies": topic.get("reply_count"),
            "solved": bool(topic.get("has_accepted_answer")),
            "url": f"{base}/t/{topic.get('slug')}/{topic.get('id')}",
        })
    return rows


def stack_questions(tag: str, *, site: str = "stackoverflow",
                    pagesize: int = 20, key: str = "") -> tuple[list[dict[str, Any]], Any]:
    """The only source with an absolute per-question demand number."""
    params = {
        "site": site, "sort": "votes", "order": "desc",
        "pagesize": pagesize, "filter": _SE_FILTER, "tagged": tag,
    }
    if key:
        params["key"] = key
    try:
        response = _get("https://api.stackexchange.com/2.3/search/advanced", params=params)
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! stackoverflow/{tag} failed: {exc}", file=sys.stderr)
        return [], None
    rows = [{
        "source": f"stackoverflow:{tag}",
        "title": html.unescape(item.get("title") or ""),
        "views": item.get("view_count"),
        "score": item.get("score"),
        "answered": bool(item.get("is_answered")),
        "url": item.get("link"),
    } for item in (payload.get("items") or [])]
    # The API has no sort=views option, so rank locally.
    rows.sort(key=lambda r: r["views"] or 0, reverse=True)
    return rows, payload.get("quota_remaining")


def github_issues(query: str, *, per_page: int = 8, token: str = "") -> dict[str, Any]:
    """total_count is the signal: N repos independently hitting one error."""
    headers = dict(UA)
    headers["Accept"] = "application/vnd.github+json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(
            "https://api.github.com/search/issues",
            params={"q": query, "sort": "comments", "order": "desc", "per_page": per_page},
            headers=headers, timeout=TIMEOUT,
        )
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! github '{query}' failed: {exc}", file=sys.stderr)
        return {"query": query, "total_count": 0, "items": []}
    return {
        "query": query,
        "total_count": payload.get("total_count", 0),
        "items": [{
            "title": item.get("title"),
            "comments": item.get("comments"),
            "url": item.get("html_url"),
        } for item in (payload.get("items") or [])],
    }


def _print_rows(rows: list[dict[str, Any]], *, show_solved: bool = True) -> None:
    for row in rows:
        views = row.get("views")
        views_text = f"{views:>8,}" if isinstance(views, int) else "       ?"
        if show_solved:
            flag = "  " if row.get("solved") or row.get("answered") else "GAP"
        else:
            flag = "  "
        print(f"  {flag} {views_text} views | {row['title'][:88]}")
        print(f"              {row['url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["all", "discourse", "stack", "github"],
                        default="all")
    parser.add_argument("--tag", action="append", default=[],
                        help="Stack Overflow tag (repeatable). Default: %s" % ", ".join(DEFAULT_SE_TAGS))
    parser.add_argument("--period", default="weekly",
                        choices=["daily", "weekly", "monthly", "yearly", "all"])
    parser.add_argument("--se-key", default="", help="Optional Stack Exchange key (raises daily quota)")
    parser.add_argument("--gh-token", default="", help="Optional GitHub token (10/min -> 30/min)")
    parser.add_argument("--json", default="", help="Also write results to this JSON path")
    args = parser.parse_args()

    tags = args.tag or DEFAULT_SE_TAGS
    result: dict[str, Any] = {"discourse": [], "stackoverflow": [], "github": []}

    if args.source in ("all", "discourse"):
        print("\n=== Vendor forums (Discourse) — 'GAP' = high views, nobody answered ===")
        for base, slug, cat_id in DISCOURSE_TARGETS:
            rows = discourse_top(base, slug, cat_id, period=args.period)
            result["discourse"].extend(rows)
            if rows:
                print(f"\n[{rows[0]['source']}]")
                _print_rows(rows)
            time.sleep(0.5)
        for base in DISCOURSE_ROOTS:
            rows = discourse_top(base, period=args.period)
            result["discourse"].extend(rows)
            if rows:
                print(f"\n[{rows[0]['source']}]")
                _print_rows(rows)
            time.sleep(0.5)

    if args.source in ("all", "stack"):
        print("\n=== Stack Overflow — absolute view counts ('GAP' = unanswered) ===")
        quota = None
        for tag in tags:
            rows, quota = stack_questions(tag, key=args.se_key)
            result["stackoverflow"].extend(rows)
            if rows:
                print(f"\n[{tag}]")
                _print_rows(rows[:10])
            else:
                print(f"\n[{tag}] no items — check the tag actually exists on Stack Overflow")
            time.sleep(0.5)
        if quota is not None:
            print(f"\n  (Stack Exchange quota remaining today: {quota})")

    if args.source in ("all", "github"):
        print("\n=== GitHub issues — total_count = how many repos hit this ===")
        for query in DEFAULT_GH_QUERIES:
            found = github_issues(query, token=args.gh_token)
            result["github"].append(found)
            print(f"\n[{query}]  total_count={found['total_count']}")
            for item in found["items"][:4]:
                print(f"     {item['comments']:>3} cmts | {str(item['title'])[:80]}")
            time.sleep(7)  # unauthenticated search allows 10/min

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
