"""영어 전환(2026-07-17) 회귀 테스트.

BLOG_LANGUAGE=en일 때: 주제·제목·라벨·본문 검증·GEO 레이어가 전부 영어로 동작하고
발행 HTML에 한국어가 새지 않아야 한다. 기본(ko) 동작은 기존 테스트가 지킨다.
"""
from __future__ import annotations

import re

import pytest


@pytest.fixture
def en_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    yield


def test_blog_language_default_is_korean(monkeypatch):
    monkeypatch.delenv("BLOG_LANGUAGE", raising=False)
    from blogspot_automation.services.blog_language import blog_language, is_english_mode

    assert blog_language() == "ko"
    assert is_english_mode() is False


def test_blog_language_english_values(monkeypatch):
    from blogspot_automation.services.blog_language import is_english_mode

    for value in ("en", "EN", "en-US", "english"):
        monkeypatch.setenv("BLOG_LANGUAGE", value)
        assert is_english_mode() is True


def test_en_validator_rejects_korean_and_thin_content(en_mode):
    from blogspot_automation.services.llm_content_service import (
        _ContentValidationError,
        _validate_generated_content,
    )

    # 한글 혼입 → 차단
    korean_mixed = "<p>" + ("This is a fine English sentence. " * 80) + "안녕하세요</p>"
    with pytest.raises(_ContentValidationError):
        _validate_generated_content(korean_mixed)

    # 단어 수 미달(thin content) → 차단
    thin = "<p>Short article about ChatGPT pricing plans and limits today.</p>"
    with pytest.raises(_ContentValidationError):
        _validate_generated_content(thin)

    # 영어 상투 문구 → 차단
    slop_body = "<p>" + ("Solid factual sentence about pricing details here. " * 60) + "This is a game-changer.</p>"
    with pytest.raises(_ContentValidationError):
        _validate_generated_content(slop_body)


def test_en_validator_accepts_clean_long_english(en_mode):
    from blogspot_automation.services.llm_content_service import _validate_generated_content

    sentences = [
        f"Paragraph {i}: the plan includes concrete usage limits, and the pricing page lists the current rate for tier {i}."
        for i in range(160)
    ]
    html = "<p>" + " ".join(sentences) + "</p>"
    _validate_generated_content(html)  # 예외 없어야 함


def test_content_family_en_mapping(en_mode):
    from blogspot_automation.services.llm_content_service import content_family_en

    assert content_family_en("Claude vs ChatGPT for Excel work") == "Comparisons"
    assert content_family_en("ChatGPT Plus pricing explained") == "Pricing"
    assert content_family_en("ChatGPT not working: fixes") == "Fixes"
    assert content_family_en("AI adoption statistics 2026") == "Data & Stats"
    assert content_family_en("How to automate meeting notes") == "How-To"
    assert content_family_en("OpenAI announces new office") == "News"


def test_en_title_candidates_are_english(en_mode):
    from blogspot_automation.services.title_candidate_service import TitleCandidateService

    svc = TitleCandidateService()
    result = svc.generate_candidates(
        "Claude vs ChatGPT for Excel work",
        content_type="ai_work_tip",
        topic_group="ai_work",
        pattern_id="ai_tool_comparison",
    )
    best = result["best_title"].get("title", "")
    assert best, "영어 모드 최적 제목이 비어 있음"
    assert not re.search(r"[가-힣]", best), f"영어 제목에 한글 누출: {best}"
    assert any(c["is_allowed"] for c in result["candidates"])


def test_en_labels_and_hashtags(en_mode):
    from blogspot_automation.services.news_label_service import NewsLabelService

    svc = NewsLabelService()
    labels = svc.build(
        selected_topic="ChatGPT free vs paid difference",
        selected_title="ChatGPT Free vs Paid: What You Actually Get (2026)",
        topic_group="ai_work",
        content_type="ai_work_tip",
    )
    assert labels and all(not re.search(r"[가-힣]", label) for label in labels)

    hashtags = svc.build_hashtags(
        selected_topic="ChatGPT free vs paid difference",
        selected_title="ChatGPT Free vs Paid: What You Actually Get (2026)",
        topic_group="ai_work",
        content_type="ai_work_tip",
    )
    assert hashtags and all(not re.search(r"[가-힣]", tag) for tag in hashtags)


def test_en_evergreen_bank_is_english_ai_axis(en_mode):
    from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService

    candidates = EvergreenTopicService().collect_candidates()
    assert candidates, "영어 에버그린 후보가 비어 있음"
    for cand in candidates:
        assert cand.raw.get("evergreen_axis") == "ai_automation"
        assert cand.raw.get("topic_group") == "ai_work"
        blob = " ".join([
            cand.topic,
            cand.summary,
            *[str(q) for q in cand.raw.get("reader_search_questions") or []],
        ])
        assert not re.search(r"[가-힣]", blob), f"에버그린 후보에 한글: {cand.topic}"


def test_en_query_plan_uses_english_queries(en_mode):
    from blogspot_automation.services.news_topic_service import NewsTopicService

    svc = NewsTopicService()
    plan = svc._query_plan()
    assert plan, "영어 쿼리 플랜이 비어 있음"
    for query, group in plan:
        assert group == "ai_work"
        assert not re.search(r"[가-힣]", query), f"영어 쿼리 플랜에 한국어 쿼리: {query}"


def test_en_geo_layer_no_hangul_leak(en_mode):
    from blogspot_automation.services.answer_engine_policy import (
        ensure_answer_engine_optimized_html,
    )

    body = (
        "<p>Claude and ChatGPT both handle spreadsheets, but they differ on limits. "
        "As of July 2026, both offer free tiers with meaningful caps.</p>"
        "<h2>Which tool reads Excel files better?</h2>"
        "<p>Claude accepts larger uploads on paid plans. ChatGPT runs code to analyze data.</p>"
        '<div class="quick-decision-table"><table><thead><tr><th>Plan</th><th>Price</th></tr></thead>'
        "<tbody><tr><td>Free</td><td>check the official page</td></tr></tbody></table></div>"
        '<h2>Frequently Asked Questions</h2><div class="faq-section">'
        '<article class="faq-item"><h3 class="faq-q">Can ChatGPT analyze spreadsheets?</h3>'
        '<p class="faq-a">Yes, within plan limits that vary by tier and change over time.</p></article></div>'
        '<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">'
        '<div class="confirmed-section"><h3>What\'s confirmed</h3><ul><li>Both accept uploads.</li></ul></div>'
        '<div class="check-needed-section"><h3>Check for yourself</h3><ul><li>Current prices.</li></ul></div></section>'
    )
    out = ensure_answer_engine_optimized_html(
        body,
        title="Claude vs ChatGPT for Excel Work (2026)",
        topic="Claude vs ChatGPT for Excel work",
        content_type="ai_work_tip",
        topic_group="ai_work",
        reader_questions=["Is Claude or ChatGPT better for Excel?"],
    )
    leaked = sorted(set(re.findall(r"[가-힣]+", out)))
    assert not leaked, f"영어 모드 GEO 출력에 한글 누출: {leaked[:10]}"
    # 필수 GEO 블록 ID는 그대로 있어야 한다 (스코어카드 계약)
    for block_id in (
        "AI_OVERVIEW_TARGET_ANSWER",
        "ISSUE_CONTEXT_BLOCK",
        "INTENT_ANSWER_BLOCK",
        "SOURCE_TRUST_BLOCK",
    ):
        assert block_id in out, f"영어 모드에서 GEO 블록 누락: {block_id}"


def test_en_overview_long_slots_do_not_truncate_mid_word(en_mode):
    # 2026-07-20~21 라이브 실측 사고: hook_opening/real_criterion이 길면
    # (LLM 서술형에서 흔함) 이 셋을 합친 문자열이 이전 result[:500] 하드컷에
    # 걸려 yomi_judgment나 뒤이은 canned 문장 중간에서 잘렸다("check the of",
    # "The key he" 등). 발행 4건 전부(AI_OVERVIEW_TARGET_ANSWER/TL;DR 박스)에서
    # 재현됨 — 문장 경계에서만 잘라야 한다.
    from blogspot_automation.services.geo_intent_service import GeoIntentService

    gi = GeoIntentService()
    long_hook = (
        "ChatGPT, Claude, Gemini, and Perplexity all publish subscription tiers, "
        "but the fine print on usage caps, context windows, and add-on seat pricing "
        "rarely matches the headline number shown on the marketing page. "
    )
    long_real = (
        "Independent trackers that aggregate these plans update on their own schedule, "
        "so a number that was accurate last month can already be stale by the time "
        "you read a comparison post, which is exactly why every claim here is labeled "
        "as either confirmed or still needing your own verification. "
    )
    slots = {
        "hook_opening": long_hook,
        "real_criterion": long_real,
        "yomi_judgment": (
            "The key here is separating the actual impact from the noise, "
            "and knowing what to verify yourself."
        ),
    }
    text = gi.generate_ai_overview_target_answer(
        topic="AI assistant pricing comparison", content_type="ai_work_tip", slots=slots,
    )
    assert len(long_hook) + len(long_real) > 400, "test fixture must be long enough to force the old 500-char cut"
    assert text, "overview must not be empty"
    assert text[-1] in ".!?", f"overview must end on a sentence boundary, got: {text!r}"
    assert "check the of" not in text, f"mid-word truncation of the canned sentence leaked through: {text!r}"


def test_en_dedup_english_filler_not_counted(en_mode):
    from blogspot_automation.services.topic_dedup_service import TopicDedupService

    kws = TopicDedupService().extract_keywords(
        "How to use the best free AI tools for your work in 2026"
    )
    for filler in ("the", "for", "your", "how", "best", "free", "tools"):
        assert filler not in kws, f"영어 불용어가 dedup 키워드로 남음: {filler}"
