"""Google Autocomplete 수요 신호 테스트 (2026-07-22)."""
from __future__ import annotations

import pytest

from blogspot_automation.services import search_autocomplete_signal as sig
from blogspot_automation.services.search_autocomplete_signal import (
    SearchAutocompleteSignal,
    build_probe_query,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    SearchAutocompleteSignal.reset_cache()
    yield
    SearchAutocompleteSignal.reset_cache()


@pytest.fixture()
def _enabled(monkeypatch):
    # pytest는 각 단계마다 PYTEST_CURRENT_TEST를 다시 설정하므로 delenv로는
    # 자동 비활성 가드를 풀 수 없다 — 신호 자체 테스트는 함수를 직접 패치한다.
    monkeypatch.setattr(sig, "is_signal_enabled", lambda: True)


def test_probe_query_strips_stopwords_and_years():
    assert build_probe_query("AI assistant pricing and limits comparison 2026") == (
        "ai assistant pricing limits"
    )
    assert build_probe_query("best AI tools for students") == "ai tools students"


def test_high_suggestion_count_gives_max_boost(monkeypatch, _enabled):
    monkeypatch.setattr(
        sig, "_fetch_suggestions",
        lambda q: tuple(f"{q} variant {i}" for i in range(9)),
    )
    boost, keywords = SearchAutocompleteSignal.score_topic_demand(
        "chatgpt pricing plans", max_boost=12
    )
    assert boost == 12
    assert keywords and keywords[0].startswith("autocomplete:")


def test_zero_suggestions_means_no_boost(monkeypatch, _enabled):
    monkeypatch.setattr(sig, "_fetch_suggestions", lambda q: ())
    boost, keywords = SearchAutocompleteSignal.score_topic_demand("zxqv obscure topic")
    assert boost == 0
    assert keywords == []


def test_fetch_failure_is_non_fatal(monkeypatch, _enabled):
    def _boom(q):
        raise RuntimeError("network down")
    # suggestions_for 내부에서 _fetch_suggestions 예외는 발생하지 않는 계약이지만,
    # 혹시 모를 예외도 score 래퍼 밖으로 새지 않아야 한다.
    monkeypatch.setattr(sig, "_fetch_suggestions", lambda q: ())
    boost, _ = sig.score_topic_boost("chatgpt pricing")
    assert boost == 0


def test_cache_prevents_duplicate_fetches(monkeypatch, _enabled):
    calls = []

    def _fake_fetch(q):
        calls.append(q)
        return ("chatgpt pricing plans", "chatgpt pricing india")

    monkeypatch.setattr(sig, "_fetch_suggestions", _fake_fetch)
    SearchAutocompleteSignal.suggestions_for("chatgpt pricing")
    SearchAutocompleteSignal.suggestions_for("chatgpt pricing")
    assert len(calls) == 1


def test_disabled_under_pytest_env(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_x")
    assert sig.is_signal_enabled() is False
    assert SearchAutocompleteSignal.suggestions_for("chatgpt pricing") == ()
