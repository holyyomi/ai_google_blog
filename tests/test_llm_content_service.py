from __future__ import annotations

import json
import urllib.request

from blogspot_automation.services import llm_content_service as module
from blogspot_automation.services.llm_content_service import LlmContentService


def test_llm_provider_order_uses_openrouter_before_openai_fallback() -> None:
    names = [provider["name"] for provider in module._PROVIDERS]

    assert names == [
        "openrouter_primary",
        "openai_api_fallback",
    ]
    assert [p["api_key_env"] for p in module._PROVIDERS] == [
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]


def test_llm_provider_chain_excludes_gemini_for_main_generation() -> None:
    assert all(provider["api_key_env"] != "GOOGLE_AI_API_KEY" for provider in module._PROVIDERS)
    assert all("gemini" not in provider["name"] for provider in module._PROVIDERS)


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


def test_gemini_native_generate_content_api_still_available_for_direct_calls(monkeypatch) -> None:
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
        {
            "name": "gemini_direct",
            "provider_type": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key_env": "GOOGLE_AI_API_KEY",
            "model_env": "GEMINI_MODEL",
            "model": "gemini-2.5-flash",
            "free": True,
            "max_tokens": 16384,
            "extra_headers": {},
        },
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


def test_openrouter_primary_uses_openrouter_url_and_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>openrouter generated html</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._call_provider(
        next(provider for provider in module._PROVIDERS if provider["name"] == "openrouter_primary"),
        "test-key",
        "Write a post",
        "System prompt",
    )

    assert result == "<p>openrouter generated html</p>"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["timeout"] == 45
    assert captured["payload"]["model"] == "openai/gpt-oss-120b:free"
    assert captured["payload"]["max_tokens"] == 12000
    assert captured["payload"]["temperature"] == 0.7
    assert captured["headers"]["Http-referer"] == "https://holyyomiai.blogspot.com/"
    assert captured["headers"]["X-title"] == "holyyomi AI"


def test_call_with_fallback_uses_openai_when_openrouter_fails(monkeypatch) -> None:
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
        if "openrouter.ai" in req.full_url:
            raise RuntimeError("openrouter failed")
        return FakeOpenAIResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService().call_with_fallback("Write a post", "System prompt", min_chars=20)

    assert result and "openai fallback" in result
    # flash → flash-lite(둘 다 Gemini, 실패) → openai 폴백 = 3회
    assert len(calls) == 2
    assert calls[0] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[1] == "https://api.openai.com/v1/chat/completions"
