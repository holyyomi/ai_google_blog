"""하이브리드 주제 풀 회귀 테스트.

운영 방침(2026-07): 뉴스가 약한 날 에버그린 폴백으로 AI 업무·자동화·수익화
how-to를 로테이션한다. 이 주제들이 풀에 유지되고 구조가 유효한지 지킨다.
개인 수익 일기(실측 숫자 필요)는 봇이 지어낼 수 있어 자동 풀에서 제외한다.
"""
from __future__ import annotations

from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService


HYBRID_MARKERS = [
    "OpenAI API",          # AI 요금 계산
    "품질 검수",            # AI 글 검수 체크리스트
    "Cursor",              # AI 코딩 자동화 실전
    "검색에서 약한",        # AI 자동생성 글 검색 약점
    "자동화 수익",          # AI 블로그 자동화 수익 현실
    "자동화 도구 직접",     # 자동화 도구 구성(정보형)
    "애드센스 정책",        # AI 글 애드센스 정책
]


def _all_texts() -> list[str]:
    svc = EvergreenTopicService()
    texts = []
    for c in svc.collect_candidates(limit=200):
        raw = c.raw or {}
        texts.append(f"{c.topic} {raw.get('search_demand_topic','')} {c.summary}")
    return texts


def test_hybrid_topics_present_in_pool() -> None:
    blob = " \n ".join(_all_texts())
    missing = [m for m in HYBRID_MARKERS if m not in blob]
    assert not missing, f"하이브리드 주제 누락: {missing}"


def test_no_personal_income_diary_in_auto_pool() -> None:
    # 봇은 실제 수익 데이터가 없어 지어내면 팩트-세이프티 위반 → 자동 풀 금지.
    blob = " \n ".join(_all_texts())
    for banned in ["퇴사 후", "수익 인증", "월 수익 공개", "내 수익 기록"]:
        assert banned not in blob, f"개인 수익 일기형 주제가 자동 풀에 있음: {banned}"


def test_hybrid_topics_have_valid_structure() -> None:
    svc = EvergreenTopicService()
    for c in svc.collect_candidates(limit=200):
        raw = c.raw or {}
        assert c.topic and c.summary
        assert raw.get("topic_group")
        assert (raw.get("content_angle") or {}).get("content_type")
        assert len(raw.get("reader_search_questions") or []) == 3
