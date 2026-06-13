from __future__ import annotations

from blogspot_automation.services.title_integrity_policy import audit_title_integrity, clean_source_title


def test_clean_source_title_removes_source_series_before_bracket_strip() -> None:
    assert clean_source_title("[재계는 지금] KT 초이스 요금제 무료 혜택") == "KT 초이스 요금제 무료 혜택"
    assert clean_source_title("재계는 지금] KT 초이스 요금제 무료 혜택") == "KT 초이스 요금제 무료 혜택"


def test_audit_title_integrity_blocks_source_series_and_broken_reaction_phrase() -> None:
    result = audit_title_integrity(
        "재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지",
        content_type="viral_issue_decode",
        topic_group="ott_platform",
        source_text="[재계는 지금] KT 초이스 요금제 무료 혜택",
    )

    assert not result["passed"]
    assert "source_series_name_leaked:재계는 지금" in result["blocking_issues"]
    assert "malformed_reaction_phrase" in result["blocking_issues"]
    assert "telecom_plan_topic_using_viral_reaction_template" in result["blocking_issues"]


def test_audit_title_integrity_blocks_policy_faq_heading_leak() -> None:
    result = audit_title_integrity("신청전 많이 묻는 질문")

    assert not result["passed"]
    assert "policy_faq_heading_leak" in result["blocking_issues"]
