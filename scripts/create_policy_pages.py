"""정책 페이지 4종 1회성 생성 — 애드센스 운영 필수 고지.

개인정보처리방침 / 이용약관 / 면책조항 / 문의 페이지를 Blogger Pages API로 게시.
실행: PYTHONPATH=src python scripts/create_policy_pages.py
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE

CONTACT_EMAIL = "holyyomi@gmail.com"
LAST_UPDATED = "2026년 6월 10일"

def _wrap(body: str) -> str:
    # CSS에 중괄호가 많아 str.format 사용 불가 — 단순 연결.
    return YOMI_CLEAN_ARTICLE_STYLE + '\n<article class="yomi-clean-post">' + body + "</article>"

PAGES: dict[str, str] = {
    "개인정보처리방침": _wrap(f"""
<section class="yomi-lede"><p>요미의 오늘 이슈(이하 "본 블로그")는 방문자의 개인정보를 소중히 여기며,
관련 법령과 Google 정책에 따라 아래와 같이 개인정보 처리 방침을 안내합니다.</p></section>

<h2>1. 수집하는 정보</h2>
<p>본 블로그는 회원가입 기능이 없으며, 방문자가 직접 입력하는 개인정보를 수집하지 않습니다.
다만 아래 서비스들이 쿠키 등을 통해 비식별 정보를 자동 수집할 수 있습니다.</p>

<h2>2. Google AdSense 광고</h2>
<ul>
<li>본 블로그는 <strong>Google AdSense 광고</strong>를 게재합니다.</li>
<li>Google을 포함한 제3자 광고 사업자는 <strong>쿠키</strong>를 사용하여 방문자의 이전 방문 기록에 기반한
<strong>맞춤형 광고</strong>를 제공할 수 있습니다.</li>
<li>Google의 광고 쿠키 사용에 대한 자세한 내용과 사용 중지 방법은
<a href="https://policies.google.com/technologies/ads" rel="noopener">Google 광고 정책</a>에서 확인할 수 있습니다.</li>
<li>방문자는 <a href="https://adssettings.google.com" rel="noopener">Google 광고 설정</a>에서
맞춤형 광고를 관리하거나 사용 중지할 수 있습니다.</li>
</ul>

<h2>3. 분석 도구</h2>
<p>본 블로그는 방문 통계 파악을 위해 <strong>Google Analytics</strong> 등 분석 도구를 사용할 수 있습니다.
이 도구들은 쿠키를 통해 비식별 트래픽 정보(방문 페이지, 체류 시간, 유입 경로 등)를 수집하며,
특정 개인을 식별하지 않습니다. 새로운 분석 도구를 도입하는 경우 본 문서에 고지합니다.</p>

<h2>4. 쿠키 관리</h2>
<p>방문자는 브라우저 설정에서 쿠키 저장을 거부하거나 삭제할 수 있습니다.
쿠키를 거부해도 본 블로그 콘텐츠 이용에는 제한이 없습니다.</p>

<h2>5. 문의</h2>
<p>개인정보 처리에 관한 문의는 <strong>{CONTACT_EMAIL}</strong> 로 보내주세요.</p>

<p class="yomi-note">본 방침은 {LAST_UPDATED}에 최종 수정되었으며, 내용 변경 시 본 페이지를 통해 고지합니다.</p>
"""),

    "이용약관": _wrap(f"""
<section class="yomi-lede"><p>요미의 오늘 이슈를 방문해 주셔서 감사합니다.
본 블로그의 콘텐츠를 이용하시기 전에 아래 약관을 확인해 주세요.</p></section>

<h2>1. 콘텐츠 이용</h2>
<ul>
<li>본 블로그의 모든 글은 정보 제공 목적으로 작성됩니다.</li>
<li>콘텐츠의 무단 전재·복제·재배포를 금지합니다. 인용 시 출처(본 블로그 링크)를 명시해 주세요.</li>
</ul>

<h2>2. 책임의 범위</h2>
<ul>
<li>본 블로그는 작성 시점의 공개된 보도·공식 발표를 기준으로 콘텐츠를 작성하며,
이후 상황 변화로 내용이 실제와 달라질 수 있습니다.</li>
<li>본 블로그의 정보를 근거로 한 의사결정의 결과에 대해 운영자는 법적 책임을 지지 않습니다.
중요한 결정은 반드시 공식 출처를 직접 확인하시기 바랍니다.</li>
</ul>

<h2>3. 광고</h2>
<p>본 블로그에는 Google AdSense 광고가 게재되며, 광고 내용은 운영자의 견해와 무관합니다.</p>

<h2>4. 약관 변경</h2>
<p>본 약관은 필요 시 변경될 수 있으며, 변경 시 본 페이지를 통해 고지합니다.
문의: {CONTACT_EMAIL}</p>

<p class="yomi-note">최종 수정일: {LAST_UPDATED}</p>
"""),

    "면책조항": _wrap(f"""
<section class="yomi-lede"><p>본 블로그의 콘텐츠를 이용하시기 전에 아래 면책 사항을 확인해 주세요.</p></section>

<h2>1. 정보의 한계</h2>
<ul>
<li>본 블로그의 글은 작성 시점에 공개된 복수 언론 보도와 공식 발표를 교차 확인하여 작성되지만,
<strong>진행 중인 사안은 후속 발표에 따라 사실관계가 달라질 수 있습니다.</strong></li>
<li>글에 포함된 해석·전망은 운영자의 의견이며, 사실과 구분하여 표기합니다.</li>
</ul>

<h2>2. 전문 조언이 아님</h2>
<p>본 블로그의 콘텐츠는 법률·세무·투자·의료 등 전문 분야의 조언이 아닙니다.
해당 분야의 의사결정은 반드시 전문가와 상담하거나 공식 기관의 안내를 확인하세요.</p>

<h2>3. 외부 링크</h2>
<p>본 블로그가 안내하는 외부 사이트의 콘텐츠·정책에 대해 운영자는 책임지지 않습니다.</p>

<h2>4. 광고·제휴 고지</h2>
<p>본 블로그에는 Google AdSense 광고가 게재됩니다. 특정 글에 제휴·협찬이 포함되는 경우
해당 글에 별도로 명시합니다.</p>

<h2>5. 정정 요청</h2>
<p>사실관계 오류를 발견하셨다면 <strong>{CONTACT_EMAIL}</strong> 로 알려주세요. 확인 후 신속히 정정합니다.</p>

<p class="yomi-note">최종 수정일: {LAST_UPDATED}</p>
"""),

    "문의하기": _wrap(f"""
<section class="yomi-lede"><p>요미의 오늘 이슈에 전하고 싶은 말씀이 있다면 아래 연락처로 보내주세요.</p></section>

<h2>이메일</h2>
<p><strong>{CONTACT_EMAIL}</strong></p>

<h2>이런 내용을 환영합니다</h2>
<ul class="yomi-list">
<li data-step="1"><strong>내용 정정 요청</strong> — 사실관계 오류는 확인 후 본문에 반영하고 정정 사실을 남깁니다.</li>
<li data-step="2"><strong>다뤄줬으면 하는 이슈 제보</strong> — 독자 생활에 영향이 있는 주제를 우선 검토합니다.</li>
<li data-step="3"><strong>제휴·기타 문의</strong> — 블로그 운영 원칙에 맞는 제안만 회신드립니다.</li>
</ul>

<p class="yomi-note">개별 회신까지 시간이 걸릴 수 있습니다. 정정 요청은 가장 우선으로 처리합니다.</p>
"""),
}


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

    list_req = urllib.request.Request(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(list_req, timeout=30) as r:
        existing_titles = {
            str(p.get("title", "")).strip()
            for p in (json.loads(r.read()).get("items") or [])
        }

    for title, html in PAGES.items():
        if title in existing_titles:
            print(f"SKIP (이미 존재): {title}")
            continue
        page_req = urllib.request.Request(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages",
            data=json.dumps({"kind": "blogger#page", "title": title, "content": html}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(page_req, timeout=60) as r:
            data = json.loads(r.read())
        print(f"CREATED: {title} → {data.get('url')}")


if __name__ == "__main__":
    main()
