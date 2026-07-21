#!/usr/bin/env bash
# Cloud Scheduler 잡 2개 생성 — 07:31/19:31 KST GHA 스케줄보다 19분 늦게(07:50/19:50)
# 쏴서 GHA가 먼저 시작할 시간을 준다(entrypoint.sh가 GHA 최근 run 존재 여부를
# 확인해 있으면 no-op으로 즉시 종료).
#
# 재시도 상한(2026-07-21 사용자 결정): "의미없는 반복실행 금지" — 이 HTTP
# 트리거(:run 호출) 자체가 실패하면(예: Cloud Run API 일시 장애) 최대 3회까지만
# (최초 1회 + 재시도 2회) 시도하고 그 다음 스케줄 시각까지 기다린다. 기존 기본값
# (max-retry-attempts=0)은 "실패해도 재시도 안 함"이었으므로 이 설정은 완전한
# 무재시도에서 상한 있는 재시도로 바뀌는 것이지, 무한 반복 방지가 아니다 —
# 다만 max-retry-attempts를 앞으로 올릴 경우를 대비해 max-retry-duration도
# 함께 유한값(30분)으로 명시해 절대 무한 재시도가 되지 않게 고정한다.
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
    --oauth-service-account-email="${SERVICE_ACCOUNT}" \
    --max-retry-attempts=2 \
    --max-retry-duration=1800s
  echo "Scheduler job '${ACTION}'d: ${NAME} (${CRON} Asia/Seoul)"
done
