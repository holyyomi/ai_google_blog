from __future__ import annotations

from blogspot_automation.services.news_taxonomy import (
    build_search_angle,
    classify_public_benefit,
    classify_topic_group,
)


def test_specific_support_keyword_is_preserved_from_generic_support_title() -> None:
    text = "1인당 최대 50만 원 줍니다 2026 청년 운전면허 지원금, 어떻게 받나?"

    result = classify_public_benefit(text)
    angle = build_search_angle(text)

    assert result["public_benefit_keyword"] == "청년 운전면허 지원금"
    assert result["generic_support_keyword"] == "지원금"
    assert result["public_benefit_confidence"] == "high"
    assert angle["search_demand_topic"] == "청년 운전면허 지원금 신청방법과 대상 조건"


def test_plain_government_support_stays_generic() -> None:
    result = classify_public_benefit("정부 지원금 신청 시작")

    assert result["public_benefit_keyword"] == "지원금"
    assert result["public_benefit_confidence"] == "medium"


def test_malformed_support_descriptor_is_rejected() -> None:
    result = classify_public_benefit("지원한다 이를 달간의 지원금 신청 안내")

    assert result["public_benefit_keyword"] == ""
    assert result["generic_support_keyword"] == "지원금"
    assert result["public_benefit_confidence"] == "low"


def test_employment_insurance_refund_keyword_is_specific() -> None:
    text = "소상공인 고용보험료 돌려받으세요 전남신보, 환급사업 본격화"

    result = classify_public_benefit(text)
    angle = build_search_angle(text)

    assert result["public_benefit_keyword"] == "소상공인 고용보험료 환급"
    assert angle["search_demand_topic"] == "소상공인 고용보험료 환급 신청방법과 대상 조건"


def test_generic_refund_word_without_refund_context_is_not_promoted() -> None:
    text = "해수욕장서 치킨 배달 가능합니다 생활밀착형 국민체감과제 눈길 환급금"

    result = classify_public_benefit(text)

    assert result["public_benefit_keyword"] == ""
    assert result["public_benefit_confidence"] == "none"


def test_refund_word_with_hometax_context_is_promoted() -> None:
    result = classify_public_benefit("홈택스 미수령 환급금 조회 방법")

    assert result["public_benefit_keyword"]
    assert "환급금" in result["public_benefit_keyword"]


def test_platform_fee_change_is_not_forced_into_delivery_money() -> None:
    angle = build_search_angle(
        "\"12월은 너무 늦다\" 게임협단체, 구글 수수료 인하에 환영 반 아쉬움 반",
        category="money",
        raw={"query_group": "platform_change_secondary"},
    )

    assert angle["angle_type"] == "platform_check"
    assert angle["search_demand_topic"] == "구글 수수료 변경 전에 확인할 것"
    assert "쿠폰" not in " ".join(angle["reader_search_questions"])


def test_platform_fee_policy_change_is_not_support_end() -> None:
    angle = build_search_angle("예고)브런치 작가멤버십 플랫폼 수수료 정책 변경 안내")

    assert angle["angle_type"] == "platform_check"
    assert angle["search_demand_topic"] == "예고)브런치 작가멤버십 플랫폼 수수료 변경 전에 확인할 것"
    assert "지원 종료" not in angle["search_demand_topic"]


def test_quoted_privacy_entity_is_cleaned() -> None:
    angle = build_search_angle("티빙' 개인정보 유출...비밀번호·계좌번호까지 털렸나")

    assert angle["search_demand_topic"] == "티빙 개인정보 유출 비밀번호 변경 안내 후 확인할 것"


def test_delivery_fee_change_still_uses_money_compare() -> None:
    angle = build_search_angle("배달앱 수수료 인상 소비자 부담")

    assert angle["angle_type"] == "money_compare"
    assert "배달앱 결제금액" in angle["search_demand_topic"]


def test_delivery_worker_safety_issue_is_not_money_compare() -> None:
    title = "수익은 줄고, 위험은 늘고… 배달앱 새벽배달 확대에 분통"

    angle = build_search_angle(title)

    assert classify_topic_group(title) == "platform_issue"
    assert angle["angle_type"] == "platform_check"
    assert angle["search_demand_topic"] == "배달앱 새벽배달 변경 전에 확인할 것"
    assert "쿠폰" not in " ".join(angle["reader_search_questions"])
    assert "최종 결제금액" not in angle["reader_benefit"]


def test_insurance_fee_story_is_not_delivery_money_compare() -> None:
    angle = build_search_angle("자동차 보험료인상 이유와 소비자에게 미치는 영향")

    assert angle["angle_type"] != "money_compare"
    assert "쿠폰" not in " ".join(angle["reader_search_questions"])


def test_tving_password_leak_is_privacy_warning_not_money_compare() -> None:
    title = '티빙, ID·이름·전화번호 탈탈 털렸다…"비밀번호 변경 권장'
    summary = (
        "걱정된다, 결합 요금제로 구독 중인데 내 정보도 포함된 거냐 등 이용자들의 "
        "항의와 우려가 이어졌고 비밀번호 전면 변경을 권장했다."
    )

    angle = build_search_angle(title, summary=summary, category="life", raw={"query_group": "platform_consumer"})

    assert classify_topic_group(f"{title} {summary}") == "privacy_security"
    assert angle["angle_type"] == "consumer_warning"
    assert angle["search_demand_topic"] == "티빙 비밀번호 변경 안내 후 확인할 것"
    assert "쿠폰" not in " ".join(angle["reader_search_questions"])
    assert "최종 결제금액" not in angle["reader_benefit"]


def test_viral_search_demand_uses_correct_subject_particle() -> None:
    angle = build_search_angle("티빙, OTT 신작 공개")

    assert angle["angle_type"] == "viral_issue_decode"
    assert angle["search_demand_topic"].startswith("티빙이 ")
    assert "티빙가" not in angle["search_demand_topic"]
