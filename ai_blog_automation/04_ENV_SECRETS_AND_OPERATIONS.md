# AI 블로그 환경 변수, 시크릿, 운영 체크리스트

이 문서는 새 AI 블로그 자동화의 운영 환경을 분리하기 위한 체크리스트다.

## 1. GitHub Secrets

필수:

| 이름 | 목적 |
| --- | --- |
| `GOOGLE_AI_API_KEY` | Gemini 기반 1차 생성 |
| `OPENAI_API_KEY` | OpenAI fallback 생성 |
| `BLOGGER_CLIENT_ID` | Blogger OAuth client |
| `BLOGGER_CLIENT_SECRET` | Blogger OAuth secret |
| `BLOGGER_REFRESH_TOKEN` | 새 블로그용 refresh token |
| `BLOGGER_BLOG_ID` | 새 Blogspot blog ID |

선택:

| 이름 | 목적 |
| --- | --- |
| `GOOGLE_SEARCH_API_KEY` | Google Custom Search를 명시적으로 켤 때만 |
| `GOOGLE_SEARCH_CX` | Programmable Search Engine ID |
| `NAVER_CLIENT_ID` | Naver Search 후보 수집 |
| `NAVER_CLIENT_SECRET` | Naver Search 후보 수집 |
| `TAVILY_API_KEY` | 상위 후보 검증 |
| `EXA_API_KEY` | 의미 기반 검증 |
| `FIRECRAWL_API_KEY` | 최종 출처 확인 |
| `NEWS_COVER_IMAGE_URL` | 기본 대표 이미지 |

절대 넣지 말 것:

- 기존 블로그의 `BLOGGER_BLOG_ID`
- 기존 블로그의 refresh token
- 개인 `.env` 파일 내용 전체
- 테스트용 임시 토큰

## 2. 권장 환경 변수

초기 dry-run:

```text
DRY_RUN=true
NEWS_PUBLISH_MODE=dry_run
AUTO_PUBLISH=false
ALLOW_AI_NEWS_TOPICS=true
NEWS_EXCLUDED_QUERY_GROUPS=
ENABLE_GOOGLE_CUSTOM_SEARCH=false
DISABLE_IMAGE_GENERATION=true
DISABLE_IMAGE_UPLOAD=true
```

모델:

```text
GEMINI_MODEL=gemini-2.5-flash
OPENAI_MODEL=gpt-5-mini
```

검색:

```text
ENABLE_GOOGLE_CUSTOM_SEARCH=false
NEWS_NAVER_MAX_REQUESTS=18
NEWS_NAVER_DATALAB_MAX_REQUESTS=5
NEWS_TAVILY_MAX_REQUESTS=3
NEWS_EXA_MAX_REQUESTS=1
NEWS_FIRECRAWL_MAX_REQUESTS=1
```

live publish 전환:

```text
DRY_RUN=false
NEWS_PUBLISH_MODE=publish
AUTO_PUBLISH=true
```

## 3. 스케줄 권장안

처음 2주:

- 하루 1개 dry-run
- 사람이 글을 확인
- 내부 링크와 제목 품질 점검

안정화 후:

- KST `08:13`, `16:13` 2회 이하 권장
- AI 뉴스는 변동이 많으므로 과도한 자동 발행보다 검증 품질을 우선

기존 3회 발행 슬롯을 그대로 쓸 수 있지만, AI 주제는 가격/모델/기능 변화 검증 부담이 크므로 처음에는 줄이는 편이 안전하다.

## 4. 로컬 검증 명령

비밀값 없이 기본 진단:

```powershell
python scripts/validate_news_env.py
```

엄격 검증:

```powershell
python scripts/validate_news_env.py --strict
```

컴파일:

```powershell
python -m compileall src
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

## 5. 발행 히스토리 운영

새 블로그에서는 `data/publish_history.json`을 빈 상태에서 시작한다.

초기 형태:

```json
[]
```

운영 중 보정이 필요할 때:

```powershell
python tools/sync_publish_history.py --dry-run --verify-live-urls
python tools/sync_publish_history.py --verify-live-urls
```

주의:

- 기존 블로그의 발행 URL을 새 블로그 history에 넣지 않는다.
- 삭제/404/dereferenced 기록을 되살리지 않는다.
- live URL 검증 없는 dry-run 기록을 실제 발행으로 바꾸지 않는다.
- 백업 없이 운영 데이터 쓰기 작업을 하지 않는다.

## 6. 첫 발행 전 최종 체크

첫 live publish 전 반드시 확인:

- 새 Blogspot 관리자 화면에서 blog ID 확인
- 새 OAuth refresh token으로 대상 블로그가 맞는지 확인
- `.env.example`에는 비밀값이 없고 기본값이 dry-run인지 확인
- GitHub Actions secrets가 새 repo에만 등록됐는지 확인
- 내부 링크 host가 새 블로그 주소인지 확인
- 기존 블로그 CTA나 도메인이 남아 있지 않은지 `rg`로 확인

검색 명령:

```powershell
rg -n "holyeverymoments|blog.naver.com|BLOGGER_BLOG_ID|today-issue|오늘이슈|생활정보"
```

## 7. 운영 중 사고 방지 규칙

즉시 자동 발행을 중단해야 하는 경우:

- 다른 블로그에 발행됨
- 이전 블로그 내부 링크가 노출됨
- 가짜 수익/가짜 후기/가짜 가격이 생성됨
- AI 도구 관련 허위 정보가 반복됨
- HTML이 깨져 본문에 코드 조각이 보임
- AdSense 리스크 문구가 생성됨

중단 설정:

```text
DRY_RUN=true
NEWS_PUBLISH_MODE=dry_run
AUTO_PUBLISH=false
```
