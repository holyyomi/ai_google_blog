#!/usr/bin/env bash
# Cloud Run Job entrypoint — 얇은 셔틀 (2026-07-24 구조 정리).
#
# 이 파일은 이미지에 구워지므로(빌드 시 COPY) 여기 로직을 바꾸면 이미지
# 재빌드가 필요하다. 그래서 여기는 "origin/main clone → 저장소 안의
# scripts/cloud_run_pipeline.sh 실행"만 하고, 실제 파이프라인/우선순위/중복
# 가드 로직은 전부 저장소 쪽 스크립트에 둔다 — 로직 수정이 git push만으로
# 다음 실행부터 반영되고, 이미지 재빌드는 의존성이 바뀔 때만 필요하다.
set -euo pipefail

: "${GITHUB_REPO_TOKEN:?GITHUB_REPO_TOKEN not set}"
: "${GIT_REPO_URL:=github.com/holyyomi/ai_google_blog.git}"

# 시크릿 값에 trailing newline이 섞여 들어오면 git 자격증명 URL이 깨진다
# (2026-07-20 실측: "fatal: credential url cannot be parsed"). 방어적으로 trim.
GITHUB_REPO_TOKEN="$(printf '%s' "${GITHUB_REPO_TOKEN}" | tr -d '\n\r')"
export GITHUB_REPO_TOKEN

WORKDIR="$(mktemp -d)"
echo "[entrypoint] cloning into ${WORKDIR}"
git clone --depth 1 "https://x-access-token:${GITHUB_REPO_TOKEN}@${GIT_REPO_URL}" "${WORKDIR}"
cd "${WORKDIR}"

if [ ! -f scripts/cloud_run_pipeline.sh ]; then
  echo "[entrypoint] scripts/cloud_run_pipeline.sh missing in clone — cannot proceed" >&2
  exit 1
fi
exec bash scripts/cloud_run_pipeline.sh
