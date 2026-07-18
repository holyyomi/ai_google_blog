"""Create/update the English static pages for holyyomi AI via Blogger Pages API.

Mirrors the existing create_about_page.py / create_policy_pages.py pattern,
but in English for the holyyomiai.blogspot.com conversion (BLOG_LANGUAGE=en).

DRAFT-ONLY BY DEFAULT: this script only prints what it *would* create unless
you pass --publish. Review the content below before publishing anything live.

Run (dry preview):
  PYTHONPATH=src python scripts/create_english_static_pages.py

Run (actually create pages on Blogger):
  PYTHONPATH=src python scripts/create_english_static_pages.py --publish

Existing Korean pages (개인정보처리방침/이용약관/면책조항/문의하기/About holyyomi AI Insight)
are left untouched — this creates NEW English-titled pages alongside them.
Decide separately whether to unpublish/redirect the old Korean pages once the
English versions are live (not handled by this script).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Windows 로컬 콘솔(cp949)에서 em-dash 등 비-cp949 문자 출력 시 크래시 방지.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE

CONTACT_EMAIL = "holyyomi@gmail.com"
BRAND_NAME = "holyyomi AI"
BLOG_URL = "https://holyyomiai.blogspot.com/"
LAST_UPDATED = "July 2026"


def _en_style() -> str:
    """YOMI_CLEAN_ARTICLE_STYLE with Korean CSS comments stripped (same rule the
    live EN article pipeline applies in seo_policy._yomi_clean_style_for_mode)."""
    stripped = re.sub(r"/\*.*?\*/", "", YOMI_CLEAN_ARTICLE_STYLE, flags=re.DOTALL)
    return re.sub(r"\n{2,}", "\n", stripped)


def _wrap(body: str) -> str:
    return _en_style() + '\n<article class="yomi-clean-post">' + body + "</article>"


PAGES: dict[str, str] = {
    f"About {BRAND_NAME}": _wrap(f"""
<section class="yomi-lede"><p><strong>{BRAND_NAME}</strong> is a practical reference for people choosing, comparing, pricing, and troubleshooting AI tools — ChatGPT, Claude, Gemini, Copilot, Perplexity, and the rest of the fast-moving AI toolkit.</p></section>
<h2>What we cover</h2>
<ul class="yomi-list">
<li data-step="1"><strong>Comparisons</strong> — which tool actually fits your job, not a generic feature list</li>
<li data-step="2"><strong>Pricing</strong> — what free vs. paid plans really get you, with current numbers and sources</li>
<li data-step="3"><strong>Fixes</strong> — real errors and limits, and what to do about them</li>
<li data-step="4"><strong>Data &amp; Stats</strong> — adoption numbers and benchmarks, with the source and scope attached</li>
<li data-step="5"><strong>How-To</strong> — reusable workflows you can run yourself</li>
</ul>
<h2>How we work</h2>
<p>We prioritize verified information over speed. Every price, limit, or spec we publish carries an as-of date and a named source — official pricing pages and release notes first, community reports only for spotting what to check next. We do not publish invented benchmarks, fabricated hands-on experience, or income guarantees.</p>
<h2>Contact</h2>
<p>Corrections, topic suggestions, and feedback: <strong>{CONTACT_EMAIL}</strong></p>
"""),
    "Privacy Policy": _wrap(f"""
<section class="yomi-lede"><p>{BRAND_NAME} ({BLOG_URL}) respects your privacy. This page explains what data is collected when you visit.</p></section>
<h2>Information we collect</h2>
<p>This blog does not require registration and does not ask you to submit personal information directly. Blogger (our hosting platform), Google Analytics, and Google AdSense may process cookies and non-identifying usage data such as pages visited, approximate location, device type, and referring site.</p>
<h2>Google AdSense &amp; advertising cookies</h2>
<p>This site displays Google AdSense ads. Google and its advertising partners use cookies to serve ads based on your visits to this and other websites. You can review and adjust how Google personalizes ads at <a href="https://adssettings.google.com" rel="noopener nofollow" target="_blank">Google Ad Settings</a>.</p>
<h2>Cookies</h2>
<p>You can manage or disable cookies in your browser settings at any time. Disabling cookies may affect how some parts of the site display.</p>
<h2>Third-party links</h2>
<p>Articles may link to official product pages, documentation, or news sources for verification. We are not responsible for the privacy practices of external sites.</p>
<h2>Children's privacy</h2>
<p>This site is not directed at children under 13 and we do not knowingly collect personal information from them.</p>
<h2>Contact</h2>
<p>Questions about this policy: <strong>{CONTACT_EMAIL}</strong></p>
<p class="yomi-note">Last updated: {LAST_UPDATED}</p>
"""),
    "Terms of Use": _wrap(f"""
<section class="yomi-lede"><p>Please review these terms before using {BRAND_NAME}.</p></section>
<h2>Use of content</h2>
<p>Articles on this site are provided for informational purposes. You may quote short excerpts with a link back to the original article; bulk reproduction or scraping without permission is not allowed.</p>
<h2>No professional advice</h2>
<p>Nothing on this site is financial, legal, tax, or medical advice. Content about AI tools, pricing, and workflows reflects publicly available information and editorial judgment at the time of writing — verify anything decision-critical against the official source before acting on it.</p>
<h2>Accuracy</h2>
<p>AI product pricing, features, and policies change frequently. We date-stamp verified numbers ("as of [Month Year]") and cite sources, but you should confirm current details on the official page before purchasing or relying on any figure.</p>
<h2>Advertising</h2>
<p>This site displays Google AdSense advertising. Ad content is served by Google and its partners and does not reflect the views of {BRAND_NAME}.</p>
<p class="yomi-note">Last updated: {LAST_UPDATED}</p>
"""),
    "Disclaimer": _wrap(f"""
<section class="yomi-lede"><p>Content on {BRAND_NAME} is provided for general informational purposes only.</p></section>
<h2>Not professional advice</h2>
<p>Nothing here constitutes legal, tax, financial, or medical advice. For decisions in those areas, consult a qualified professional or the relevant official authority.</p>
<h2>Limits of AI tool coverage</h2>
<p>AI product pricing, capabilities, terms, and availability change often and can vary by account, plan, or region. Article content reflects information verified as of its publish or last-checked date — always confirm current details on the official product page before you rely on them.</p>
<h2>No income guarantees</h2>
<p>Any content touching monetization, automation, or business use of AI tools describes general strategy, not a promised outcome. Results depend on your own execution, market conditions, and platform policies.</p>
<p class="yomi-note">Last updated: {LAST_UPDATED}</p>
"""),
    "Contact": _wrap(f"""
<section class="yomi-lede"><p>Have a correction, a topic request, or feedback for {BRAND_NAME}? Reach us below.</p></section>
<h2>Email</h2>
<p><strong>{CONTACT_EMAIL}</strong></p>
<h2>What to contact us about</h2>
<ul class="yomi-list">
<li data-step="1"><strong>Corrections</strong> — outdated pricing, a factual error, or a broken source link</li>
<li data-step="2"><strong>Topic requests</strong> — an AI tool, comparison, or pricing question you want covered</li>
<li data-step="3"><strong>Partnership inquiries</strong> — proposals that fit our editorial standards (no paid placements or affiliate links)</li>
</ul>
<p class="yomi-note">We read every message; individual replies may take a few days.</p>
"""),
    "How We Use AI": _wrap(f"""
<section class="yomi-lede"><p>{BRAND_NAME} uses AI tools as part of its writing and editing process. Here is exactly how, and what we do to keep it trustworthy.</p></section>
<h2>What AI assists with</h2>
<p>We use AI tools to help organize research, draft article sections, and edit for clarity. A publishing pipeline reviews every draft against a fact-safety policy before it goes live.</p>
<h2>Our fact-safety rules</h2>
<ul class="yomi-list">
<li data-step="1"><strong>Sourced numbers only</strong> — prices, limits, and specs are published only with an as-of date and a named source (official pricing pages and release notes first)</li>
<li data-step="2"><strong>No invented benchmarks or statistics</strong> — figures we can't verify are left out, with a note to check the official page instead</li>
<li data-step="3"><strong>No fabricated hands-on experience</strong> — we do not publish first-person "I tested this" claims; where a workflow is described, it's presented as a recipe you can run yourself, not a claimed result</li>
<li data-step="4"><strong>Quality gate before publish</strong> — drafts that fail our accuracy and structure checks are not published</li>
</ul>
<h2>Found an error?</h2>
<p>Tell us and we'll correct it: <strong>{CONTACT_EMAIL}</strong></p>
<p class="yomi-note">Last updated: {LAST_UPDATED}</p>
"""),
}


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#") and not line.startswith("$"):
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
        help="Actually create the pages on Blogger. Without this flag, only prints a preview.",
    )
    args = parser.parse_args()

    if not args.publish:
        print("DRY PREVIEW (no --publish flag) — pages that would be created:\n")
        for title, html in PAGES.items():
            print(f"=== {title} ({len(html)} chars) ===")
        print("\nRe-run with --publish to actually create these on Blogger.")
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
        existing_titles = {str(page.get("title", "")).strip() for page in (json.loads(response.read()).get("items") or [])}

    for title, html in PAGES.items():
        if title in existing_titles:
            print(f"SKIP already exists: {title}")
            continue
        page_req = urllib.request.Request(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
            data=json.dumps({"kind": "blogger#page", "title": title, "content": html}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(page_req, timeout=60) as response:
            data = json.loads(response.read())
        print(f"CREATED: {title} -> {data.get('url')}")


if __name__ == "__main__":
    main()
