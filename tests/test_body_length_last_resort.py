"""전 provider가 길이 때문에 실패했을 때 '글 없음' 대신 최선 초안을 쓰는 경로.

2026-08-26 GHA 리허설 실측: 후보 4개가 연속으로 1119·1153·1277·1392단어를 냈고
전부 폐기돼 그날 클러스터 슬롯이 통째로 밀렸다. 대안은 1500단어 글이 아니라 글 없음이다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services import llm_content_service as L


def _body(words: int) -> str:
    return "<p>" + " ".join(f"word{i}" for i in range(words)) + "</p>"


@pytest.fixture(autouse=True)
def _en_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("EN_ACCEPTABLE_BODY_WORDS", raising=False)


def _shortfall_validator(text: str) -> None:
    import re

    count = L.count_body_words(re.sub(r"<[^>]+>", " ", text))
    if count < L.EN_MIN_BODY_WORDS:
        raise L._WordCountShortfallError(count, L.EN_MIN_BODY_WORDS)


def test_long_enough_best_effort_is_published_instead_of_nothing(monkeypatch):
    draft = _body(1400)
    monkeypatch.setattr(L.LlmContentService, "_call_provider", lambda *a, **k: draft)

    result = L.LlmContentService().call_with_fallback(
        "prompt", min_chars=10, validator=_shortfall_validator,
    )
    assert result == draft


def test_too_short_best_effort_is_still_rejected(monkeypatch):
    """예전 사고 재발 방지: 아무거나 채택하는 게 아니라 하한이 있다."""
    draft = _body(900)
    monkeypatch.setattr(L.LlmContentService, "_call_provider", lambda *a, **k: draft)

    assert L.LlmContentService().call_with_fallback(
        "prompt", min_chars=10, validator=_shortfall_validator,
    ) is None


def test_non_length_failures_are_never_accepted(monkeypatch):
    """절단·한국어 혼입·FAQ 파손은 '짧은' 게 아니라 '깨진' 것이다 — 채택 금지."""
    draft = _body(1400)
    monkeypatch.setattr(L.LlmContentService, "_call_provider", lambda *a, **k: draft)

    def broken(text: str) -> None:
        raise L._ContentValidationError("응답이 태그로 끝나지 않음 — 중간 절단 의심")

    assert L.LlmContentService().call_with_fallback(
        "prompt", min_chars=10, validator=broken,
    ) is None


def test_floor_is_env_tunable(monkeypatch):
    monkeypatch.setenv("EN_ACCEPTABLE_BODY_WORDS", "1450")
    draft = _body(1400)
    monkeypatch.setattr(L.LlmContentService, "_call_provider", lambda *a, **k: draft)

    assert L.LlmContentService().call_with_fallback(
        "prompt", min_chars=10, validator=_shortfall_validator,
    ) is None


def test_a_passing_draft_still_wins_over_the_last_resort(monkeypatch):
    """정상 경로가 그대로여야 한다 — 최후 수단이 통과본을 가로채면 안 된다."""
    good = _body(1600)
    monkeypatch.setattr(L.LlmContentService, "_call_provider", lambda *a, **k: good)

    assert L.LlmContentService().call_with_fallback(
        "prompt", min_chars=10, validator=_shortfall_validator,
    ) == good


def test_longest_draft_across_providers_is_kept(monkeypatch):
    drafts = [_body(1310), _body(1480), _body(1200)]
    calls = {"n": 0}

    def fake(self, provider, api_key, user_prompt, system_prompt=None):
        index = min(calls["n"], len(drafts) - 1)
        calls["n"] += 1
        return drafts[index]

    monkeypatch.setattr(L.LlmContentService, "_call_provider", fake)
    result = L.LlmContentService().call_with_fallback(
        "prompt", min_chars=10, validator=_shortfall_validator,
    )
    assert result == drafts[1], "가장 긴 초안이 아니라 다른 걸 골랐다"
