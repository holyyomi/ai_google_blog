"""Create the About page for holyyomi AI Insight via Blogger Pages API.

Run:
  PYTHONPATH=src python scripts/create_about_page.py
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE

PAGE_TITLE = "About holyyomi AI Insight"

PAGE_HTML = YOMI_CLEAN_ARTICLE_STYLE + """
<article class="yomi-clean-post">
<section class="yomi-lede">
<p><strong>holyyomi AI Insight</strong>는 AI 도구, 자동화, 생산성, 검색 경험 변화를 일상 업무와 수익화 관점에서 쉽게 정리하는 블로그입니다.</p>
</section>

<h2>이 블로그가 다루는 것</h2>
<ul class="yomi-list">
<li data-step="1"><strong>AI 업무 자동화</strong> - ChatGPT, Gemini, Perplexity, 에이전트 도구를 실제 업무에 적용하는 방법</li>
<li data-step="2"><strong>AI 도구 비교</strong> - 기능 나열이 아니라 어떤 상황에서 무엇을 써야 하는지 판단 기준 제공</li>
<li data-step="3"><strong>AI 검색과 콘텐츠 전략</strong> - SEO, AEO, GEO, SGE 흐름에 맞춘 글 구조와 노출 전략</li>
<li data-step="4"><strong>수익화 관점</strong> - 애드센스와 블로그 운영에 도움이 되는 실전 체크리스트</li>
</ul>

<h2>작성 원칙</h2>
<p>단순한 AI 뉴스 요약보다 독자가 바로 실행할 수 있는 기준을 우선합니다. 과장된 수익 보장, 확인되지 않은 성능 주장, 특정 서비스 홍보성 표현은 피하고 실제 활용 시 주의할 점을 함께 정리합니다.</p>

<h2>문의</h2>
<p>수정 요청, 제휴 문의, 피드백은 <strong>holyyomi@gmail.com</strong> 으로 보내주세요.</p>
</article>
"""


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#") and not line.startswith("$"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))


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
        existing = json.loads(response.read()).get("items") or []
    for page in existing:
        if str(page.get("title", "")).strip() == PAGE_TITLE:
            print("Already exists:", page.get("url"))
            return

    page_req = urllib.request.Request(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
        data=json.dumps({"kind": "blogger#page", "title": PAGE_TITLE, "content": PAGE_HTML}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(page_req, timeout=60) as response:
        data = json.loads(response.read())
    print("ABOUT_PAGE_URL:", data.get("url"))


if __name__ == "__main__":
    main()
