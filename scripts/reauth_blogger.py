"""Blogger OAuth 리프레시 토큰 재발급 (2026-07 만료 대응).

실행하면 브라우저가 자동으로 열리고, holyyomi 계정으로 로그인 + 권한 허용을
누르면 끝난다. 새 리프레시 토큰을 GCP Secret Manager(blogger-refresh-token)에
바로 저장하고, 로컬 .env의 BLOGGER_REFRESH_TOKEN도 같이 갱신한다.

실행: python scripts/reauth_blogger.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_SECRET_FILE = "client_secret_606500166269-d3rljphnljf78fiphifurcq5alres2kk.apps.googleusercontent.com.json"
SCOPES = ["https://www.googleapis.com/auth/blogger"]
PROJECT = "blog-auto-476403"


def main() -> None:
    print("브라우저가 열립니다. holyyomi Blogger 계정으로 로그인 후 '허용'을 눌러주세요.")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    if not creds.refresh_token:
        raise SystemExit(
            "refresh_token이 발급되지 않았습니다. 이미 이 앱에 권한을 허용한 적이 있으면 "
            "https://myaccount.google.com/permissions 에서 'holyyomi AI Blog' 앱 접근을 "
            "제거한 뒤 다시 실행해 주세요(재동의해야 refresh_token이 새로 나옵니다)."
        )

    print("새 refresh_token 발급 완료. Secret Manager에 저장 중...")
    subprocess.run(
        ["gcloud", "secrets", "versions", "add", "blogger-refresh-token",
         "--data-file=-", f"--project={PROJECT}"],
        input=creds.refresh_token, text=True, check=True, shell=True,
    )

    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("BLOGGER_REFRESH_TOKEN="):
            lines[i] = f"BLOGGER_REFRESH_TOKEN={creds.refresh_token}"
            updated = True
            break
    if not updated:
        lines.append(f"BLOGGER_REFRESH_TOKEN={creds.refresh_token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("완료: Secret Manager(blogger-refresh-token)와 로컬 .env 둘 다 갱신했습니다.")


if __name__ == "__main__":
    main()
