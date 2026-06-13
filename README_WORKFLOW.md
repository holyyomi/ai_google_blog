# README_WORKFLOW

## 목적

현재 운영 원칙은 세 가지다.

1. 실제 기사 3건 미만이면 주제 생성 중단
2. QA가 PASS가 아니면 자동 발행 금지
3. 실패 원인은 반드시 디버그 가능해야 함

## Source Discovery Debug

이번 단계에서 가장 중요한 것은 `source_insufficient`가 왜 발생했는지 바로 보이는 것이다.

Streamlit과 SQLite에는 아래 정보가 저장되고 노출된다.

- `selected_pillar`
- `attempted_strategy_type`
- `search_queries_used`
- `feed/source URLs called`
- 각 source fetch 성공/실패
- response length
- parse status
- parse count
- raw candidate count
- parsed candidate count
- filtered candidate count
- reject reasons summary
- final failure reason
- final discovery status

운영자가 확인하는 순서:

1. provider가 실제로 로드됐는지
2. fetch 단계에서 0건인지
3. parse count가 0인지
4. filter 단계에서 무엇이 탈락했는지
5. 최종적으로 기사 수 부족인지, 도메인 다양성 부족인지

## Source Provider 확장

`config/monetization_topic_sources.json`은 이제 pillar 기준으로 source를 관리한다.

- `search_queries_ko[]`
- `search_queries_en[]`
- `rss_sources[]`
- `official_sources[]`
- `evergreen_sources[]`

지원 provider 타입:

- `google_news_search_rss`
- `rss_feed`
- `official_blog`
- `official_newsroom`
- `evergreen_source`

## TOP5 전략 분리

TOP5는 같은 수집기를 공유하지 않는다.

- `매일 새로운 부업 해부`: `hybrid_news_search`
- `한국뉴스 기반 관심 한국주식 해설`: `news_driven`
- `AI 부업 / 온라인 수익화 실전`: `hybrid_news_search + official_source_driven`
- `부업 세금 / N잡 세금`: `evergreen_search + official_source_driven`
- `한국주식 초보 가이드`: `evergreen_search`

각 pillar 설정에는 아래가 들어간다.

- `strategy_types`
- `provider_priority`
- `search_queries_ko`
- `search_queries_en`
- `rss_sources`
- `official_sources`
- `evergreen_sources`

UI에서는 선택 결과와 함께 아래를 확인한다.

- `strategy_type`
- `provider_mix`
- `query_group`
- `retry_count`
- `retry_path`
- `fallback_strategy_used`
- `fallback_pillar_used`
- `final_selected_queries`

## Retry / Re-discovery Loop

source discovery媛 泥?踰덉㎏ ?ㅽ뙣?섎㈃ 洹몃깷 醫낅즺?섏? ?딆퀬 ?꾨옒 ?쒖꽌濡??ㅽ떆???쒕룄?쒕떎.

1. 媛숈? pillar ?댁뿉??query expansion
2. 媛숈? pillar ?댁뿉??provider mix expansion
3. fallback pillar濡??꾪솚
4. 理쒖쥌 evergreen fallback

query expansion? ?숈쓽???좎? 寃??, ?깆? 寃??, ?쎈? 寃??, ?곷Ц 蹂댁“ keyword瑜?醫낱빀?쒕떎.

SQLite? ?꾨옒 ?꾨뱶瑜???ν븳??.

- `retry_count`
- `retry_path`
- `fallback_strategy_used`
- `fallback_pillar_used`
- `discovery_attempts_json`

UI `Source Discovery Debug`?먯꽌 ?꾨옒瑜?諛붾줈 ?뺤씤?쒕떎.

- retry count / retry reason
- fallback path
- final selected strategy / pillar / queries
- 媛? retry attempt raw/parsed/filtered count

## Article Pack Handoff

二쇱젣 ?좏깮???깃났?섎㈃ 肄섑뀗痢??앹꽦 ?④퀎濡??⑥닚 topic臾몄옄?댁? ?꾨땲??`article pack`?쇰줈 ?꾨꽆湲덈떎.

- `selected_pillar`
- `selected_topic`
- `why_selected`
- `source_articles[]`
- `source_domains[]`
- `source_count`
- `keyword_set`
- `search_intent_guess`
- `source_consensus`
- `source_differences`
- `hard_facts`
- `reader_relevance`
- `title_candidates`
- `title_candidate_types`

source article 카드?먯꽌??紐⑹젣, ?꾨찓??, ?쒖쨷 ?붿빟, ?좏깮 湲곗뿬 ?ъ쑀, 最新/??湲곕낯 ?좊?瑜?媛숈씠 蹂댁씠寃??좎?

brief ?앹꽦? `selected_topic`留?諛쏆? ?딆퀬 article pack?먯꽌 `search_intent_guess`, `hard_facts`, `source_consensus`, `source_differences`, `reader_relevance`瑜?癒쇱? ?ъ슜?쒕떎.

Google News 검색형 RSS 형식:

- `https://news.google.com/rss/search?q=QUERY&hl=ko&gl=KR&ceid=KR:ko`
- 영문 쿼리는 `hl=en-US&gl=US&ceid=US:en`

운영 기본 임계치:

- 기사 3개 이상
- 도메인 2개 이상

디버그/테스트 모드:

- 환경변수 `BLOG_DISCOVERY_TEST_MODE=1`
- 기사 2개 이상
- 도메인 1개 이상

## 저장 필드

`blog_work_items`에 아래 필드를 저장한다.

- `discovery_debug_json`
- `raw_candidate_count`
- `parsed_candidate_count`
- `filtered_candidate_count`
- `reject_reason_summary`
- `final_discovery_status`
- `generated_image_status`
- `image_error_message`
- `final_image_url`
- `qa_result`
- `qa_issues`
- `source_quality_status`
- `publish_block_reason`
- `approval_required`

## 이미지 처리

정상 흐름:

- provider 응답 구조 확인
- `b64_json` 또는 URL 존재 확인
- 업로드 응답 확인
- 최종 공개 URL 검증

실패 흐름:

- 이미지 생성 실패
- base64 없음
- 업로드 응답 이상
- 공개 URL 검증 실패

이 경우 `allow_publish_without_image=True`이면 브랜딩 fallback 이미지를 사용한다.

- `generated_image_status=fallback_branding_image`
- `image_error_message` 저장
- `final_image_url`은 비울 수 있음
- 로컬 파일 경로는 사용하지 않음

## QA 기준

### PASS

- source article 3개 이상
- placeholder URL 없음
- 제목 후보 5개 중복 없음
- 실행 정보가 충분함
- 과장 표현 없음

### SOFT_FAIL

- 치명적 실패는 아니지만 운영자 확인이 필요한 상태
- UI에서 명시적 승인 후에만 발행 가능

### FAIL / FIX_REQUIRED

아래는 발행 금지:

- 샘플/placeholder 주제
- 기사 3개 미만
- example.com / dummy / sample URL
- 제목 후보 중복
- 실행 정보 부족
- 과장/확정 수익 표현

## 발행 잠금

- `PASS`만 자동 발행 가능
- `SOFT_FAIL`은 수동 승인 필요
- `FAIL`, `FIX_REQUIRED`는 발행 차단
- 발행 직전 sanity check에서 QA, source 품질, final title, 본문 길이, meta description을 다시 확인

## Streamlit 운영 흐름

1. `오늘 주제 찾기`
2. `Source Discovery Debug`로 실패 지점 확인
3. `콘텐츠 생성`
4. `QA 실행`
5. `PASS` 또는 승인된 `SOFT_FAIL`만 `발행`
