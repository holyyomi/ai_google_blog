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

### 영어 블로그 운영 원칙 (2026-07-18 품질 업그레이드)
- 이 블로그는 AI 뉴스 요약 사이트가 아니라, 영어권 독자가 AI 도구를 **선택·비교·가격판단·문제해결·활용**할 때 참고하는 검증된 실용 자료실이다. 모든 글은 이 중 최소 하나를 독자가 할 수 있게 해야 한다.
- GEO는 꼼수가 아니라 보조 전략이다: 명확한 즉답·검증된 수치·표·출처·as-of 날짜가 AI 검색 인용 **가능성을 높일 뿐**, 인용을 보장하는 공식은 없다. 항상 독자 우선.
- 타겟은 **US-first English**. 가격·기능이 지역별로 다를 수 있으면 본문에 "pricing may vary by region"을 명시한다.
- 출처 우선순위: 공식 가격 페이지 > 릴리즈 노트 > 공식 문서 > 벤더 블로그 > 신뢰 2차 매체. 커뮤니티(Reddit/X)는 pain point 탐색용으로만 — 가격·스펙·벤치마크의 근거 금지.
- **1인칭 테스트 주장("I tested") 절대 금지** — 자동 파이프라인은 실테스트가 불가능하므로 항상 날조다. 대신 독자가 직접 돌릴 재현 가능한 레시피(프롬프트·조건·측정 항목)를 준다. 우회/탈취 표현(bypass/unlock paid/avoid detection)도 프롬프트+검증기+게이트 3중 차단.
- 발행 로그(run_meta)의 content_family/official_source_count로 유형별 성과(RPM·CTR)를 추적한다.

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

## 워크플로우 스케줄 (운영 방침 2026-08-03: 하루 1회, **GHA 단독**)

**자동 발행 경로는 GHA `ai_blog.yml` schedule 하나뿐이다. Cloud Run 폴백은 중단됐다.**

| 트리거 | 시각 (UTC) | 역할 | 동작 |
|------|------|------|------|
| GHA `ai_blog.yml` schedule | 12:31 하루 1회 | **유일한 자동 발행** | DRY_RUN=false, AUTO_PUBLISH=true. 원장 중복 가드만 통과하면 실행 |
| Cloud Scheduler `ai-blog-evening` → Cloud Run Job `ai-blog-pipeline` | — | **중단(PAUSED, 2026-08-03)** | 아래 "왜 껐는가" 참고 |
| Cloud Scheduler `ai-blog-morning` | — | 일시정지(PAUSED) | 하루 1회 전환(2026-07-22)으로 중단 |
| GHA `ai_blog.yml` workflow_dispatch | 수동 | 스모크 테스트/publish_draft 리허설 | 게이트와 무관하게 항상 동작 |
| GHA `news_blog.yml` (schedule 없음) | — | 수동 전용 (별도 프로젝트 — 건드리지 말 것) | workflow_dispatch만 지원 |

### Cloud Run 폴백을 왜 껐는가 (2026-08-03, 실측 근거)

1. **30분 하드 타임아웃에 구조적으로 못 맞는다.** Cloud Run job의 `--task-timeout=1800s`인데
   파이프라인 완주에 22~49분이 걸린다(GHA 실측: 8/1 48분56초, 8/2 22분9초).
   **7/29~8/2 5일 연속 정확히 1800초에 SIGKILL**됐다. 원장 커밋이 파이프라인 실행
   *뒤에* 순차로 붙어 있어서 죽으면 그 실행의 결과가 성공이든 실패든 기록조차 안 남았고,
   GHA가 7월 게이트로 스킵되던 7/29~31 사흘은 발행이 통째로 증발했다.
2. **매일 중복으로 풀 파이프라인을 태웠다.** GHA 12:31이 큐 지연되면(8/2 실측 95분 지연)
   12:50의 Cloud Run이 "최근 120분 내 GHA 없음"으로 오판하고 자기가 발행을 시작했다.
3. 7월 Actions-minute 한도 소진 기간이 끝나 8/1부터 GHA가 정상 복귀했다 — 폴백의 존재
   이유였던 조건 자체가 사라졌다.

**되살릴 경우 반드시 먼저 할 것**: `scripts/deploy_cloud_run.sh`의 `--task-timeout`을
3300s 이상으로 올릴 것. 1800s로는 완주 불가능하다. 이중 발행 방지 설계(원장 가드)는
그대로 유효하다.

**이중 발행 구조적 차단(경로가 하나여도 유지)**: 시간 기반 핸드셰이크만으로는 GHA 큐
지연(57분~2시간 실측)에 깨져 슬롯당 2건 중복 발행됐다(2026-07-20~21 사고). 지금은 실행
시작 시점에 `scripts/check_published_today.py`로 원장(data/publish_history.json)을 직접
확인해 "오늘(KST) 라이브 발행이 이미 있으면" 스킵한다 — 트리거가 얼마나 지연되든,
재실행이 몇 번이든 하루 1건을 넘지 않는다. (라이브 판정: published=true + blogspot.com
URL. 리허설 초안은 blogger.com/edit URL이라 자연히 제외.)

**Cloud Run 이미지 계약(중단 상태에서도 유지)**: 이미지의 entrypoint.sh는
"clone → `scripts/cloud_run_pipeline.sh` exec"만 하는 얇은 셔틀이다. 로직 수정은 git
push만으로 반영되고, 이미지 재빌드는 requirements.txt 등 의존성이 바뀔 때만 필요하다.

## 외부 API 예산 정책 (2026-08-03)

크레딧이 소진된 provider를 계속 호출하면 시간과 돈이 동시에 샌다. 실측(7/29~8/2):
Tavily 전 호출 HTTP 432, Firecrawl 전 호출 HTTP 402, Reddit 6개 서브레딧 전부 HTTP 403.
재시도 6회를 곱해 **실행당 약 3분**을 버렸고 이것이 30분 타임아웃의 한 축이었다.

- **끈 것**: `ENABLE_TAVILY_SEARCH=false`, `ENABLE_FIRECRAWL_SEARCH=false`,
  `COMMUNITY_REDDIT_SUBS=off`(Reddit만 끄고 HN 신호는 유지).
- **끄면 안 되는 것**: `ENABLE_EXA_SEARCH`. Exa는 본문 팩트 수집 체인의 핵심이고,
  끄면 팩트가 RSS 헤드라인만 남아 "껍데기 글"이 나온다(2026-07-24 실측 사고).
- **회로차단기**: `external_news_search_service`가 401/402/403/429/432를 받으면 그
  provider를 이번 실행 동안 차단하고 로그를 1회 남긴다. 5xx·타임아웃은 일시 장애이므로
  차단하지 않는다. Exa만은 429(일시 rate limit)로 죽이지 않고 401/402/403/432에서만
  차단한다. `community_topic_service`도 Reddit 전용 회로차단을 갖는다(HN은 무관하게 계속).
- 크레딧을 다시 채우면 `ENABLE_*`를 true로 되돌리기만 하면 된다. 다시 소진돼도
  회로차단기가 첫 확정 실패에서 자동으로 멈추므로 이번 같은 며칠짜리 낭비는 재발하지 않는다.

> GitHub Actions schedule은 main 브랜치에서만 실행됨
> GOOGLE_AI_API_KEY(Gemini)는 더 이상 사용하지 않음 — 팩트 수집은 Custom Search(키 있을 때) → Google News RSS(키 불필요) 폴백

## 자료 수집 상한 — 헤지·껍데기 글의 진짜 원인 (2026-09-01)

**증상이었던 것**: 글이 "공식 페이지를 확인하세요"로 도배되고, 헤지 포화 검증기가
초안을 두 번 연속 거부해 그날 발행이 통째로 실패했다. 주제가 나빠서라고 생각했지만
아니었다.

**원인**: `_exa_facts_and_citations`가 `numResults=3`·`maxCharacters=400`으로 요청하고
받아온 본문을 코드에서 `[:300]`으로 한 번 더 잘랐다. **자료 상한이 약 1,200자**였고,
그 1,200자로 1,700~2,200단어를 쓰라고 요구했다. 모델이 헤지로 채우는 것 말고 할 수
있는 게 없었다.

**Exa는 검색 1회당 과금이다.** 같은 쿼리 실측:

| 설정 | 확보 자료 |
|------|-----------|
| 3건 × 400자 (기존) | 1,200자 |
| 5건 × 1500자 (현재) | 7,500자 |

비용은 사실상 같은데 84%를 버리고 있었다. 실제 주제 3개에서 수집량이 **1,005자 →
6,320자**가 됐다. 분량 규격을 손대기 전에 **자료가 실제로 얼마나 들어오는지부터
재라** — 얇은 자료로 긴 글을 요구하는 구조에서는 어떤 문장 규칙도 소용없다.

회귀 방지: `tests/test_length_targets_follow_facts.py`가 400자·`[:300]`·numResults<5로
되돌아가는 것을 막는다.

**분량은 자료를 따라간다**: `_length_targets_for_facts()`가 팩트 분량으로 목표를 정한다
(얇으면 700/800~1200, 충분하면 1500/1700~2200). 이때 **프롬프트·검증기·보강 세 곳이
같은 숫자를 봐야 한다** — 2026-09-01에 프롬프트만 800~1200으로 바꾸고 검증기가 1500을
보게 뒀더니, 규격대로 나온 832단어 초안을 "부족"으로 거부하고 폴백이 헛돌다 429까지
맞아 발행이 실패했다.

## 도입부 답변 게이트 (2026-09-01, **관찰 모드**)

`AI_OVERVIEW_TARGET_ANSWER` 블록(=AI 검색이 인용해가는 구간)이 제목의 질문에
답하는지 검사한다. 회피 표현이 있거나 제목 내용어를 40% 미만으로 담으면 지적한다.

**지금은 경고만 낸다.** 도입 당일 드라이런에서 정상 도입부("Free ChatGPT ... 500 MB
Library limit")에 off_topic 판정을 냈고, 재시도 중 버려진 초안을 본 것으로 보이나
확증하지 못했다. 검증 안 된 차단 게이트가 발행을 멈추는 위험이 이 게이트가 막으려는
문제보다 크다. **승격 조건**: 실제 발행 몇 회에서 나쁜 글에만 뜨고 정상 글엔 안 뜨는
것을 확인한 뒤 `ANSWER_BLOCK_GATE=block`.

## 주제 선정 1순위 — 매일 실측 질문 발굴 (2026-08-31 도입)

**요미님 지시: "미리 채워놓고 하면 더 나쁜 글이 올라간다."** 실제 운영 경험이고, 아래
"주제 선정 정책"의 *고정 주제 후보 금지, 뱅크는 폴백* 원칙과 같은 말이다. 미리 적어둔
슬롯은 몇 주 전 판단을 굳혀버린다 — 가격·모델명·에러 문구가 바뀌어도 문안은 그대로고,
글쓰는 쪽은 오늘의 근거를 조사하는 대신 정해진 각도에 칸을 채우게 된다.

`services/question_demand_service.py`가 **발행 시점에** 수요를 다시 재서 그날 주제를 고른다.

- **수요 신호**: Stack Exchange API. 유일하게 **질문당 절대 조회수**를 준다. Google
  Autocomplete는 "검색되긴 하는가"만 알려줄 뿐 크기를 모르고, 긴 질문형엔 빈 배열을
  돌려준다(실측). 그래서 크기 판정은 Stack Overflow 조회수로 한다.
- **왜 에러 메시지인가**: 사람이 검색창에 치는 문장이자 LLM에 그대로 복붙해 묻는 문장이고,
  상위가 포럼 스레드·GitHub 이슈뿐이라 답한 문서가 비어 있으며, 뉴스와 달리 1년 뒤에도
  같은 수요가 있다. (실측: OpenAI 429 quota 한 건 488,097 조회)
- **자체 게이트 확인이 핵심**: 슬롯 뱅크였다면 사람이 문안을 손봐 confidence를 올릴 수
  있지만 매일 발굴은 제목을 미리 알 수 없다. 실측에서 발굴 8개 중 2개가 confidence 25로
  기준(80) 미달이었다. 그래서 서비스가 **파이프라인과 같은 GoldenArticlePreviewService로
  미리 판정해 통과하는 후보만 내보낸다** — 안 그러면 글은 다 써놓고
  `article_candidate_not_generated`로 발행만 막히는 조용한 실패가 된다.
- **전부 비치명**: 네트워크·쿼터 실패, 니치 밖 필터링, 원장 중복 제외로 후보가 0개가 되면
  아래 클러스터 → 뉴스 경로로 그대로 내려간다. `ENABLE_QUESTION_DEMAND=false`로 끈다.
  태그는 `QUESTION_DEMAND_TAGS`(기본 `openai-api,google-gemini,langchain,ollama`).
  주의: `gemini-api`는 존재하지 않는 태그라 조용히 0건이 된다 — 실제 태그는 `google-gemini`.
- **조회수만 보고 정하지 않는다**: 벤더 포럼 실측에서 "OPEN LETTER TO SUNDAR PICHAI" 같은
  불만글이 조회수만 높게 올라온 적이 있다. 니치 정규식 + 제외 정규식으로 거른다.
- **탐색 도구**: `tools/demand_mine.py` (사람이 직접 돌려 읽는 read-only 조사 도구.
  Discourse 벤더 포럼·GitHub 이슈까지 함께 본다. 파이프라인엔 연결돼 있지 않다.)

## 주제 클러스터 (2026-08-26 도입, 2026-08-31 폴백으로 강등)

**왜**: GSC 실측에서 사이트맵 32 URL 중 색인 0건, 검색 노출 0이었다. 남은 원인 세 개 중
두 개가 "외부 링크 0 → 권위 0"과 **"주제 분산"**이었다 — 32편이 전부 다른 AI 뉴스라
구글이 이 사이트를 무엇의 전문가로 볼 근거가 없다. 클러스터는 그중 주제 분산을 푼다.

**지금 위치**: 위 매일 발굴이 후보를 못 찾은 날에만 쓰이는 **폴백**이다. 발굴이 성공하면
클러스터는 아예 호출되지 않는다.

- **계획 파일**: `config/clusters.json` (클러스터 2개, 슬롯 15개).
  슬롯의 `search_demand_topic`은 전부 실측으로 고른 검색어이고, 두 번째 클러스터
  `ai_api_errors_decoded`는 슬롯마다 `demand_evidence`(SO 조회수 + 자동완성 제안 수)를 싣는다.
- **진행 판정**: 별도 상태파일 없음. 원장(`data/publish_history.json`)의
  `cluster_key`/`cluster_slot`만 본다. 허브(`is_pillar`)는 자식이 전부 발행된 뒤에 나온다.
- **완주하면 다음 클러스터로 자동 승계**(2026-08-31). 이전엔 active_cluster 하나만 보고
  완주 후 영원히 빈 리스트를 돌려줘서, 다음 날부터 **조용히 100% 뉴스로 되돌아갔다** —
  로그 한 줄만 남기고. 발행 56편의 65%가 뉴스였던 구조적 원인이다.
  `CLUSTER_KEY`로 콕 집어 지정하면 승계하지 않는다.
- **스케줄**: `CLUSTER_WEEKDAYS`(기본 전 요일 `0,1,2,3,4,5,6`, 2026-08-31 변경 —
  이전 `0,2,4,6`) 요일에만 후보를 주입한다. `ENABLE_TOPIC_CLUSTER=false`로 통째로 끈다.
- **골든패턴 회귀 방지**: `tests/test_cluster_service.py`가 **설정의 모든 클러스터**를
  검사한다. 활성 클러스터만 보던 시절, 새로 넣은 슬롯 2개가 confidence 54/79로 발행이
  막히는 상태인데도 테스트는 초록이었다.
- **링크 정책(2026-08-26 요미님 결정)**: **외부 링크는 걸지 않는다. 내부 링크만 쓴다.**
  그래서 내부 링크 배분이 이 사이트가 가진 유일한 구조 신호다. 같은 `cluster_key`에 +20을
  주고(기존 `topic_group` +8은 발행 53편이 전부 ai_work라 죽어 있었다 — 사실상 최근 글 3개
  랜덤 링크였다), 링크 개수도 고정 3개가 아니라 **같은 클러스터의 발행된 형제 수만큼**
  3~6개로 늘어난다(`NewsPipeline._internal_link_limit`). 3개로 고정하면 클러스터가 6편이
  돼도 절반은 아무 데서도 링크받지 못한다. **이미 발행된 라이브 글은 수정하지 않는다** —
  앞으로 쓸 글에만 적용한다(같은 날 확인한 범위 결정).
- **후보 계약**: `source_type`은 일부러 `evergreen_fallback`을 재사용한다. 새 값을 만들면
  신선도·자동발행 허용·골든패턴 분기를 전부 다시 통과시켜야 하고 하나만 놓쳐도
  "글은 썼는데 발행만 안 되는" 조용한 0건이 된다. 클러스터 식별은 `topic_cluster`/
  `cluster_slot` 마커로만 한다.

**도입하며 실제로 밟은 지뢰 3개(같은 함정이 다음 클러스터에도 있다)**
1. `publishable = real_news_publishable`이 evergreen 계열을 통째로 버려서, 뉴스 후보가
   하나라도 있는 날엔 클러스터가 사라졌다 → `_narrow_publishable_to_real_news`가 살려둔다.
2. 점수 부스트로 1등을 만들려 했으나 커뮤니티 뉴스가 수요 가산으로 **100점**까지 올라가
   96점 클러스터를 이겼다 → 순위는 `_choose_selected_candidate`가 확정으로 정한다.
3. 슬롯 7개 중 5개가 골든 패턴 confidence 52(기준 80)라 `article_candidate_not_generated`로
   발행이 막혔다 → 후보 raw에 `sample_titles`를 싣고 슬롯 문안을 실제 글 어휘(free tier,
   pricing, LLM 등)로 고쳤다. `tests/test_cluster_service.py`가 전 슬롯 매칭을 고정한다.

**직접 측정한 표**: 클러스터 글에만 `model_benchmark_service`가 만든 "무료 모델 실측 표"가
붙는다(`data/benchmarks/<date>.json`, 7일 재사용). AI 요약 뉴스는 인용되지 않는다는 진단의
대응이라 1차 자료를 싣는 것이다. 1회 측정을 벤치마크라고 부르지 않고, 실패한 모델과
라우팅된 실제 모델명을 표에 그대로 남긴다. 측정이 전멸하면 표를 아예 붙이지 않는다
(추정치로 칸을 채우지 않는다). 표가 발행을 막는 일은 없다.

## 주제 선정 정책 (2026-07-24 확정)

- **고정 주제 후보 금지**: 매 실행마다 신선 발굴(뉴스 RSS/Exa/커뮤니티 언급량/실측
  검색수요)로 새 AI·이슈 AI 후보를 찾는 것이 1순위. 에버그린 뱅크는 신선 후보가
  전멸했을 때의 폴백일 뿐이다 (`ALLOW_EVERGREEN_AUTO_PUBLISH=true`는 그 폴백의
  자동발행 허용이지 우선순위 역전이 아님).
- **중복 금지 창**: 주제 dedup `DEDUP_DAYS=7` (요구 최소치 3일보다 강함) + 같은 회사
  엔티티 쿨다운 3일(PR #57). 에버그린 폴백도 소프트 엔티티 다양성 랭킹으로 직전에
  다룬 AI와 다른 AI를 우선한다.
- **품질 우선**: 발행 게이트(구체성/원문보존/헤지 포화/가격표/제목-본문 정합 등)를
  통과하지 못하면 후보를 최대 `NEWS_MAX_PUBLISH_ATTEMPTS=12`개까지 갈아끼우고,
  그래도 없으면 그날 발행을 건너뛴다 — 물량보다 품질.

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
