# 기존 프로젝트 클론 후 AI 블로그로 개편하는 마이그레이션 계획

이 문서는 현재 Blogspot 자동화 프로젝트를 복제해 새 AI 블로그 자동화로 바꾸는 실행 계획이다.  
목표는 기존 자동화 엔진의 안정성은 유지하되, 전략/프롬프트/라벨/히스토리/도메인을 새 블로그에 맞게 완전히 분리하는 것이다.

## 1. 개편 원칙

- 기존 블로그 운영 데이터는 새 블로그로 가져가지 않는다.
- 먼저 dry-run이 정상이어야 live publish를 허용한다.
- 코드 변경보다 전략 문서와 데이터 분리를 먼저 한다.
- 기존 발행 히스토리와 내부 링크가 새 글에 섞이면 안 된다.
- `.env`, token, secret은 절대 커밋하지 않는다.

## 2. 추천 작업 순서

### 2-1. 새 저장소 준비

1. GitHub에서 새 repo 생성
2. 현재 프로젝트를 새 폴더로 clone/copy
3. 새 remote 연결
4. 첫 작업 브랜치 생성

예시:

```powershell
git clone <current-repo-url> ai-blogspot-automation
cd ai-blogspot-automation
git remote set-url origin <new-repo-url>
git checkout -b setup-ai-blog-automation
```

### 2-2. 기존 운영 데이터 제거 또는 초기화

새 repo에서 초기화할 대상:

- `data/publish_history.json`
- `state/news_published_history.json`
- `runs/`
- `logs/`
- `_run_artifact/`
- `_pub_artifact/`

권장 초기 상태:

```json
[]
```

주의:

- 삭제 작업은 반드시 새 repo에서만 한다.
- 원본 repo에서는 운영 데이터를 지우지 않는다.
- 기존 발행 히스토리를 참고 문서로만 보고 새 블로그 데이터에는 넣지 않는다.

### 2-3. 전략 문서 교체

새 블로그에 맞게 바꿀 문서:

- `docs/CONTENT_STRATEGY_LOCK.md`
- `docs/GOLDEN_ARTICLE_EXAMPLES.md`
- `docs/QUALITY_REVIEW_PROMPT.md`
- `docs/NEWS_RECOMMENDATION_POLICY.md`
- `docs/RUNBOOK.md`
- `docs/DEPLOYMENT_GUIDE.md`
- `prompts/google_blogspot_prompt_v1_3.md`
- `golden_samples/patterns.json`

교체 기준:

- 생활 이슈 중심 표현을 AI 업무/자동화 중심으로 바꾼다.
- `policy_benefit`, `tax_refund`, `refund_consumer` 중심 규칙은 보조로 내리고 AI 전용 topic_group을 우선한다.
- AI 뉴스 차단 설정은 해제한다.
- AI 도구 비교, 프롬프트, 자동화 워크플로, 보안 체크 유형을 추가한다.

### 2-4. 환경 변수와 워크플로 조정

현재 프로젝트는 생활 이슈 블로그를 위해 AI 뉴스가 제외될 수 있다.  
새 AI 블로그에서는 아래 방향으로 바꾼다.

점검할 값:

```text
ALLOW_AI_NEWS_TOPICS=true
NEWS_EXCLUDED_QUERY_GROUPS=
ENABLE_GOOGLE_CUSTOM_SEARCH=false
NEWS_PUBLISH_MODE=dry_run
AUTO_PUBLISH=false
```

처음 2주는 권장:

```text
DRY_RUN=true
NEWS_PUBLISH_MODE=dry_run
AUTO_PUBLISH=false
```

live publish 전환은 dry-run 글 품질을 확인한 뒤 한다.

### 2-5. 내부 링크 도메인 교체

기존 블로그 도메인 기준 로직을 새 Blogspot 주소로 바꿔야 한다.

찾을 키워드:

```powershell
rg -n "holyeverymoments|blogspot.com|_OWN_LINK_HOSTS|BLOGGER_BLOG_ID|NEWS_COVER_IMAGE_URL|today-issue|오늘이슈"
```

주의할 파일 후보:

- `src/blogspot_automation/services/seo_policy.py`
- `src/blogspot_automation/services/news_label_service.py`
- `src/blogspot_automation/pipelines/news_pipeline.py`
- `.github/workflows/news_blog.yml`
- `.env.example`
- 문서와 프롬프트 파일

### 2-6. 라벨/해시태그 체계 교체

AI 블로그 기본 라벨 예:

- AI활용
- 업무자동화
- 프롬프트
- AI도구비교
- 생산성
- 콘텐츠자동화
- AI보안
- 수익화실험

금지:

- 기존 생활 이슈용 라벨이 기본값으로 남는 것
- `오늘이슈`, `생활정보`, `체크리스트`만 반복되는 것
- 언론사명, URL, 도메인이 라벨에 들어가는 것

### 2-7. 검색/주제 수집 쿼리 교체

AI 블로그용 seed query 예:

- 오늘 AI 뉴스
- ChatGPT 업데이트
- Claude 새 기능
- Gemini AI 기능
- Perplexity 검색
- AI 업무 자동화
- AI 프롬프트 예시
- n8n AI 자동화
- Make AI workflow
- Zapier AI automation
- AI 블로그 글쓰기
- AI 저작권 이슈
- 회사 ChatGPT 보안

### 2-8. 품질 게이트 조정

AI 블로그에서 추가로 막아야 할 것:

- 가짜 수익 인증
- 직접 써보지 않은 1인칭 체험
- 검증 안 된 가격/성능/출시일
- 회사 기밀 입력을 권장하는 문장
- 무단 다운로드/크랙/우회 사용법
- 저작권 침해 유도

AI 블로그에서 필수로 요구할 것:

- 도구명/모델명/업무명 구체성
- 무료/유료/제한 확인
- 보안/개인정보/저작권 주의
- 바로 쓸 프롬프트 또는 워크플로
- 결과 검수 기준
- 공식 문서 또는 신뢰 가능한 출처 확인

### 2-9. 검증 순서

문서/코드 개편 후:

```powershell
git status -sb
python -m compileall src
python scripts/validate_news_env.py
```

dry-run:

```powershell
$env:DRY_RUN='true'
$env:NEWS_PUBLISH_MODE='dry_run'
$env:AUTO_PUBLISH='false'
$env:ALLOW_AI_NEWS_TOPICS='true'
$env:NEWS_EXCLUDED_QUERY_GROUPS=''
python src/blogspot_automation/cli_news.py
```

확인할 산출물:

- `runs/news_*/selected_topic.json`
- `runs/news_*/scoring.json`
- `runs/news_*/title_candidates.json`
- `runs/news_*/article.html`
- `runs/news_*/run_meta.json`

통과 기준:

- AI 주제가 선택된다.
- 제목이 AI 도구/업무/이득을 구체적으로 말한다.
- 본문이 AI 뉴스 요약이 아니라 실무 판단 기준을 준다.
- 보안/검수/저작권 주의가 포함된다.
- 기존 블로그 내부 링크가 나오지 않는다.
- publish mode가 아닌 dry-run으로만 저장된다.

## 3. live publish 전 체크

live publish는 아래가 모두 확인된 뒤 진행한다.

- 새 Blogspot 블로그 ID가 맞다.
- 새 OAuth refresh token이 맞다.
- 새 GitHub repo secrets가 등록됐다.
- `data/publish_history.json`이 새 블로그 기준이다.
- 내부 링크 host가 새 블로그 주소다.
- Search Console/AdSense 연결이 새 블로그 기준이다.
- dry-run 산출물 3개 이상이 전략에 맞다.
- 첫 publish는 수동으로 한 번만 실행한다.

## 4. 롤백 기준

아래 문제가 생기면 자동 발행을 끈다.

- 기존 블로그 URL이 새 글에 노출됨
- AI 주제가 아닌 생활 이슈가 계속 선택됨
- 수익 보장/가짜 후기 문구가 생성됨
- HTML 깨짐 또는 내부 링크 깨짐 발생
- Blogger OAuth가 다른 블로그를 가리킴
- publish history가 실제 발행과 맞지 않음

즉시 설정:

```text
DRY_RUN=true
NEWS_PUBLISH_MODE=dry_run
AUTO_PUBLISH=false
```
