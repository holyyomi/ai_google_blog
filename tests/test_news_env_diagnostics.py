from __future__ import annotations

from blogspot_automation.services.news_env_diagnostics import build_news_env_diagnostics


def test_news_env_diagnostics_reports_free_first_chain() -> None:
    diagnostics = build_news_env_diagnostics({
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_MODEL": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "OPENAI_API_KEY": "openai-key",
        "OPENAI_MODEL": "gpt-test",
    })

    assert diagnostics["user_required_actions"] == []
    assert [item["name"] for item in diagnostics["provider_chain"]] == [
        "openrouter_primary",
        "openrouter_secondary",
        "openai_api_fallback",
    ]
    assert diagnostics["provider_chain"][0]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert diagnostics["provider_chain"][1]["model"] == "openai/gpt-oss-120b:free"
    assert diagnostics["provider_chain"][2]["model"] == "gpt-test"
    assert diagnostics["checks"]["enable_google_custom_search"]["value"] == "false"


def test_news_env_diagnostics_lists_only_user_owned_missing_keys() -> None:
    diagnostics = build_news_env_diagnostics({})

    assert "Create or register OPENROUTER_API_KEY for free-first article generation." in diagnostics["user_required_actions"]
    assert "Create or register OPENAI_API_KEY as paid fallback." in diagnostics["user_required_actions"]
    assert diagnostics["provider_chain"][0]["configured"] is False


def test_news_env_diagnostics_custom_search_keys_are_optional_by_default() -> None:
    diagnostics = build_news_env_diagnostics({
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_MODEL": "openai/gpt-oss-120b:free",
        "OPENAI_API_KEY": "openai-key",
    })

    assert diagnostics["ok"] is True
    assert diagnostics["checks"]["google_search_api_key"]["present"] is False
    assert diagnostics["checks"]["google_search_cx"]["present"] is False
    assert diagnostics["checks"]["ai_image_upload_key"]["present"] is False
    assert diagnostics["advisories"]
    assert diagnostics["checks"]["enable_google_custom_search"]["value"] == "false"
    assert diagnostics["user_required_actions"] == []


def test_news_env_diagnostics_reports_ai_image_upload_key() -> None:
    diagnostics = build_news_env_diagnostics({
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_MODEL": "openai/gpt-oss-120b:free",
        "OPENAI_API_KEY": "openai-key",
        "AI_IMAGE_UPLOAD_KEY": "img-upload-key",
        "AI_DEFAULT_COVER_IMAGE_URL": "https://cdn.example.com/default-ai-cover.png",
    })

    assert diagnostics["ok"] is True
    assert diagnostics["checks"]["ai_image_upload_key"]["present"] is True
    assert diagnostics["checks"]["ai_default_cover_image_url"]["present"] is True
    assert diagnostics["advisories"] == []


def test_news_env_diagnostics_reports_external_search_keys_without_values() -> None:
    diagnostics = build_news_env_diagnostics({
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_MODEL": "openai/gpt-oss-120b:free",
        "OPENAI_API_KEY": "openai-key",
        "NAVER_CLIENT_ID": "naver-id",
        "NAVER_CLIENT_SECRET": "naver-secret",
        "TAVILY_API_KEY": "tavily-key",
        "EXA_API_KEY": "exa-key",
        "FIRECRAWL_API_KEY": "firecrawl-key",
        "ENABLE_NAVER_SEARCH": "true",
        "ENABLE_TAVILY_SEARCH": "true",
    })

    assert diagnostics["ok"] is True
    assert diagnostics["checks"]["naver_client_id"]["present"] is True
    assert diagnostics["checks"]["naver_client_secret"]["value"] == ""
    assert diagnostics["checks"]["tavily_api_key"]["present"] is True
    assert diagnostics["checks"]["enable_naver_search"]["value"] == "true"
    assert diagnostics["checks"]["enable_tavily_search"]["value"] == "true"


def test_news_env_diagnostics_requires_blogger_only_for_live_auto_publish() -> None:
    diagnostics = build_news_env_diagnostics({
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_MODEL": "openai/gpt-oss-120b:free",
        "OPENAI_API_KEY": "openai-key",
        "DRY_RUN": "false",
        "NEWS_PUBLISH_MODE": "publish",
        "AUTO_PUBLISH": "true",
    })

    assert "Register BLOGGER_CLIENT_ID for scheduled Blogger publishing." in diagnostics["user_required_actions"]
    assert "Register BLOGGER_REFRESH_TOKEN for scheduled Blogger publishing." in diagnostics["user_required_actions"]
    assert diagnostics["checks"]["news_publish_mode"]["value"] == "publish"
    assert diagnostics["checks"]["auto_publish"]["value"] == "true"


def test_news_env_diagnostics_accepts_complete_live_publish_secrets() -> None:
    diagnostics = build_news_env_diagnostics({
        "OPENROUTER_API_KEY": "openrouter-key",
        "OPENROUTER_MODEL": "openai/gpt-oss-120b:free",
        "OPENAI_API_KEY": "openai-key",
        "DRY_RUN": "false",
        "NEWS_PUBLISH_MODE": "publish",
        "AUTO_PUBLISH": "true",
        "BLOGGER_CLIENT_ID": "client-id",
        "BLOGGER_CLIENT_SECRET": "client-secret",
        "BLOGGER_REFRESH_TOKEN": "refresh-token",
        "BLOGGER_BLOG_ID": "blog-id",
    })

    assert diagnostics["user_required_actions"] == []
    assert diagnostics["checks"]["blogger_blog_id"]["present"] is True
