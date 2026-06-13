"""Create policy pages for holyyomi AI Insight via Blogger Pages API.

Run:
  PYTHONPATH=src python scripts/create_policy_pages.py
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE

CONTACT_EMAIL = "holyyomi@gmail.com"
LAST_UPDATED = "2026년 6월 13일"


def _wrap(body: str) -> str:
    return YOMI_CLEAN_ARTICLE_STYLE + '\n<article class="yomi-clean-post">' + body + "</article>"


PAGES: dict[str, str] = {
    "개인정보처리방침": _wrap(f"""
<section class="yomi-lede"><p>holyyomi AI Insight는 방문자의 개인정보를 소중히 여기며, 관련 법령과 Google 정책을 준수하기 위해 아래와 같이 개인정보 처리 방침을 안내합니다.</p></section>
<h2>수집하는 정보</h2>
<p>본 블로그는 별도 회원가입 기능을 운영하지 않으며 방문자가 직접 개인정보를 입력하도록 요구하지 않습니다. 다만 Blogger, Google AdSense, 분석 도구는 쿠키와 비식별 이용 정보를 처리할 수 있습니다.</p>
<h2>Google AdSense 광고</h2>
<p>본 블로그에는 Google AdSense 광고가 게재될 수 있습니다. Google 및 제휴 광고 사업자는 쿠키를 사용해 방문 기록 기반의 맞춤형 광고를 제공할 수 있습니다.</p>
<h2>쿠키 관리</h2>
<p>방문자는 브라우저 설정 또는 Google 광고 설정에서 쿠키와 맞춤형 광고를 관리할 수 있습니다.</p>
<h2>문의</h2>
<p>개인정보 관련 문의는 <strong>{CONTACT_EMAIL}</strong> 으로 보내주세요.</p>
<p class="yomi-note">최종 수정일: {LAST_UPDATED}</p>
"""),
    "이용약관": _wrap(f"""
<section class="yomi-lede"><p>holyyomi AI Insight를 이용하기 전에 아래 기준을 확인해 주세요.</p></section>
<h2>콘텐츠 이용</h2>
<p>본 블로그의 글은 정보 제공 목적입니다. 무단 복제, 대량 수집, 재배포를 금지하며 인용 시 출처와 링크를 표시해 주세요.</p>
<h2>책임 범위</h2>
<p>AI 도구, 자동화, 수익화 관련 내용은 작성 시점의 공개 정보와 운영 경험을 바탕으로 정리됩니다. 중요한 의사결정은 각 서비스의 공식 문서와 정책을 직접 확인한 뒤 진행해 주세요.</p>
<h2>광고</h2>
<p>본 블로그에는 Google AdSense 광고가 게재될 수 있으며, 광고 내용은 운영자의 의견과 무관할 수 있습니다.</p>
<p class="yomi-note">최종 수정일: {LAST_UPDATED}</p>
"""),
    "면책조항": _wrap(f"""
<section class="yomi-lede"><p>본 블로그의 AI 도구, 자동화, 수익화 관련 콘텐츠는 일반 정보 제공을 목적으로 합니다.</p></section>
<h2>전문 조언 아님</h2>
<p>본 블로그의 글은 법률, 세무, 투자, 의료 등 전문 조언이 아닙니다. 각 분야의 중요한 판단은 전문가 또는 공식 기관을 통해 확인해 주세요.</p>
<h2>AI 도구 결과의 한계</h2>
<p>AI 서비스의 성능, 가격, 약관, 모델 정책은 수시로 바뀔 수 있습니다. 글의 내용은 작성 시점 기준이며, 실제 사용 전 공식 문서를 확인해야 합니다.</p>
<h2>수익 보장 없음</h2>
<p>애드센스, 블로그, 자동화 수익은 트래픽, 콘텐츠 품질, 정책 준수, 시장 상황에 따라 달라집니다. 본 블로그는 특정 수익을 보장하지 않습니다.</p>
<p class="yomi-note">최종 수정일: {LAST_UPDATED}</p>
"""),
    "문의하기": _wrap(f"""
<section class="yomi-lede"><p>holyyomi AI Insight에 전하고 싶은 의견이나 수정 요청이 있다면 아래 연락처로 보내주세요.</p></section>
<h2>이메일</h2>
<p><strong>{CONTACT_EMAIL}</strong></p>
<h2>문의 가능 내용</h2>
<ul class="yomi-list">
<li data-step="1"><strong>내용 정정 요청</strong> - 오류나 오래된 정보가 있는 경우</li>
<li data-step="2"><strong>주제 제안</strong> - 다뤘으면 하는 AI 도구, 자동화, 수익화 주제</li>
<li data-step="3"><strong>제휴 문의</strong> - 블로그 운영 원칙에 맞는 제안</li>
</ul>
<p class="yomi-note">개별 회신까지 시간이 걸릴 수 있습니다.</p>
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
