#!/usr/bin/env bash
# Cloud Run Job entrypoint — 유일한 자동 발행 경로 (2026-07-24 사용자 결정).
# 코드는 이미지에 굽지 않고 매 실행마다 origin/main을 새로 clone —
# 파이프라인 코드 수정은 git push만으로 다음 실행부터 반영된다.
#
# ai_blog.yml의 4단계(checkout → deps install → cli_ai.py 실행 → 원장 병합-push)를
# 그대로 재현한다. ai_blog.yml은 더 이상 schedule로 자동 실행되지 않으므로
# (workflow_dispatch만 남음) 이 Cloud Run Job이 유일한 자동 발행 트리거다 —
# 과거처럼 "GHA가 이미 이 슬롯을 처리했는지" 확인할 필요가 없다.
#
# 이전 설계(2026-07-20~21)는 GHA를 1순위, 이 잡을 "GHA가 스케줄 시간대에
# 못 돌았을 때만" 도는 폴백으로 두고 90분 핸드셰이크로 중복을 막았다. 그런데
# GHA가 Actions-minute 한도로 큐에서 57분~2시간 지연되다 결국 늦게라도
# 성공해버리면서, 핸드셰이크 체크 시점 이후 지연된 GHA가 같은 슬롯에 또
# 발행해 슬롯당 2건 중복 발행되는 사고가 있었다. GHA의 schedule 트리거
# 자체를 없애 이 핸드셰이크가 더 이상 필요 없게 만들었다.
set -euo pipefail

: "${GITHUB_REPO_TOKEN:?GITHUB_REPO_TOKEN not set}"
: "${GIT_REPO_URL:=github.com/holyyomi/ai_google_blog.git}"

# 시크릿 값에 trailing newline이 섞여 들어오면 git 자격증명 URL이 깨진다
# (2026-07-20 실측: `gh auth token > file`로 저장한 값에 개행이 남아
# "fatal: credential url cannot be parsed"로 즉시 실패). 방어적으로 trim.
GITHUB_REPO_TOKEN="$(printf '%s' "${GITHUB_REPO_TOKEN}" | tr -d '\n\r')"

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
