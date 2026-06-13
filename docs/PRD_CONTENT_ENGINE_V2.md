# PRD: Content Engine V2 — 골든 패턴 기반 고품질 초안 생성 시스템

**버전**: 1.0.0
**작성일**: 2026-05-03
**작성자**: 요미 (holyyomi)
**브랜치**: improve-news-engine-v2
**상태**: Phase 1 완료 / Phase 2 설계 단계

---

## 1. 문제 정의

### 현상

기존 뉴스 파이프라인은 기술적으로 동작하지만, 생성되는 콘텐츠가 **읽을 만한 글이 아니다**.

- 제목은 다르지만 본문 구조가 거의 동일하다
- content_type별 고정 문구("이 글에서 알아볼 내용은…")가 토픽과 무관하게 삽입된다
- 독자가 실제로 알고 싶은 것이 아닌, 시스템이 채우기 쉬운 것을 채운다
- 결과적으로 Google AdSense 심사 및 SEO 기준을 충족하지 못하는 수준의 글이 발행된다

### 근본 원인

> 현재 시스템은 **"박스 채우기"** 구조다.  
> content_type → HTML 섹션 매핑 → 섹션별 기본 문구 삽입 → 완성.  
> topic이 무엇이든 구조와 문구가 거의 같다.

---

## 2. 기존 시스템의 한계

| 구분 | 한계 |
|------|------|
| content_type 기본 문구 | topic과 무관한 generic string이 본문의 30~50%를 차지 |
| 슬롯 채우기 전략 없음 | "오늘의 이슈는 X입니다" → topic만 교체, 분석 없음 |
| 품질 게이트 미흡 | total_score >= 75 통과 = publish 허용 → 실제 글 품질과 무관 |
| viral_issue_decode 라우팅 버그 | "ai" in lower가 entertainment 토픽을 AI 기사로 잘못 분류 |
| 패턴 매칭 없음 | topic이 어느 golden pattern에 가장 가까운지 판단하는 로직 없음 |
| human review 없음 | 모든 글이 자동 발행 → 품질 하한선 없음 |

---

## 3. 살릴 것 / 버릴 것

### 살릴 것

- 뉴스 수집 + 스코어링 파이프라인 (news_topic_service, news_scoring_service)
- taxonomy 기반 content_type / topic_group 분류 체계
- viral_issue_decode 분류 로직 (45B에서 구현)
- 품질 게이트 기본 구조 (news_quality_gate.py)
- 라벨/해시태그 생성 (news_label_service.py)
- 요미 에디토리얼 보이스 HTML 블록 (yomi-judgment-box, misconception-box, quick-decision-table)
- evergreen 폴백 메커니즘 (주제 공급이 없을 때 안전망)

### 버릴 것

- content_type 키로 매핑된 **모든 기본 문구 (default strings)**
- HTML 섹션 내 topic-agnostic generic sentences
- "이 글에서는 ~에 대해 알아보겠습니다" 류의 도입 패턴
- total_score >= 75 단독 publish 허용 기준
- human_review 없는 자동 발행 경로

---

## 4. 새 시스템 목표

### 핵심 전환

> **자동발행기 → 고품질 초안 생성기 + 게이팅 시스템**

| 기존 | V2 목표 |
|------|---------|
| topic 들어오면 자동 발행 | topic → 패턴 매칭 → 슬롯 채우기 → 게이트 통과 → human 발행 |
| HTML 박스 채우기 | golden pattern 기반 슬롯 채우기 |
| 점수 >= 75 = publish | pattern_confidence >= 80 + slot_fill_rate >= 0.8 + human 승인 |
| content_type default 문구 | topic-specific 슬롯 컨텐츠 |
| 모든 topic 자동 처리 | 패턴 매칭 실패 시 발행 보류 (보류 큐 저장) |

### 품질 기준 (V2)

1. 독자가 실제 상황에서 공감할 수 있는 후킹 오프닝
2. 요미의 판단이 topic-specific 관점으로 채워짐
3. 착각 vs 실제 표가 해당 topic의 실제 오해를 반영
4. 30초 판단표가 독자 행동을 즉시 안내
5. 행동 3개가 "지금 바로 실행 가능"한 것
6. FAQ가 실제 검색 질문 기반

---

## 5. 콘텐츠 생성 단계 (V2 파이프라인)

```
[뉴스 수집]
    ↓
[스코어링 + content_type 분류]
    ↓
[golden_pattern_service: topic → pattern 매칭]
    ↓ 매칭 성공 (confidence >= 80)
[slot_filler_service: 슬롯별 topic-specific 컨텐츠 생성]
    ↓
[news_quality_gate: pattern_confidence + slot_fill_rate + risk_flags 검사]
    ↓ 게이트 통과
[초안 저장 (dry_run 모드)]
    ↓
[human_review: 수동 확인 후 publish 명령]
    ↓
[Blogspot 발행]

※ 매칭 실패 또는 게이트 미통과 → pending_queue 저장 → 보류 보고
```

---

## 6. 골든 패턴 매칭 방식

### 매칭 알고리즘 (golden_pattern_service.py)

```python
def match_pattern(topic: str, content_type: str, topic_group: str) -> PatternMatchResult:
    """
    1. content_type 기반 후보 패턴 필터링
    2. match_keywords 키워드 점수 계산
    3. match_negative 페널티 적용
    4. confidence score 반환 (0-100)
    5. confidence < 80 → NO_MATCH (발행 보류)
    """
```

### 매칭 점수 계산

- `+10점` per match_keyword 히트 (상한 100점)
- `-20점` per match_negative 히트
- `+15점` content_type 정확 일치
- `+10점` topic_group 정확 일치
- 최종 score >= 80 → 매칭 성공

### patterns.json 구조

- `golden_samples/patterns.json` 참조
- 3개 패턴 정의: `tax_refund_hometax_check`, `viral_ott_reaction_decode`, `ai_work_time_savings`
- 각 패턴: 9개 required_slots + optional_slots + quality_checks + banned_default_phrases + publish_policy

---

## 7. 슬롯 채우기 방식 (slot_filler_service.py)

### 슬롯 채우기 원칙

1. **topic-specific first**: 슬롯의 내용은 반드시 해당 topic에서 파생되어야 한다
2. **default 금지**: content_type 키로 매핑된 generic string 사용 불가
3. **검증 포함**: 슬롯 채운 뒤 banned_default_phrases 포함 여부 자동 검사

### 슬롯별 채우기 전략

| 슬롯 | 채우기 방식 |
|------|-----------|
| hook_opening | topic의 실제 발생 상황 → 독자 공감 포인트 추출 → 5문장 이내 |
| yomi_judgment | "요미 판단: " 마커 + topic-specific 결론 + 행동 촉구 |
| misconceptions | topic 관련 실제 오해 3개 + 사실 기반 반박 (2열 표) |
| real_criterion | 패턴의 slot_filling_strategy.real_criterion 지침 따름 |
| quick_decision_table | 독자 상황 매핑 표 — topic의 상황 분기 기반 |
| actions | 지금 바로 할 수 있는 행동 3개 — 구체 경로 포함 |
| faq | 실제 검색 질문 3개 기반 — topic 관련 FAQ |
| hashtags | must_include_one_of 조건 충족 + banned_tags 미포함 |
| internal_links | 동일 독자가 다음에 읽을 법한 주제 2개 이상 |

### slot_fill_rate 계산

```
slot_fill_rate = (채워진 슬롯 수) / (required_slots 총수)
채워진 슬롯 = 내용이 있고 + banned_default_phrases 미포함
```

---

## 8. viral_issue_decode 처리 방식

### 특성

- 토픽: 연예·스포츠·OTT 이슈 반응 분석
- 목표: "왜 반응이 갈렸는가" — 단순 요약이 아닌 관점 해석
- 위험: 루머·사생활 침해·단정 표현

### 처리 흐름

```
topic 입력
    ↓
viral_safety_score 계산 (VIRAL_RISK_KEYWORDS 기반)
    ↓ score < 3 (위험 낮음)
pattern: viral_ott_reaction_decode (또는 유사 패턴)
    ↓
슬롯 채우기:
  - misconceptions: 순위/반응 오해 기반
  - real_criterion: 반응 갈리는 원인 3가지 관점
  - yomi_judgment: 단정 피하기 + 재해석 관점
    ↓
quality_gate:
  - no_specific_work_defamation: true
  - no_specific_person_defamation: true
  - banned_default_phrases 검사
```

### viral 발행 보류 기준

- `viral_safety_score >= 3` → 루머/사생활 위험 → 즉시 보류
- `yomi_judgment_avoids_definitive_verdict == false` → 보류
- 특정 인물 명예훼손성 표현 감지 → 보류

---

## 9. evergreen 처리 방식

### 역할

evergreen은 뉴스 공급이 없을 때의 **안전망**이다. V2에서도 유지하되 품질 기준 동일 적용.

### V2 evergreen 정책

- evergreen 토픽도 golden_pattern_service 매칭 필수
- 매칭 실패 시 발행 불가 (기존처럼 자동 발행 금지)
- `FORCE_EVERGREEN_FALLBACK=true` 시: dry_run 모드 강제 적용
- evergreen 발행은 human_publish_required 동일 적용

### 우선순위

```
실시간 뉴스 viral → 실시간 뉴스 일반 → evergreen (매칭 성공 시만)
```

---

## 10. 품질 게이트 재설계

### 기존 게이트 (V1)

```python
if total_score >= 75:
    publish_allowed = True
```

### V2 게이트 (다중 조건 AND)

```python
publish_allowed = (
    pattern_match_confidence >= 80      # 패턴 매칭 성공
    and slot_fill_rate >= 0.8           # 슬롯 80% 이상 채워짐
    and not default_phrase_detected     # 기본 문구 없음
    and not risk_flags                  # 위험 플래그 없음
    and human_publish_required == True  # human 발행 필수
)
```

### 게이트 실패 처리

| 실패 조건 | 처리 |
|----------|------|
| pattern_confidence < 80 | `pending_queue` 저장 + 보류 사유 기록 |
| slot_fill_rate < 0.8 | 미채워진 슬롯 목록 로그 + 보류 |
| default_phrase_detected | 감지된 문구 로그 + 보류 |
| risk_flags 있음 | 위험 항목 로그 + 즉시 보류 |

---

## 11. 발행 보류 기준

아래 조건 중 하나라도 해당되면 자동 발행 불가, `pending_queue`에 저장:

| 번호 | 보류 조건 | 우선순위 |
|------|----------|---------|
| 1 | `pattern_match_confidence < 80` | HIGH |
| 2 | `slot_fill_rate < 0.8` | HIGH |
| 3 | `default_phrase_detected == true` | HIGH |
| 4 | `risk_flags` 비어있지 않음 | CRITICAL |
| 5 | `viral_safety_score >= 3` | CRITICAL |
| 6 | `human_publish_required == true` (모든 케이스) | REQUIRED |
| 7 | `yomi_judgment` 슬롯 미채워짐 | HIGH |
| 8 | `hook_opening`이 금지 오프닝 패턴으로 시작 | MEDIUM |

---

## 12. Phase 2 코드 작업 계획

### 작업 원칙

- Phase 2 전체 기간: `DRY_RUN=true` 강제 운영 (실제 Blogspot 발행 없음)
- 각 파일 수정 전 현재 코드 읽기 → 영향 범위 분석 → 승인 후 실행

### 작업 목록

#### Step 2-1: golden_pattern_service.py 신규 생성

```
파일: src/blogspot_automation/services/golden_pattern_service.py
역할: patterns.json 로드 + topic/content_type/topic_group → 패턴 매칭
핵심 함수:
  - load_patterns() -> list[PatternConfig]
  - match_pattern(topic, content_type, topic_group) -> PatternMatchResult
  - calculate_confidence(topic, pattern) -> float
출력: PatternMatchResult(pattern_id, confidence, matched_keywords, negative_hits)
```

#### Step 2-2: slot_filler_service.py 신규 생성

```
파일: src/blogspot_automation/services/slot_filler_service.py
역할: PatternMatchResult + topic → 슬롯별 topic-specific 컨텐츠 생성
핵심 함수:
  - fill_slots(topic, pattern_match, raw_article) -> FilledSlots
  - validate_slots(slots, pattern) -> SlotValidationResult
  - calculate_fill_rate(slots, pattern) -> float
출력: FilledSlots(slot_name -> content, fill_rate, validation_errors)
```

#### Step 2-3: contrarian_content_service.py 수정

```
변경 사항:
  - content_type 키 기반 default string 제거
  - FilledSlots 객체를 HTML로 렌더링하는 render_from_slots() 메서드 추가
  - 기존 _generate_*_html() 메서드는 fallback으로 유지 (dry_run 전용)
```

#### Step 2-4: news_quality_gate.py 수정

```
변경 사항:
  - pattern_match_confidence 체크 추가
  - slot_fill_rate 체크 추가
  - default_phrase_detected 체크 추가 (banned_default_phrases 목록 기반)
  - V2 게이트 조건 AND 로직 구현
  - pending_queue 저장 로직 추가
```

#### Step 2-5: news_pipeline.py 수정

```
변경 사항:
  - golden_pattern_service 호출 추가 (스코어링 이후)
  - slot_filler_service 호출 추가 (패턴 매칭 이후)
  - DRY_RUN=true 시 pending_queue 저장으로 라우팅
  - human_publish_required 플래그 처리 추가
```

### Phase 2 운영 모드

```
DRY_RUN=true (강제):
  - 뉴스 수집 → 스코어링 → 패턴 매칭 → 슬롯 채우기 → 게이트 검사
  - 결과를 runs/dry_run_YYYYMMDD_HHMMSS.json으로 저장
  - Blogspot 발행 없음

DRY_RUN=false (human 명령 시만):
  - 게이트 통과 + human 승인 후에만 발행
```

---

## 13. 다음 Claude/Codex 작업 프롬프트

### Phase 2 시작 시 사용할 프롬프트

```
Context:
- 프로젝트: Blogspot 자동화 (요미 브랜드, 한국어 생활정보 블로그)
- 브랜치: improve-news-engine-v2
- 현재 상태: Phase 1 완료 (golden_samples/ + patterns.json + PRD_CONTENT_ENGINE_V2.md)

지금 해야 할 작업:
golden_pattern_service.py를 신규 생성하세요.

파일 위치: src/blogspot_automation/services/golden_pattern_service.py

요구사항:
1. golden_samples/patterns.json을 로드해서 패턴 목록을 반환하는 load_patterns()
2. topic + content_type + topic_group을 입력받아 confidence score를 계산하는 match_pattern()
3. confidence >= 80이면 매칭 성공, 미만이면 NO_MATCH 반환
4. match_keywords 히트 시 +10점, match_negative 히트 시 -20점, content_type 일치 시 +15점, topic_group 일치 시 +10점
5. 타입 힌트 필수, 로깅 포함, 재시도 없음 (단순 매칭)

참고 파일:
- golden_samples/patterns.json (패턴 정의)
- src/blogspot_automation/services/news_taxonomy.py (content_type, topic_group 상수)
- PRD_CONTENT_ENGINE_V2.md Section 6 (매칭 알고리즘)

제약:
- 다른 파일 수정 금지
- 새 패키지 설치 금지
- DRY_RUN 플래그 처리 불필요 (이 파일은 순수 매칭 로직만)
```

### Phase 2 검증 프롬프트 (golden_pattern_service 완성 후)

```
다음을 검증하세요:
1. python -c "from src.blogspot_automation.services.golden_pattern_service import GoldenPatternService; ..."로 임포트 성공 확인
2. match_pattern("홈택스 환급금 조회", "tax_refund", "policy_benefit") → confidence >= 80 확인
3. match_pattern("넷플릭스 드라마 반응", "viral_issue_decode", "ott_platform") → confidence >= 80 확인
4. match_pattern("지원금 신청 방법", "policy_deadline", "policy_benefit") → NO_MATCH (confidence < 80) 확인
5. 로그 출력 형식 확인: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
```

---

## Appendix: Phase 1 산출물 목록

| 파일 | 설명 |
|------|------|
| `golden_samples/tax_refund_hometax_check.md` | tax_refund 타입 골든 샘플 |
| `golden_samples/viral_ott_reaction_decode.md` | viral_issue_decode 타입 골든 샘플 |
| `golden_samples/ai_work_time_savings.md` | ai_work_tip 타입 골든 샘플 |
| `golden_samples/patterns.json` | 패턴 매칭 품질 기준 JSON (3패턴, 9슬롯, publish_policy) |
| `PRD_CONTENT_ENGINE_V2.md` | 이 문서 |

---

*이 PRD는 살아있는 문서입니다. Phase 2 진행 중 변경 사항은 이 문서에 반영합니다.*
