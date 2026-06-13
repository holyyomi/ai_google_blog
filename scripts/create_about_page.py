"""소개(About) 페이지 1회성 생성 — E-E-A-T 신뢰 신호.

Blogger Pages API로 정적 페이지를 게시한다. 본문은 yomi-clean 스타일을 임베드.
실행: PYTHONPATH=src python scripts/create_about_page.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE

PAGE_TITLE = "소개 — 요미의 오늘 이슈"

PAGE_HTML = YOMI_CLEAN_ARTICLE_STYLE + """
<article class="yomi-clean-post">
<section class="yomi-lede">
<p><strong>요미의 오늘 이슈</strong>는 매일 한국에서 가장 화제가 된 이슈를 골라,
단순 요약이 아니라 <strong>맥락과 다양한 관점</strong>으로 풀어내는 해설 블로그입니다.</p>
</section>

<h2>이 블로그가 다루는 것</h2>
<p>하루에도 수백 개의 기사가 같은 사건을 거의 같은 문장으로 전합니다.
이 블로그는 그중 독자의 생활에 실제로 영향을 주는 이슈를 골라,
"무슨 일이 있었나"에서 멈추지 않고 <strong>왜 지금 중요한지, 누구에게 어떤 영향이 가는지,
다음에 무엇을 지켜봐야 하는지</strong>까지 정리합니다.</p>

<h2>작성 원칙</h2>
<ul class="yomi-list">
<li data-step="1"><strong>복수 보도 교차 확인</strong> — 사실로 적는 내용은 여러 매체가 동시에 전한 범위로 한정합니다.</li>
<li data-step="2"><strong>사실과 해석의 분리</strong> — 확인된 사실은 단정하고, 글쓴이의 해석은 해석임을 드러냅니다.</li>
<li data-step="3"><strong>확인된 것 / 아직인 것 구분</strong> — 모든 글 끝에 확정 사실과 미확정 쟁점을 나눠 정리합니다.</li>
<li data-step="4"><strong>출처 표기</strong> — 본문 근거가 된 보도·공식 발표의 출처를 글마다 밝힙니다.</li>
</ul>

<h2>콘텐츠 기준</h2>
<p class="yomi-note">자극적 표현·미확인 루머·특정 인물에 대한 단정적 평가는 다루지 않습니다.
진행 중인 사안은 후속 발표에 따라 내용이 달라질 수 있으며, 중요한 판단은 원문 보도와
공식 발표를 함께 확인하시길 권합니다.</p>

<h2>문의</h2>
<p>내용 정정 요청이나 다뤄줬으면 하는 이슈가 있다면 해당 글의 댓글로 남겨주세요.
정정 요청은 확인 후 본문에 반영합니다.</p>
</article>
"""


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#") and not line.startswith("$"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip().lstrip("﻿"), v.strip().strip('"').strip("'"))


def main() -> None:
    _load_env()
    client_id = os.getenv("BLOGGER_CLIENT_ID", "")
    client_secret = os.getenv("BLOGGER_CLIENT_SECRET", "")
    refresh_token = os.getenv("BLOGGER_REFRESH_TOKEN", "")
    blog_id = os.getenv("BLOGGER_BLOG_ID", "")
    assert all([client_id, client_secret, refresh_token, blog_id]), "Blogger 자격증명 누락"

    import urllib.parse
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
    with urllib.request.urlopen(token_req, timeout=30) as r:
        token = json.loads(r.read())["access_token"]

    # 이미 같은 제목의 페이지가 있으면 중복 생성 방지
    list_req = urllib.request.Request(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(list_req, timeout=30) as r:
        existing = json.loads(r.read()).get("items") or []
    for p in existing:
        if str(p.get("title", "")).strip() == PAGE_TITLE:
            print("이미 존재:", p.get("url"))
            return

    page_req = urllib.request.Request(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
        data=json.dumps({
            "kind": "blogger#page",
            "title": PAGE_TITLE,
            "content": PAGE_HTML,
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(page_req, timeout=60) as r:
        data = json.loads(r.read())
    print("ABOUT_PAGE_URL:", data.get("url"))


if __name__ == "__main__":
    main()
