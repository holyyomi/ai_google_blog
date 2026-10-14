"""엔티티+의도 30일 쿨다운·DEDUP_DAYS 30·AI 신호 필터 (2026-10-14).

실측 사고: "ChatGPT vs Codex"가 8일 만에 재발행, "Gemini Free API Limits" 류 3편,
"Volvo EX40"·"Splunk earnings" 같은 비AI 글이 AI 블로그에 발행.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.news_focus_policy import evaluate_news_focus
from blogspot_automation.services.topic_dedup_service import (
    TopicDedupService,
    entity_intent_key,
)

ROOT = Path(__file__).resolve().parents[1]


def _scored(topic: str, *, raw: dict | None = None) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(topic=topic, category="ai", summary="", raw=raw or {}),
        freshness_score=20,
        search_demand_score=20,
        contrarian_gap_score=20,
        mass_impact_score=20,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="",
    )


def _published(title: str, *, days_ago: int) -> dict:
    return {
        "date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "status": "published",
        "published": True,
        "title": title,
    }


@pytest.fixture
def en_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.delenv("ENTITY_INTENT_COOLDOWN_DAYS", raising=False)
    monkeypatch.delenv("ENTITY_INTENT_COOLDOWN_INTENTS", raising=False)


def _service() -> TopicDedupService:
    # 다른 규칙(콘텐츠 dedup·회사 쿨다운)을 꺼서 이 쿨다운만 본다.
    return TopicDedupService(dedup_days=0, entity_cooldown_days=0)


def test_key_ignores_word_order_and_tail() -> None:
    a = entity_intent_key("ChatGPT vs Codex: Which One Wins?")
    b = entity_intent_key("Codex vs ChatGPT: migration guide for teams")
    assert a == b == (frozenset({"chatgpt", "codex"}), "comparison")


def test_key_gemini_free_limits_is_pricing_limits() -> None:
    assert entity_intent_key("Gemini Free API Limits Explained (2026)") == (
        frozenset({"gemini"}),
        "pricing-limits",
    )


def test_comparison_repeat_within_30_days_blocked(en_mode) -> None:
    history = [_published("ChatGPT vs Codex: Which One Wins? (2026)", days_ago=8)]
    assert _service().is_duplicate(_scored("Codex vs ChatGPT: migration for small teams"), history)


def test_gemini_limits_repeat_blocked_even_for_big_issue_and_cluster(en_mode) -> None:
    history = [_published("Gemini Free API Limits: What Changed (2026)", days_ago=12)]
    raw = {"today_buzz_score": 99, "topic_cluster": True, "cluster_slot": "gemini_limits"}
    assert _service().is_duplicate(_scored("gemini api free tier limits per day", raw=raw), history)


def test_older_than_30_days_allowed(en_mode) -> None:
    history = [_published("ChatGPT vs Codex: Which One Wins? (2026)", days_ago=31)]
    assert not _service().is_duplicate(_scored("Codex vs ChatGPT for beginners"), history)


def test_different_entity_set_or_intent_allowed(en_mode) -> None:
    history = [_published("ChatGPT vs Codex: Which One Wins? (2026)", days_ago=3)]
    service = _service()
    assert not service.is_duplicate(_scored("ChatGPT vs Claude for long documents"), history)
    assert not service.is_duplicate(_scored("ChatGPT and Codex pricing for students"), history)


def test_news_intent_not_cooled_by_default(en_mode) -> None:
    history = [_published("OpenAI acquires a coding startup", days_ago=2)]
    assert not _service().is_duplicate(_scored("OpenAI unveils new hardware team"), history)


def test_env_controls_window(en_mode, monkeypatch) -> None:
    monkeypatch.setenv("ENTITY_INTENT_COOLDOWN_DAYS", "5")
    history = [_published("ChatGPT vs Codex: Which One Wins? (2026)", days_ago=8)]
    assert not _service().is_duplicate(_scored("Codex vs ChatGPT"), history)
    monkeypatch.setenv("ENTITY_INTENT_COOLDOWN_DAYS", "0")
    history = [_published("ChatGPT vs Codex", days_ago=1)]
    assert not _service().is_duplicate(_scored("Codex vs ChatGPT"), history)


def test_korean_mode_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    history = [_published("ChatGPT vs Codex: Which One Wins? (2026)", days_ago=8)]
    assert not _service().is_duplicate(_scored("Codex vs ChatGPT"), history)


def test_dedup_days_defaults_are_30() -> None:
    assert TopicDedupService().dedup_days == 30
    workflow = (ROOT / ".github" / "workflows" / "ai_blog.yml").read_text(encoding="utf-8")
    assert 'DEDUP_DAYS: "30"' in workflow
    settings_src = (ROOT / "src" / "blogspot_automation" / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'os.getenv("DEDUP_DAYS", "30")' in settings_src


# ─── AI 신호 필터 ───────────────────────────────────────────────────────────

@pytest.fixture
def en_ai_blog(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("AI_SIGNAL_FILTER", raising=False)


_AI_META = {"topic_group": "ai_work", "content_type": "ai_work_tip"}


@pytest.mark.parametrize(
    "topic,summary",
    [
        ("Volvo EX40 gets a new battery and longer range", "The compact electric SUV gets a refresh."),
        ("Splunk earnings beat expectations in third quarter", "Shares rose after the report."),
    ],
)
def test_non_ai_news_blocked_even_with_ai_metadata(en_ai_blog, topic, summary) -> None:
    decision = evaluate_news_focus(topic=topic, summary=summary, raw=dict(_AI_META))
    assert not decision.allowed
    assert decision.reason == "non_ai_topic_blocked_no_ai_signal"


@pytest.mark.parametrize(
    "topic",
    [
        "Splunk adds AI agent to its security platform",
        "Anthropic ships a new reasoning model",
        "Ollama adds support for open-weight models",
    ],
)
def test_ai_signal_passes(en_ai_blog, topic) -> None:
    assert evaluate_news_focus(topic=topic, raw=dict(_AI_META)).allowed


def test_evergreen_and_cluster_candidates_not_subject_to_signal_filter(en_ai_blog) -> None:
    raw = dict(_AI_META, evergreen_fallback=True)
    assert evaluate_news_focus(topic="Volvo EX40 range test", raw=raw).reason != "non_ai_topic_blocked_no_ai_signal"


def test_signal_filter_off_in_korean_mode(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    decision = evaluate_news_focus(topic="Volvo EX40 gets a new battery", raw=dict(_AI_META))
    assert decision.reason != "non_ai_topic_blocked_no_ai_signal"
