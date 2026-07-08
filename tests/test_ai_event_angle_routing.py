"""AI 뉴스 사건 유형별 앵글 라우팅 테스트 — 주제 틀 붕괴의 근본 회귀 가드.

배경(2026-07-08): "AI" 단어만 있으면 광고 출시·요금 개편·규제·모델 발표까지
전부 "{제품} AI 기능 설정" how-to 하나로 뭉갰다. 그 결과
- 설정이 없는 사건에 설정 글을 지어내 제목↔본문 불일치·원문 이슈 소실 게이트에
  걸렸고(2026-07-03~07 5일 미발행 사건의 뿌리),
- 게이트를 통과한 날에는 같은 모양의 글만 연속 발행됐다(네이버 AI 3연속).
또 ai_model/ai_search/ai_risk/ai_compare 그룹과 골든 패턴은 Phase 3부터
존재했지만 분류기가 도달시키지 않아 죽은 코드였다.

이 파일이 고정하는 계약:
1. 서로 다른 사건 유형은 서로 다른 프레임을 받는다 (다양성).
2. "설정" how-to는 기능 신호가 있는 뉴스에만 배정된다 (날조 금지).
3. 앵글 프레임 ↔ 토픽 그룹 ↔ 골든 패턴이 한 분류기에서 일관되게 파생된다.
4. 모든 프레임이 골든 매칭을 통과한다 (PR #19 "키워드 갭 → 미발행" 재발 방지).
"""
from __future__ import annotations

import pytest

from blogspot_automation.services.golden_pattern_service import GoldenPatternService
from blogspot_automation.services.news_taxonomy import (
    _classify_ai_event,
    build_search_angle,
    classify_topic_group,
    content_type_for_topic_group,
)

# (헤드라인, 기대 사건 유형, 기대 angle_type, 기대 topic_group)
CASES = [
    ("네이버, AI 브리핑 광고 상품 정식 출시", "business", "ai_service_change", "ai_work"),
    ("네이버, AI 확산 맞춰 보안 경쟁력 강화…정보보호 투자 660억원", "risk", "ai_risk_check", "ai_risk"),
    ("OpenAI, 챗GPT 플러스 요금제 가격 인상 발표", "pricing", "money_compare", "ai_work"),
    ("구글, 제미나이 3 모델 공개…성능 대폭 향상", "model_release", "ai_model_release", "ai_model"),
    ("정부, AI 기본법 시행령 초안 공개", "regulation", "ai_policy_impact", "ai_work"),
    ("카카오, 카나나에 AI 추천 기능 도입", "feature", "ai_setting", "ai_work"),
    ("구글 AI 검색 한국 출시…검색 결과가 달라진다", "search", "ai_search_change", "ai_search"),
    ("ChatGPT vs Gemini, 업무용 AI 비교", "comparison", "ai_comparison", "ai_compare"),
]


@pytest.mark.parametrize("headline,event,angle_type,topic_group", CASES)
def test_event_type_routes_to_matching_frame(headline, event, angle_type, topic_group) -> None:
    assert _classify_ai_event(headline) == event
    angle = build_search_angle(headline)
    assert angle["angle_type"] == angle_type
    assert classify_topic_group(headline) == topic_group


def test_distinct_events_do_not_collapse_into_one_skeleton() -> None:
    """다양성 계약: 8가지 사건이 하나의 틀로 뭉개지면 안 된다."""
    angle_types = {build_search_angle(h)["angle_type"] for h, *_ in CASES}
    assert len(angle_types) >= 6, f"프레임이 {len(angle_types)}종뿐 — 틀 붕괴 재발: {angle_types}"


def test_setting_howto_only_for_feature_news() -> None:
    """설정 how-to 날조 금지: 기능 신호가 있는 뉴스에만 '설정' 프레임."""
    for headline, event, *_ in CASES:
        demand = build_search_angle(headline)["search_demand_topic"]
        if event == "feature":
            assert "설정" in demand
        else:
            assert "설정" not in demand, (
                f"설정이 없는 사건({event})에 설정 프레임 배정: {headline} → {demand}"
            )


def test_every_frame_passes_golden_matching() -> None:
    """PR #19 재발 방지: 생성기가 만드는 모든 프레임은 골든 매칭을 통과해야 한다.

    (과거: 템플릿과 패턴 키워드가 'AI' 한 단어만 겹쳐 confidence 52 고정 →
    5일 연속 미발행. 프레임을 늘릴 때는 반드시 매처와 함께 정렬할 것.)
    """
    ps = GoldenPatternService()
    for headline, *_ in CASES:
        angle = build_search_angle(headline)
        group = classify_topic_group(headline)
        match = ps.match_pattern(
            topic=angle["search_demand_topic"],
            content_type=content_type_for_topic_group(group),
            topic_group=group,
            summary=headline,
        )
        assert match["matched"], (
            f"골든 매칭 실패(confidence={match['confidence']}): "
            f"{headline} → {angle['search_demand_topic']} [{group}]"
        )


def test_original_issue_noun_preserved_in_frames() -> None:
    """PR #28 교훈 유지: 원문 이슈 명사가 demand topic에 보존된다."""
    naver_security = build_search_angle("네이버, AI 확산 맞춰 보안 경쟁력 강화…정보보호 투자 660억원")
    assert "보안" in naver_security["search_demand_topic"]
    naver_ads = build_search_angle("네이버, AI 브리핑 광고 상품 정식 출시")
    assert "광고" in naver_ads["search_demand_topic"]


def test_brand_names_with_ai_suffix_not_mangled() -> None:
    """실측 회귀: 꼬리 'AI' 제거가 OpenAI/xAI 브랜드명을 자르면 안 된다."""
    angle = build_search_angle("OpenAI, 챗GPT 플러스 요금제 가격 인상 발표")
    assert "OpenAI" in angle["search_demand_topic"]
    assert "Open " not in angle["search_demand_topic"].replace("OpenAI", "")


def test_ai_product_name_without_literal_ai_still_enters_ai_branch() -> None:
    """실측 회귀: 'AI' 문자열 없는 제품명 헤드라인('제미나이 3 공개')도 AI 뉴스."""
    angle = build_search_angle("구글, 제미나이 3 모델 공개…성능 대폭 향상")
    assert angle["angle_type"] == "ai_model_release"
    assert classify_topic_group("구글, 제미나이 3 모델 공개…성능 대폭 향상") == "ai_model"


def test_safety_governance_news_gets_explainer_not_setting() -> None:
    """실측 회귀: AI 안전·거버넌스 체계 뉴스는 '출시'가 붙어도 설정 프레임 금지.

    (같은 '네이버 AI 안전관리 2.0' 뉴스가 '발표'→소식, '출시'→설정으로 갈리던
    불일치. 안전 체계는 사용자 설정이 없으므로 해설 프레임으로 통일한다.)
    """
    for headline in (
        "네이버, AI 안전관리 'ASF 2.0' 출시…서비스 전 과정 관리",
        "AI탭 만든 네이버, AI 안전성 체계 2.0 발표",
        "카카오, 책임있는 AI 거버넌스 체계 도입",
    ):
        assert _classify_ai_event(headline) == "announcement", headline
        assert "설정" not in build_search_angle(headline)["search_demand_topic"], headline


def test_non_ai_news_unaffected_by_ai_routing() -> None:
    """비-AI 뉴스는 기존 분류 경로 그대로."""
    assert classify_topic_group("카카오톡 지원 종료, 구형폰 사용자 확인") == "platform_issue"
    assert build_search_angle("환불 지연 피해 급증, 소비자원 주의보")["angle_type"] in (
        "refund_action", "consumer_warning",
    )
