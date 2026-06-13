# Blogger Automation

로컬/Actions에서 실행하는 Streamlit + SQLite 기반 Blogger 자동화 프로젝트입니다.  
현재 기본 목적은 `AI 주제 선정 -> AI 업무/자동화형 HTML 생성 -> 이미지 처리 -> QA -> holyyomiai.blogspot.com 발행`입니다.

## 현재 상태

완료:

- Streamlit 운영 UI
- SQLite 저장소
- AI 뉴스/AI 도구/업무 자동화 기반 주제 선정
- 기사 기반 브리프 생성
- Blogger HTML 패키지 생성
- 대표 이미지 생성 및 공개 URL 처리
- PASS 중심 QA
- Blogger 발행 기록 저장

## 빠른 시작

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e . --no-build-isolation
copy .env.example .env
streamlit run src/blogspot_automation/ui/app.py
```

## Streamlit 사용 순서

화면에서 아래 버튼을 순서대로 누르면 됩니다.

1. `오늘 주제 찾기`
2. `콘텐츠 생성`
3. `QA 실행`
4. `발행`

화면에는 아래 정보가 카드형으로 보입니다.

- 선택된 대주제
- 주제 제목
- 기사 요약
- 제목 후보
- 최종 제목
- QA 결과
- 발행 URL
- HTML 미리보기
- 이미지 미리보기
- 최근 생성/발행 기록

## 설치와 실행

### 1. 설치

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e . --no-build-isolation
```

### 2. 환경 변수

```powershell
copy .env.example .env
```

최소 입력:

- 콘텐츠/이미지 생성: `OPENAI_API_KEY`
- Blogger 발행: `BLOGGER_BLOG_ID` + OAuth 정보
- 이미지 공개 URL 업로드 사용 시: `IMGBB_API_KEY`
- AI 블로그 기본 URL: `BLOGSPOT_HOME_URL=https://holyyomiai.blogspot.com/`

### 3. 실행

```powershell
streamlit run src/blogspot_automation/ui/app.py
```

## 환경 변수 가이드

### OpenAI

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`
- `OPENAI_IMAGE_MODEL`

규칙:

- `OPENAI_BASE_URL`은 `/v1`까지만 사용합니다.

### Blogger

- `BLOGGER_BLOG_ID`
- `BLOGGER_ACCESS_TOKEN`

또는

- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REFRESH_TOKEN`

### ImgBB

- `ENABLE_IMGBB_UPLOAD`
- `IMGBB_API_KEY`

## Blogger API 설정

발행을 위해 아래 둘 중 하나가 필요합니다.

1. `BLOGGER_ACCESS_TOKEN`
2. `BLOGGER_CLIENT_ID`, `BLOGGER_CLIENT_SECRET`, `BLOGGER_REFRESH_TOKEN`

추가로 반드시:

- `BLOGGER_BLOG_ID`

`publish_mode="draft"`면 초안 발행, `publish_mode="public"`이면 즉시 공개 발행입니다.

## imgbb 설정

이미지를 본문에서 외부 공개 URL로 써야 하면 아래를 켭니다.

```env
ENABLE_IMGBB_UPLOAD=true
IMGBB_API_KEY=your_key
```

## 저장 구조

기본 DB:

- `data/blog_automation.db`

주요 테이블:

- `blog_work_items`
- `brief_records`
- `content_package_records`
- `qa_review_records`
- `publish_records`

fallback 저장:

- `data/fallback/`

## QA 정책

- `PASS`: 발행 가능
- `SOFT_FAIL`: 수동 승인 없이는 발행 금지
- `FIX_REQUIRED`: refine 후 재검수
- `FAIL`: 발행 금지

기본 발행 정책은 `PASS` 중심입니다.

## 뉴스 provider 교체

뉴스 수집은 provider 인터페이스로 분리되어 있습니다.

인터페이스:

- `NewsProvider`

기본 구현:

- `RssNewsProvider`
- `InMemoryNewsProvider`

교체 지점:

- [topic_selection_service.py](/abs/path/C:/Users/a0104/Desktop/자동화/블로그스팟/src/blogspot_automation/services/topic_selection_service.py)

## 테스트

```powershell
python -m unittest discover -s tests -v
```

포함 내용:

- 저장소
- 주제 선정
- 브리프 생성
- HTML 패키지 생성
- 이미지 처리
- QA / refine / publish
- end-to-end workflow

## 관련 문서

- [README_WORKFLOW.md](README_WORKFLOW.md)
- [CLAUDE.md](CLAUDE.md) — 운영 정책 / 보호 파일 정의
- [CLEANUP_PLAN.md](CLEANUP_PLAN.md) — 정리 감사 보고서
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/CONFIG_SPEC.md](docs/CONFIG_SPEC.md)
- [docs/RUNBOOK.md](docs/RUNBOOK.md)
- [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)
- [docs/PRD_CONTENT_ENGINE_V2.md](docs/PRD_CONTENT_ENGINE_V2.md) — 현행 콘텐츠 엔진 PRD
- [docs/CONTENT_STRATEGY_LOCK.md](docs/CONTENT_STRATEGY_LOCK.md) — 콘텐츠 전략 기준
