"""GoogleAutocompleteSignal — 실검색 수요 실측 부스트 테스트 (네트워크 mock)."""
from __future__ import annotations

import io
import json
import os
from unittest.mock import patch

import pytest

from blogspot_automation.services.google_autocomplete_signal import (
    GoogleAutocompleteSignal,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    GoogleAutocompleteSignal.reset_cache_for_tests()
    yield
    GoogleAutocompleteSignal.reset_cache_for_tests()


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _fake_urlopen_factory(suggestions_by_query: dict[str, list[str]]):
    def _fake_urlopen(req, timeout=None):  # noqa: ANN001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for query, suggestions in suggestions_by_query.items():
            if query.replace(" ", "%20") in url or query.replace(" ", "+") in url:
                return _FakeResponse(json.dumps([query, suggestions]).encode())
        return _FakeResponse(json.dumps(["", []]).encode())

    return _fake_urlopen


class TestProbePhraseExtraction:
    def test_extracts_versioned_model_names(self):
        phrases = GoogleAutocompleteSignal.extract_probe_phrases(
            "GPT-5.6 price cuts lower costs as Gemini Robotics 2 launches"
        )
        assert "GPT-5.6" in phrases
        assert any("Gemini Robotics" in p for p in phrases)

    def test_drops_bare_brand_names(self):
        # 브랜드 단독명("ChatGPT")은 항상 자동완성이 가득해 신호가 아니다.
        phrases = GoogleAutocompleteSignal.extract_probe_phrases(
            "ChatGPT is down for many users"
        )
        assert "ChatGPT" not in phrases

    def test_drops_sentence_head_stopwords(self):
        phrases = GoogleAutocompleteSignal.extract_probe_phrases(
            "How Claude usage limits work"
        )
        assert not any(p.lower().startswith("how") for p in phrases)


class TestScoreTopicBoost:
    def test_boost_when_real_suggestions_contain_phrase(self):
        fake = _fake_urlopen_factory(
            {"GPT-5.6": ["gpt-5.6 price", "gpt-5.6 release date", "gpt-5.6 vs claude"]}
        )
        with patch(
            "blogspot_automation.services.google_autocomplete_signal.request.urlopen",
            side_effect=fake,
        ):
            boost, matched = GoogleAutocompleteSignal.score_topic_boost(
                "GPT-5.6 price cuts announced"
            )
        assert boost == 9  # 매칭 제안 3개 × 3점
        assert len(matched) == 3

    def test_zero_when_no_suggestions(self):
        fake = _fake_urlopen_factory({})
        with patch(
            "blogspot_automation.services.google_autocomplete_signal.request.urlopen",
            side_effect=fake,
        ):
            boost, matched = GoogleAutocompleteSignal.score_topic_boost(
                "Valar Atomics Raises Nuclear Funding"
            )
        assert boost == 0
        assert matched == []

    def test_boost_capped_at_max(self):
        many = [f"gpt-5.6 thing {i}" for i in range(10)]
        fake = _fake_urlopen_factory({"GPT-5.6": many})
        with patch(
            "blogspot_automation.services.google_autocomplete_signal.request.urlopen",
            side_effect=fake,
        ):
            boost, _ = GoogleAutocompleteSignal.score_topic_boost(
                "GPT-5.6 update", max_boost=15
            )
        assert boost == 15

    def test_kill_switch_env(self):
        with patch.dict(os.environ, {"ENABLE_GOOGLE_AUTOCOMPLETE_SIGNAL": "false"}):
            boost, matched = GoogleAutocompleteSignal.score_topic_boost("GPT-5.6 update")
        assert boost == 0
        assert matched == []

    def test_network_failure_is_silent_zero(self):
        with patch(
            "blogspot_automation.services.google_autocomplete_signal.request.urlopen",
            side_effect=OSError("boom"),
        ):
            boost, matched = GoogleAutocompleteSignal.score_topic_boost("GPT-5.6 update")
        assert boost == 0
        assert matched == []
