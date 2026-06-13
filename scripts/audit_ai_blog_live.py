from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_BLOG_URL = "https://holyyomiai.blogspot.com/"
DEFAULT_OUTPUT_DIR = Path("runs/live_blog_audit")
USER_AGENT = "holyyomi-ai-live-audit/1.0"
LEGACY_PHRASES = (
    "오늘의 이슈 해부",
    "생활 뉴스 핵심",
    "생활비, 플랫폼 변화를 중심",
    "today issue",
)
EXPECTED_PHRASES = (
    "holyyomi AI Insight",
    "AI 기술과 트렌드",
)


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int | None
    body: str
    error: str = ""


@dataclass(slots=True)
class LiveAuditPayload:
    generated_at: str
    blog_url: str
    passed: bool
    issues: list[str]
    warnings: list[str]
    checks: dict[str, object]


def fetch_text(url: str, *, timeout: int = 30) -> FetchResult:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return FetchResult(url=url, status=int(response.status), body=body)
    except HTTPError as exc:
        return FetchResult(url=url, status=int(exc.code), body="", error=str(exc))
    except (URLError, TimeoutError, OSError) as exc:
        return FetchResult(url=url, status=None, body="", error=f"{type(exc).__name__}: {exc}")


def audit_live_blog(*, blog_url: str = DEFAULT_BLOG_URL, timeout: int = 30) -> LiveAuditPayload:
    base = blog_url.rstrip("/") + "/"
    issues: list[str] = []
    warnings: list[str] = []
    checks: dict[str, object] = {}

    home = fetch_text(base, timeout=timeout)
    checks["home_status"] = home.status
    checks["home_error"] = home.error
    if home.status != 200 or not home.body:
        issues.append(f"home_not_reachable:{home.status}")
    else:
        home_checks = audit_home_html(home.body)
        checks.update(home_checks)
        issues.extend(str(item) for item in home_checks.get("issues", []))
        warnings.extend(str(item) for item in home_checks.get("warnings", []))

    robots = fetch_text(urljoin(base, "robots.txt"), timeout=timeout)
    checks["robots_status"] = robots.status
    checks["robots_has_sitemap"] = "Sitemap:" in robots.body
    if robots.status not in {200, 404}:
        warnings.append(f"robots_unexpected_status:{robots.status}")

    sitemap = fetch_text(urljoin(base, "sitemap.xml"), timeout=timeout)
    checks["sitemap_status"] = sitemap.status
    checks["sitemap_has_urls"] = bool(re.search(r"<loc>\s*https?://", sitemap.body or "", flags=re.IGNORECASE))
    if sitemap.status != 200:
        warnings.append(f"sitemap_unexpected_status:{sitemap.status}")
    elif not checks["sitemap_has_urls"]:
        warnings.append("sitemap_has_no_urls")

    checks["recent_post_urls"] = extract_recent_post_urls(home.body, base=base) if home.body else []
    checks["legacy_phrase_source"] = "homepage"

    payload = LiveAuditPayload(
        generated_at=datetime.now(timezone.utc).isoformat(),
        blog_url=base,
        passed=not issues,
        issues=list(dict.fromkeys(issues)),
        warnings=list(dict.fromkeys(warnings)),
        checks=checks,
    )
    return payload


def audit_home_html(html: str) -> dict[str, object]:
    issues: list[str] = []
    warnings: list[str] = []
    content = html or ""

    legacy_found = [phrase for phrase in LEGACY_PHRASES if phrase.lower() in content.lower()]
    if legacy_found:
        issues.append("legacy_today_issue_phrase_visible")

    expected_found = [phrase for phrase in EXPECTED_PHRASES if phrase in content]
    if "holyyomi AI Insight" not in expected_found:
        issues.append("blog_title_not_ai_brand")
    if not any("AI 기술" in phrase for phrase in expected_found):
        warnings.append("ai_blog_description_phrase_missing")

    head = _head_html(content)
    meta_description = bool(re.search(r"<meta\b(?=[^>]*\bname=['\"]description['\"])", head, flags=re.IGNORECASE))
    og_description = bool(re.search(r"<meta\b(?=[^>]*\bproperty=['\"]og:description['\"])", head, flags=re.IGNORECASE))
    canonical_home = bool(re.search(r"<link\b(?=[^>]*\brel=['\"]canonical['\"])(?=[^>]*https://holyyomiai\.blogspot\.com/?['\"])", head, flags=re.IGNORECASE))
    if not meta_description:
        issues.append("home_meta_description_missing")
    if not og_description:
        warnings.append("home_og_description_missing")
    if not canonical_home:
        warnings.append("home_canonical_not_detected")

    mixed_case_links = re.findall(r"https://holyyomiAI\.blogspot\.com[^'\"<\s]+", content)
    if mixed_case_links:
        warnings.append("mixed_case_blogspot_links_present")

    return {
        "issues": issues,
        "warnings": warnings,
        "legacy_phrases_found": legacy_found,
        "expected_phrases_found": expected_found,
        "home_meta_description_present": meta_description,
        "home_og_description_present": og_description,
        "home_canonical_detected": canonical_home,
        "mixed_case_blogspot_link_count": len(mixed_case_links),
    }


def extract_recent_post_urls(html: str, *, base: str, limit: int = 8) -> list[str]:
    host = base.rstrip("/")
    urls: list[str] = []
    for match in re.finditer(r"https://holyyomiai\.blogspot\.com/\d{4}/\d{2}/[^'\"<\s]+?\.html", html or "", flags=re.IGNORECASE):
        url = match.group(0)
        url = re.sub(r"&amp;.*$", "", url)
        normalized = url.replace("https://holyyomiAI.blogspot.com", host)
        if normalized not in urls:
            urls.append(normalized)
        if len(urls) >= limit:
            break
    return urls


def write_reports(payload: LiveAuditPayload, *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"live_blog_audit_{stamp}.json"
    md_path = output_dir / f"live_blog_audit_{stamp}.md"
    json_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


def render_markdown(payload: LiveAuditPayload) -> str:
    lines = [
        "# Live AI Blog Audit",
        "",
        f"- Blog: {payload.blog_url}",
        f"- Generated: {payload.generated_at}",
        f"- Passed: {payload.passed}",
        "",
        "## Issues",
    ]
    lines.extend(f"- {item}" for item in payload.issues) if payload.issues else lines.append("- None")
    lines.append("")
    lines.append("## Warnings")
    lines.extend(f"- {item}" for item in payload.warnings) if payload.warnings else lines.append("- None")
    lines.append("")
    lines.append("## Checks")
    for key, value in payload.checks.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    return "\n".join(lines)


def _head_html(html: str) -> str:
    match = re.search(r"<head\b[^>]*>(.*?)</head>", html or "", flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit live holyyomi AI Blogspot configuration.")
    parser.add_argument("--blog-url", default=DEFAULT_BLOG_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when blocking issues are found.")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)

    payload = audit_live_blog(blog_url=args.blog_url, timeout=args.timeout)
    json_path, md_path = write_reports(payload, output_dir=Path(args.output_dir))
    print(json.dumps(asdict(payload), ensure_ascii=False, indent=2))
    print(f"reports: {json_path} {md_path}")
    if args.strict and payload.issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
