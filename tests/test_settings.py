from __future__ import annotations

from blogspot_automation.config.settings import Settings


def test_settings_from_env_loads_news_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "search-cx")
    monkeypatch.setenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "true")
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("EXA_API_KEY", "exa-key")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "firecrawl-key")
    monkeypatch.setenv("NEWS_TAVILY_MAX_REQUESTS", "4")

    settings = Settings.from_env()

    assert settings.google_ai_api_key == "gemini-key"
    assert settings.gemini_model == "gemini-test-model"
    assert settings.google_search_api_key == "search-key"
    assert settings.google_search_cx == "search-cx"
    assert settings.enable_google_custom_search is True
    assert settings.naver_client_id == "naver-id"
    assert settings.naver_client_secret == "naver-secret"
    assert settings.enable_naver_search is True
    assert settings.enable_naver_datalab is True
    assert settings.tavily_api_key == "tavily-key"
    assert settings.exa_api_key == "exa-key"
    assert settings.firecrawl_api_key == "firecrawl-key"
    assert settings.enable_tavily_search is True
    assert settings.news_tavily_max_requests == 4
