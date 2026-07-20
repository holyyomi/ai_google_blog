#!/usr/bin/env bash
# Cloud Scheduler 잡 2개 생성 — 07:31/19:31 KST GHA 스케줄보다 19분 늦게(07:50/19:50)
# 쏴서 GHA가 먼저 시작할 시간을 준다(entrypoint.sh가 GHA 최근 run 존재 여부를
# 확인해 있으면 no-op으로 즉시 종료).
set -euo pipefail

PROJECT="blog-auto-476403"
REGION="asia-northeast3"
JOB_NAME="ai-blog-pipeline"

RUN_JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run"
SERVICE_ACCOUNT="ai-google-blog@${PROJECT}.iam.gserviceaccount.com"

for pair in "ai-blog-morning:50 7 * * *" "ai-blog-evening:50 19 * * *"; do
  NAME="${pair%%:*}"
  CRON="${pair#*:}"
  if gcloud scheduler jobs describe "${NAME}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
    ACTION="update"
  else
    ACTION="create"
  fi
  gcloud scheduler jobs "${ACTION}" http "${NAME}" \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --schedule="${CRON}" \
    --time-zone="Asia/Seoul" \
    --uri="${RUN_JOB_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SERVICE_ACCOUNT}"
  echo "Scheduler job '${ACTION}'d: ${NAME} (${CRON} Asia/Seoul)"
done
