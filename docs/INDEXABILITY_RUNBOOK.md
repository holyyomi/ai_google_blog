# Indexability Runbook — 색인/노출 운영 가이드

발행은 됐는데 Google `site:` 검색에 안 잡히고 조회수 0인 문제를 진단·복구하기 위한 운영 문서.
코드가 아니라 **Blogger 대시보드 설정 + Search Console 운영 루틴**이 핵심 레버인 항목을 모았다.

> 진단 도구: `PYTHONPATH=src python tools/indexability_audit.py --recent 8`
> (read-only HTTP GET만 수행. 발행/삭제/수정 없음. 리포트는 `runs/indexability_audit/`에 저장)

---

## 2026-06-13 감사에서 확인된 실제 문제

`tools/indexability_audit.py`로 최근 6개 발행 URL을 라이브 점검한 결과:

| 증상 | 근거 | 원인 분류 |
|------|------|-----------|
| 최근 6개 중 **3개가 404** (발행 후 사라짐) | `ai-today-issue-update-news-e15d18`, `refund-consumer-update-a2c044-news`, `70.html` | 코드/운영 (아래 A) |
| **모든 라이브 글의 head에 `<meta name="description">` 없음** | ps5, 63-cj, 80-10-4 전부 누락 | Blogger 설정 (아래 B) |
| robots `index,follow` 정상, canonical self 정상, noindex 없음 | 라이브 head 확인 | 정상 — 기술 버그 아님 |
| sitemap/feed에는 살아있는 글이 포함됨 | 감사 리포트 | 정상 |
| Google 색인 요청 경로 없음 | IndexNow는 Naver+Bing만 ping | 운영 (아래 C) |

**핵심 결론:** noindex/canonical 같은 기술 색인 버그는 없다. 진짜 원인은
(A) 발행한 글이 자동 삭제돼 404가 되는 것, (B) Blogger 검색설명 설정이 꺼져 head meta가 안 나오는 것,
(C) 새 저품질 블로그라 Google 크롤/색인까지 시간이 걸리는데 색인 요청 루틴이 없다는 것이다.

---

## A. 발행 후 404 — post-publish 자동 삭제 (최우선)

### 메커니즘
`news_pipeline._post_publish_audit()` → `fetch_and_audit_post()`가 발행 직후 라이브 URL을 받아
`post_publish_audit_service.audit_post_html()`로 감사한다. 이때 head에 meta description이 없으면
`missing_meta_description`을 **hard issue**로 올리고 `passed=False`가 되며,
`news_pipeline.py:1606~1609`에서 **방금 발행한 글을 `delete_post`로 삭제**한다.

Blogger는 기본적으로 head meta description을 렌더링하지 않으므로(아래 B),
이 감사는 **정상 글에도 항상 실패**할 수 있고, 삭제가 성공하면 글이 404가 된다.
조회수가 0인 이유는 글이 사람·검색엔진이 보기 전에 사라지기 때문이다.

### 확인 방법
```bash
PYTHONPATH=src python tools/indexability_audit.py --recent 8
# 리포트에서 http_status=404 인 URL이 dead_urls 에 잡힘
```

### 복구 (적용 완료 2026-06-13)
- `services/post_publish_audit_service.py`: `missing_meta_description` /
  `body_only_meta_description`를 hard issue → **warning으로 강등**. meta는 본문이 아니라
  Blogger 설정으로 렌더링되므로 글을 지울 사유가 아니다.
- `pipelines/news_pipeline.py`: `_post_publish_fatal_issues()` 게이트 추가. post-publish
  자동 삭제는 **치명적 이슈일 때만** 발동 — 제목 불일치, AI 주제 누출, 임시 slug 제목 노출,
  라벨 mojibake, title-integrity 위반. 그 외(meta/canonical/answer-engine/cover/slug/sitemap)는
  글을 유지하고 warning 로그만 남긴다.
- 결과: 정상 글이 meta 누락만으로 삭제돼 404가 되는 자기파괴 루프 제거.

---

## B. head meta description 누락 — Blogger 대시보드 설정 (사람이 처리)

### ⚠️ 2026-07-25 정정 — 토글로 해결되지 않는다 (실측)

**아래 "토글만 켜면 된다"는 원래 설명은 틀렸다.** 실측 결과:

1. 요미님이 **"검색 설명 사용" 토글을 ON**으로 확인했고 블로그 단위 검색 설명도
   채워져 있다. 그런데도 라이브 글에 `<meta name="description">`이 **여전히 없다**.
   있는 것은 `og:description` 하나이고, 그 값은 **글마다 동일한 블로그 소개문**이다
   (= 토글/블로그 설명은 블로그 단위 메타에만 관여).
2. **Blogger API v3는 `searchDescription`·`customMetaData`를 저장하지 않는다.**
   테스트 초안에 두 필드를 함께 전송 → INSERT 응답에 두 필드 모두 없음 →
   `view=AUTHOR` 재조회에도 없음 → 라이브 발행글 3건도 전부 `None`.
   즉 `publishing/client.py`가 보내는 값은 조용히 버려진다(코드 정상이 아니었다).

**결론: 자동 발행 경로로는 글별 head meta description을 만들 수 없다.**
Blogspot은 meta description이 없으면 **첫 문단을 SERP 스니펫으로 쓰므로**,
글별 스니펫은 lede로만 제어된다. 그래서
`answer_engine_policy.ensure_answer_engine_optimized_html`의 lede를 주제별 확정
사실(LLM confirmed_facts)로 시작하게 바꿨다 — 이게 유일한 레버다.
(그전에는 lede가 본문 중복 제거로 상투어만 남아 최근 5개 글 중 4개의 스니펫이
같은 문장으로 시작했다.)

남은 개선 여지(미착수, 사람 작업): Blogger 테마 HTML을 편집해 글 페이지에서
`og:description`을 글별 값으로 출력하게 하는 방법. 테마 XML 수정이라 승인 필요.

### (원래 설명 — 참고용, 위 정정이 우선한다)
`publishing/client.py`는 `searchDescription` / `metaDescription` / `customMetaData`를
Blogger API에 전송한다. Blogger는 블로그 단위 설정
**"메타 태그 → 검색 설명 사용(Enable search description)"이 켜져 있을 때만**
head에 `<meta name="description">`를 렌더링한다고 봤으나, 위 실측으로 반증됐다.

1. Blogger 대시보드 → **설정(Settings) → 메타 태그(Meta tags)**
2. **"검색 설명 사용(Enable search description)" 켜기** — 완료(2026-07-25 확인)
3. `tools/indexability_audit.py --recent 4`로 `head_meta_description_present` 확인 시
   여전히 false가 정상이다(API로 설정 불가).

---

## C. Google 색인 운영 루틴 (사람이 처리)

IndexNow(`services/indexnow_client.py`)는 **Naver SearchAdvisor + Bing**에만 ping을 보낸다.
**Google은 IndexNow를 쓰지 않으므로** Google 색인에는 영향이 없다.
일반 블로그 글에 Google Indexing API를 붙이는 것은 정책상 권장되지 않으니
(Indexing API는 JobPosting/BroadcastEvent 전용), Search Console 운영 루틴으로 처리한다.

### 1회 설정
- [ ] Google Search Console에 `holyyomiai.blogspot.com` 속성 등록 + 소유권 확인
- [ ] Sitemaps 메뉴에 `sitemap.xml` 제출 (Blogger는 자동 생성)
- [ ] (선택) Bing Webmaster Tools에도 동일 등록

### 새 글 발행 후 (글당)
- [ ] Search Console **URL 검사(URL Inspection)**에 새 글 URL 입력
- [ ] "색인 생성 요청(Request indexing)" 클릭
- [ ] 며칠 뒤 `site:holyyomiai.blogspot.com <키워드>`로 노출 확인

### 주간 점검
- [ ] Search Console **페이지(색인 생성)** 리포트에서 "크롤링됨 - 현재 색인 안 됨
      (Crawled - currently not indexed)" 항목 확인. 이게 많으면 콘텐츠 차별화 부족 신호.
- [ ] `tools/indexability_audit.py --recent 10` 실행 → 404/누락 조기 발견

### 현실적 기대치
새로 만든 저권위 Blogspot 블로그는 Google이 크롤·색인하기까지 **며칠~수 주**가 걸린다.
URL이 200이고 robots/canonical/sitemap이 정상이어도 즉시 노출되지 않는 것은 정상이다.
A(404)와 B(meta)를 먼저 해결하고, 색인 요청을 꾸준히 하면서 시간을 줘야 한다.

---

## D. slug 품질 (개선 완료 2026-06-13)

- 구 게시물: `70.html`, `80-10-4.html` 같은 숫자형 약한 slug (한글 제목 → Blogger 자동 생성)
- 기존 신규 slug: `*-today-issue-update-news-*` 처럼 generic filler가 키워드를 밀어냄
- 개선(`seo_policy.py`):
  1. `_SLUG_KEYWORD_MAP`에 AI/게임/OTT/IT/업무 한국어→영어 매핑 추가
     (예: 자동화→automation, 출시→launch, 베타→beta, 넷플릭스→netflix)
  2. `_SLUG_GENERIC_TOKENS`(today/issue/update/korea/news/online)를 실제 키워드 뒤로 배치
  3. `_normalize_slug` 길이 컷을 **토큰 경계**로 변경 → `issu`처럼 단어 토막 제거
- 결과 예: `ai-today-issue-update-news` → `chatgpt-ai-automation-productivity-worker`,
  `ps5-today-issue-update-news` → `ps5-game-launch-beta-reveal-today-news`
- 기존 발행 글의 slug는 Blogger에서 사후 변경 불가(변경 시 URL 깨짐)이므로 **신규부터 적용**.

---

## E. 발견 경로 소실 — 오래된 글은 sitemap/feed/홈에서 통째로 사라진다 (2026-08-31)

### 실측
GSC "페이지 색인 생성" 리포트(2026-08-31, 로그인 상태에서 직접 확인):

| 사유 | 개수 |
|------|------|
| 발견됨 - 현재 색인이 생성되지 않음 | 21 |
| 크롤링됨 - 현재 색인이 생성되지 않음 | 5 |
| 리디렉션 오류 | 10 |
| **색인 생성됨** | **0** |

구글이 아는 URL이 36개뿐인데, 원장의 `published: true`는 51개다. 원인은 삭제가 아니라
**밀려남**이었다: `sitemap.xml`(37개), Atom 피드, 홈 최근글, 사이드바 Archive 위젯이
전부 **최근 ~35개만 담는 롤링 윈도우**다. 그 창을 벗어난 글은

- sitemap `in_sitemap=False`
- 피드 `in_feed=False`
- 홈 `linked_from_homepage=False`
- 내부링크도 없음 (내부링크 정책이 최근 글끼리만 연결)

즉 **발견 경로가 0**이 된다. 창 안에 있을 때 크롤되지 못했으면 영영 재발견되지 않는다.
`tools/indexability_audit.py`가 이 세 필드를 이미 찍어주니 판정은 그걸로 한다.

### 조치 (완료)
1. `scripts/create_all_articles_page.py` → Blogger Page "All Articles" 생성.
   살아있는 글 전부를 월별로 잇는 **내부링크 인덱스**. 외부링크 금지 정책과 무관하게
   안전하다(전부 내부링크). 새 글이 쌓이면 `--publish`로 다시 돌려 갱신한다(같은 제목이면
   PUT으로 덮어쓴다 — 중복 생성 안 됨).
2. 이미 상단 메뉴에 있는 **About 페이지에서 "All Articles"로 링크** → 홈에서 2클릭 안에
   전체 글에 닿는다.
3. `docs/sitemap-full.xml`(전체 URL) → GitHub Pages로 호스팅하고 Blogger **커스텀
   robots.txt**에 `Sitemap:` 한 줄로 등록. 교차 도메인 sitemap이라 robots.txt 선언이
   필수다(GSC 폼은 같은 도메인 파일만 받는다).

### ⚠️ 되풀이하면 안 되는 함정
- **GitHub Pages 소스를 `/docs`로 켜면 이 폴더의 내부 문서 `*.md`가 전부 공개 배포된다**
  (2026-08-31 실측: RUNBOOK/PRD/CONTENT_STRATEGY_LOCK 전부 HTTP 200). 프로젝트 페이지
  (`/<repo>/` 경로)는 **robots.txt로 막을 수 없다** — robots.txt는 도메인 루트에서만
  유효하고 그건 별도 저장소다. 그래서 `docs/_config.yml`의 `exclude: ["*.md"]`로
  빌드에서 제외한다. 이 파일을 지우면 내부 문서가 다시 공개된다.
- sitemap URL은 이미 라이브 robots.txt에 박혀 있다. 경로를 바꾸면 **robots.txt도 같이
  고쳐야** 한다(Blogger 대시보드 → 설정 → 크롤러 및 색인 생성, 사람 작업).

## F. 발행 후 자동삭제 — 이미 해소됨 (2026-08-31 재확인)

A절의 자멸 루프는 **끝났다**. 원장 실측:

- 2026-07-03~07-18 글: `audit_passed=False` + `og_description_not_post_specific` → **17개 전부 404**
- 2026-07-20 이후: `audit_passed=True` → 전부 생존
- 2026-08-30 글: `audit_passed=False`인데 **살아있음** ← 현재 동작의 증거

현재 `_POST_PUBLISH_FATAL_ISSUES`에 `og_description_not_post_specific`가 없어서, 감사
실패가 더는 삭제로 이어지지 않는다. **죽은 17개는 과거 피해자이고 신규 글은 안전하다.**
그 17개는 `scripts/create_all_articles_page.py`의 `KNOWN_DEAD`에 박아 인덱스에서 제외했다.

---

## 체크리스트 요약 (live publish 전/후)

발행 전(자동 파이프라인 검증):
- [ ] `python -m compileall src`
- [ ] 관련 pytest 통과
- [ ] `tools/indexability_audit.py`로 최근 글 404/meta 누락 0건

사람이 1회 처리:
- [ ] Blogger "검색 설명 사용" 토글 ON (B)
- [ ] Search Console 속성 등록 + sitemap 제출 (C)
- [x] Blogger 커스텀 robots.txt에 `sitemap-full.xml` 등록 (E, 2026-08-31 완료)

주기적으로(월 1회 정도):
- [ ] `PYTHONPATH=src python scripts/create_all_articles_page.py --publish` — 새 글 반영
- [ ] `sitemap-full.xml` 재생성 후 푸시 (죽은 URL이 새로 생겼는지 audit으로 먼저 확인)

코드 수정(승인 후):
- [x] post-publish 자동삭제를 meta 누락으로 트리거하지 않도록 완화 (A — F절 참고, 해소됨)
