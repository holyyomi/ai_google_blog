"""회사/소재 쿨다운(같은 주체 기본 3일 1회) 테스트.

배경: 서로 다른 뉴스가 같은 회사(네이버/구글/OpenAI 등)로 며칠 연속 발행되는
"주제 모양 중복"을 막는다. 제목·주제가 조금씩 달라 키워드 겹침 규칙을
빠져나가더라도, 같은 주체면 쿨다운 창 안에서는 재발행을 차단한다.
"""
from __future__ import annotations

from datetime import date, timedelta

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _scored(topic: str, *, summary: str = "", raw: dict | None = None) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(
            topic=topic,
            category="ai",
            summary=summary,
            raw=raw or {},
        ),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="",
    )


def _published(topic: str, *, days_ago: int = 0, **extra) -> dict:
    record = {
        "date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "status": "published",
        "published": True,
        "selected_topic": topic,
    }
    record.update(extra)
    return record


def test_same_company_within_cooldown_is_duplicate() -> None:
    # 다른 네이버 뉴스여도 7일 안이면 중복 처리.
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored("네이버 AI 브리핑 광고 상품 정식 출시")
    assert dedup.is_duplicate(
        candidate, [_published("네이버 AI 검색 탭 5000만 개방", days_ago=1)]
    )


def test_clova_and_naver_treated_as_same_entity() -> None:
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored("클로바X 종료 후 네이버 검색은 어떻게 바뀌나")
    assert dedup.is_duplicate(candidate, [_published("네이버 AI 탭 설정 3가지", days_ago=2)])


def test_different_company_not_blocked_by_entity_rule() -> None:
    # 구글 발행 뒤 OpenAI 후보 — 다른 주체이므로 엔티티 쿨다운은 통과.
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored("ChatGPT 새 음성 모드로 회의록 정리하는 법")
    assert not dedup.is_duplicate(
        candidate, [_published("구글 제미나이 지도 기능 켜기 전 설정", days_ago=1)]
    )


def test_same_company_outside_cooldown_allowed() -> None:
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored("네이버 AI 브리핑 광고 상품 정식 출시")
    assert not dedup.is_duplicate(
        candidate, [_published("네이버 AI 검색 탭 5000만 개방", days_ago=10)]
    )


def test_entity_cooldown_ignores_unpublished_attempt() -> None:
    # 발행 성공만 근거로 삼는다 — 보류/차단 시도는 쿨다운을 걸지 않는다.
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored("네이버 AI 브리핑 광고 상품 정식 출시")
    held = {
        "date": date.today().isoformat(),
        "status": "blocked_by_quality_gate",
        "published": False,
        "selected_topic": "네이버 AI 검색 탭 5000만 개방",
    }
    assert not dedup.is_duplicate(candidate, [held])


def test_entity_cooldown_zero_disables_entity_rule() -> None:
    # 키워드 겹침이 2개 미만이라 엔티티 규칙만이 잡을 수 있는 쌍.
    # entity_cooldown_days=0이면 엔티티 규칙이 꺼져 통과해야 한다.
    candidate = _scored("클로바X 종료 후 검색 방향")
    history = [_published("네이버 지도 리뷰 개편", days_ago=1)]
    assert TopicDedupService(dedup_days=7, entity_cooldown_days=0).is_duplicate(
        candidate, history
    ) is False
    # 같은 쌍이라도 엔티티 규칙이 켜지면(둘 다 naver) 중복으로 잡힌다.
    assert TopicDedupService(dedup_days=7, entity_cooldown_days=7).is_duplicate(
        candidate, history
    ) is True


def test_summary_competitor_mention_does_not_trigger_entity() -> None:
    # 요약에 경쟁사가 언급돼도 '주제' 엔티티만 본다.
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored(
        "OpenAI ChatGPT 새 요금제 정리",
        summary="구글 제미나이와 비교하면 네이버 클로바보다 저렴하다",
    )
    assert not dedup.is_duplicate(
        candidate, [_published("구글 제미나이 지도 설정 3가지", days_ago=1)]
    )


def test_metabus_token_not_matched_as_meta() -> None:
    # '메타버스'는 토큰 경계 매칭이라 meta 엔티티로 잡히지 않는다.
    dedup = TopicDedupService()
    assert dedup.extract_entities("메타버스 부동산 투자 열풍") == set()
    assert dedup.extract_entities("메타 라마 3 공개") == {"meta"}


def test_no_entity_topic_falls_back_to_keyword_rule() -> None:
    # 브랜드가 없는 정책 주제는 엔티티 규칙과 무관 — 기존 키워드 규칙만 적용.
    dedup = TopicDedupService(dedup_days=7)
    candidate = _scored("고유가 피해지원금 지급일과 신청방법 정리")
    assert not dedup.is_duplicate(
        candidate, [_published("청년 운전면허 지원금 신청방법과 대상 조건", days_ago=1)]
    )


def test_default_entity_cooldown_is_3_days(monkeypatch) -> None:
    """2026-07-22: 기본 쿨다운 7→3일 — 4일 전 같은 회사 글은 더 이상 차단하지 않는다."""
    monkeypatch.delenv("ENTITY_COOLDOWN_DAYS", raising=False)
    dedup = TopicDedupService(dedup_days=7)
    assert dedup.entity_cooldown_days == 3
    candidate = _scored("네이버 AI 브리핑 광고 상품 정식 출시")
    # 4일 전(창 밖) → 엔티티 쿨다운으로는 차단 안 됨. (키워드 겹침 회피를 위해
    # 과거 레코드는 공유 키워드가 '네이버' 하나뿐인 제목을 쓴다.)
    assert not dedup.is_duplicate(
        candidate, [_published("네이버 쇼핑 라이브 개편", days_ago=4)]
    )
    # 2일 전(창 안) → 차단 유지.
    assert dedup.is_duplicate(
        candidate, [_published("네이버 쇼핑 라이브 개편", days_ago=2)]
    )


def test_entity_cooldown_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ENTITY_COOLDOWN_DAYS", "5")
    dedup = TopicDedupService(dedup_days=7)
    assert dedup.entity_cooldown_days == 5
    # 호출부 명시값은 env보다 우선.
    explicit = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    assert explicit.entity_cooldown_days == 7


def test_evergreen_fallback_candidate_exempt_from_entity_cooldown(monkeypatch) -> None:
    """2026-07-22 실측: ai_automation 에버그린 뱅크 골든매칭 14개가 엔티티
    쿨다운에 전부 걸려 발행 0건. AI 툴 비교 콘텐츠는 상시 엔티티(ChatGPT 등)를
    구조적으로 반복 언급하므로 evergreen_fallback 후보는 엔티티 쿨다운을
    면제해야 한다(콘텐츠 레벨 dedup은 계속 적용)."""
    monkeypatch.delenv("ENTITY_COOLDOWN_APPLIES_TO_EVERGREEN", raising=False)
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored(
        "Claude vs ChatGPT for spreadsheet work",
        raw={"evergreen_fallback": True},
    )
    # 키워드 겹침을 피하려 과거 레코드 제목을 다르게 둔다 — 엔티티 규칙만이
    # 잡을 수 있는 쌍이어야 이 테스트가 의미 있다.
    history = [_published("ChatGPT rolls out a new voice feature", days_ago=1)]
    assert not dedup.is_duplicate(candidate, history)


def test_evergreen_fallback_exemption_can_be_reverted_via_env(monkeypatch) -> None:
    monkeypatch.setenv("ENTITY_COOLDOWN_APPLIES_TO_EVERGREEN", "true")
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored(
        "Claude vs ChatGPT for spreadsheet work",
        raw={"evergreen_fallback": True},
    )
    history = [_published("ChatGPT rolls out a new voice feature", days_ago=1)]
    assert dedup.is_duplicate(candidate, history)


def test_non_evergreen_candidate_still_gets_entity_cooldown(monkeypatch) -> None:
    # evergreen_fallback 플래그가 없는(=실제 뉴스) 후보는 예외 대상이 아니다.
    monkeypatch.delenv("ENTITY_COOLDOWN_APPLIES_TO_EVERGREEN", raising=False)
    dedup = TopicDedupService(dedup_days=7, entity_cooldown_days=7)
    candidate = _scored("ChatGPT outage knocks out enterprise workflows")
    history = [_published("ChatGPT rolls out a new voice feature", days_ago=1)]
    assert dedup.is_duplicate(candidate, history)
