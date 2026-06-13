"""BLOGGER_REFRESH_TOKEN 재발급 로컬 도구.

사전 조건:
  - 환경변수 BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET 설정 (.env 또는 셸 export)
  - Google Cloud Console에 "Desktop app" 유형 OAuth Client 생성
  - 동의 화면(Consent screen)에서 본인 Google 계정이 "테스트 사용자"로 등록됨
  - google-auth-oauthlib 설치됨 (이미 requirements.txt 포함)

실행:
  python tools/oauth_refresh_token.py

발급된 refresh token은 stdout에 한 줄만 출력된다. 어떤 파일에도 저장되지 않는다.
즉시 복사해 GitHub Repo Settings → Secrets에 BLOGGER_REFRESH_TOKEN 값으로 등록할 것.
"""
from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/blogger"]


def main() -> int:
    client_id = (os.getenv("BLOGGER_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("BLOGGER_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        sys.stderr.write(
            "ERROR: 환경변수 BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET 둘 다 필요합니다.\n"
            "  - 로컬 .env 파일에 추가하거나, 셸에서 export 후 다시 실행하세요.\n"
            "  - 값은 절대 깃에 커밋하지 마세요.\n"
        )
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    sys.stderr.write(
        "브라우저가 열리면 BLOGGER_BLOG_ID 소유 계정으로 로그인하고 권한을 승인하세요.\n"
        "승인 후 이 터미널에 refresh token이 출력됩니다.\n\n"
    )

    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        success_message="Refresh token 발급 완료. 터미널 창으로 돌아가세요.",
    )

    if not creds.refresh_token:
        sys.stderr.write(
            "ERROR: refresh_token이 응답에 없습니다.\n"
            "  - OAuth client 유형이 'Desktop app'인지 확인하세요.\n"
            "  - 동의 화면에 본인 계정이 테스트 사용자로 등록됐는지 확인하세요.\n"
        )
        return 2

    print(creds.refresh_token)
    sys.stderr.write(
        "\n위의 한 줄이 새 BLOGGER_REFRESH_TOKEN입니다.\n"
        "GitHub Repo Settings → Secrets and variables → Actions 에서\n"
        "BLOGGER_REFRESH_TOKEN 값으로 등록하세요.\n"
        "이 토큰은 어떤 파일에도 저장되지 않았습니다. 화면을 닫기 전 즉시 복사하세요.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
