from __future__ import annotations

import json
import re
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from blogspot_automation.services.news_focus_policy import evaluate_news_focus


DEFAULT_SITEMAP_URL = "https://holyyomiai.blogspot.com/sitemap.xml"
AI_BLOG_HOST = "holyyomiai.blogspot.com"


@dataclass(frozen=True, slots=True)
class SitemapUrlAudit:
    url: str
    slug: str
    year_month: str
    risk_level: str
    action: str
    cleanup_bucket: str
    priority_score: int
    reasons: tuple[str, ...]


def audit_sitemap(
    *,
    sitemap_url: str = DEFAULT_SITEMAP_URL,
    output_dir: str | Path = "runs/site_audit",
    max_urls: int = 500,
) -> dict[str, Any]:
    urls = fetch_sitemap_urls(sitemap_url=sitemap_url, max_urls=max_urls)
    items = [classify_sitemap_url(url) for url in urls]
    summary = _summary(items)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sitemap_url": sitemap_url,
        "summary": summary,
        "items": [asdict(item) for item in items],
    }
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"site_audit_{stamp}.json"
    md_path = out_dir / f"site_audit_{stamp}.md"
    csv_path = out_dir / f"site_audit_{stamp}.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_audit_markdown(payload), encoding="utf-8")
    _write_audit_csv(csv_path, items)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    payload["csv_path"] = str(csv_path)
    return payload


def fetch_sitemap_urls(*, sitemap_url: str, max_urls: int = 500) -> list[str]:
    request = Request(sitemap_url, headers={"User-Agent": "blogspot-site-audit/1.0"})
    with urlopen(request, timeout=30) as response:
        xml_text = response.read().decode("utf-8", errors="replace")
    root = ElementTree.fromstring(xml_text)
    urls: list[str] = []
    for loc in root.findall(".//{*}loc"):
        text = " ".join((loc.text or "").split()).strip()
        if text:
            urls.append(text)
        if len(urls) >= max_urls:
            break
    return urls


def classify_sitemap_url(url: str) -> SitemapUrlAudit:
    slug = _slug_from_url(url)
    reasons: list[str] = []
    action = "keep"
    risk_level = "low"
    cleanup_bucket = "keep"
    priority_score = 0

    if _is_blogspot_auto_slug(slug):
        reasons.append("weak_auto_permalink")
        action = "rewrite_or_unpublish"
        risk_level = "high"
        cleanup_bucket = "bad_permalink"
        priority_score = max(priority_score, 85)
    elif _is_numeric_slug(slug):
        reasons.append("weak_numeric_permalink")
        action = "rewrite_or_unpublish"
        risk_level = "high"
        cleanup_bucket = "bad_permalink"
        priority_score = max(priority_score, 80)
    elif len(slug) < 12:
        reasons.append("thin_slug")
        action = "review"
        risk_level = "medium"
        cleanup_bucket = "thin_slug_review"
        priority_score = max(priority_score, 50)

    focus = evaluate_news_focus(topic=slug.replace("-", " "), raw={})
    if not _is_ai_blog_url(url) and not focus.allowed:
        reasons.append("ai_topic_url")
        action = "unpublish_or_move_out_of_news_blog"
        risk_level = "high"
        cleanup_bucket = "off_topic_ai"
        priority_score = max(priority_score, 95)

    if not reasons:
        reasons.append("no_url_level_issue_detected")

    return SitemapUrlAudit(
        url=url,
        slug=slug,
        year_month=_year_month_from_url(url),
        risk_level=risk_level,
        action=action,
        cleanup_bucket=cleanup_bucket,
        priority_score=priority_score,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def render_audit_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Site Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- sitemap_url: {payload.get('sitemap_url')}",
        f"- total_urls: {summary.get('total_urls', 0)}",
        f"- high_risk_urls: {summary.get('high_risk_urls', 0)}",
        f"- medium_risk_urls: {summary.get('medium_risk_urls', 0)}",
        "",
        "| risk | action | reasons | url |",
        "| --- | --- | --- | --- |",
    ]
    items = payload.get("items") or []
    risky = sorted(
        [item for item in items if item.get("risk_level") in {"high", "medium"}],
        key=lambda item: int(item.get("priority_score") or 0),
        reverse=True,
    )
    for item in risky[:120]:
        reasons = ", ".join(item.get("reasons") or [])
        lines.append(
            f"| {item.get('risk_level')} | {item.get('action')} | {reasons} | {item.get('url')} |"
        )
    return "\n".join(lines) + "\n"


def _summary(items: list[SitemapUrlAudit]) -> dict[str, int]:
    return {
        "total_urls": len(items),
        "high_risk_urls": sum(1 for item in items if item.risk_level == "high"),
        "medium_risk_urls": sum(1 for item in items if item.risk_level == "medium"),
        "weak_auto_permalink_urls": sum(1 for item in items if "weak_auto_permalink" in item.reasons),
        "weak_numeric_permalink_urls": sum(1 for item in items if "weak_numeric_permalink" in item.reasons),
        "ai_topic_urls": sum(1 for item in items if "ai_topic_url" in item.reasons),
    }


def _write_audit_csv(path: Path, items: list[SitemapUrlAudit]) -> None:
    ordered = sorted(items, key=lambda item: item.priority_score, reverse=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "priority_score",
                "risk_level",
                "cleanup_bucket",
                "action",
                "reasons",
                "year_month",
                "slug",
                "url",
            ],
        )
        writer.writeheader()
        for item in ordered:
            writer.writerow(
                {
                    "priority_score": item.priority_score,
                    "risk_level": item.risk_level,
                    "cleanup_bucket": item.cleanup_bucket,
                    "action": item.action,
                    "reasons": ",".join(item.reasons),
                    "year_month": item.year_month,
                    "slug": item.slug,
                    "url": item.url,
                }
            )


def _slug_from_url(url: str) -> str:
    path = url.split("?", 1)[0].rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return re.sub(r"\.html$", "", last, flags=re.IGNORECASE)


def _is_ai_blog_url(url: str) -> bool:
    return urlsplit(url).netloc.lower() == AI_BLOG_HOST


def _year_month_from_url(url: str) -> str:
    match = re.search(r"/(20\d{2})/(\d{2})/", url)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}"


def _is_blogspot_auto_slug(slug: str) -> bool:
    return bool(re.fullmatch(r"blog-post(?:_\d+)?", slug or ""))


def _is_numeric_slug(slug: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:[-_]\d+)*", slug or ""))
