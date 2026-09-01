"""출처 대조 검사 회귀 방지 (2026-09-02).

기준점은 2026-09-01에 실제로 발행된 거짓 글이다. 그 글은 OpenAI Free Tier FAQ를
근거로 걸어놓고 "daily limits that are not disclosed"라고 썼는데, 그 FAQ는
"Free users have unlimited everyday text chats"라고 말한다. 기존 게이트 24종이
전부 통과시킨 글이라, 이 검사가 죽으면 같은 사고를 막을 수단이 다시 0이 된다.
"""

from __future__ import annotations

from blogspot_automation.services.source_grounding_service import audit_grounding


# 그날 인용했던 출처의 핵심 문장.
OPENAI_FAQ_FACTS = """
[OFFICIAL] ChatGPT Free Tier FAQ (help.openai.com/en/articles/9275245)
Free users have unlimited everyday text chats, subject to abuse-prevention safeguards.
File uploads, image generation, voice, data analysis, and other tools have separate
usage limits. ChatGPT will notify you when you reach an applicable limit.
Free users get access to GPT-5.6 Luna. The Library has a 500 MB storage limit.
"""


def test_catches_the_2026_09_01_false_claim():
    """사고 재현 — 출처가 말한 적 없는 '비공개'를 단정하면 잡아야 한다."""
    html = (
        "<p>Free ChatGPT gives you access to GPT-5.6 Luna with daily limits that "
        "are not disclosed as of September 2026.</p>"
    )
    report = audit_grounding(html, OPENAI_FAQ_FACTS)
    assert report.checked is True
    assert report.clean is False
    assert report.ungrounded_absence, "부재 주장을 하나도 못 잡았다"
    assert "not disclosed" in report.ungrounded_absence[0].lower()


def test_catches_every_phrasing_of_the_same_invention():
    """같은 거짓말의 다른 표현들 — 한 패턴만 막으면 옆으로 새어나간다."""
    variants = [
        "<p>Heavy sessions can hit the undisclosed daily cap.</p>",
        "<p>OpenAI does not publish a fixed daily message quota.</p>",
        "<p>No fixed daily limits are publicly disclosed.</p>",
        "<p>The exact quotas are not publicly documented.</p>",
    ]
    for html in variants:
        report = audit_grounding(html, OPENAI_FAQ_FACTS)
        assert report.ungrounded_absence, f"놓쳤다: {html}"


def test_accurate_article_passes():
    """출처대로 쓴 글은 통과해야 한다 — 오탐이 나면 게이트를 못 켠다."""
    html = (
        "<p>Free ChatGPT gives you unlimited everyday text chats on GPT-5.6 Luna, "
        "per OpenAI's Free Tier FAQ. What is capped is everything around the chat "
        "box: file uploads, image generation, voice, and data analysis. The Library "
        "holds 500 MB.</p>"
    )
    report = audit_grounding(html, OPENAI_FAQ_FACTS)
    assert report.clean is True, report.as_dict()


def test_absence_claim_allowed_when_the_source_actually_says_so():
    """출처가 직접 '비공개'라고 하면 그건 인용이지 날조가 아니다."""
    facts = (
        "[OFFICIAL] Vendor pricing page. Enterprise pricing is not publicly disclosed; "
        "contact sales for a quote."
    )
    html = "<p>Enterprise pricing is not disclosed, so you have to contact sales.</p>"
    report = audit_grounding(html, facts)
    assert report.ungrounded_absence == []


def test_ungrounded_price_is_flagged():
    """팩트에 없는 가격은 지어낸 것이다."""
    html = "<p>The Plus plan costs $20 per month and includes 5000 tokens.</p>"
    report = audit_grounding(html, "[OFFICIAL] The free plan has a 500 MB library limit.")
    assert "$20" in " ".join(report.ungrounded_numbers)


def test_grounded_numbers_survive_formatting_differences():
    """'500MB' vs '500 MB', '$1,500' vs '1500' 같은 표기 차이로 오탐 내지 않는다."""
    facts = "[OFFICIAL] Storage is capped at 500MB. The team plan is 1500 USD per year."
    html = "<p>You get 500 MB of storage, and the team plan runs $1,500 a year.</p>"
    report = audit_grounding(html, facts)
    assert report.ungrounded_numbers == [], report.as_dict()


def test_years_are_never_treated_as_unsupported_numbers():
    """연도는 글 구조상 항상 들어간다 — 출처에 없어도 거짓이 아니다."""
    html = "<p>As of 2026, the free plan still exists. It costs 0 credits.</p>"
    report = audit_grounding(html, "[OFFICIAL] The free plan still exists.")
    assert all("2026" not in n for n in report.ungrounded_numbers)


def test_json_ld_is_not_double_counted():
    """구조화 데이터는 본문 문장의 복사본이라, 같은 주장을 두 번 세면 안 된다."""
    claim = "Pricing is not disclosed."
    html = (
        f"<p>{claim}</p>"
        f'<script type="application/ld+json">{{"description": "{claim}"}}</script>'
    )
    report = audit_grounding(html, OPENAI_FAQ_FACTS)
    assert len(report.ungrounded_absence) == 1


def test_no_facts_means_no_verdict():
    """대조할 기준이 없으면 검사하지 않는다 — 전부 '근거 없음'은 신호가 아니라 잡음."""
    report = audit_grounding("<p>Limits are not disclosed. It costs $20.</p>", "")
    assert report.checked is False
    assert report.clean is True


def test_report_is_json_serializable_for_run_meta():
    """run_meta에 실려야 하므로 dict로 떨어져야 한다."""
    import json

    report = audit_grounding("<p>Costs $20.</p>", "[OFFICIAL] free plan")
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["checked"] is True
    assert set(payload) >= {"checked", "facts_chars", "ungrounded_numbers", "clean"}
