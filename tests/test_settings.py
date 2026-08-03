from __future__ import annotations

import pytest

from blogspot_automation.config import settings as settings_module
from blogspot_automation.config.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_from_local_dotenv(monkeypatch):
    """개발자 로컬 `.env`가 테스트 판정에 새어들어오지 않게 막는다.

    `Settings.from_env()`는 `_load_dotenv(Path(".env"))`를 호출하고, 그 함수는
    `os.environ.setdefault`를 쓴다. 즉 테스트가 명시적으로 monkeypatch하지 않은
    변수는 로컬 `.env` 값이 그대로 들어온다. 2026-08-03에 운영 정책상
    `.env`에 `ENABLE_TAVILY_SEARCH=false`를 넣자마자 "키가 있으면 기본 활성"을
    검증하던 이 파일의 테스트가 로컬에서만 깨졌다(CI는 `.env`가 없어 통과).
    기본값 파생을 검증하는 테스트는 `.env`와 무관해야 한다.
    """
    monkeypatch.setattr(settings_module, "_load_dotenv", lambda _path: None)


def test_settings_from_env_loads_news_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "search-cx")
    monkeypatch.setenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "true")
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    monkeypatch.setenv("ENABLE_NAVER_SEARCH", "true")
    monkeypatch.setenv("ENABLE_NAVER_DATALAB", "true")
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
