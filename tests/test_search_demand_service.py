from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services import ai_slot_enricher
from blogspot_automation.services import autocomplete_client
from blogspot_automation.services import search_demand_service as demand
from blogspot_automation.services.news_quality_gate import NewsQualityGate
from blogspot_automation.services.title_candidate_service import TitleCandidateService


@pytest.fixture(autouse=True)
def _reset_search_demand(monkeypatch):
    demand._reset_for_tests()
    monkeypatch.setenv("ENABLE_SEARCH_DEMAND", "true")
    monkeypatch.delenv("SEARCH_DEMAND_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("SEARCH_DEMAND_TIMEOUT", raising=False)
    monkeypatch.delenv("BLOG_LANGUAGE", raising=False)
    yield
    demand._reset_for_tests()


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _urlopen_factory(payloads: dict[str, list[str] | BaseException], calls: list[tuple[str, float | None]]):
    def _fake_urlopen(req, timeout=None):  # noqa: ANN001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert url.startswith("https://suggestqueries.google.com/complete/search?")
        params = parse_qs(urlsplit(url).query)
        assert params.get("client") == ["firefox"]
        assert params.get("hl") == ["en"]
        query = params["q"][0]
        calls.append((query, timeout))
        payload = payloads.get(query, [])
        if isinstance(payload, BaseException):
            raise payload
        return _FakeResponse(json.dumps([query, payload]).encode("utf-8"))

    return _fake_urlopen


def test_collect_demand_parses_dedupes_longtails_and_questions(monkeypatch):
    calls: list[tuple[str, float | None]] = []
    monkeypatch.setattr(
        autocomplete_client.request,
        "urlopen",
        _urlopen_factory(
            {
                "gpt-5.6 pricing": [
                    "gpt-5.6 pricing",
                    "gpt-5.6 pricing calculator",
                    "gpt-5.6 pricing calculator",
                    "what is gpt-5.6 pricing",
                ],
                "gpt-5.6": [
                    "gpt-5.6 pricing",
                    "gpt-5.6 release date",
                    "gpt-5.6 vs claude",
                ],
            },
            calls,
        ),
    )

    result = demand.collect_demand_phrases("GPT-5.6 pricing update", limit=4)

    assert result["measured"] is True
    assert result["seeds"][:2] == ["gpt-5.6 pricing", "gpt-5.6"]
    assert result["phrases"] == [
        "gpt-5.6 pricing calculator",
        "what is gpt-5.6 pricing",
        "gpt-5.6 release date",
        "gpt-5.6 vs claude",
    ]
    assert "gpt-5.6 pricing" not in result["phrases"]
    assert result["questions"] == [
        "gpt-5.6 pricing calculator",
        "what is gpt-5.6 pricing",
        "gpt-5.6 vs claude",
    ]
    assert [call[0] for call in calls] == ["gpt-5.6 pricing", "gpt-5.6"]


def test_fetch_suggestions_uses_seed_cache(monkeypatch):
    calls: list[tuple[str, float | None]] = []
    monkeypatch.setattr(
        autocomplete_client.request,
        "urlopen",
        _urlopen_factory({"grok pricing": ["grok pricing plans"]}, calls),
    )

    assert demand.fetch_suggestions("Grok pricing") == ["grok pricing plans"]
    assert demand.fetch_suggestions("grok pricing") == ["grok pricing plans"]
    assert [call[0] for call in calls] == ["grok pricing"]


def test_all_failures_are_nonfatal_and_open_circuit(monkeypatch):
    calls: list[tuple[str, float | None]] = []
    monkeypatch.setattr(
        autocomplete_client.request,
        "urlopen",
        _urlopen_factory(
            {
                "grok pricing": OSError("down"),
                "grok api": OSError("down"),
                "grok risks": OSError("down"),
            },
            calls,
        ),
    )

    result = demand.collect_demand_phrases("Grok pricing API risks", limit=10)

    assert result["measured"] is False
    assert result["phrases"] == []
    assert result["failures"] >= 2
    assert [call[0] for call in calls] == ["grok pricing", "grok api"]


def test_extract_seeds_gets_product_names_from_headlines():
    assert "grok" in demand.extract_seeds(
        "SpaceXAI Southaven Plant Hearing Postponed Grok Risk 2026",
        limit=3,
    )
    assert demand.extract_seeds("Microsoft Copilot security settings", limit=3) == [
        "microsoft copilot security",
        "microsoft copilot settings",
        "microsoft copilot",
    ]
    assert demand.extract_seeds("OpenAI GPT-5.6 pricing change", limit=2)[0] == "gpt-5.6 pricing"


class _FakeLlm:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.prompts: list[str] = []

    def gather_facts(self, topic: str) -> str:
        return ""

    def call_with_fallback(self, user_prompt, system_prompt=None, min_chars=0, validator=None):  # noqa: ANN001
        self.prompts.append(user_prompt)
        text = json.dumps(self.response)
        if validator is not None:
            validator(text)
        return text


def _enrich_response() -> dict:
    return {
        "title": "Claude Code Pricing Guide 2026",
        "hook_opening": "Claude Code pricing now matters because teams need to know whether the subscription is worth it.",
        "yomi_judgment": "Use official billing information as the source of truth, then separate install steps from pricing claims.",
        "real_criterion": "Check the plan page, install path, seat policy, and usage limits before relying on the tool.",
        "misconceptions": [{"wrong": "Claude Code is always free", "real": "Plan limits can vary by account."}],
        "faq": [
            {"Q": "How much does Claude Code cost?", "A": "Check the official pricing page before subscribing."},
            {"Q": "Can Claude Code be installed locally?", "A": "Follow the current install instructions for your environment."},
            {"Q": "Is Claude Code free?", "A": "Free access depends on the current account and plan rules."},
        ],
    }


def test_measured_demand_is_added_to_english_prompt(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setattr(
        ai_slot_enricher,
        "collect_demand_phrases",
        lambda topic, raw=None: {
            "measured": True,
            "seeds": ["claude code pricing"],
            "phrases": ["claude code pricing", "claude code install", "claude code skills"],
            "questions": ["claude code pricing", "claude code install", "claude code skills"],
            # 2026-08-25부터 프롬프트에 들어가는 건 phrases가 아니라 answerable이다.
            "answerable": ["claude code pricing", "claude code install", "claude code skills"],
            "excluded": [],
            "failures": 0,
        },
    )
    llm = _FakeLlm(_enrich_response())

    out = ai_slot_enricher.enrich_slots_with_llm(
        slots={"hook_opening": "old", "yomi_judgment": "old", "faq": []},
        topic="Claude Code pricing",
        content_type="ai_tool_review",
        llm_service=llm,
    )

    assert "[MEASURED GOOGLE AUTOCOMPLETE SEARCH DEMAND]" in llm.prompts[0]
    assert "- claude code pricing" in llm.prompts[0]
    assert "verbatim" in llm.prompts[0]
    assert "Do not invent the `paa` list" in llm.prompts[0]
    assert out["_llm_demand_phrases"] == [
        "claude code pricing",
        "claude code install",
        "claude code skills",
    ]


def test_unmeasured_demand_does_not_change_english_prompt(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setattr(
        ai_slot_enricher,
        "collect_demand_phrases",
        lambda topic, raw=None: {
            "measured": False,
            "seeds": ["claude code pricing"],
            "phrases": ["claude code pricing"],
            "questions": [],
            "failures": 1,
        },
    )
    llm = _FakeLlm(_enrich_response())

    out = ai_slot_enricher.enrich_slots_with_llm(
        slots={"hook_opening": "old", "yomi_judgment": "old", "faq": []},
        topic="Claude Code pricing",
        content_type="ai_tool_review",
        llm_service=llm,
    )

    assert "[MEASURED GOOGLE AUTOCOMPLETE SEARCH DEMAND]" not in llm.prompts[0]
    assert "_llm_demand_phrases" not in out


def test_english_prompt_reuses_existing_demand_without_collect(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")

    def _unexpected_collect(topic, raw=None):  # noqa: ANN001
        raise AssertionError("existing measured demand should be reused")

    monkeypatch.setattr(ai_slot_enricher, "collect_demand_phrases", _unexpected_collect)
    llm = _FakeLlm(_enrich_response())

    out = ai_slot_enricher.enrich_slots_with_llm(
        slots={
            "hook_opening": "old",
            "yomi_judgment": "old",
            "faq": [],
            "_llm_demand_phrases": ["grok api"],
        },
        topic="Grok API",
        content_type="ai_tool_review",
        llm_service=llm,
    )

    assert "- grok api" in llm.prompts[0]
    assert out["_llm_demand_phrases"] == ["grok api"]


def test_score_title_adds_small_bonus_for_measured_phrase(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    svc = TitleCandidateService()
    title = "Claude Code Pricing Guide 2026"

    plain = svc.score_title(title)
    boosted = svc.score_title(title, demand_phrases=["claude code pricing"])
    missed = svc.score_title(title, demand_phrases=["claude code install"])

    assert boosted["ctr_score"] == min(100, plain["ctr_score"] + 8)
    assert missed["ctr_score"] == plain["ctr_score"]
    assert "measured_search_demand_bonus=8:claude code pricing" in boosted["reason"]


def _quality_candidate() -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(
            topic="Claude Code pricing update",
            category="ai_work",
            summary="Claude Code pricing and install considerations for working teams.",
            raw={
                "source_type": "google_news_rss",
                "topic_group": "ai_work",
                "content_angle": {"content_type": "ai_tool_review"},
                "hook_angle": {"safe_title_keyword": "Claude Code"},
                "click_potential_score": 9,
                "raw_total_score": 85,
                "measured_search_demand": True,
                "measured_search_demand_phrases": ["claude code pricing"],
            },
        ),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=15,
        mass_impact_score=15,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=85,
        reason="test",
    )


def _quality_html() -> str:
    body = " ".join(
        "Claude Code teams should verify current billing, install instructions, seat rules, and usage limits before rollout."
        for _ in range(90)
    )
    return f"""<html><head>
<meta name="description" content="Claude Code billing, install, and security checks for teams.">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[]}}</script>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BlogPosting","headline":"Claude Code Install Guide 2026"}}</script>
</head><body>
<h1>Claude Code Install Guide 2026</h1>
<section id="AI_OVERVIEW_TARGET_ANSWER">Claude Code users should verify billing and setup details before enabling it.</section>
<section id="ISSUE_CONTEXT_BLOCK">The practical issue is plan fit, setup effort, and account policy.</section>
<section id="INTENT_ANSWER_BLOCK"><h3>How much does Claude Code cost?</h3><p>Check the official pricing page.</p><h3>How do I install Claude Code?</h3><p>Use current install docs.</p><h3>Is Claude Code safe for work?</h3><p>Review company policy first.</p></section>
<section id="SOURCE_TRUST_BLOCK">Verify prices and setup steps on the official pages.</section>
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK"><h3>What's confirmed</h3><ul><li>Teams need setup checks.</li></ul><h3>Check for yourself</h3><ul><li>Current prices.</li></ul></section>
<section class="hero-summary-box">Summary</section>
<section class="target-reader-box">Team users</section>
<section class="core-message-box">Verify before rollout</section>
<section class="key-fact-cards">Billing, setup, policy</section>
<div class="checklist">Check plan, install path, permissions, and data policy.</div>
<div class="warning">Do not assume every account has the same limits.</div>
<section class="faq-card"><h3>How much does Claude Code cost?</h3><p>Use the official pricing page.</p></section>
<section class="faq-card"><h3>How do I install Claude Code?</h3><p>Use the current install instructions.</p></section>
<section class="faq-card"><h3>Can teams use Claude Code safely?</h3><p>Review company data policy first.</p></section>
<section class="yomi-judgment-box">Check price, install path, and policy before rollout.</section>
<section class="misconception-box">It is not safe to assume every account has the same limits.</section>
<section class="quick-decision-table"><table><tr><td>Use it</td><td>When policy allows it</td></tr></table></section>
<p>{body}</p>
</body></html>"""


def test_quality_gate_warns_only_when_measured_title_phrase_missing(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")

    result = NewsQualityGate().evaluate(
        selected=_quality_candidate(),
        selected_title="Claude Code Install Guide 2026",
        html=_quality_html(),
        image_prompt="A clean editorial image about Claude Code setup.",
        image_alt_text="Claude Code setup and billing checklist",
        labels=["AI", "Claude Code"],
        hashtags=["#ClaudeCode"],
    )

    assert "title_without_measured_search_demand" in result["warnings"]
    assert "title_without_measured_search_demand" not in result["blocking_issues"]


def test_lookalike_entity_suggestions_are_dropped():
    """자동완성이 철자 비슷한 다른 엔티티로 새면 그 제안은 수요가 아니다.

    2026-08-25 실측: 시드 "spacexai"에 "spacex stock price"(다른 회사 주가)가
    돌아왔다. 길이만 보는 필터는 이걸 통과시켜 엉뚱한 검색어를 제목에 박게 된다.
    """
    assert demand._is_longtail("spacex stock price", "spacexai") is False
    assert demand._is_longtail("spacexai grok colossus", "spacexai") is True


def test_version_notation_differences_still_count_as_demand():
    """"gpt-5.6" / "gpt 5.6"처럼 표기만 다른 건 같은 수요로 본다."""
    assert demand._is_longtail("gpt 5.6 pricing", "gpt-5.6") is True
    assert demand._is_longtail("claude code install", "claude code") is True


def test_headline_without_intent_words_gets_default_intents():
    """의도어 없는 사건형 헤드라인도 가격·사용법 축으로는 수요를 잰다.

    맨 제품명 시드는 자동완성이 브랜드 일반어만 돌려줘 질문형 수확이 0이었다.
    """
    seeds = demand.extract_seeds("Google Gemini Rolls Out Proactive Briefs", limit=3)
    assert any(seed.startswith("gemini ") for seed in seeds), seeds
    assert "gemini pricing" in seeds or "gemini how to use" in seeds, seeds


def test_intent_words_in_headline_still_win_over_defaults():
    """헤드라인에 진짜 의도어가 있으면 기본 의도로 덮어쓰지 않는다."""
    seeds = demand.extract_seeds("Microsoft Copilot Security Flaws Let One Click Leak Data", limit=3)
    assert any("security" in seed for seed in seeds), seeds


def test_geo_suffix_suggestions_are_dropped():
    """US-first 블로그에 "pricing india" 류 지역 롱테일은 재료가 안 된다."""
    assert demand._GEO_NOISE.search("gemini pricing india")
    assert demand._GEO_NOISE.search("claude pricing korea")
    assert not demand._GEO_NOISE.search("claude pricing plans")


def test_event_words_in_headline_map_to_searched_intent_words():
    """기사 어휘(flaw/exfiltrate)를 검색창 어휘(security)로 번역한다.

    2026-08-25 실측: "Microsoft Copilot Personal Flaws ... Exfiltrate Data"가
    의도어를 못 찾아 기본값(pricing)으로 떨어졌고, 정작 사람들이 치는 건
    "microsoft copilot security risks"였다.
    """
    seeds = demand.extract_seeds(
        "Microsoft Copilot Personal Flaws Could Let One Click Exfiltrate Data", limit=3
    )
    assert any("security" in seed for seed in seeds), seeds


def test_plural_system_prompts_headline_is_recognized():
    seeds = demand.extract_seeds("Claude System Prompts: Core Updates for Web and Mobile", limit=3)
    assert any("system prompt" in seed for seed in seeds), seeds


def test_single_seed_cannot_monopolize_the_phrase_budget(monkeypatch):
    """한 시드가 limit을 다 먹으면 검색어가 한 축으로 도배된다."""
    calls: list[str] = []

    def fake_fetch(seed, *, lang, timeout):
        calls.append(seed)
        return [f"{seed} variant {i}" for i in range(10)], True

    monkeypatch.setattr(demand, "_fetch_suggestions_result", fake_fetch)
    demand.reset_state() if hasattr(demand, "reset_state") else None
    result = demand._collect_demand_phrases("Gemini Rolls Out Proactive Briefs", limit=12)
    assert len(calls) >= 2, calls
    for seed in calls:
        # 시드가 서로 접두사 관계라("gemini" ⊂ "gemini pricing") 정확히 그 시드가
        # 만든 문구만 센다.
        taken = [p for p in result["phrases"] if p.startswith(f"{seed} variant ")]
        assert len(taken) <= demand._PER_SEED_LIMIT, (seed, taken)


def test_unanswerable_queries_are_classified_and_excluded():
    """검색량이 있어도 블로그가 만족시킬 수 없는 질의는 재료에서 뺀다.

    2026-08-25 실측 사고: "claude status"가 자동완성에 잡힌다는 이유로
    "claude status 99.35% uptime 2026"을 발행했다. 그 검색을 하는 사람은
    실시간 상태 페이지를 원하지 어제 쓴 글을 원하지 않는다. 같은 측정 목록에
    "claude api pricing"처럼 답할 수 있는 게 있었는데도 못 답하는 걸 골랐다.
    """
    assert demand.classify_intent("claude status") == "realtime"
    assert demand.classify_intent("claude outage today") == "realtime"
    assert demand.classify_intent("claude down detector") == "realtime"
    assert demand.classify_intent("claude login") == "navigational"
    assert demand.classify_intent("claude app download") == "navigational"
    assert demand.classify_intent("claude api pricing") == "informational"
    assert demand.classify_intent("how to use claude code") == "informational"
    assert demand.classify_intent("claude vs chatgpt") == "informational"
    # 신호가 없는 브랜드 단독어는 좋은 검색어로 오인하지 않는다
    assert demand.classify_intent("claude ai") == "unknown"


def test_collect_splits_answerable_from_unanswerable(monkeypatch):
    def fake_fetch(seed, *, lang, timeout):
        return ["claude status page", "claude api pricing", "claude login", "claude api costs"], True

    monkeypatch.setattr(demand, "_fetch_suggestions_result", fake_fetch)
    result = demand._collect_demand_phrases("Claude API outage", limit=12)
    assert "claude api pricing" in result["answerable"]
    assert "claude api costs" in result["answerable"]
    assert all("status" not in p for p in result["answerable"]), result["answerable"]
    excluded = {row["phrase"] for row in result["excluded"]}
    assert "claude status page" in excluded
    assert "claude login" in excluded


def test_prompt_block_is_skipped_when_nothing_is_answerable(monkeypatch):
    """전부 못 쓰는 검색어면 검색어 블록을 아예 넣지 않는다 — 억지로 넣느니 뺀다."""
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setattr(
        ai_slot_enricher,
        "collect_demand_phrases",
        lambda topic, raw=None: {
            "measured": True,
            "seeds": ["claude status"],
            "phrases": ["claude status page", "claude down detector"],
            "questions": [],
            "answerable": [],
            "excluded": [{"phrase": "claude status page", "intent": "realtime", "reason": "realtime:status"}],
            "failures": 0,
        },
    )
    llm = _FakeLlm(_enrich_response())
    ai_slot_enricher.enrich_slots_with_llm(
        slots={"hook_opening": "old", "yomi_judgment": "old", "faq": []},
        topic="Anthropic Claude and API service outages",
        content_type="ai_tool_review",
        llm_service=llm,
    )
    assert "[MEASURED GOOGLE AUTOCOMPLETE SEARCH DEMAND]" not in llm.prompts[0]
