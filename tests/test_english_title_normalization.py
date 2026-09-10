"""영문 제목 표기 통일 회귀 테스트 (2026-09-10 신설).

제목 후보 생성 경로가 여러 개라 검색어를 그대로 실은 소문자 제목이 발행됐다.
실측 발행분: 'chatgpt free version attachment limits 2026',
'grok pricing api 2026: what the new rates mean for you'.
"""

from __future__ import annotations

from blogspot_automation.services.title_candidate_service import (
    TitleCandidateService,
    normalize_english_title,
)


def test_lowercase_search_query_title_becomes_title_case() -> None:
    assert (
        normalize_english_title("chatgpt free version attachment limits 2026")
        == "ChatGPT Free Version Attachment Limits 2026"
    )


def test_colon_titles_are_cased_on_both_sides() -> None:
    assert (
        normalize_english_title("grok pricing api 2026: what the new rates mean for you")
        == "Grok Pricing API 2026: What the New Rates Mean for You"
    )


def test_acronyms_are_uppercased() -> None:
    assert "API" in normalize_english_title("free api limits explained")
    assert "SEO" in normalize_english_title("seo basics for a new blog")


def test_brand_casing_is_restored() -> None:
    assert normalize_english_title("openrouter free models limit reset 2026").startswith("OpenRouter")
    assert "Hugging Face" in normalize_english_title("ggml joins huggingface 2026")


def test_lowercase_brands_stay_lowercase() -> None:
    """ggml / cpp 처럼 소문자가 정식인 이름은 대문자로 올리지 않는다."""
    out = normalize_english_title("llama cpp how to use after ggml joins Hugging Face 2026")
    assert "ggml" in out
    assert "Ggml" not in out


def test_small_words_stay_lowercase_in_the_middle() -> None:
    out = normalize_english_title("what the new rates mean for you")
    assert " the " in out and " for " in out


def test_already_correct_title_is_unchanged() -> None:
    title = "ChatGPT Free Version Limits: What Works in 2026"
    assert normalize_english_title(title) == title


def test_korean_titles_are_untouched() -> None:
    title = "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지"
    assert normalize_english_title(title) == title


def test_empty_and_symbol_only_titles_are_safe() -> None:
    assert normalize_english_title("") == ""
    assert normalize_english_title("   ") == ""
    assert normalize_english_title("2026 —") == "2026 —"


def test_select_best_title_applies_normalization() -> None:
    """선택 지점에서 실제로 적용되는지 — 함수만 고치고 배선을 빠뜨리면 무의미하다."""
    svc = TitleCandidateService()
    best = svc.select_best_title(
        [{"title": "chatgpt free version limits 2026", "is_allowed": True, "ctr_score": 10}]
    )
    assert best["title"] == "ChatGPT Free Version Limits 2026"
    assert best.get("title_case_normalized") is True


def test_select_best_title_does_not_flag_already_correct_titles() -> None:
    svc = TitleCandidateService()
    best = svc.select_best_title(
        [{"title": "ChatGPT Free Version Limits 2026", "is_allowed": True, "ctr_score": 10}]
    )
    assert "title_case_normalized" not in best
