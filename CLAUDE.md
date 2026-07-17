# Blogspot 자동화 프로젝트 — CLAUDE.md

## 프로젝트 개요
Blogspot 오늘의 이슈 자동화 파이프라인.
뉴스/에버그린/AI 주제를 골든 패턴으로 매칭해 article_candidate.html을 생성하고 검토 후 발행한다.

## 출력 언어 — 영어 전환 (2026-07-17)
holyyomiai.blogspot.com은 영어권(미국·영국·캐나다·인도) 대상 **영어 AI 블로그**다.
- 스위치: `BLOG_LANGUAGE` env (`services/blog_language.py`). 기본값 `ko`(기존 테스트·네이버 플로우 보존)이지만 **cli_ai.py가 `en`을 setdefault**하므로 ai_blog.yml 스케줄 경로는 영어 모드로 돈다.
- 영어 모드에서 바뀌는 것: 주제 쿼리(EN_QUERY_GROUPS + en-US RSS), 에버그린 뱅크(`_ai_automation_topics_en`), 본문 프롬프트(`_SYSTEM_PROMPT_EN`), 리서치(Exa+RSS en, Naver 스킵), GEO 블록·meta description·JSON-LD 영어, 제목 빌더(`_build_english_titles`), 라벨 6종(Comparisons/Pricing/How-To/Fixes/Data & Stats/News).
- **영어 모드 강화 게이트**: LLM 영어 서술 본문이 자체 게이트를 통과하지 못하면 한국어 템플릿 폴백 발행을 차단한다(`en_mode_template_fallback_blocked`) — 템플릿 candidate는 게이트 판정용으로만 쓰인다.
- 게이트 영어 텀뱅크는 전부 additive — 한국어 검사·차단 조건은 그대로다. 회귀는 `tests/test_english_mode.py`가 지킨다.
- 콘텐츠 전략(주제군 6종·글 구조·안전 규칙)은 루트의 사용자 지침 문서를 따른다.

---

## 운영 브랜치
현재 운영 브랜치: `main`
Phase 3 + Completion Patch 1 (GoldenPattern, SlotFiller, TitleCandidate, GEO layer, AI_CITATION_SUMMARY, corporate_issue_decode 등) 모두 main에 머지 완료, 실제 스케줄 워크플로우에서 가동 중.

---

## 파일 보호 정책

### 삭제/구조 수정 절대 금지
| 파일 | 이유 |
|------|------|
| `src/blogspot_automation/publishing/client.py` | Blogger API 직접 호출 (양 플로우 공용) |
| `src/blogspot_automation/services/publish_service.py` | 네이버 플로우 발행 서비스 |
| `src/blogspot_automation/services/news_publish_service.py` | 뉴스 플로우 Blogger 발행 |
| `src/blogspot_automation/cli_news.py` | news_blog.yml 진입점 |
| `retired legacy Naver rewrite entrypoint` | retired Naver rewrite workflow 진입점 (최소 수정 가능) |
| `src/blogspot_automation/pipelines/news_pipeline.py` | 뉴스 자동발행 메인 파이프라인 |
| `src/blogspot_automation/services/golden_article_preview_service.py` | 핵심 HTML 렌더링 (article_candidate.html 생성) |
| `src/blogspot_automation/services/news_quality_gate.py` | 자동발행 차단 게이트 |
| `src/blogspot_automation/services/golden_pattern_service.py` | 패턴 매칭 엔진 |
| `golden_samples/patterns.json` | 골든 패턴 데이터 원본 |
| `.github/workflows/news_blog.yml` | 뉴스 자동발행 워크플로우 |
| `.github/workflows/retired Naver rewrite workflow` | 네이버 자동발행 워크플로우 |

### 최소 수정 허용 (삭제/대수술 금지)
| 파일 | 허용 수정 범위 |
|------|--------------|
| `retired legacy Naver rewrite entrypoint` | QA FAIL 시 발행 차단, publish_ready/quality gate 추가, 네이버 CTA 보장, AI 내부 라벨 제거, 이미지 생성/업로드 비활성화 유지, publish_attempted/succeeded/blogger_url 로그 명확화 |
| `pipelines/news_pipeline.py` | 새 게이트/필터 추가는 가능. 기존 발행 경로/조건 변경은 별도 승인 필요 |
| `services/news_quality_gate.py` | 게이트 강화는 가능. 기존 차단 조건 완화/제거는 별도 승인 필요 |

### 보호의 진짜 의미 = 머지 조건 (2026-07-08 구조 감사로 재정의)
감사 실측: 보호 정책은 변경을 막지 못했고(최근 60커밋에서 news_pipeline.py 6회 수정),
"새 게이트 추가는 싸게, 구조 정리는 비싸게" 만들어 additive 패치만 쌓였다
(5,270줄·게이트 24종·status 31종). 그래서 보호를 "수정 자제"가 아니라
**"아래 검증 없이 머지 금지"**로 재정의한다:

1. **통합 테스트 통과 필수**: 보호 파일(발행 경로·게이트·워크플로우)을 건드리는
   모든 변경은 `tests/test_integration_fake_blogger.py`(fake Blogger로 발행
   파이프라인 끝까지) + `tests/test_env_contract.py`(env 계약)를 포함한 전체
   스위트 통과 후에만 머지.
2. **발행 경로/최종 계약 변경 시 실측 리허설 필수**: `gh workflow run ai_blog.yml
   --ref <branch> -f publish_mode=publish_draft`로 실제 GHA에서 1회 실행해
   `draft_saved_for_review` 도달을 확인 후 머지. (`publish_mode=publish`는
   라이브 발행이므로 검증용 사용 금지 — dry_run은 auto_publish_gate·최종
   발행 계약을 실행하지 않아 검증으로 불충분.)
3. **구조 정리(중복 제거·경로 통합·책임 분리)는 위 1·2를 통과하는 한 환영**:
   "기존 경로를 건드리면 안 된다"가 아니라 "기존 동작을 통합 테스트가 지키는
   상태에서 정리하라"가 규칙이다. 기존 차단 조건의 완화/제거만 여전히
   사용자 승인 필요.

---

## 발행 정책 — 로컬 개발 모드 vs schedule 운영 모드

### 로컬 개발 / dry_run / 수동 검증 (안전 원칙)
- `PUBLISH_HOLD_PHASE2=true` 권장
- `DRY_RUN=true` 또는 `NEWS_PUBLISH_MODE=dry_run` 권장
- `AUTO_PUBLISH=false` 권장
- main 브랜치 직접 push 금지 (PR 경유)
- GitHub workflow 수동 실행은 스모크 테스트 목적으로만 허용

### GitHub Actions schedule 운영 모드 (자동)
- `news_blog.yml` schedule: `DRY_RUN=false`, `PUBLISH_HOLD_PHASE2=false`, `AUTO_PUBLISH=true` — 자동 발행 경로
- `retired Naver rewrite workflow` schedule: retired legacy Naver rewrite entrypoint 실행 후 자동 발행

### 자동 발행 허용 조건 (news_blog.yml)
아래 조건을 **모두** 통과해야 실제 발행:
- `publish_ready=true`
- `geo_ready=true`
- `sge_ready=true` (또는 동등 품질 게이트 통과)
- final publish HTML QA 통과 (hard blocking issue 없음)
- AI 내부 라벨 노출 없음
- `naver_blog_cta_present=true`
- 커버 자동 생성 비활성은 `ENABLE_COVER_IMAGE_AUTOGEN=false`가 담당 (과거 문서의 `DISABLE_IMAGE_GENERATION`/`DISABLE_IMAGE_UPLOAD`는 어떤 코드도 읽지 않는 죽은 env였음 — 2026-07-08 env 계약 테스트로 확인)

---

## 파이프라인 흐름

```
cli_news.py
  └─ NewsPipeline.run_once()
       ├─ NewsTopicService / EvergreenTopicService  (주제 수집)
       ├─ NewsScoringService + Topic Engine v2       (스코어링)
       ├─ GoldenPatternService.match_pattern()       (패턴 매칭, near_match 지원)
       ├─ SlotFillerService.fill_slots()             (슬롯 채움)
       ├─ GoldenArticlePreviewService                (HTML 렌더링 + GEO layer)
       ├─ TitleCandidateService                      (제목 후보, specificity 우선)
       └─ RunArtifactService                         (artifact 저장)
            ├─ article_candidate.html
            ├─ article_candidate_meta.json
            ├─ golden_preview_meta.json
            └─ candidate_hold_report.json (미생성 시)

cli_ai.py
  └─ AiTopicPipeline.run_once()            (AI 주제 동일 품질 엔진)
```

---

## 골든 패턴

| pattern_id | content_type | topic_group |
|------------|-------------|------------|
| tax_refund_hometax_check | tax_refund | policy_benefit |
| viral_ott_reaction_decode | viral_issue_decode | ott_platform |
| ai_work_time_savings | ai_work_tip | ai_work |
| ai_tool_comparison | ai_work_tip | ai_work |
| ai_automation_workflow | ai_work_tip | ai_work |
| corporate_issue_decode | viral_issue_decode | platform_issue |

---

## article_candidate 생성 조건

```python
# 완전 매칭 (confidence >= 80)
matched=True AND ready_for_review=True AND confidence>=80

# near_match 허용 (confidence 75~79 + ct_match + tg_match)
near_match=True AND confidence>=75 AND ct_match AND tg_match AND slot_fill>=0.8

# 공통
content_candidate_grade in ("A", "B")  # near_match면 "C"도 허용
slot_fill_rate >= 0.8
```

---

## publish_ready 조건

```python
publish_ready = (
    content_candidate_grade in ("A", "B")
    AND geo_ready == True          # meta_desc_valid + title_applied + score>=80
    AND stale_source_warning == False
    AND candidate_meta_description_valid == True
    AND pre_publish_checklist 모든 항목 True
    # schedule 운영 모드: AUTO_PUBLISH=true 시 자동 발행 진행
    # 로컬/수동 모드: human_review_required=True로 항상 홀드
)
```

---

## 워크플로우 스케줄 (운영 방침 2026-07-03: AI 주제 하루 1회 자동 발행)

| 파일 | cron (UTC) | KST | 목적 | 동작 |
|------|------|-----|------|------|
| ai_blog.yml | `31 22 * * *`, `31 10 * * *` | 07:31 / 19:31 | **유일한 자동 발행** — AI 이슈 2건/일 (아침·저녁) | schedule: DRY_RUN=false, AUTO_PUBLISH=true. LLM은 OpenRouter 무료(1차 nemotron→2차 gpt-oss) → OpenAI 유료 폴백 |
| news_blog.yml | (schedule 없음) | — | 수동 스모크 테스트/수동 발행 전용 | workflow_dispatch만 지원 (30분 주기 schedule은 2026-07-03 제거) |

> GitHub Actions schedule은 main 브랜치에서만 실행됨
> GOOGLE_AI_API_KEY(Gemini)는 더 이상 사용하지 않음 — 팩트 수집은 Custom Search(키 있을 때) → Google News RSS(키 불필요) 폴백

---

## 검증 명령

```bash
# 컴파일 검사
python -m compileall src

# 발행 경로 통합 테스트 (보호 파일 변경 시 필수 — fake Blogger로 끝까지)
PYTHONPATH=src pytest tests/test_integration_fake_blogger.py tests/test_env_contract.py -q

# 발행 경로/최종 계약 변경 시 실측 리허설 (라이브 오염 0 — Blogger 초안까지만)
# gh workflow run ai_blog.yml --ref <branch> -f publish_mode=publish_draft

# 전체 테스트 (핵심)
PYTHONPATH=src pytest tests/test_golden_pattern_service.py \
  tests/test_slot_filler_service.py \
  tests/test_golden_article_preview_service.py \
  tests/test_article_candidate_artifact.py \
  tests/test_article_candidate_title_geo.py \
  tests/test_article_candidate_metadata.py \
  tests/test_evergreen_golden_matching.py \
  tests/test_title_candidate_service.py \
  tests/test_article_candidate_quality_final.py -q

# 뉴스 dry_run
PYTHONPATH=src DRY_RUN=true NEWS_PUBLISH_MODE=dry_run PUBLISH_HOLD_PHASE2=true \
  python src/blogspot_automation/cli_news.py

# 에버그린 dry_run
PYTHONPATH=src DRY_RUN=true FORCE_EVERGREEN_FALLBACK=true PUBLISH_HOLD_PHASE2=true \
  python src/blogspot_automation/cli_news.py

# AI 주제 dry_run
PYTHONPATH=src DRY_RUN=true python src/blogspot_automation/cli_ai.py
```

---

## 다음 작업 후보

1. stale 후보 full retry (현재 hint만 저장)
2. AI_CITATION_SUMMARY 3문장 이하 케이스 보강
3. meta description 중복 단어 필터
4. 이미지 자동 생성 (image_missing warning 해소)
5. 실제 발행 승인 플로우 (explicit_approval flag)
