#!/usr/bin/env bash
# GCP Secret Manager -> GitHub Actions secrets 동기화 (2026-07-23).
#
# 배경: Cloud Run job은 deploy_cloud_run.sh의 --set-secrets가 매 실행마다
# ":latest"를 읽어 Secret Manager 갱신을 자동 반영하지만, ai_blog.yml(GHA)은
# 별도의 GitHub Actions repo secret을 쓴다. 토큰을 Secret Manager에서만
# 롤하고 이 GitHub 쪽을 빼먹으면 Cloud Run은 멀쩡한데 GHA(리허설·8/1부터
# 재개될 schedule)만 401로 죽는다 — 실측: CLOUDFLARE_API_TOKEN이 2026-06-13
# 이후 한 번도 GitHub에 반영 안 된 채 방치돼 있었음.
#
# 이 스크립트는 그 수동 동기화를 한 번의 명령으로 만든다. Secret Manager
# 이름을 바꾸지 않는 시크릿(계정 ID처럼 거의 안 바뀌는 값 포함)이라도 그냥
# 다시 밀어 넣는 건 안전하다.
#
# 사용: bash scripts/sync_github_secrets_from_gcp.sh [github_secret_name ...]
#   인자 없이 실행하면 아래 매핑 전체를 동기화한다.
set -euo pipefail

REPO="holyyomi/ai_google_blog"

# GitHub secret name -> GCP Secret Manager name (deploy_cloud_run.sh의
# SECRETS 매핑과 동일한 이름을 쓴다 — 새 시크릿을 추가할 때 거기도 같이 볼 것).
declare -A SECRET_MAP=(
  [CLOUDFLARE_API_TOKEN]=cloudflare-api-token
  [CLOUDFLARE_ACCOUNT_ID]=cloudflare-account-id
  [GOOGLE_SEARCH_API_KEY]=google-search-api-key
  [GOOGLE_SEARCH_CX]=google-search-cx
  [OPENROUTER_API_KEY]=openrouter-api-key
  [OPENAI_API_KEY]=openai-api-key
  [IMGBB_API_KEY]=imgbb-api-key
  [NAVER_CLIENT_ID]=naver-client-id
  [NAVER_CLIENT_SECRET]=naver-client-secret
  [TAVILY_API_KEY]=tavily-api-key
  [EXA_API_KEY]=exa-api-key
  [FIRECRAWL_API_KEY]=firecrawl-api-key
  [NAVER_INDEXNOW_KEY]=naver-indexnow-key
  [NAVER_INDEXNOW_KEY_LOCATION]=naver-indexnow-key-location
  [BLOGGER_CLIENT_ID]=blogger-client-id
  [BLOGGER_CLIENT_SECRET]=blogger-client-secret
  [BLOGGER_REFRESH_TOKEN]=blogger-refresh-token
  [BLOGGER_BLOG_ID]=blogger-blog-id
)

targets=("$@")
if [ ${#targets[@]} -eq 0 ]; then
  targets=("${!SECRET_MAP[@]}")
fi

for gh_name in "${targets[@]}"; do
  gcp_name="${SECRET_MAP[$gh_name]:-}"
  if [ -z "$gcp_name" ]; then
    echo "skip: no GCP mapping for '${gh_name}' (add it to SECRET_MAP if needed)" >&2
    continue
  fi
  value="$(gcloud secrets versions access latest --secret="${gcp_name}")"
  gh secret set "${gh_name}" --repo "${REPO}" --body "${value}"
  echo "synced: ${gh_name} <- gcp:${gcp_name}"
done
