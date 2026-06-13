from __future__ import annotations

import argparse
import json
import re
import urllib.request


DEFAULT_URL = "https://holyyomiai.blogspot.com/2026/06/chatgpt-ai-work-automation-productivity_0535613546.html"


def visible(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value or "").split())


def first(pattern: str, html: str) -> str:
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    return visible(match.group(1)) if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a published Blogspot AI post.")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    request = urllib.request.Request(args.url, headers={"User-Agent": "ai-blog-post-verify/1.0"})
    html = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", errors="replace")
    labels = [
        visible(match)
        for match in re.findall(r'rel=["\']tag["\'][^>]*>(.*?)</a>', html, flags=re.IGNORECASE | re.DOTALL)
    ]
    result = {
        "url": args.url,
        "html_length": len(html),
        "html_title": first(r"<title[^>]*>(.*?)</title>", html),
        "first_h1": first(r"<h1[^>]*>(.*?)</h1>", html),
        "meta_description_present": bool(
            re.search(r'<meta\b(?=[^>]*name=["\']description["\'])', html, flags=re.IGNORECASE | re.DOTALL)
        ),
        "canonical_self": args.url in html,
        "cover_image_present": "news-cover-image" in html and re.search(r"<img\b", html, re.IGNORECASE) is not None,
        "ai_citation_present": "AI_CITATION_SUMMARY" in html,
        "ai_overview_present": "AI_OVERVIEW_TARGET_ANSWER" in html,
        "faq_jsonld_present": "FAQPage" in html,
        "blogposting_jsonld_present": "BlogPosting" in html,
        "labels": labels,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    required = (
        result["canonical_self"]
        and result["cover_image_present"]
        and result["ai_citation_present"]
        and result["ai_overview_present"]
        and result["faq_jsonld_present"]
        and result["blogposting_jsonld_present"]
    )
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(main())
