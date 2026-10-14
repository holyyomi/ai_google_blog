"""제목 엉킴·브랜드 표기·고정 꼬리 (2026-10-14).

실측: "OpenAI How to Use ChatGPT Lawsuit Briefs Unsealed" — 기본 의도 시드
("openai how to use")가 소송 헤드라인 앞에 붙었다. "Chatgpt" 대소문자 깨짐,
"Which One Wins?"/"The Real Numbers" 고정 꼬리.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services.search_demand_service import extract_seeds
from blogspot_automation.services.title_candidate_service import (
    TitleCandidateService,
    _build_english_titles,
    fix_brand_casing,
    normalize_english_title,
)
from blogspot_automation.services.title_integrity_policy import (
    audit_title_integrity,
    has_spliced_how_to_use_event,
)


# (1) 사건형 헤드라인에는 기본 의도(pricing / how to use)를 붙이지 않는다.
@pytest.mark.parametrize(
    "headline",
    [
        "ChatGPT lawsuit briefs unsealed in OpenAI copyright case",
        "OpenAI acquires coding startup Windsurf",
        "Anthropic settles authors lawsuit for $1.5B",
    ],
)
def test_event_headline_gets_no_default_intent_seed(headline) -> None:
    seeds = extract_seeds(headline, limit=6)
    assert seeds, "제품명 시드는 남아야 한다"
    assert not any("how to use" in s or s.endswith(" pricing") for s in seeds), seeds


def test_product_headline_keeps_default_intents() -> None:
    seeds = extract_seeds("Gemini adds a new canvas mode", limit=6)
    assert "gemini how to use" in seeds or "gemini pricing" in seeds


# (2) "<제품> How to Use <다른 사건>" 차단.
def test_spliced_how_to_use_event_blocked() -> None:
    title = "OpenAI How to Use ChatGPT Lawsuit Briefs Unsealed"
    assert has_spliced_how_to_use_event(title)
    result = audit_title_integrity(title)
    assert not result["passed"]
    assert "spliced_how_to_use_event_title" in result["blocking_issues"]
    scored = TitleCandidateService().score_title(title)
    assert not scored["is_allowed"]


@pytest.mark.parametrize(
    "title",
    [
        "How to Use ChatGPT Projects for Research (2026)",
        "ChatGPT Agent Mode: How to Use It Safely",
        # "Claude Code How to Use Subagents" 같은 검색어 어순은 비문이라 차단 대상이다.
        # 최종 제목 정규화가 "How to Use Claude Code Subagents"로 고친다.
        "How to Use Claude Code Subagents",
    ],
)
def test_normal_how_to_titles_pass(title) -> None:
    assert not has_spliced_how_to_use_event(title)
    assert "spliced_how_to_use_event_title" not in audit_title_integrity(title)["blocking_issues"]


# (3) 브랜드 대소문자 교정.
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Chatgpt Free Limits", "ChatGPT Free Limits"),
        ("Openai and Github Copilot", "OpenAI and GitHub Copilot"),
        ("Deepseek vs Notebooklm", "DeepSeek vs NotebookLM"),
        ("Elevenlabs Voice Api", "ElevenLabs Voice API"),
        ("Gpt-5 vs Gpt-4o for Ai Coding", "GPT-5 vs GPT-4o for AI Coding"),
        ("Midjourney and Perplexity", "Midjourney and Perplexity"),
        ("ChatGPT, OpenAI, GitHub, AI, API", "ChatGPT, OpenAI, GitHub, AI, API"),
        ("Aim for Rapid Apis", "Aim for Rapid APIs"),  # 단어 경계: Aim·Rapid 는 그대로
    ],
)
def test_fix_brand_casing(raw, expected) -> None:
    assert fix_brand_casing(raw) == expected


def test_fix_brand_casing_skips_korean() -> None:
    assert fix_brand_casing("Chatgpt 무료 한도") == "Chatgpt 무료 한도"


def test_normalize_english_title_applies_brand_casing() -> None:
    assert normalize_english_title("chatgpt vs gpt-5 api pricing") == "ChatGPT vs GPT-5 API Pricing"


# (4) 고정 꼬리 폐기.
@pytest.mark.parametrize(
    "topic",
    ["ChatGPT vs Claude for coding", "Gemini API pricing for small teams"],
)
def test_no_fixed_tails(topic) -> None:
    titles = [t for t, _ in _build_english_titles(topic=topic, raw={})]
    assert titles
    assert not any("Which One Wins" in t or "The Real Numbers" in t for t in titles), titles
