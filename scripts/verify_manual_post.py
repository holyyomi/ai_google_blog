from __future__ import annotations

import json
import re
import urllib.request


URL = "https://holyeverymoments.blogspot.com/2026/06/ai-today-issue-update-news-e15d18.html"


def visible(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value or "").split())


def first(pattern: str, html: str) -> str:
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    return visible(match.group(1)) if match else ""


def main() -> int:
    request = urllib.request.Request(URL, headers={"User-Agent": "manual-post-verify/1.0"})
    html = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", errors="replace")
    labels = [
        visible(match)
        for match in re.findall(r'rel=["\']tag["\'][^>]*>(.*?)</a>', html, flags=re.IGNORECASE | re.DOTALL)
    ]
    result = {
        "url": URL,
        "html_length": len(html),
        "html_title": first(r"<title[^>]*>(.*?)</title>", html),
        "first_h1": first(r"<h1[^>]*>(.*?)</h1>", html),
        "post_title_h3": first(r'<h3[^>]*class=["\'][^"\']*post-title[^"\']*["\'][^>]*>(.*?)</h3>', html),
        "contains_manual_title": "젠슨 황 방한 보도" in html,
        "meta_description_present": bool(
            re.search(r'<meta\b(?=[^>]*name=["\']description["\'])', html, flags=re.IGNORECASE | re.DOTALL)
        ),
        "canonical_self": URL in html,
        "labels": labels,
        "contains_bad_phrases": any(
            phrase in html
            for phrase in ("재계는 지금", "화제 된 이 반응", "사람들이 본 에", "사람들이 본 의", "신청전 많이 묻는 질문")
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["contains_manual_title"] and not result["contains_bad_phrases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
