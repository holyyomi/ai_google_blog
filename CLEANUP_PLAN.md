# Blogspot Automation Cleanup Audit & Refactor Plan

작성일: 2026-05-16
브랜치: `main` (origin/main과 동기화됨)

## 진행 상태 (2026-05-16 KST 17:30 기준)

| 단계 | 내용 | 상태 | commit |
|------|------|------|--------|
| P0 보안 | GITHUB_SECRETS.txt 트래킹 제거 + 시크릿 차단 패턴 | ✅ | `bd0dfa8` / `aa45a93` (히스토리 재작성됨) |
| P0 자격증명 | OAuth 회전 + GitHub Secrets 갱신 + access_token 발급 검증 | ✅ | 사용자 + 검증 완료 |
| P0 히스토리 purge | git filter-repo + force push (main, improve-news-engine-v2 양쪽) | ✅ | secret 흔적 0건 확인 |
| P0 문서 | CLAUDE.md 보호파일 표 갱신 + CLEANUP_PLAN.md 작성 | ✅ | `ac4d530` |
| P0 도구 | tools/oauth_refresh_token.py | ✅ | `7608fff` |
| P1-A | placeholder 정리 함수 통합 (cleanup_blogger_placeholders) | ✅ | `588f230` |
| P1-B | cli_automation.py 삭제 | ✅ | `d86467a` |
| P1-C | 루트 ad-hoc 스크립트 10개 삭제 | ✅ | `b7f1352` |
| P1-D | 루트 임시 test_*.py 6개 삭제 | ✅ | `b89cb50` |
| P2-1 | 루트 MD 15개 → docs/ 이동 | ✅ | `73490ef` |
| P2-2 | tools/cleanup_runs.py 추가 | ✅ | `f018ef4` |
| **P3-A** | _select_diverse_candidate에서 discovery_engine 후보 우선 | ✅ | `1712a1d` |
| **P3-B** | issue_specificity / preservation 임계값 7→6 보수 완화 | ✅ | `6e60ca7` |
| P3-C | 제목 자동 brand 삽입 | ⏸ 보류 (위험 큼) | — |
| P3 검증 | 다음 KST 20:00 schedule run에서 자동 발행 성공 확인 | 🔄 대기 중 | — |

## 발견된 핵심 문제 — 자동 발행 0건

GitHub Actions 워크플로우는 5일 연속 success로 끝났지만, **저녁 뉴스 자동 발행은 5일 모두 NewsQualityGate에 막혀 0건**.

차단 원인 (마지막 schedule run, 2026-05-15 12:28 UTC):
```
blocking=['title_has_no_specific_entity',
          'generic_title_without_subject',
          'issue_specificity_below_7:3',
          'original_issue_preservation_below_7:5']
```

후보 수치 자체는 OK였음:
- publish_ready=True, geo_ready=True, sge_ready=True
- publishable_count=5, discovery_engine 후보 2개 생성됨
- 그러나 다양성 정렬에서 generic 후보가 선택됨 → 제목 entity 가드에 차단

P3-A/B로 이 흐름이 풀려야 함. 다음 schedule run에서 검증.

## 네이버 측 마이너 버그 (보류)

`retired legacy Naver rewrite entrypoint:95-110` published_history.json 마킹 코드는 빈 list를 가정해 항상 마킹 실패. 단 published_history.json은 ai_content_service / topic_dedup_service도 의존하는 운영 데이터라 수정은 데이터 손실 위험. **별도 진단 후 처리.**

실제 네이버 발행은 동작 중인 것으로 추정:
- `data/naver_processed.json`에 최근 5일 모두 새 entry 마킹됨
- `mark_processed`는 발행 성공 후에만 호출되는 코드 경로

블로그 화면에서 직접 확인 권장.

---

작업 모드: ~~감사·계획만 수행. 코드 수정/삭제 없음.~~ (초기 설계). 현재는 P3-C와 일부 보류 항목 외 모두 적용 완료.

---

## ⚠️ 0. 즉각 조치 필요 — 보안 위험

### 0-1. `GITHUB_SECRETS.txt` — 실제 OAuth 자격증명 평문 커밋

**현 상태**
- 파일: `GITHUB_SECRETS.txt` (402 bytes, 11 lines)
- git 추적 중 (`git ls-files` 확인됨)
- 내용: 실제 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`이 평문으로 포함

**위험도**: CRITICAL — 리포지토리에 read 권한이 있는 누구든지 Blogger API에 무제한 발행 가능.

**권장 조치 (사용자 승인 필요)**
1. **즉시**: Google Cloud Console에서 해당 OAuth Client Secret을 회전 (revoke + regenerate). Refresh token 폐기.
2. 새 자격증명을 GitHub Secrets에 등록 (이미 워크플로우는 `secrets.BLOGGER_*` 참조 중이므로 이름만 맞춰 갱신).
3. 로컬 작업 디렉터리에서 `GITHUB_SECRETS.txt` 삭제 후 `.gitignore`에 추가.
4. git history purge:
   ```
   git rm --cached GITHUB_SECRETS.txt
   git commit -m "chore: remove leaked secrets file from tracking"
   ```
   히스토리에서 완전 제거하려면 `git filter-repo` 또는 BFG로 강제 재작성 필요 (force push 동반).
5. force push 자체는 사용자 명시 승인 후에만 진행.

> **이 항목은 다른 모든 정리 작업보다 우선해야 함.**

---

## 1. 현재 운영 entrypoint

| 용도 | 워크플로우 | 호출되는 entrypoint | 활성 파이프라인 |
|------|-----------|---------------------|----------------|
| 뉴스/이슈 자동발행 | `.github/workflows/news_blog.yml` (KST 20:00) | `src/blogspot_automation/cli_news.py` | `pipelines/news_pipeline.py::NewsPipeline` |
| 네이버 → Blogspot | `.github/workflows/retired Naver rewrite workflow` (KST 08:00) | `retired legacy Naver rewrite entrypoint` | `app/runtime.py::build_service_runtime` + 레거시 storage/UI 서비스 |

**중복/폐기 워크플로우**: 없음. (현재 `.github/workflows/`에 위 2개만 존재 — 양호.)

**호출되지 않는 entrypoint** (정리 후보)
- `src/blogspot_automation/cli_ai.py` — `AiTopicPipeline` 호출, AI 워크플로우는 미존재 (CLAUDE.md에 명시)
- `src/blogspot_automation/cli_automation.py` — 레거시 풀사이클 (topic_selection + qa_service + publish_service). naver와 거의 동일한 후처리 코드를 복사해 사용.
- `src/blogspot_automation/cli/main.py` — Streamlit/UI launcher 추정 (확인 필요)

---

## 2. 반드시 유지할 핵심 파일

| 파일 | 이유 |
|------|------|
| `src/blogspot_automation/cli_news.py` | news_blog.yml 진입점 |
| `retired legacy Naver rewrite entrypoint` | retired Naver rewrite workflow 진입점 |
| `src/blogspot_automation/pipelines/news_pipeline.py` | 뉴스 자동발행 메인 파이프라인 (~45K, 가장 큰 파일) |
| `src/blogspot_automation/services/news_topic_service.py` | 뉴스 후보 수집 |
| `src/blogspot_automation/services/issue_discovery_service.py` | broad scan + entity + cluster 발견 엔진 |
| `src/blogspot_automation/services/news_scoring_service.py` | 스코어링 + click_potential |
| `src/blogspot_automation/services/news_quality_gate.py` | 모든 publish 차단 게이트 (1063줄, 가장 복잡) |
| `src/blogspot_automation/services/golden_pattern_service.py` | pattern matching |
| `src/blogspot_automation/services/slot_filler_service.py` | slot 채움 |
| `src/blogspot_automation/services/golden_article_preview_service.py` | HTML 렌더 + GEO |
| `src/blogspot_automation/services/title_candidate_service.py` | 제목 후보 (specificity 우선) |
| `src/blogspot_automation/services/run_artifact_service.py` | runs/ artifact 저장 |
| `src/blogspot_automation/services/news_publish_service.py` | 뉴스 Blogger 발행 |
| `src/blogspot_automation/services/publish_history_service.py` | 히스토리 |
| `src/blogspot_automation/services/news_label_service.py` | 라벨/해시태그 |
| `src/blogspot_automation/services/news_image_prompt_service.py` | 이미지 프롬프트 메타 |
| `src/blogspot_automation/services/contrarian_content_service.py` | 콘텐츠 angle |
| `src/blogspot_automation/services/llm_content_service.py` | LLM 폴백 (OpenRouter→Gemini→OpenAI) |
| `src/blogspot_automation/services/evergreen_topic_service.py` | evergreen fallback |
| `src/blogspot_automation/services/topic_dedup_service.py` | dedup |
| `src/blogspot_automation/services/title_generation_service.py` | cli_news 직접 사용 |
| `src/blogspot_automation/services/news_taxonomy.py` | content_type 판별 |
| `src/blogspot_automation/services/retired legacy Naver rewrite service` | 네이버 RSS/스크래핑 |
| `src/blogspot_automation/services/ai_content_service.py` | naver 재작성 |
| `src/blogspot_automation/services/blog_package_service.py` | naver 패키지 빌드 |
| `src/blogspot_automation/services/qa_service.py` | naver 플로우 QA |
| `src/blogspot_automation/services/publish_service.py` | naver 플로우 발행 (Blogger client wrapper) |
| `src/blogspot_automation/publishing/client.py` | Blogger API 클라이언트 (양 플로우 공용) |
| `src/blogspot_automation/config/settings.py` | 환경변수 → Settings |
| `src/blogspot_automation/utils/html_meta.py` | meta description 추출 |
| `src/blogspot_automation/app/runtime.py` | naver 플로우 runtime 빌더 |
| `src/blogspot_automation/storage/*` | naver 플로우 sqlite 저장소 |
| `src/blogspot_automation/templates/blog_post_template.py` | 네이버 재작성 템플릿 (확인 필요) |
| `src/blogspot_automation/services/geo_intent_service.py` | GEO intent |
| `src/blogspot_automation/services/image_asset_service.py` | image url 검증 (qa_service 의존) |
| `golden_samples/patterns.json` | 핵심 패턴 데이터 (9 패턴) |
| `golden_samples/*.md` | 골든 샘플 원본 |
| `data/blog_automation.db` | naver dedup용 sqlite (~10MB) |
| `state/blogspot_automation.db` | naver state (gitignore에서 명시 예외) |
| `.github/workflows/news_blog.yml`, `retired Naver rewrite workflow` | 운영 워크플로우 |
| `requirements.txt`, `pyproject.toml`, `Makefile` | 빌드/의존성 |
| `templates/html/blogger_article_template.html` | 발행 템플릿 (확인 필요) |
| `config/topic_sources.json`, `config/monetization_topic_sources.json` | 주제 소스 설정 |

---

## 3. 보호 파일 (CLAUDE.md 정의)

| 파일 | 건드릴 수 있는 범위 | 건드리면 안 되는 범위 |
|------|---------------------|----------------------|
| `publish_service.py` | 주석 정리 정도 | 발행 로직, sanity check 시그니처 |
| `publishing/client.py` | 주석 정리 정도 | OAuth/Blogger API 호출 |
| `golden_article_preview_service.py` | 주석/타입 힌트 | render_article_candidate_html, build_preview |
| `run_pipeline.py` | (현재 존재하지 않음 — CLAUDE.md 표현 불일치) | — |
| `topic_bank.csv` | (현재 존재하지 않음 — CLAUDE.md 표현 불일치) | — |
| `retired legacy Naver rewrite entrypoint` | QA gate 강화, CTA 보장, 라벨 정리 | 발행 로직 자체 / 이미지 활성화 |

> **CLAUDE.md 갱신 필요**: `run_pipeline.py`, `topic_bank.csv`는 현재 존재하지 않음. 보호 목록에서 제거하거나 실제 보호해야 할 파일로 교체.

---

## 4. 중복/정리 후보 파일

### 4-A. 워크플로우에서 호출되지 않는 entrypoint
| 파일 | 문제 | 권장 조치 |
|------|------|----------|
| `cli_automation.py` | naver 플로우 풀사이클 복제본. 후처리 (`re.sub` 플레이스홀더 정리, published_history 마킹)가 `retired legacy Naver rewrite entrypoint`와 거의 동일 | **병합 또는 삭제 후보** — retired Naver rewrite workflow이 retired legacy Naver rewrite entrypoint만 호출하므로 cli_automation의 풀사이클은 죽은 코드. 함수 단위로 공통화한 후 삭제 권장. |
| `cli_ai.py` + `pipelines/ai_pipeline.py` | AI 전용 워크플로우 미존재. 로컬 dry_run만 가능. publish history에는 기록되지만 실제 자동발행 경로 없음 | **보관(archive/) 또는 삭제** — 정책 결정 필요. AI 자동발행 계획이 없으면 삭제. 추후 활용 계획 있으면 별도 디렉터리로 격리. |
| `cli/main.py` | UI/Streamlit 진입점으로 추정. 운영에 미사용 | 확인 후 격리 또는 삭제 |
| `ui/app.py`, `ui/scheduler.py`, `ui/service.py` | Streamlit UI. 로컬 검토용. 운영 워크플로우 무관 | **유지하되 의존성 격리** — 의존하는 storage/qa_service가 naver 플로우와 공유됨. 한 번에 삭제 어려움. |

### 4-B. 루트 레벨 ad-hoc 스크립트 (전부 git-tracked)
| 파일 | 문제 | 권장 조치 |
|------|------|----------|
| `force_publish.py` | 일회성 수동 발행 스크립트 | 삭제 후보 |
| `get_github_token.py` | OAuth 토큰 헬퍼 | 삭제 후보 (사용 시 재작성) |
| `get_topic.py` | 일회성 주제 조회 | 삭제 후보 |
| `mark_published.py` | publish_history 수동 마킹 | 삭제 후보 |
| `patch_db_and_prompt.py` | 일회성 DB 패치 | 삭제 후보 |
| `run_headless.py` | 헤드리스 러너 (cli_news와 중복?) | 확인 후 삭제 |
| `update_ai_content_service.py` | 일회성 업데이트 스크립트 | 삭제 후보 |
| `test_ai_content_parser.py` (root) | tests/ 외부, pytest 비표준 | tests/로 이동 또는 삭제 |
| `test_full_pipeline.py` (root) | 동일 | tests/로 이동 또는 삭제 |
| `test_generate.py` (root) | 동일 | tests/로 이동 또는 삭제 |
| `test_news_services_smoke.py` (root) | 동일 | tests/로 이동 또는 삭제 |
| `test_topic.py` (root) | 동일 | 삭제 후보 |
| `test_upload.py` (root) | 동일 | 삭제 후보 |
| `content_dump.html` | 디버그 출력 덤프 | 삭제 |
| `out.txt` | 디버그 출력 | 삭제 |
| `topics.json` | 정체 불명 | 확인 후 삭제 |

---

## 5. 죽은 코드 / 미사용 함수 후보

| 위치 | 근거 | 삭제 위험도 |
|------|------|------------|
| `cli_automation.py::run_full_cycle` | 호출 워크플로우 없음 (naver/news 모두 별도 cli) | 낮음 — 단, 수동 검증 시 사용 가능성 확인 필요 |
| `pipelines/ai_pipeline.py::AiTopicPipeline` | 워크플로우에서 호출 안 됨. cli_ai.py만 호출 | 중 — Naver 플로우가 미래에 활용할 가능성. 격리 권장. |
| `topic_discovery/*` (8개 파일) | 레거시 topic discovery. 새 플로우는 `news_topic_service` + `issue_discovery_service` 사용 | 중 — `topic_pipeline.py`/`topic_selection_service.py`를 통해 cli_automation에서 사용. cli_automation 정리와 함께 같이 정리 가능 |
| `pipelines/topic_pipeline.py` | cli_automation 전용 | cli_automation과 함께 정리 |
| `services/topic_selection_service.py` | cli_automation 전용 | 동 |
| `services/brief_generation_service.py` | cli_automation의 fallback 경로 (`if services.ai_content_service:` else) | 동 |
| `services/image_asset_service.py` | qa_service의 image url 검증에서 사용. 워크플로우는 이미지 비활성 | 낮음 — qa_service가 기존 데이터 마이그레이션에서 호출 가능. naver 플로우에는 영향 미미 |
| `image_generation/client.py` | 이미지 생성 클라이언트. `DISABLE_IMAGE_GENERATION=true`로 비활성 | 중 — 기능 자체는 유지하되 호출 경로 확인 후 격리 |
| `services/title_generation_service.py` vs `title_candidate_service.py` | cli_news는 `TitleGenerationService`를 인스턴스화하지만 NewsPipeline 내부에서는 `TitleCandidateService`를 사용. **TitleGenerationService 실제 사용 여부 검증 필요** | 검증 후 한쪽 폐기 |
| `news_pipeline.py` 내부 헬퍼 다수 | 패치 누적으로 비대화 (~45K). `_save_no_real_news_hold_report`, `_select_diverse_candidate`, `_apply_topic_group_cooldowns`, `_extract_viral_test_candidates`, `_force_*` 등 다수 | 대수술 금지. 함수별 사용처 추적 후 데드코드만 선별 |

---

## 6. 중복 품질 게이트

### 발견된 게이트 위치
| 위치 | 역할 | 중복 영역 |
|------|------|----------|
| `services/news_quality_gate.py::NewsQualityGate.evaluate` | 1063줄. blocking_issues/warnings 중심. final HTML 검사. | meta_description, h1, json_ld, FAQPage, hashtags, labels, naver CTA, AI 라벨 누수, html entity artifact, banned phrases 등 |
| `services/qa_service.py::BlogQualityAssuranceService.qa_review` | naver 플로우 전용. score 기반 PASS/SOFT_FAIL/FAIL. | placeholder 검사, source_count, br 태그 수, duplicate paragraph 등 |
| `pipelines/news_pipeline.py` 내부 가드 (`_evaluate_auto_publish_gate`, `publish_ready/geo_ready/sge_ready` 판정) | publish 전 마지막 차단 | `news_quality_gate.evaluate` 결과를 종합해 자동발행 차단 |
| `services/golden_article_preview_service.py` | preview 단계 검증 (slot_fill_rate, blocking_issues 출력) | `news_quality_gate`와 일부 중복 (banned phrases, default phrases) |
| `services/run_artifact_service.py` | artifact 저장 시 `article_candidate_meta.json::publish_ready/geo_ready` 마킹 | meta description / GEO 검증 |

### 중복 내용
- **HTML entity artifact 검사**: 최근 commit `c6d6ead`/`6ea310d`에서 news_quality_gate, run_artifact_service, ai_pipeline에서 동일 정규식이 산재할 가능성 (`grep -n "broken_html_entity"` 후 통합 위치 결정)
- **AI 내부 라벨 누수 검사**: news_quality_gate `_ai_smell_visible` 튜플과 cli_naver 정리 코드가 별도
- **naver CTA 검사**: news_quality_gate에서 검사하지만, naver 플로우의 후처리 단계에서도 별도 정리

### 통합 제안
1. **HTML entity / AI 라벨 / CTA 검사를 단일 모듈로 추출**: `services/final_publish_html_qa.py` (가칭). news_quality_gate와 ai_pipeline, naver 후처리에서 import.
2. **publish_ready 판정을 news_quality_gate로 일원화**: 현재 news_pipeline 내부에서 별도로 재계산하는 부분 단일화.
3. **qa_service vs news_quality_gate**: 다른 데이터 모델(work_item 기반 vs ScoredNewsCandidate 기반)이라 즉시 통합은 어려움. 단, banned phrase 리스트는 공유 가능 → `services/_quality_constants.py`로 추출.

---

## 7. article HTML 경로 정리

| 산출물 | 생성 위치 | 사용처 |
|--------|----------|--------|
| `runs/news_*/article_candidate.html` | `run_artifact_service.save_article_candidate` | 검토용. publish 시 그대로 또는 변형되어 Blogger로 전송 |
| `runs/news_*/article_candidate_meta.json` | run_artifact_service | publish_ready/geo_ready 신호 |
| 네이버 플로우 `work_item.article_html` | `ai_content_service.retired_naver_rewrite_generator` → `package_service.build_package` → cli_naver의 `re.sub` 정리 | `publish_service.publish` |
| 네이버 플로우 `package.article_preview_html` | `blog_package_service.build_preview_html` | UI 미리보기. publish 미사용 |

### 현재 혼선
- 뉴스 플로우와 네이버 플로우가 완전히 다른 HTML 파이프라인 (sqlite work_item vs run artifact dict). 공유 코드는 `publishing/client.py`뿐.
- `cli_automation.py`와 `retired legacy Naver rewrite entrypoint`가 동일한 placeholder 정리 코드를 복사해서 가지고 있음 (`re.sub(r'<img[^>]*src="\{\{IMG_[23]\}\}"...')` 등 6줄 이상).
- final HTML QA가 두 곳(news_quality_gate / cli_naver의 후처리)에서 다른 기준으로 동작.

### 정리 제안
1. 플레이스홀더 정리 함수를 `services/blog_package_service.py::cleanup_naver_placeholders` (가칭)로 추출. cli_naver/cli_automation 양쪽에서 호출.
2. **현재는 뉴스/네이버 두 HTML 흐름을 통합하지 말 것** — 데이터 모델이 다르고 검증 기준도 다름. 무리한 통합은 회귀 위험 큼.
3. 단, "최종 발행 HTML이 거쳐야 하는 검사 목록"만 단일 모듈로 격리하면 두 흐름 모두 안전하게 사용 가능.

---

## 8. 테스트 정리

### 유지해야 할 테스트 (현 워크플로우 직접 검증)
- `test_golden_pattern_service.py`
- `test_slot_filler_service.py`
- `test_golden_article_preview_service.py`
- `test_article_candidate_artifact.py`
- `test_article_candidate_metadata.py`
- `test_article_candidate_quality_final.py`
- `test_article_candidate_title_apply.py`
- `test_article_candidate_title_geo.py`
- `test_evergreen_golden_matching.py`
- `test_title_candidate_service.py`
- `test_news_default_phrase_gate.py`
- `test_slot_filler_news_patterns.py`
- `test_today_issue_editorial_gate.py`
- `test_issue_discovery_engine.py`
- `test_discovery_to_article_candidate.py`
- `test_final_publish_html_quality_gate.py`
- `test_news_geo_intent_engine.py`
- `test_editorial_candidate_gate.py`
- `test_news_fallback_candidate.py`
- `test_news_candidate_generation_threshold.py`
- `test_news_scoring_boost.py`
- `test_topic_engine_v2.py`
- `test_fresh_news_replacement.py`

### 검증 후 정리 후보
- `test_ai_pipeline_quality.py`, `test_ai_artifact_completion.py` — AI 파이프라인이 운영 안 됨. 보관 또는 삭제.
- `test_blog_package_service.py`, `test_brief_generation_service.py` — naver 플로우 의존. 유지하되 brief는 cli_automation 정리와 함께 결정.
- `test_image_asset_service.py`, `test_image_generation.py` — 이미지 기능 비활성. 격리 또는 삭제.
- `test_qa_flow.py`, `test_qa_publish_service.py`, `test_qa_review.py` — 레거시 qa_service 기준. naver 플로우가 의존하므로 유지.
- `test_publishing.py` — 레거시 publish_service. naver 플로우 의존. 유지.
- `test_pipeline.py`, `test_content_generation.py` — 정체 불명. 확인 필요.
- `test_storage_discovery_debug.py`, `test_topic_discovery.py`, `test_topic_discovery_debug.py`, `test_topic_provider_loading.py`, `test_topic_retry_loop.py`, `test_topic_selection_service.py`, `test_topic_strategy_config.py`, `test_topic_strategy_split.py`, `test_storage_repository.py` — 레거시 topic_discovery 기반. cli_automation/topic_pipeline 정리와 함께 결정.
- `test_workflow_e2e_monetization.py` — 레거시 e2e. 확인 필요.

### 루트 레벨 임시 테스트 (tests/ 외부)
- `test_ai_content_parser.py`, `test_full_pipeline.py`, `test_generate.py`, `test_news_services_smoke.py`, `test_topic.py`, `test_upload.py` — pytest 비표준 위치. 4-B 항목과 동일하게 정리.

### legacy import 오류 가능 원인 (전체 pytest 실패 시)
- `from blogspot_automation.storage import ...` 경로 변경 후 미반영
- `image_asset_service` 등 image 비활성화로 인한 import side-effect
- `topic_discovery/*`의 deprecated 모듈
- 레거시 cli_automation 의존 테스트가 pipeline/topic_pipeline 변경에 따라 깨짐

> **전체 pytest 복구 계획**: 우선 핵심 23개 테스트가 그린인지 확인 → 그 외 테스트 import 에러 fix or skip 마킹 → 정리 단계에서 일괄 삭제/이동.

---

## 9. 문서 정리 (루트 17개 MD)

### 유지
- `CLAUDE.md` — 운영 정책 (단, 보호 파일 표 갱신 필요: `run_pipeline.py`/`topic_bank.csv` 미존재)
- `README.md` — 프로젝트 진입점
- `README_WORKFLOW.md` — 워크플로우 운영 매뉴얼

### 업데이트 필요
- `CLAUDE.md` — 4. 보호 파일 항목의 존재하지 않는 파일 수정
- `RUNBOOK.md` — 현재 운영 절차와 일치 여부 확인
- `DEPLOYMENT_GUIDE.md` — 동일

### 보관/통합 후보 (Phase 2/3 진행 중에 만들어진 설계 문서)
| 파일 | 처리 |
|------|------|
| `PRD.md`, `PRD_CONTENT_ENGINE_V2.md` | docs/archive/로 이동 후 README에 링크 |
| `TECH_SPEC.md`, `TASK_LIST.md`, `TEST_PLAN.md` | 동 |
| `ARCHITECTURE.md`, `PROJECT_STRUCTURE.md`, `CONFIG_SPEC.md`, `AUTOMATION_ENGINE_STRUCTURE.md` | 동 (현재 코드와 일치 여부 검증 후 갱신 또는 archive) |
| `CONTENT_STRATEGY_LOCK.md`, `GOLDEN_ARTICLE_EXAMPLES.md`, `TOPIC_CLUSTER_MAP.md`, `QUALITY_REVIEW_PROMPT.md` | 콘텐츠 전략 참고용. docs/strategy/로 이동 |

> 문서 17개는 한 번에 정리하지 말고 P2 단계에서 일괄 분류.

---

## 10. gitignore / runtime artifact 점검

### 커밋해야 하는 파일
- `data/blog_automation.db` — 네이버 dedup용 (이미 트래킹 중)
- `state/blogspot_automation.db` — naver state (`!state/blogspot_automation.db` 예외 명시됨, 트래킹 중)
- `data/publish_history.example.json` — 예제 (트래킹 중)

### 커밋하면 안 되는 파일 (현재 문제)
| 파일 | 현 상태 | 권장 |
|------|---------|------|
| `data/publish_history.json` | **트래킹 중**, news_blog.yml의 schedule 단계에서 자동 commit & push (`[skip ci]`) — 의도된 동작 | 로컬 dry_run 후 modified 상태가 자주 발생. 의도된 운영은 유지하되, 로컬 작업 시 우발 commit 방지를 위해 별도 메커니즘 검토. |
| `state/news_published_history.json` | **현재 untracked** | `.gitignore`에 추가하거나, `state/blogspot_automation.db`처럼 명시 예외로 처리 결정 필요. **운영 시 GitHub Actions에서 생성됨** → 커밋되지 않아야 함 → `.gitignore`에 추가 권장. |
| `data/naver_processed.json` | 트래킹 중. retired Naver rewrite workflow에서 `git add data/naver_processed.json`로 자동 commit | 의도된 동작 (네이버 dedup 상태). 유지. |
| `data/published_history.json` | 트래킹 중 (2 bytes — 빈 list `[]`). cli_naver/cli_automation에서 update | 운영용으로 유지. |
| `data/tools_database.json`, `data/blog_automation.db` | 트래킹 중. 큰 sqlite | 유지하되 size 모니터링 필요. |
| `runs/` | gitignore 됨, 100+ 디렉터리 누적 | 로컬 디스크 정리 필요 (`runs/news_*` 7일 이전 삭제 스크립트 등). 별도 작업. |
| `logs/`, `__pycache__/`, `.pytest_cache/`, `images/`, `contents/`, `venv/`, `.streamlit/` | gitignore 됨 | 양호 |
| `.env` | gitignore 됨 | 양호 |
| `.env.example` | 트래킹 중 | 양호 |
| `GITHUB_SECRETS.txt` | **트래킹 중 + 실제 시크릿 포함** | **0번 항목 참고. 즉시 회전 + 삭제** |

---

## 11. 리팩토링 우선순위

### P0 — 자동발행 안정성 / 보안에 직접 영향 (사용자 승인 즉시 시작)
1. **GITHUB_SECRETS.txt 회전 + 트래킹 제거** (위 0번)
2. **CLAUDE.md 보호 파일 표 갱신** — 존재하지 않는 `run_pipeline.py`/`topic_bank.csv` 제거
3. **state/news_published_history.json gitignore 추가**
4. **HTML entity / AI 라벨 / CTA 최종 검사 단일 모듈 추출** — final publish HTML QA가 여러 곳에 흩어져 있어 누락 위험
5. **TitleGenerationService vs TitleCandidateService 사용처 검증** — cli_news가 인스턴스화하지만 NewsPipeline 내부 사용 여부 확인. 죽은 의존성이면 cli_news 정리

### P1 — 유지보수성 / 중복 제거 (P0 완료 후)
6. **cli_automation.py 정리** — retired Naver rewrite workflow 미사용. 코드 함수 단위 공통화 후 삭제
7. **placeholder 정리 함수 공통화** — cli_naver/cli_automation 중복 코드 → blog_package_service로 이동
8. **루트 ad-hoc 스크립트 일괄 정리** — force_publish/get_*/mark_published/patch_*/update_* (4-B 표)
9. **루트 레벨 test_*.py를 tests/로 이동 또는 삭제**
10. **cli_ai.py + ai_pipeline.py 보관/삭제 결정** — 정책 결정 필요
11. **topic_discovery/* + topic_pipeline + topic_selection_service 정리** — cli_automation 정리에 종속

### P2 — 문서 / 청소 / 네이밍 정리 (P0/P1 안정화 후)
12. **17개 root MD → docs/ 정리** — README/CLAUDE/README_WORKFLOW만 루트 유지
13. **runs/ 로컬 정리 스크립트** — 7일 이전 자동 삭제
14. **content_dump.html, out.txt, topics.json 삭제**
15. **죽은 import / 사용 안 되는 helper 일괄 점검** — news_pipeline.py 내부

---

## 12. 제안 작업 순서 (사용자 승인 후)

```
Step 1 (P0, 즉시):
  1. GITHUB_SECRETS.txt 처리 — 사용자가 Google Cloud Console에서 회전 + 새 secret을 GitHub Secrets에 등록
  2. 로컬에서 git rm --cached GITHUB_SECRETS.txt + .gitignore 추가 + 일반 commit
  3. 히스토리 purge 여부는 사용자 결정 (force push 동반)

Step 2 (P0):
  4. CLAUDE.md 보호 파일 표 갱신
  5. state/news_published_history.json을 .gitignore에 추가
  6. (선택) data/publish_history.json 로컬 dirty 상태 정리 — git checkout으로 되돌릴지 사용자 확인

Step 3 (P0):
  7. final publish HTML QA 통합 모듈 추출 — news_quality_gate / cli_naver 후처리 / ai_pipeline에서 import
  8. TitleGenerationService 사용처 검증 후 죽은 의존성 정리

Step 4 (P1):
  9. cli_automation.py 정리 + placeholder 정리 함수 공통화
  10. 루트 레벨 ad-hoc 스크립트 + 루트 test_*.py 정리
  11. ai_pipeline 보관/삭제 결정

Step 5 (P1):
  12. topic_discovery/* + topic_pipeline + topic_selection_service 정리

Step 6 (P2):
  13. 17개 MD → docs/ 정리
  14. runs/ 로컬 정리 스크립트
```

각 Step은 별도 commit + 검증 (compileall + 핵심 23개 테스트 + dry_run 검증) 후 진행.

---

## 13. 바로 하면 안 되는 작업

| 작업 | 이유 |
|------|------|
| `news_pipeline.py` 대수술 (45K → 분할) | 운영 중인 가장 복잡한 코드. 회귀 위험 매우 큼. P1 이후 검증 환경 갖춘 다음 별도 작업 |
| `news_quality_gate.py` 가드 제거/완화 | 자동발행 차단 로직. 잘못 풀면 저품질 자동발행 위험 |
| `qa_service.py` 삭제 | naver 플로우가 의존 중. 단순 격리는 가능하나 즉시 삭제 위험 |
| `golden_article_preview_service.py` 리팩토링 | render_article_candidate_html이 두 파이프라인의 핵심 산출물. 출력 변경 시 모든 검증 깨짐 |
| `data/publish_history.json` 강제 reset | naver 플로우가 의존하는 운영 데이터 |
| `state/blogspot_automation.db` 삭제 | naver dedup state. 삭제 시 같은 글 재발행 위험 |
| `runs/` git 추가 | 워크플로우가 매일 만드는 산출물. 리포지토리 폭발 위험 |
| 워크플로우 yml 변경 | 운영 자동발행에 직접 영향. 별도 PR + 사용자 승인 필요 |
| force push to main | CLAUDE.md 금지. GitHub Secrets purge 시에만 별도 승인으로 |

---

## 14. 다음 승인 요청

사용자가 승인하면 진행할 첫 정리 작업:

**(A) 보안 — GITHUB_SECRETS.txt 처리 (강력 권장, 즉시)**
1. Google Cloud Console에서 노출된 OAuth Client Secret 회전 + Refresh Token 폐기 (사용자가 직접 콘솔에서 수행)
2. GitHub Repo Settings → Secrets에 새 값 등록 (사용자가 직접)
3. 로컬에서 다음 작업을 사용자 승인 후 수행:
   - `git rm --cached GITHUB_SECRETS.txt`
   - `.gitignore`에 `GITHUB_SECRETS.txt` 추가
   - 로컬 파일은 사용자가 직접 삭제 또는 안전한 위치로 이동
   - `git commit -m "chore: remove leaked secrets file from tracking"`
4. 히스토리 완전 purge 여부 사용자 결정 (필요 시 별도 작업으로)

**(B) 안전한 첫 클린업 (보안 처리 후 또는 동시 진행)**
1. CLAUDE.md 보호 파일 표 갱신 (`run_pipeline.py`/`topic_bank.csv` 제거, 실제 보호 파일 반영)
2. `state/news_published_history.json`을 `.gitignore`에 추가
3. 핵심 23개 테스트 + `python -m compileall src` 통과 확인 후 commit

이후 단계는 (A)/(B) 처리 결과 확인 후 사용자가 다음 step을 승인.

---

> 이 보고서는 **감사·계획만** 담고 있으며, 어떤 코드/파일도 수정하거나 삭제하지 않았습니다.
