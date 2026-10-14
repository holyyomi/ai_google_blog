"""검색 시드가 제목 앞에 붙은 엉킴을 바로잡는다(2026-10-14 리허설 실측)."""
from blogspot_automation.services.title_candidate_service import normalize_english_title


def test_reorders_seed_prefix_from_rehearsal():
    assert normalize_english_title("Gemini Pricing API: Gemini 4 Argon Launch 2026") == (
        "Gemini 4 Argon Launch: Pricing and API (2026)"
    )


def test_keeps_title_when_tail_already_states_intent():
    assert normalize_english_title("Gemini API: Gemini Rate Limits Explained") == (
        "Gemini API: Gemini Rate Limits Explained"
    )


def test_keeps_title_when_product_not_repeated():
    assert normalize_english_title("Claude API: Fixing the 429 Error") == "Claude API: Fixing the 429 Error"


def test_keeps_normal_headline_colon_title():
    title = "Grok vs ChatGPT: Free vs Paid Decision Guide 2026"
    assert normalize_english_title(title) == title
