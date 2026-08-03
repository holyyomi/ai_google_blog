#!/usr/bin/env bash
# Cloud Run Job 배포/업데이트 — GHA Actions 분당 한도 소진 폴백 인프라 (2026-07-20).
#
# ⚠️ 2026-08-03 현재 이 폴백은 **중단(PAUSED)** 상태다.
#    Cloud Scheduler "ai-blog-evening"이 정지돼 있고 자동 발행은 GHA 단독이다.
#    이유는 CLAUDE.md "Cloud Run 폴백을 왜 껐는가" 참고 — 요약하면 파이프라인
#    완주에 22~49분이 걸리는데 task-timeout이 1800초(30분)라 7/29~8/2 5일 연속
#    SIGKILL됐고, GHA 큐 지연 시 매일 중복 실행까지 하고 있었다.
#
#    되살리려면 (1) 아래 --task-timeout이 3300s인지 확인하고
#    (2) bash scripts/deploy_cloud_run.sh 로 재배포한 뒤
#    (3) gcloud scheduler jobs resume ai-blog-evening --location=asia-northeast3
#    순서로 할 것. 1800s로는 구조적으로 완주가 불가능하다.
#
# 실행: bash scripts/deploy_cloud_run.sh
set -euo pipefail

PROJECT="blog-auto-476403"
REGION="asia-northeast3"
JOB_NAME="ai-blog-pipeline"
IMAGE="asia-northeast3-docker.pkg.dev/${PROJECT}/ai-blog-images/ai-blog-pipeline:latest"
SERVICE_ACCOUNT="ai-google-blog@${PROJECT}.iam.gserviceaccount.com"

# 2026-08-03: ENABLE_TAVILY_SEARCH·ENABLE_FIRECRAWL_SEARCH를 false로,
# COMMUNITY_REDDIT_SUBS=off를 추가 — ai_blog.yml과 동일한 예산 정책을 유지한다
# (실측 전 호출 실패: Tavily 432 / Firecrawl 402 / Reddit 403).
# ENABLE_EXA_SEARCH는 본문 팩트의 핵심이라 true 유지 필수.
ENV_VARS="DRY_RUN=false,AUTO_PUBLISH=true,NEWS_PUBLISH_MODE=publish,NEWS_PUBLISH_AS_DRAFT=false,PUBLISH_HOLD_PHASE2=false,NEWS_MODE=news,AI_BLOG_MODE=true,AI_BLOG_AUTO_PUBLISH=true,ALLOW_AI_NEWS_TOPICS=true,MIN_TOPIC_SCORE=75,TOPIC_CANDIDATE_LIMIT=120,DEDUP_DAYS=7,TITLE_CANDIDATE_COUNT=10,NEWS_MAX_PUBLISH_ATTEMPTS=6,NEWS_EXA_MAX_FACT_CALLS=12,ALLOW_EVERGREEN_AUTO_PUBLISH=true,ENABLE_AI_LLM_ENRICH=true,ENABLE_GOOGLE_CUSTOM_SEARCH=false,OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free,OPENROUTER_MODEL_FALLBACK=google/gemma-4-26b-a4b-it:free,OPENAI_MODEL=gpt-5-mini,ENABLE_COVER_IMAGE_AUTOGEN=true,REQUIRE_NEWS_COVER_IMAGE=false,AI_DEFAULT_COVER_IMAGE_URL=https://raw.githubusercontent.com/holyyomi/ai_google_blog/main/assets/ai-blog-cover-default.png,ENABLE_NAVER_SEARCH=true,ENABLE_NAVER_DATALAB=true,ENABLE_TAVILY_SEARCH=false,ENABLE_EXA_SEARCH=true,ENABLE_FIRECRAWL_SEARCH=false,COMMUNITY_REDDIT_SUBS=off,NEWS_TAVILY_MAX_REQUESTS=3,NEWS_EXA_MAX_REQUESTS=3,NEWS_FIRECRAWL_MAX_REQUESTS=1,BLOGSPOT_HOME_URL=https://holyyomiai.blogspot.com/,BLOG_BRAND_NAME=holyyomi AI,BLOG_AUTHOR_NAME=holyyomi AI,RUNS_DIR=runs,BLOG_LANGUAGE=en"

# GSC_SERVICE_ACCOUNT_JSON: 2026-07-25 추가. 없으면 fetch_search_performance.py가 조용히
# 스킵되어 검색수요 가산점(_apply_search_performance_boost)이 상시 no-op이 된다 —
# 2026-07 내내 Cloud Run이 1순위였는데 이 env가 없어서 성과 피드백 루프가 끊겨 있었다.
SECRETS="GSC_SERVICE_ACCOUNT_JSON=gsc-service-account-json:latest,GOOGLE_SEARCH_API_KEY=google-search-api-key:latest,GOOGLE_SEARCH_CX=google-search-cx:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,OPENAI_API_KEY=openai-api-key:latest,IMGBB_API_KEY=imgbb-api-key:latest,CLOUDFLARE_ACCOUNT_ID=cloudflare-account-id:latest,CLOUDFLARE_API_TOKEN=cloudflare-api-token:latest,NAVER_CLIENT_ID=naver-client-id:latest,NAVER_CLIENT_SECRET=naver-client-secret:latest,TAVILY_API_KEY=tavily-api-key:latest,EXA_API_KEY=exa-api-key:latest,FIRECRAWL_API_KEY=firecrawl-api-key:latest,NAVER_INDEXNOW_KEY=naver-indexnow-key:latest,NAVER_INDEXNOW_KEY_LOCATION=naver-indexnow-key-location:latest,BLOGGER_CLIENT_ID=blogger-client-id:latest,BLOGGER_CLIENT_SECRET=blogger-client-secret:latest,BLOGGER_REFRESH_TOKEN=blogger-refresh-token:latest,BLOGGER_BLOG_ID=blogger-blog-id:latest,CLAUDE_CODE_OAUTH_TOKEN=claude-code-oauth-token:latest,GITHUB_REPO_TOKEN=github-repo-token:latest"

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
  --task-timeout=3300s \
  --max-retries=0 \
  --memory=1Gi \
  --cpu=1

echo "Cloud Run Job '${ACTION}'d: ${JOB_NAME}"
