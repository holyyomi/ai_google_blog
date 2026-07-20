"""2026-07-18 한국어 껍데기로 발행된 2건을 라이브에서 초안으로 강등한다.

대상 (2026-07-20 감사에서 확인, 본문에 주제 콘텐츠 0 + 한국어 템플릿):
  - 4662313197665085644  Best AI Tools for Real Estate Agents (2026)
  - 1186129086956971667  Claude Fable 5: Free Access Extended to July 19 ...

삭제가 아니라 Blogger API `revert`(발행→초안) — 대시보드에서 언제든 복구 가능.

실행: PYTHONPATH=src python scripts/revert_shell_posts_to_draft.py
"""
from __future__ import annotations

import json
import urllib.request

from dotenv import load_dotenv

load_dotenv()

from blogspot_automation.config import Settings  # noqa: E402
from blogspot_automation.publishing.client import BloggerClient  # noqa: E402

SHELL_POSTS = [
    ("4662313197665085644", "Best AI Tools for Real Estate Agents (2026)"),
    ("1186129086956971667", "Claude Fable 5: Free Access Extended to July 19"),
]


def main() -> None:
    client = BloggerClient(Settings())
    token = client._get_access_token()
    for post_id, name in SHELL_POSTS:
        url = (
            f"https://www.googleapis.com/blogger/v3/blogs/"
            f"{client.blog_id}/posts/{post_id}/revert"
        )
        req = urllib.request.Request(
            url, data=b"", headers={"Authorization": f"Bearer {token}"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        print(f"{name} -> status: {result.get('status')}")


if __name__ == "__main__":
    main()
