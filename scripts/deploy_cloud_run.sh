#!/usr/bin/env bash
# Cloud Run Job 배포/업데이트 — GHA Actions 분당 한도 소진 폴백 인프라 (2026-07-20).
# 실행: bash scripts/deploy_cloud_run.sh
set -euo pipefail

PROJECT="blog-auto-476403"
REGION="asia-northeast3"
JOB_NAME="ai-blog-pipeline"
IMAGE="asia-northeast3-docker.pkg.dev/${PROJECT}/ai-blog-images/ai-blog-pipeline:latest"
SERVICE_ACCOUNT="ai-google-blog@${PROJECT}.iam.gserviceaccount.com"

ENV_VARS="DRY_RUN=false,AUTO_PUBLISH=true,NEWS_PUBLISH_MODE=publish,NEWS_PUBLISH_AS_DRAFT=false,PUBLISH_HOLD_PHASE2=false,NEWS_MODE=news,AI_BLOG_MODE=true,AI_BLOG_AUTO_PUBLISH=true,ALLOW_AI_NEWS_TOPICS=true,MIN_TOPIC_SCORE=75,TOPIC_CANDIDATE_LIMIT=120,DEDUP_DAYS=7,TITLE_CANDIDATE_COUNT=10,NEWS_MAX_PUBLISH_ATTEMPTS=12,ALLOW_EVERGREEN_AUTO_PUBLISH=true,ENABLE_AI_LLM_ENRICH=true,ENABLE_GOOGLE_CUSTOM_SEARCH=false,OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free,OPENROUTER_MODEL_FALLBACK=google/gemma-4-26b-a4b-it:free,OPENAI_MODEL=gpt-5-mini,ENABLE_COVER_IMAGE_AUTOGEN=true,REQUIRE_NEWS_COVER_IMAGE=false,AI_DEFAULT_COVER_IMAGE_URL=https://raw.githubusercontent.com/holyyomi/ai_google_blog/main/assets/ai-blog-cover-default.png,ENABLE_NAVER_SEARCH=true,ENABLE_NAVER_DATALAB=true,ENABLE_TAVILY_SEARCH=true,ENABLE_EXA_SEARCH=true,ENABLE_FIRECRAWL_SEARCH=true,NEWS_TAVILY_MAX_REQUESTS=3,NEWS_EXA_MAX_REQUESTS=3,NEWS_FIRECRAWL_MAX_REQUESTS=1,BLOGSPOT_HOME_URL=https://holyyomiai.blogspot.com/,BLOG_BRAND_NAME=holyyomi AI,BLOG_AUTHOR_NAME=holyyomi AI,RUNS_DIR=runs,BLOG_LANGUAGE=en"

SECRETS="GOOGLE_SEARCH_API_KEY=google-search-api-key:latest,GOOGLE_SEARCH_CX=google-search-cx:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,OPENAI_API_KEY=openai-api-key:latest,IMGBB_API_KEY=imgbb-api-key:latest,CLOUDFLARE_ACCOUNT_ID=cloudflare-account-id:latest,CLOUDFLARE_API_TOKEN=cloudflare-api-token:latest,NAVER_CLIENT_ID=naver-client-id:latest,NAVER_CLIENT_SECRET=naver-client-secret:latest,TAVILY_API_KEY=tavily-api-key:latest,EXA_API_KEY=exa-api-key:latest,FIRECRAWL_API_KEY=firecrawl-api-key:latest,NAVER_INDEXNOW_KEY=naver-indexnow-key:latest,NAVER_INDEXNOW_KEY_LOCATION=naver-indexnow-key-location:latest,BLOGGER_CLIENT_ID=blogger-client-id:latest,BLOGGER_CLIENT_SECRET=blogger-client-secret:latest,BLOGGER_REFRESH_TOKEN=blogger-refresh-token:latest,BLOGGER_BLOG_ID=blogger-blog-id:latest,CLAUDE_CODE_OAUTH_TOKEN=claude-code-oauth-token:latest,GITHUB_REPO_TOKEN=github-repo-token:latest"

if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  ACTION="update"
else
  ACTION="create"
fi

gcloud run jobs "${ACTION}" "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --set-env-vars="${ENV_VARS}" \
  --set-secrets="${SECRETS}" \
  --task-timeout=1800s \
  --max-retries=0 \
  --memory=1Gi \
  --cpu=1

echo "Cloud Run Job '${ACTION}'d: ${JOB_NAME}"
