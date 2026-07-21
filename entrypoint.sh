#!/usr/bin/env bash
# Cloud Run Job entrypoint — GitHub Actions Actions 분당 무료 한도 소진 대응
# (2026-07-20). 코드는 이미지에 굽지 않고 매 실행마다 origin/main을 새로 clone —
# 파이프라인 코드 수정은 git push만으로 다음 실행부터 반영된다.
#
# ai_blog.yml의 4단계(checkout → deps install → cli_ai.py 실행 → 원장 병합-push)를
# 그대로 재현해, GHA와 원장(dedup)을 공유하며 서로 안전하게 병행 가능하다.
set -euo pipefail

: "${GITHUB_REPO_TOKEN:?GITHUB_REPO_TOKEN not set}"
: "${GIT_REPO_URL:=github.com/holyyomi/ai_google_blog.git}"

# 시크릿 값에 trailing newline이 섞여 들어오면 git 자격증명 URL이 깨진다
# (2026-07-20 실측: `gh auth token > file`로 저장한 값에 개행이 남아
# "fatal: credential url cannot be parsed"로 즉시 실패). 방어적으로 trim.
GITHUB_REPO_TOKEN="$(printf '%s' "${GITHUB_REPO_TOKEN}" | tr -d '\n\r')"

# ── 실행 우선순위(2026-07-20 설계, 2026-07-21 사용자 결정으로 한시 변경):
# 원래는 GitHub Actions가 1순위이고 이 Cloud Run 잡은 "GHA가 이번 스케줄
# 시간대에 아예 못 돌았을 때만" 실행되는 폴백이었다. 그런데 실측 결과
# (2026-07-20~21) GHA가 Actions-minute 한도 소진으로 큐에서 57분~2시간
# 지연되다 결국 늦게라도 성공해버려서, "최근 90분 내 GHA run 없음" 체크가
# Cloud Run 실행 *시점*엔 참이라도 그 뒤 지연된 GHA가 같은 슬롯에 또 발행해
# 슬롯당 2건씩 중복 발행되는 사고가 있었다. ai_blog.yml에 2026-08-01 KST까지
# schedule 자동실행을 건너뛰는 게이트를 추가했으므로, 이 기간 동안은 GHA
# run 존재 여부를 확인할 필요가 없다 — Cloud Run이 무조건 1순위로 실행한다.
# 2026-08-01부터는 아래 원래 로직(GHA run 존재 확인)으로 자동 복귀해 GHA가
# 다시 1순위가 된다. Cloud Scheduler는 07:31/19:31 KST보다 살짝 늦게(예:
# 07:50/19:50) 쏘도록 설정되어 있다(8월부터 원래 로직이 쓰는 여유 시간).
NOW_KST="$(TZ=Asia/Seoul date +%Y-%m-%d)"
if [[ "${NOW_KST}" < "2026-08-01" ]]; then
  echo "[entrypoint] 2026-07 GHA 한도소진 기간 — Cloud Run이 무조건 1순위로 실행 (today KST=${NOW_KST}, 2026-08-01부터 자동 복귀)"
  GHA_HANDLED="false"
else
echo "[entrypoint] checking whether GitHub Actions already handled this schedule slot"
GHA_HANDLED=$(python3 - <<'PYEOF'
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

token = os.environ["GITHUB_REPO_TOKEN"]
req = urllib.request.Request(
    "https://api.github.com/repos/holyyomi/ai_google_blog/actions/workflows/ai_blog.yml/runs"
    "?event=schedule&per_page=5",
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cloud-run-fallback-check",
    },
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
except Exception as exc:  # noqa: BLE001 — API 조회 실패 시 안전하게 폴백 진행
    print(f"[entrypoint] GHA run check failed ({exc}) — proceeding with fallback", file=sys.stderr)
    print("false")
    sys.exit(0)

cutoff = datetime.now(timezone.utc) - timedelta(minutes=90)
for run in data.get("workflow_runs", []):
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    if created >= cutoff:
        print(f"[entrypoint] GHA scheduled run found at {run['created_at']} (status={run['status']})", file=sys.stderr)
        print("true")
        sys.exit(0)
print("[entrypoint] no recent GHA scheduled run found — GHA likely blocked (quota)", file=sys.stderr)
print("false")
PYEOF
)
fi

if [ "${GHA_HANDLED}" = "true" ]; then
  echo "[entrypoint] GitHub Actions already ran this slot — Cloud Run fallback is a no-op, exiting."
  exit 0
fi

WORKDIR="$(mktemp -d)"
echo "[entrypoint] cloning into ${WORKDIR}"
git clone --depth 1 "https://x-access-token:${GITHUB_REPO_TOKEN}@${GIT_REPO_URL}" "${WORKDIR}"
cd "${WORKDIR}"

# requirements.txt는 이미지 빌드 시 이미 설치돼 있다(Dockerfile 레이어 캐시).
# clone된 코드의 requirements.txt가 이미지 빌드 시점과 달라졌을 가능성에 대비해
# 차이가 있을 때만 재설치 — 매 실행 전체 재설치를 피해 기동 시간을 줄인다.
if ! diff -q requirements.txt /app/requirements.txt >/dev/null 2>&1; then
  echo "[entrypoint] requirements.txt changed since image build — reinstalling"
  pip install --no-cache-dir -r requirements.txt
fi

echo "[entrypoint] fetch search console performance (best-effort)"
PYTHONPATH=src python scripts/fetch_search_performance.py || echo "[entrypoint] search performance fetch skipped"

echo "[entrypoint] running AI topic pipeline"
set +e
PYTHONPATH=src python src/blogspot_automation/cli_ai.py
PIPELINE_EXIT=$?
set -e

# 파이프라인이 실패해도 원장 병합-push는 항상 실행한다(GHA의 if: always()와 동치) —
# 부분 실행(skipped/blocked 등)도 dedup에 의미 있는 기록일 수 있다.
echo "[entrypoint] persisting publish history ledger"
if [ -f data/publish_history.json ]; then
  cp data/publish_history.json /tmp/run_ledger.json
  cp scripts/merge_publish_history.py /tmp/merge_publish_history.py
  git config user.name "cloud-run-job[bot]"
  git config user.email "cloud-run-job@holyyomi.blog"
  for attempt in 1 2 3; do
    git fetch origin main
    git checkout -f -B ledger-merge origin/main
    python /tmp/merge_publish_history.py \
      --base data/publish_history.json \
      --incoming /tmp/run_ledger.json \
      --out data/publish_history.json
    if git diff --quiet -- data/publish_history.json; then
      echo "[entrypoint] ledger unchanged; skipping commit"
      break
    fi
    git add data/publish_history.json
    git commit -m "chore: merge publish history from Cloud Run run [skip ci]"
    if git push origin HEAD:main; then
      break
    fi
    echo "[entrypoint] push race detected; re-merging (attempt ${attempt})"
  done
else
  echo "[entrypoint] no ledger produced; skipping"
fi

exit "${PIPELINE_EXIT}"
