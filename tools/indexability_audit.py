"""Indexability audit — verify recently published posts are crawlable/indexable.

Read-only HTTP GET only. Does NOT publish, delete, or modify any post.
Pulls recent live URLs from the published history and checks, per URL:

  - HTTP 200 (alive, not 404/redirect-to-home)
  - robots meta has no `noindex` / `nofollow`
  - canonical is self-referencing (not home, not another post)
  - <meta name="description"> present in <head> (Blogger search description rendered)
  - BlogPosting + FAQPage JSON-LD present
  - URL is included in sitemap.xml
  - URL is linked from the blog homepage
  - URL is present in the Atom/RSS feed
  - internal <a> links inside the post body resolve to live (200) same-host URLs

Writes a JSON + Markdown report under runs/indexability_audit/<stamp>/.

Usage:
  PYTHONPATH=src python tools/indexability_audit.py --recent 8
  PYTHONPATH=src python tools/indexability_audit.py --url https://.../post.html
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

logger = logging.getLogger("indexability_audit")

DEFAULT_BLOG_BASE = "https://holyeverymoments.blogspot.com"
DEFAULT_PUBLISHED_HISTORY_PATH = Path("state/news_published_history.json")
DEFAULT_OUTPUT_DIR = Path("runs/indexability_audit")
_UA = "blogspot-indexability-audit/1.0 (read-only)"
_TIMEOUT = 30


@dataclass(slots=True)
class UrlAudit:
    url: str
    http_status: int | None
    alive: bool
    robots_indexable: bool
    canonical_self: bool
    head_meta_description_present: bool
    blogposting_jsonld_present: bool
    faqpage_jsonld_present: bool
    in_sitemap: bool
    linked_from_homepage: bool
    in_feed: bool
    weak_slug: bool
    internal_links_total: int
    internal_links_dead: tuple[str, ...]
    issues: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _SiteContext:
    base: str
    sitemap_urls: set[str] = field(default_factory=set)
    homepage_html: str = ""
    feed_text: str = ""


def _fetch(url: str, *, timeout: int = _TIMEOUT) -> tuple[int | None, str]:
    req = Request(url, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except HTTPError as exc:
        return exc.code, ""
    except (URLError, Exception) as exc:  # noqa: BLE001
        logger.warning("fetch failed %s: %s", url, exc)
        return None, ""


def _head_html(html: str) -> str:
    m = re.search(r"<head\b[^>]*>(.*?)</head>", html or "", re.I | re.S)
    return m.group(1) if m else ""


def _robots_indexable(html: str) -> bool:
    m = re.search(r"<meta[^>]+name=['\"]robots['\"][^>]*>", html or "", re.I)
    if not m:
        return True  # no robots meta => default indexable
    tag = m.group(0).lower()
    return "noindex" not in tag and "nofollow" not in tag


def _canonical_self(url: str, html: str) -> bool:
    m = re.search(
        r"<link[^>]+rel=['\"]canonical['\"][^>]*href=['\"]([^'\"]+)['\"]|"
        r"<link[^>]+href=['\"]([^'\"]+)['\"][^>]*rel=['\"]canonical['\"]",
        html or "",
        re.I,
    )
    if not m:
        return False
    canonical = (m.group(1) or m.group(2) or "").strip().rstrip("/")
    return canonical == (url or "").strip().rstrip("/")


def _slug_from_url(url: str) -> str:
    path = (url or "").split("?", 1)[0].rstrip("/")
    return re.sub(r"\.html$", "", path.rsplit("/", 1)[-1], re.I)


def _is_weak_slug(slug: str) -> bool:
    return bool(
        re.fullmatch(r"blog-post(?:_\d+)?", slug or "")
        or re.fullmatch(r"\d+(?:[-_]\d+)*", slug or "")
        or len(slug or "") < 8
    )


def _post_body(html: str) -> str:
    for pat in (
        r'<article\b[^>]*class=["\'][^"\']*\byomi-clean-post\b[^"\']*["\'][^>]*>.*?</article>',
        r'<div\b[^>]*class=["\'][^"\']*\bpost-body\b[^"\']*["\'][^>]*>.*?</div>',
    ):
        m = re.search(pat, html or "", re.I | re.S)
        if m:
            return m.group(0)
    return ""


def _internal_links(base: str, post_body_html: str) -> list[str]:
    host = urlsplit(base).netloc
    links: list[str] = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\']', post_body_html or "", re.I):
        href = m.group(1).strip()
        if href.startswith("/"):
            href = base.rstrip("/") + href
        if urlsplit(href).netloc == host and href.endswith(".html"):
            if href not in links:
                links.append(href)
    return links


def _load_site_context(base: str, *, max_sitemap: int = 1000) -> _SiteContext:
    ctx = _SiteContext(base=base)
    _, sm = _fetch(f"{base}/sitemap.xml")
    ctx.sitemap_urls = {
        loc.strip()
        for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", sm or "", re.I)
    }
    if len(ctx.sitemap_urls) > max_sitemap:
        ctx.sitemap_urls = set(list(ctx.sitemap_urls)[:max_sitemap])
    _, ctx.homepage_html = _fetch(base)
    _, ctx.feed_text = _fetch(f"{base}/feeds/posts/default?max-results=50")
    return ctx


def audit_url(url: str, ctx: _SiteContext) -> UrlAudit:
    issues: list[str] = []
    warnings: list[str] = []

    status, html = _fetch(url)
    alive = status == 200 and bool(html)
    if not alive:
        issues.append(f"url_not_alive_http_{status}")
        return UrlAudit(
            url=url, http_status=status, alive=False, robots_indexable=False,
            canonical_self=False, head_meta_description_present=False,
            blogposting_jsonld_present=False, faqpage_jsonld_present=False,
            in_sitemap=url in ctx.sitemap_urls, linked_from_homepage=False,
            in_feed=False, weak_slug=_is_weak_slug(_slug_from_url(url)),
            internal_links_total=0, internal_links_dead=(),
            issues=tuple(issues), warnings=tuple(warnings),
        )

    robots_indexable = _robots_indexable(html)
    if not robots_indexable:
        issues.append("robots_noindex_or_nofollow")

    canonical_self = _canonical_self(url, html)
    if not canonical_self:
        issues.append("canonical_not_self_referencing")

    head = _head_html(html)
    head_meta_desc = bool(re.search(r"<meta[^>]+name=['\"]description['\"][^>]*>", head, re.I))
    if not head_meta_desc:
        issues.append("missing_head_meta_description")

    blogposting = "BlogPosting" in html
    faqpage = "FAQPage" in html
    if not blogposting:
        issues.append("blogposting_jsonld_missing")
    if not faqpage:
        warnings.append("faqpage_jsonld_missing")

    in_sitemap = url in ctx.sitemap_urls
    if not in_sitemap:
        warnings.append("not_in_sitemap")

    linked_home = url in (ctx.homepage_html or "")
    if not linked_home:
        warnings.append("not_linked_from_homepage")

    in_feed = url in (ctx.feed_text or "")
    if not in_feed:
        warnings.append("not_in_feed")

    weak = _is_weak_slug(_slug_from_url(url))
    if weak:
        warnings.append("weak_permalink_slug")

    internal = _internal_links(ctx.base, _post_body(html))
    dead: list[str] = []
    for link in internal:
        if link == url:
            continue
        st, _ = _fetch(link, timeout=20)
        if st != 200:
            dead.append(f"{link} (http {st})")
    if dead:
        issues.append("internal_links_dead")

    return UrlAudit(
        url=url, http_status=status, alive=True, robots_indexable=robots_indexable,
        canonical_self=canonical_self, head_meta_description_present=head_meta_desc,
        blogposting_jsonld_present=blogposting, faqpage_jsonld_present=faqpage,
        in_sitemap=in_sitemap, linked_from_homepage=linked_home, in_feed=in_feed,
        weak_slug=weak, internal_links_total=len(internal),
        internal_links_dead=tuple(dead),
        issues=tuple(dict.fromkeys(issues)), warnings=tuple(dict.fromkeys(warnings)),
    )


def _recent_urls_from_history(path: Path, count: int) -> list[str]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    records = raw if isinstance(raw, list) else raw.get("records", []) if isinstance(raw, dict) else []
    urls: list[str] = []
    for rec in records:
        if isinstance(rec, dict) and rec.get("url"):
            urls.append(str(rec["url"]))
    # de-dupe keeping most recent, take last N
    seen: set[str] = set()
    ordered: list[str] = []
    for u in reversed(urls):
        if u not in seen:
            seen.add(u)
            ordered.append(u)
        if len(ordered) >= count:
            break
    return ordered


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Indexability audit",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- blog_base: {payload['blog_base']}",
        f"- urls_checked: {payload['summary']['urls_checked']}",
        f"- with_issues: {payload['summary']['with_issues']}",
        "",
        "| URL | HTTP | robots | canonical | head-desc | sitemap | home | feed | issues |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for it in payload["items"]:
        def yn(v: bool) -> str:
            return "✅" if v else "❌"
        lines.append(
            f"| {_slug_from_url(it['url'])} | {it['http_status']} | "
            f"{yn(it['robots_indexable'])} | {yn(it['canonical_self'])} | "
            f"{yn(it['head_meta_description_present'])} | {yn(it['in_sitemap'])} | "
            f"{yn(it['linked_from_homepage'])} | {yn(it['in_feed'])} | "
            f"{', '.join(it['issues']) or '-'} |"
        )
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    blog_base: str,
    urls: list[str],
    output_dir: Path,
) -> dict[str, Any]:
    ctx = _load_site_context(blog_base)
    items = [audit_url(u, ctx).to_dict() for u in urls]
    summary = {
        "urls_checked": len(items),
        "with_issues": sum(1 for it in items if it["issues"]),
        "with_warnings": sum(1 for it in items if it["warnings"]),
        "dead_urls": [it["url"] for it in items if not it["alive"]],
        "missing_head_meta_description": [
            it["url"] for it in items if not it["head_meta_description_present"]
        ],
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blog_base": blog_base,
        "sitemap_url_count": len(ctx.sitemap_urls),
        "summary": summary,
        "items": items,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"indexability_{stamp}.json"
    md_path = output_dir / f"indexability_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    return payload


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(description="Audit indexability of recent Blogspot posts (read-only).")
    parser.add_argument("--blog-base", default=DEFAULT_BLOG_BASE)
    parser.add_argument("--url", action="append", default=[], help="Explicit URL(s) to audit (repeatable).")
    parser.add_argument("--recent", type=int, default=8, help="Audit the N most recent published URLs from history.")
    parser.add_argument("--history-path", default=str(DEFAULT_PUBLISHED_HISTORY_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    urls = list(args.url)
    if not urls:
        urls = _recent_urls_from_history(Path(args.history_path), args.recent)
    if not urls:
        logger.error("no URLs to audit (history empty and no --url given)")
        raise SystemExit(1)

    payload = run_audit(
        blog_base=args.blog_base.rstrip("/"),
        urls=urls,
        output_dir=Path(args.output_dir),
    )
    print(json.dumps({
        "summary": payload["summary"],
        "json_path": payload["json_path"],
        "markdown_path": payload["markdown_path"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
