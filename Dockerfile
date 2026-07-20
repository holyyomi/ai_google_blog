# Cloud Run Job — 컴퓨터/GHA 무관 무료(구독 인증) 발행 파이프라인.
#
# 코드는 이미지에 굽지 않는다: 컨테이너 시작 시 entrypoint.sh가 origin/main을
# 매번 새로 clone한다. 그래서 파이프라인 코드 수정은 git push만으로 다음 실행부터
# 즉시 반영되고, 이미지 재빌드는 Python/Node 의존성이 바뀔 때만 필요하다.
FROM python:3.11-slim

# Node.js(Claude Code CLI가 npm 배포) + git(코드 clone·원장 push) + 빌드 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates gnupg build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y --auto-remove gnupg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성만 먼저 설치해 레이어 캐시 — requirements.txt가 안 바뀌면 재빌드가 빠르다.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
