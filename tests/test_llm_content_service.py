from __future__ import annotations

import json
import urllib.request

from blogspot_automation.services import llm_content_service as module
from blogspot_automation.services.llm_content_service import LlmContentService


def test_llm_provider_order_prefers_free_before_paid_fallbacks() -> None:
    names = [provider["name"] for provider in module._PROVIDERS]

    assert names == [
        "gemini_free",
        "gemini_flash_lite",
        "openai_api_fallback",
    ]
    # 무료(Gemini) 2개가 유료(OpenAI) 앞에 와야 한다.
    assert [p["free"] for p in module._PROVIDERS] == [True, True, False]


def test_llm_provider_chain_excludes_openrouter() -> None:
    assert all(provider["api_key_env"] != "OPENROUTER_API_KEY" for provider in module._PROVIDERS)
    assert all("openrouter" not in provider["name"] for provider in module._PROVIDERS)


def test_custom_search_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_GOOGLE_CUSTOM_SEARCH", raising=False)
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx")

    svc = LlmContentService()

    assert svc._enable_custom_search is False
    assert svc._search_api_key == ""
    assert svc._search_cx == ""


def test_custom_search_can_be_enabled_for_fact_gathering(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "true")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx")

    svc = LlmContentService()

    assert svc._enable_custom_search is True
    assert svc._search_api_key == "search-key"
    assert svc._search_cx == "cx"


def test_gemini_primary_uses_native_generate_content_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": "<p>gemini generated html</p>"}]},
                }],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._call_provider(
        next(provider for provider in module._PROVIDERS if provider["name"] == "gemini_free"),
        "gemini-key",
        "Write a post",
        "System prompt",
    )

    assert result == "<p>gemini generated html</p>"
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.5-flash:generateContent?key=gemini-key"
    )
    assert captured["timeout"] == 45
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "System prompt"
    assert captured["payload"]["contents"][0]["parts"][0]["text"] == "Write a post"
    assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 16384
    # gemini-2.5-flash thinking 비활성화(렌더 안정성) 회귀 방지
    assert captured["payload"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0


def test_openai_primary_uses_official_url_and_current_default_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>generated html</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._call_provider(
        next(provider for provider in module._PROVIDERS if provider["name"] == "openai_api_fallback"),
        "test-key",
        "Write a post",
        "System prompt",
    )

    assert result == "<p>generated html</p>"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["timeout"] == 45
    assert captured["payload"]["model"] == "gpt-5-mini"
    assert captured["payload"]["max_completion_tokens"] == 12000
    assert "max_tokens" not in captured["payload"]
    assert "temperature" not in captured["payload"]


def test_call_with_fallback_uses_openai_when_gemini_fails(monkeypatch) -> None:
    calls: list[str] = []

    class FakeOpenAIResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>" + ("openai fallback " * 30) + "</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        del timeout
        calls.append(req.full_url)
        if "generativelanguage.googleapis.com" in req.full_url:
            raise RuntimeError("gemini failed")
        return FakeOpenAIResponse()

    monkeypatch.setenv("GOOGLE_AI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService().call_with_fallback("Write a post", "System prompt", min_chars=20)

    assert result and "openai fallback" in result
    # flash → flash-lite(둘 다 Gemini, 실패) → openai 폴백 = 3회
    assert len(calls) == 3
    assert "generativelanguage.googleapis.com" in calls[0]
    assert "generativelanguage.googleapis.com" in calls[1]
    assert calls[2] == "https://api.openai.com/v1/chat/completions"
