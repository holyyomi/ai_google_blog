#!/usr/bin/env bash
# Cloud Scheduler 잡 배포 — ai-blog-evening 1개 (2026-07-24 운영 방침 반영).
#
# 하루 1회 발행: GHA(ai_blog.yml schedule, 12:31 UTC)가 1순위이고, 이 잡이
# 19분 뒤(12:50 UTC) Cloud Run ai-blog-pipeline을 깨우면 scripts/
# cloud_run_pipeline.sh가 GHA 결과를 확인해 실패/부재 시에만 폴백 발행한다.
# (2026-07 한정: GHA 한도 소진으로 Cloud Run이 1순위 — 코드 게이트가 처리,
# 이 스케줄 설정은 그대로 두면 된다.)
#
# 과거의 ai-blog-morning(07:50 KST) 잡은 하루 1회 전환(2026-07-22)으로
# PAUSED 상태이며 이 스크립트는 더 이상 관리하지 않는다 — 삭제하려면:
#   gcloud scheduler jobs delete ai-blog-morning --location=asia-northeast3
#
# 재시도 상한(2026-07-21 사용자 결정): "의미없는 반복실행 금지" — 이 HTTP
# 트리거(:run 호출) 자체가 실패하면(예: Cloud Run API 일시 장애) 최대 3회까지만
# (최초 1회 + 재시도 2회) 시도하고 그 다음 스케줄 시각까지 기다린다.
# max-retry-duration도 유한값(30분)으로 명시해 절대 무한 재시도가 되지 않게 고정.
set -euo pipefail

PROJECT="blog-auto-476403"
REGION="asia-northeast3"
JOB_NAME="ai-blog-pipeline"

RUN_JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run"
SERVICE_ACCOUNT="ai-google-blog@${PROJECT}.iam.gserviceaccount.com"

NAME="ai-blog-evening"
CRON="50 12 * * *"   # 12:50 UTC — GHA 12:31 UTC보다 19분 늦게

if gcloud scheduler jobs describe "${NAME}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  ACTION="update"
else
  ACTION="create"
fi
gcloud scheduler jobs "${ACTION}" http "${NAME}" \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --schedule="${CRON}" \
  --time-zone="Etc/UTC" \
  --uri="${RUN_JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --max-retry-attempts=2 \
  --max-retry-duration=1800s
echo "Scheduler job '${ACTION}'d: ${NAME} (${CRON} UTC)"
