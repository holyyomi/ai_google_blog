"""2026-10-14 AdSense 품질 개편 — 영어 lean 경로 + 발행 직전 최종 HTML 게이트.

눈금(라이브 글, tests/fixtures/final_gate):
- 10-08 Perplexity x Amex, 10-13 ChatGPT vs Codex: 공식 출처를 인용한 괜찮은 글.
  새 파이프라인이 만들 모양(후처리 블록 4종 제거본)은 통과해야 한다.
- 10-14 Grok vs ChatGPT: GitHub 저장소 2개가 출처 전부, "roughly 200 messages per day"
  무출처 수치. 블록을 걷어내도 차단돼야 한다.
- 라이브 원본(블록 포함)은 세 글 모두 문장 중복으로 걸린다 — 중복의 원인이 후처리
  블록 자체였다는 실측(블록 제거 시 중복 0).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from blogspot_automation.services import en_editorial_policy as policy
from blogspot_automation.services.answer_engine_policy import (
    answer_engine_coverage,
    ensure_answer_engine_optimized_html,
)

FIXTURES = Path(__file__).parent / "fixtures" / "final_gate"
DISABLED = policy.LEAN_DISABLED_BLOCK_IDS


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _strip_disabled_blocks(html: str) -> str:
    for block_id in DISABLED:
        html = re.sub(
            rf'<section\b[^>]*id=["\']{block_id}["\'][^>]*>.*?</section>',
            " ",
            html,
            flags=re.S | re.I,
        )
    return html


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    for key in (
        "EN_LEGACY_GEO_BLOCKS",
        "FINAL_QUALITY_GATE",
        "AI_DISCLOSURE_MODE",
        "NEWS_PUBLISH_AS_DRAFT",
        "SOURCE_GROUNDING_STRICT_NUMBERS",
        "OFFICIAL_SOURCE_EXTRA_DOMAINS",
        "BLOG_AUTHOR_NAME",
    ):
        monkeypatch.delenv(key, raising=False)


# ── 눈금: 라이브 글 ──────────────────────────────────────────────────────────
GOOD = [
    ("live_20261008_perplexity_amex.html", "sources_20261008_perplexity_reconstructed.txt"),
    ("live_20261013_chatgpt_vs_codex.html", "sources_20261013_openai_reconstructed.txt"),
]


@pytest.mark.parametrize("post,sources", GOOD)
def test_good_live_posts_pass_in_lean_shape(post, sources):
    result = policy.audit_final_publish_html(
        _strip_disabled_blocks(_read(post)), source_text=_read(sources)
    )
    assert result["passed"], result
    assert result["issues"] == []
    assert result["details"]["official_source_urls"]


@pytest.mark.parametrize("post,sources", GOOD)
def test_good_live_posts_with_old_blocks_fail_only_on_duplication(post, sources):
    """후처리 블록이 붙은 라이브 원본은 블록이 본문을 되풀이해 중복으로 걸린다."""
    result = policy.audit_final_publish_html(_read(post), source_text=_read(sources))
    assert not result["passed"]
    assert [i for i in result["issues"] if not i.startswith("duplicate_sentences:")] == []


def test_grok_vs_chatgpt_is_blocked_even_without_old_blocks():
    result = policy.audit_final_publish_html(
        _strip_disabled_blocks(_read("live_20261014_grok_vs_chatgpt.html")),
        source_text=_read("sources_20261014_github_readmes.txt"),
    )
    assert not result["passed"]
    assert "no_official_source" in result["issues"]
    assert "unsourced_number:200 messages" in result["issues"]
    assert "unsourced_number:150 messages" in result["issues"]
    assert set(result["details"]["external_source_hosts"]) == {"github.com"}


def test_grok_vs_chatgpt_live_original_also_trips_duplicates():
    result = policy.audit_final_publish_html(
        _read("live_20261014_grok_vs_chatgpt.html"),
        source_text=_read("sources_20261014_github_readmes.txt"),
    )
    assert any(i.startswith("duplicate_sentences:") for i in result["issues"])
    assert max(d["count"] for d in result["details"]["duplicate_sentences"]) >= 3


# ── 게이트 단위 ─────────────────────────────────────────────────────────────
def test_duplicate_sentence_threshold_is_40_chars_and_twice():
    long_s = "The free plan includes fifty image generations every single day."
    short_s = "Pick the free plan."
    html = f"<p>{long_s}</p><p>Other words here.</p><p>{long_s}</p><p>{short_s}</p><p>{short_s}</p>"
    dups = policy.duplicate_sentences(html)
    assert len(dups) == 1


def test_json_ld_and_style_are_not_counted_as_duplicates():
    s = "ChatGPT Classic keeps receiving model updates and security patches for now."
    html = f'<p>{s}</p><script type="application/ld+json">{{"text": "{s}"}}</script><style>p{{}}</style>'
    assert policy.duplicate_sentences(html) == {}


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://help.openai.com/en/articles/1", "official"),
        ("https://platform.openai.com/docs/models", "official"),
        ("https://www.anthropic.com/news/x", "official"),
        ("https://ai.google.dev/gemini-api/docs/rate-limits", "official"),
        ("https://blog.google/technology/ai/x", "official"),
        ("https://www.perplexity.ai/hub/blog/x", "official"),
        ("https://docs.github.com/en/copilot", "official"),
        ("https://arxiv.org/abs/2501.00001", "official"),
        ("https://docs.somevendor.io/limits", "official"),
        ("https://github.com/someone/repo", "community"),
        ("https://community.openai.com/t/x/1", "community"),
        ("https://www.reddit.com/r/OpenAI/", "community"),
        ("https://news.ycombinator.com/item?id=1", "community"),
        ("https://techcrunch.com/2026/10/01/x", "other"),
    ],
)
def test_classify_source_url(url, expected):
    assert policy.classify_source_url(url) == expected


def test_media_only_sources_are_blocked_as_no_official_source():
    html = '<p>Claim.</p><a href="https://techcrunch.com/a">TC</a>'
    assert "no_official_source" in policy.audit_final_publish_html(html)["issues"]


def test_observe_mode_records_but_passes(monkeypatch):
    monkeypatch.setenv("FINAL_QUALITY_GATE", "observe")
    result = policy.audit_final_publish_html("<p>roughly 200 messages per day.</p>")
    assert result["passed"] and result["issues"]


def test_numbers_present_in_sources_pass():
    html = '<p>The free tier allows 250 requests per day, about 40% fewer.</p><a href="https://ai.google.dev/x">x</a>'
    src = "Gemini free tier: 250 requests per day. That is 40% fewer than before."
    assert policy.audit_final_publish_html(html, source_text=src)["passed"]


# ── lean HTML 조립 ───────────────────────────────────────────────────────────
_BODY = (
    '<article class="yomi-clean-post"><h1>Gemini Free API Limits</h1>'
    "<p>You hit the Gemini free limit halfway through a batch job, and the error does not say why. "
    'The free tier allows <a href="https://ai.google.dev/gemini-api/docs/rate-limits">250 requests per day</a> as of October 2026.</p>'
    "<h2>What the limit counts</h2><p>Each call counts once, including retries that fail.</p>"
    "<div class=\"verdict-box\"><span class=\"section-label\">Verdict</span><p>Stay on the free tier unless you run more than one batch a day.</p></div>"
    "</article>"
)
_CITES = [
    {"name": "Gemini API rate limits", "url": "https://ai.google.dev/gemini-api/docs/rate-limits"},
    {"name": "Forum thread", "url": "https://discuss.ai.google.dev/t/1"},
]


def _lean(body: str = _BODY, **kw) -> str:
    return ensure_answer_engine_optimized_html(
        body,
        title="Gemini Free API Limits",
        topic="gemini free api limits",
        content_type="ai_work_tip",
        today="2026-10-14",
        source_citations=_CITES,
        **kw,
    )


def test_lean_html_has_no_disabled_blocks_and_one_summary():
    html = _lean()
    for block_id in DISABLED:
        assert block_id not in html
    assert html.count('id="AI_OVERVIEW_TARGET_ANSWER"') == 1
    # 본문 verdict-box 에 id 를 단다 — 새 요약 문장을 만들지 않는다.
    assert re.search(r'<div id="AI_OVERVIEW_TARGET_ANSWER" class="yomi-lede verdict-box"', html)
    assert "Sources (last verified 2026-10-14)" in html
    # 공식 출처만 남고 커뮤니티 링크는 공식 출처가 있으면 뺀다.
    source_block = re.search(r'id="SOURCE_TRUST_BLOCK".*?</section>', html, re.S).group(0)
    assert "ai.google.dev/gemini-api" in source_block and "discuss.ai.google.dev" not in source_block
    for phrase in (
        "Test it on one low-stakes task first",
        "The article separates what",
        "Pricing tiers and feature rollouts change",
    ):
        assert phrase not in html


def test_lean_html_is_idempotent():
    once = _lean()
    twice = _lean(once)
    assert twice.count('id="SOURCE_TRUST_BLOCK"') == 1
    assert twice.count('class="ai-disclosure"') == 1
    assert twice.count('"@type": "BlogPosting"') == 1


def test_lean_html_has_no_forced_faq():
    html = _lean()
    assert "FAQPage" not in html
    assert 'class="faq-q"' not in html and "intent-qa-item" not in re.sub(r"<style.*?</style>", "", html, flags=re.S)


def test_lean_html_keeps_real_faq_with_json_ld():
    body = _BODY.replace(
        "</article>",
        '<h2>Frequently Asked Questions</h2><section class="faq-section"><article class="faq-item">'
        '<h3 class="faq-q">Do failed retries count against the Gemini daily limit?</h3>'
        '<p class="faq-a">Yes. Every request counts toward the 250 daily requests, including retries that return errors.</p>'
        "</article></section></article>",
    )
    html = _lean(body)
    assert '"@type": "FAQPage"' in html


def test_disclosure_text_follows_publish_mode(monkeypatch):
    assert "then reviewed before publishing" not in _lean()
    assert "Drafted with AI assistance from the official sources linked above." in _lean()
    monkeypatch.setenv("NEWS_PUBLISH_AS_DRAFT", "true")
    assert (
        "Drafted with AI assistance from the official sources linked above, then reviewed before publishing."
        in _lean()
    )
    monkeypatch.setenv("AI_DISCLOSURE_MODE", "off")
    assert "ai-disclosure" not in _lean()


def test_blogposting_author_is_person_yomi():
    html = _lean()
    payloads = [
        json.loads(m)
        for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    ]
    posting = next(p for p in payloads if p.get("@type") == "BlogPosting")
    assert posting["author"] == {**posting["author"], "@type": "Person", "name": "Yomi"}


def test_workflow_author_env_is_yomi():
    yml = (Path(__file__).parents[1] / ".github" / "workflows" / "ai_blog.yml").read_text(encoding="utf-8")
    assert 'BLOG_AUTHOR_NAME: "Yomi"' in yml


def test_lean_coverage_passes_publish_contract_keys():
    cov = answer_engine_coverage(_lean())
    assert cov["ai_overview_target_answer_present"]
    assert cov["source_trust_block_present"]
    assert cov["blogposting_json_ld_present"]


def test_legacy_env_restores_old_blocks(monkeypatch):
    monkeypatch.setenv("EN_LEGACY_GEO_BLOCKS", "on")
    html = _lean()
    assert 'id="INTENT_ANSWER_BLOCK"' in html


def test_korean_mode_is_unchanged(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    assert policy.legacy_geo_blocks_enabled() is True
    html = ensure_answer_engine_optimized_html(
        "<h1>제목</h1><p>본문 첫 문단입니다. 충분히 긴 설명을 담고 있습니다.</p>",
        title="제목",
        topic="주제",
        today="2026-10-14",
    )
    assert 'id="INTENT_ANSWER_BLOCK"' in html


# ── 제목 어순 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("copilot how to use agents: Publishing for Organizations 2026",
         "How to Use Copilot Agents: Publishing for Organizations 2026"),
        ("grok how to use free in morocco", "How to Use Grok Free in Morocco"),
        ("OpenAI How to Use ChatGPT Lawsuit Briefs Unsealed 2026",
         "OpenAI How to Use ChatGPT Lawsuit Briefs Unsealed 2026"),  # 사건형은 그대로 → 무결성 차단
    ],
)
def test_spliced_how_to_use_titles_are_reordered_or_left_for_blocking(raw, expected):
    from blogspot_automation.services.title_candidate_service import normalize_english_title
    from blogspot_automation.services.title_integrity_policy import audit_title_integrity

    fixed = normalize_english_title(raw)
    assert fixed == expected
    blocked = "spliced_how_to_use_event_title" in audit_title_integrity(fixed).get("blocking_issues", [])
    assert blocked == ("Lawsuit" in raw)


@pytest.mark.parametrize(
    "title",
    [
        "Claude How to Use Agents: Frontier Academy $100M Trains 10k Engineers 2026",
        "Grok How to Use Free in Morocco Tesla Update 2026",
    ],
)
def test_live_spliced_titles_are_blocked_by_integrity(title):
    from blogspot_automation.services.title_integrity_policy import audit_title_integrity

    assert "spliced_how_to_use_event_title" in audit_title_integrity(title)["blocking_issues"]


# ── 생성 단계 계약 ───────────────────────────────────────────────────────────
def test_strict_numbers_make_counts_hard_violations():
    from blogspot_automation.services.source_grounding_service import audit_grounding

    report = audit_grounding(
        "<p>Grok's free tier allows roughly 200 messages per day.</p>",
        "Grok has a free tier and paid SuperGrok plans.",
    )
    assert any("200 messages" in v for v in report.hard_violations)


def test_strict_numbers_off_restores_dollar_only(monkeypatch):
    from blogspot_automation.services.source_grounding_service import audit_grounding

    monkeypatch.setenv("SOURCE_GROUNDING_STRICT_NUMBERS", "off")
    report = audit_grounding("<p>roughly 200 messages per day.</p>", "Grok has a free tier.")
    assert report.hard_violations == []


def test_length_targets_scale_with_facts():
    from blogspot_automation.services.llm_content_service import _length_targets_for_facts

    thin = _length_targets_for_facts("x" * 500)
    mid = _length_targets_for_facts("x" * 3000)
    rich = _length_targets_for_facts("x" * 7500)
    assert thin[1] == 800 and rich[2] == 1400
    assert thin[0] < mid[0] < rich[0] <= 800
    assert thin[2] < mid[2] < rich[2]


def test_prompt_drops_fixed_template_and_requires_verdict():
    from blogspot_automation.services.llm_content_service import (
        _SYSTEM_PROMPT_EN,
        _USER_PROMPT_TMPL_EN,
    )

    prompt = _SYSTEM_PROMPT_EN + _USER_PROMPT_TMPL_EN
    for gone in (
        "EXACTLY 3 FAQs",
        "MANDATORY: one comparison",
        "CONFIRMED_VS_CHECK_NEEDED_BLOCK",
        "Pre-flight checklist",
        "Use it now if",
    ):
        assert gone not in prompt
    for needed in ("VERDICT DUTY", "[SOURCE LINKS", "we tested", "fix", "pricing-limits", "comparison", "how-to", "news-analysis"):
        assert needed in prompt


def test_validator_rejects_repeated_sentence_anywhere():
    from blogspot_automation.services.llm_content_service import (
        _ContentValidationError,
        _validate_generated_content,
    )

    repeated = "ChatGPT Classic keeps receiving model updates and security patches."
    filler = " ".join(f"<p>Sentence number {i} explains a different sourced point in plain words.</p>" for i in range(80))
    html = f"<p>{repeated}</p>{filler}<p>{repeated}</p>"
    with pytest.raises(_ContentValidationError):
        _validate_generated_content(html, min_words=50)
