#!/usr/bin/env bash
# Cloud Run Job 본체 로직 — GHA 1순위 / Cloud Run 폴백 (2026-07-24 확정 설계).
#
# 이미지의 entrypoint.sh는 "clone 후 이 스크립트 exec"만 하는 얇은 셔틀이다.
# 그래서 이 파일의 로직 수정은 git push만으로 다음 실행부터 반영된다 —
# 이미지 재빌드는 requirements.txt/Node 의존성이 바뀔 때만 필요하다.
#
# ── 실행 우선순위 (2026-07-24 사용자 결정):
# 1순위 GHA(ai_blog.yml schedule, 12:31 UTC 하루 1회) — 단, 2026-07은 GHA
# Actions-minute 한도 소진으로 schedule이 July 게이트에 막혀 있어 Cloud Run이
# 1순위다(이 스크립트가 GHA 확인을 건너뛰고 바로 실행). 2026-08-01(KST)부터:
#   - GHA가 이 슬롯을 성공 처리했으면 → no-op 종료
#   - GHA가 실패(failure/cancelled/timed_out)했거나 아예 없으면(한도 소진) → 폴백 발행
#   - GHA가 아직 실행 중이면 → 최대 30분 폴링 후 위 규칙 적용, 그래도 미결이면
#     GHA를 신뢰하고 종료(중복 발행보다 하루 지연이 낫다)
#
# ── 이중 발행 구조적 차단: 시간 기반 핸드셰이크만으로는 GHA 큐 지연에 깨진다
# (2026-07-20~21 슬롯당 2건 실측). 그래서 GHA·Cloud Run 양쪽 다 실행 시작 시점에
# check_published_today.py로 원장을 직접 보고 "오늘 라이브 발행이 이미 있으면"
# 스킵한다 — 트리거가 몇 개든, 얼마나 지연되든 하루 1건을 넘지 않는다.
set -euo pipefail

# ── 0. 오늘 이미 라이브 발행됐으면 즉시 종료 (원장 가드) ──
ALREADY=$(python scripts/check_published_today.py)
if [ "${ALREADY}" = "true" ]; then
  echo "[cloud-run] today's live post already exists in ledger — exiting (no-op)."
  exit 0
fi

# ── 1. GHA 1순위 확인 (2026-08-01 KST부터) ──
NOW_KST="$(TZ=Asia/Seoul date +%Y-%m-%d)"
if [[ "${NOW_KST}" < "2026-08-01" ]]; then
  echo "[cloud-run] 2026-07 GHA quota-exhausted period — Cloud Run is primary (today KST=${NOW_KST}); skipping GHA check."
else
  check_gha_state() {
    python3 - <<'PYEOF'
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
except Exception as exc:  # noqa: BLE001 — API 조회 실패 시 폴백 발행이 안전 (원장 가드가 중복을 막는다)
    print(f"[cloud-run] GHA run check failed ({exc}) — treating as absent", file=sys.stderr)
    print("absent")
    sys.exit(0)

cutoff = datetime.now(timezone.utc) - timedelta(minutes=120)
for run in data.get("workflow_runs", []):
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    if created < cutoff:
        continue
    status = run.get("status")
    conclusion = run.get("conclusion")
    print(
        f"[cloud-run] GHA scheduled run {run['created_at']} status={status} conclusion={conclusion}",
        file=sys.stderr,
    )
    if status == "completed":
        print("handled" if conclusion == "success" else "failed")
    else:  # queued / in_progress
        print("running")
    sys.exit(0)
print("absent")
PYEOF
  }

  GHA_STATE=$(check_gha_state)
  # 실행 중이면 최대 30분 폴링 — GHA 파이프라인은 보통 6~25분 걸린다.
  POLL=0
  while [ "${GHA_STATE}" = "running" ] && [ "${POLL}" -lt 30 ]; do
    POLL=$((POLL + 1))
    echo "[cloud-run] GHA run in progress — waiting (${POLL}/30 min)"
    sleep 60
    GHA_STATE=$(check_gha_state)
  done

  case "${GHA_STATE}" in
    handled)
      echo "[cloud-run] GHA handled this slot — exiting (no-op)."
      exit 0
      ;;
    running)
      # 30분을 넘겨도 실행 중 — GHA를 신뢰하고 종료. 여기서 발행을 강행하면
      # 이미 게이트를 통과해 진행 중인 GHA와 중복될 수 있다(GHA는 실행 시작
      # 시점에만 원장을 본다). GHA가 이후 실패하면 그날 발행은 건너뛰게 되지만,
      # 중복 발행(즉시 사고)보다 하루 지연(다음 슬롯에 복구)이 낫다.
      echo "[cloud-run] GHA still running after 30 min — trusting GHA, exiting."
      exit 0
      ;;
    failed)
      echo "[cloud-run] GHA failed this slot — falling back to Cloud Run publish."
      # 실패한 GHA가 발행까지 마치고 원장 push 단계에서만 죽었을 수 있다 —
      # 원장을 최신으로 갱신해 한 번 더 가드 (dedup 정확도도 함께 올라간다).
      git fetch --depth 1 origin main
      git checkout -f FETCH_HEAD -- data/publish_history.json || true
      ALREADY=$(python scripts/check_published_today.py)
      if [ "${ALREADY}" = "true" ]; then
        echo "[cloud-run] fresh ledger shows today's live post — exiting (no-op)."
        exit 0
      fi
      ;;
    absent)
      echo "[cloud-run] no recent GHA scheduled run — GHA likely blocked (quota); Cloud Run publishing."
      ;;
  esac
fi

# ── 2. 파이프라인 실행 ──
# requirements.txt는 이미지 빌드 시 이미 설치돼 있다(Dockerfile 레이어 캐시).
# clone된 코드의 requirements.txt가 이미지 빌드 시점과 달라졌을 때만 재설치.
if [ -f /app/requirements.txt ] && ! diff -q requirements.txt /app/requirements.txt >/dev/null 2>&1; then
  echo "[cloud-run] requirements.txt changed since image build — reinstalling"
  pip install --no-cache-dir -r requirements.txt
fi

echo "[cloud-run] fetch search console performance (best-effort)"
PYTHONPATH=src python scripts/fetch_search_performance.py || echo "[cloud-run] search performance fetch skipped"

echo "[cloud-run] running AI topic pipeline"
set +e
PYTHONPATH=src python src/blogspot_automation/cli_ai.py
PIPELINE_EXIT=$?
set -e

# ── 3. 원장 병합-push (파이프라인 실패해도 항상 — GHA의 if: always()와 동치) ──
# 부분 실행(skipped/blocked 등)도 dedup에 의미 있는 기록이다.
echo "[cloud-run] persisting publish history ledger"
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
      echo "[cloud-run] ledger unchanged; skipping commit"
      break
    fi
    git add data/publish_history.json
    git commit -m "chore: merge publish history from Cloud Run run [skip ci]"
    if git push origin HEAD:main; then
      break
    fi
    echo "[cloud-run] push race detected; re-merging (attempt ${attempt})"
  done
else
  echo "[cloud-run] no ledger produced; skipping"
fi

exit "${PIPELINE_EXIT}"
