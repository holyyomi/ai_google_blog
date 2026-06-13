# Codex CLI 시작 프롬프트: 기존 Blogspot 자동화를 AI 블로그 자동화로 개편

아래 프롬프트를 새로 복제한 프로젝트의 Codex CLI에 그대로 붙여넣어 시작한다.  
`TODO` 값은 가능하면 채운 뒤 사용한다.

```text
너는 Codex이며, 이 저장소는 기존 Blogspot 자동화 프로젝트를 복제한 새 프로젝트다.

목표:
이 프로젝트를 AI 주제 전용 Blogspot 자동화로 안전하게 개편한다. 기존 블로그의 운영 데이터, 내부 링크, Blogspot ID, OAuth 정보, 발행 히스토리가 새 블로그에 섞이면 안 된다.

새 블로그 정보:
- 블로그 이름: TODO
- Blogspot 주소: TODO
- 주요 독자: 30~50대 직장인, 블로거, 1인 사업자
- 포지션: AI 업무 자동화와 수익화 실험을 독자의 시간, 비용, 성과, 리스크 기준으로 번역하는 실전 미디어
- 초기 운영 모드: dry-run only
- 하루 발행 목표: TODO

먼저 반드시 읽을 문서:
- docs/YOMI_BLOG_ASSET_PLAYBOOK.md
- docs/ai_blog_automation/README.md
- docs/ai_blog_automation/01_PREP_CHECKLIST.md
- docs/ai_blog_automation/02_AI_CONTENT_STRATEGY_LOCK.md
- docs/ai_blog_automation/03_CLONE_MIGRATION_PLAN.md
- docs/ai_blog_automation/04_ENV_SECRETS_AND_OPERATIONS.md
- docs/ai_blog_automation/05_SEED_TOPICS_AND_EDITORIAL_PROMPTS.md

작업 원칙:
- 실제 Blogspot 발행을 하지 마라.
- GitHub Actions workflow를 실행하지 마라.
- push하지 마라. 내가 명시적으로 요청하기 전까지 commit도 하지 마라.
- .env, secrets, token, OAuth 값은 읽어도 출력하거나 커밋하지 마라.
- 기존 data/publish_history.json, state/news_published_history.json, runs, logs를 새 블로그 운영 데이터로 재사용하지 마라.
- 변경 전 git status를 확인하고, 변경 범위를 작게 유지해라.
- 먼저 전체 코드에서 기존 블로그 도메인, 오늘이슈/생활정보 라벨, AI 주제 제외 설정, Blogger 관련 설정을 찾아라.

1단계: 감사 리포트 작성
아래 항목을 찾아서 파일/라인 기준으로 정리해라.
- 기존 블로그 도메인이나 내부 링크 host가 박힌 곳
- 기존 BLOGGER_BLOG_ID 또는 블로그명/CTA가 문서나 코드에 남은 곳
- AI 뉴스/AI 주제를 제외하는 설정
- 오늘이슈/생활정보 중심 라벨 기본값
- CONTENT_STRATEGY_LOCK, GOLDEN_ARTICLE_EXAMPLES, QUALITY_REVIEW_PROMPT 등 바꿔야 할 문서
- publish_history/state/runs/logs 등 초기화해야 할 운영 데이터
- GitHub Actions workflow에서 바꿔야 할 env 값

2단계: 개편 계획 제시
수정하지 말고 먼저 아래 형식으로 계획을 제시해라.
- 바꿀 파일
- 바꾸는 이유
- 운영 데이터 보호 방법
- dry-run 검증 방법
- live publish 전 남겨둘 체크리스트

3단계: 내가 승인하면 구현
승인 후에는 아래를 수행해라.
- AI 블로그 전략 문서로 교체/추가
- AI topic_group과 content_type이 선택되도록 설정 조정
- ALLOW_AI_NEWS_TOPICS=true 기준으로 워크플로와 env 예시 조정
- 기존 블로그 도메인/라벨/내부 링크 기준 제거 또는 새 블로그 placeholder로 교체
- publish history와 state는 새 블로그용 빈 상태로 시작하도록 문서화하고, 실제 운영 데이터는 백업 없이 덮어쓰지 마라
- AI 블로그 품질 게이트에 가짜 수익, 가짜 후기, 출처 없는 가격/성능 단정, 회사 기밀 입력 권장, 저작권 침해 유도 차단 기준을 반영해라
- 로컬 dry-run 명령을 준비해라

검증:
- python -m compileall src
- python scripts/validate_news_env.py
- DRY_RUN=true, NEWS_PUBLISH_MODE=dry_run, AUTO_PUBLISH=false, ALLOW_AI_NEWS_TOPICS=true 상태의 로컬 dry-run

최종 보고:
- 수정한 파일
- 핵심 변경 내용
- 운영 데이터 보호 조치
- 검증 결과
- 아직 사람이 채워야 할 TODO
- live publish 전 체크리스트

지금은 1단계 감사 리포트부터 시작해라.
```
