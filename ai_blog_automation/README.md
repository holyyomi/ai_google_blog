# AI 블로그 자동화 개편 문서 세트

이 폴더는 현재 Blogspot 자동화 프로젝트를 복제해 **AI 주제 전용 블로그 자동화**로 개편하기 위한 준비 문서 모음이다.

## 문서 사용 순서

1. `01_PREP_CHECKLIST.md`
   - 새 블로그를 만들기 전에 운영자가 정해야 할 값과 준비물을 점검한다.

2. `02_AI_CONTENT_STRATEGY_LOCK.md`
   - AI 블로그의 정체성, 독자, 글 유형, 금지 주제, 제목/본문 기준을 고정한다.

3. `03_CLONE_MIGRATION_PLAN.md`
   - 기존 프로젝트를 새 저장소/새 Blogspot 블로그로 복제할 때 바꿔야 할 파일과 순서를 정리한다.

4. `04_ENV_SECRETS_AND_OPERATIONS.md`
   - Blogger, GitHub Actions, API 키, dry-run, 발행 슬롯, 운영 데이터 분리 기준을 정리한다.

5. `05_SEED_TOPICS_AND_EDITORIAL_PROMPTS.md`
   - 초기 주제 풀, 글 유형별 예시, AI 블로그용 작성 프롬프트를 제공한다.

6. `../../prompts/ai_blog_codex_cli_start_prompt.md`
   - Codex CLI에 붙여넣어 새 프로젝트 개편 작업을 시작할 때 쓰는 실행 프롬프트다.

## 중요한 전제

새 AI 블로그는 기존 블로그의 발행 데이터, 내부 링크, Blogspot ID, OAuth 정보, 히스토리를 공유하면 안 된다.

반드시 분리해야 할 것:

- Blogspot 블로그
- GitHub 저장소 또는 브랜치
- `BLOGGER_BLOG_ID`
- Blogger OAuth refresh token
- `data/publish_history.json`
- `state/news_published_history.json`
- 내부 링크 도메인
- Search Console / AdSense 연결
- GitHub Actions secrets

## 추천 진행 방식

처음부터 live publish로 가지 않는다.

권장 순서:

1. 새 Blogspot 블로그 생성
2. 새 GitHub repo 생성
3. 기존 프로젝트 clone/copy
4. 이 문서 세트를 새 repo에도 복사
5. Codex CLI 시작 프롬프트 실행
6. AI 블로그 전략 문서와 코드 설정 개편
7. 운영 데이터 초기화
8. 로컬 dry-run 3회 이상
9. GitHub Actions dry-run 확인
10. 첫 live publish는 수동 승인 후 진행

## 성공 기준

새 AI 블로그 자동화는 아래 조건을 만족해야 한다.

- AI 뉴스 요약이 아니라 독자의 업무, 수익화, 생산성, 리스크 판단 기준으로 번역한다.
- 첫 150자 안에 핵심 답이 있다.
- 각 글에 바로 실행할 프롬프트, 체크리스트, 비교표, 주의점 중 최소 2개 이상이 있다.
- AI 도구명, 모델명, 가격, 기능, 출시일, 정책 변경은 검증 가능한 출처 기준으로 다룬다.
- 가짜 사용 후기, 가짜 수익, 가짜 링크를 만들지 않는다.
- 회사 기밀, 개인정보, 저작권, 환각 위험을 반복적으로 안내한다.
- 기존 블로그의 발행 기록과 내부 링크를 새 블로그에 섞지 않는다.
