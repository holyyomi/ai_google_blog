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

### 원인
`publishing/client.py`는 `searchDescription` / `metaDescription` / `customMetaData`를
**정상적으로 Blogger API에 전송**한다(코드 정상). 그러나 Blogger는 블로그 단위 설정
**"메타 태그 → 검색 설명 사용(Enable search description)"이 켜져 있을 때만**
head에 `<meta name="description">`를 렌더링한다. 이 토글이 꺼져 있으면 API로 보낸 설명이 무시된다.

### 사람이 해야 할 일 (1회)
1. Blogger 대시보드 → **설정(Settings) → 메타 태그(Meta tags)**
2. **"검색 설명 사용(Enable search description)" 켜기**
3. 켠 뒤 새로 발행되는 글부터 head meta description이 나온다. 기존 글은 글 편집 화면
   오른쪽 **검색 설명(Search description)** 칸이 채워져 있으면 자동 반영된다.
4. 켠 직후 `tools/indexability_audit.py --recent 4`로 `head_meta_description_present=true` 확인.

> 이 토글을 켜면 A의 자동삭제 문제도 함께 완화된다(감사가 meta를 찾을 수 있게 되므로).
> 단, 발행 직후 전파 지연으로 감사 시점에 아직 안 보일 수 있으니 A의 코드 완화도 병행 권장.

---

## C. Google 색인 운영 루틴 (사람이 처리)

IndexNow(`services/indexnow_client.py`)는 **Naver SearchAdvisor + Bing**에만 ping을 보낸다.
**Google은 IndexNow를 쓰지 않으므로** Google 색인에는 영향이 없다.
일반 블로그 글에 Google Indexing API를 붙이는 것은 정책상 권장되지 않으니
(Indexing API는 JobPosting/BroadcastEvent 전용), Search Console 운영 루틴으로 처리한다.

### 1회 설정
- [ ] Google Search Console에 `holyeverymoments.blogspot.com` 속성 등록 + 소유권 확인
- [ ] Sitemaps 메뉴에 `sitemap.xml` 제출 (Blogger는 자동 생성)
- [ ] (선택) Bing Webmaster Tools에도 동일 등록

### 새 글 발행 후 (글당)
- [ ] Search Console **URL 검사(URL Inspection)**에 새 글 URL 입력
- [ ] "색인 생성 요청(Request indexing)" 클릭
- [ ] 며칠 뒤 `site:holyeverymoments.blogspot.com <키워드>`로 노출 확인

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

## 체크리스트 요약 (live publish 전/후)

발행 전(자동 파이프라인 검증):
- [ ] `python -m compileall src`
- [ ] 관련 pytest 통과
- [ ] `tools/indexability_audit.py`로 최근 글 404/meta 누락 0건

사람이 1회 처리:
- [ ] Blogger "검색 설명 사용" 토글 ON (B)
- [ ] Search Console 속성 등록 + sitemap 제출 (C)

코드 수정(승인 후):
- [ ] post-publish 자동삭제를 meta 누락으로 트리거하지 않도록 완화 (A)
