from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from blogspot_automation.services.llm_content_service import _PROVIDERS


def build_news_env_diagnostics(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if env is None else env
    checks = {
        "google_search_api_key": _env_state(source, "GOOGLE_SEARCH_API_KEY"),
        "google_search_cx": _env_state(source, "GOOGLE_SEARCH_CX"),
        "enable_google_custom_search": _env_state(
            source,
            "ENABLE_GOOGLE_CUSTOM_SEARCH",
            default="false",
        ),
        "naver_client_id": _env_state(source, "NAVER_CLIENT_ID"),
        "naver_client_secret": _env_state(source, "NAVER_CLIENT_SECRET"),
        "enable_naver_search": _env_state(source, "ENABLE_NAVER_SEARCH", default="auto"),
        "enable_naver_datalab": _env_state(source, "ENABLE_NAVER_DATALAB", default="auto"),
        "tavily_api_key": _env_state(source, "TAVILY_API_KEY"),
        "exa_api_key": _env_state(source, "EXA_API_KEY"),
        "firecrawl_api_key": _env_state(source, "FIRECRAWL_API_KEY"),
        "enable_tavily_search": _env_state(source, "ENABLE_TAVILY_SEARCH", default="auto"),
        "enable_exa_search": _env_state(source, "ENABLE_EXA_SEARCH", default="auto"),
        "enable_firecrawl_search": _env_state(source, "ENABLE_FIRECRAWL_SEARCH", default="auto"),
        "openrouter_api_key": _env_state(source, "OPENROUTER_API_KEY"),
        "openrouter_model": _env_state(source, "OPENROUTER_MODEL", default="openai/gpt-oss-120b:free"),
        "openrouter_base_url": _env_state(source, "OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1"),
        "openai_api_key": _env_state(source, "OPENAI_API_KEY"),
        "google_ai_api_key": _env_state(source, "GOOGLE_AI_API_KEY"),
        "gemini_model": _env_state(source, "GEMINI_MODEL", default="gemini-2.5-flash-lite"),
        "openai_model": _env_state(source, "OPENAI_MODEL", default="gpt-5-mini"),
        "openai_base_url": _env_state(source, "OPENAI_BASE_URL", default="https://api.openai.com/v1"),
        "dry_run": _env_state(source, "DRY_RUN", default="true"),
        "news_publish_mode": _env_state(source, "NEWS_PUBLISH_MODE", default="dry_run"),
        "auto_publish": _env_state(source, "AUTO_PUBLISH", default="false"),
        "blogger_client_id": _env_state(source, "BLOGGER_CLIENT_ID"),
        "blogger_client_secret": _env_state(source, "BLOGGER_CLIENT_SECRET"),
        "blogger_refresh_token": _env_state(source, "BLOGGER_REFRESH_TOKEN"),
        "blogger_blog_id": _env_state(source, "BLOGGER_BLOG_ID"),
        "ai_cover_image_url": _env_state(source, "AI_COVER_IMAGE_URL"),
        "ai_default_cover_image_url": _env_state(source, "AI_DEFAULT_COVER_IMAGE_URL"),
        "ai_image_upload_key": _env_state(source, "AI_IMAGE_UPLOAD_KEY"),
        "legacy_imgbb_api_key": _env_state(source, "IMGBB_API_KEY"),
    }
    provider_chain = [
        {
            "name": str(provider["name"]),
            "api_key_env": str(provider["api_key_env"]),
            "configured": bool(str(source.get(str(provider["api_key_env"]), "")).strip()),
            "model": _provider_model(provider, source),
        }
        for provider in _PROVIDERS
    ]
    warnings: list[str] = []
    advisories: list[str] = []
    custom_search_enabled = str(source.get("ENABLE_GOOGLE_CUSTOM_SEARCH", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if custom_search_enabled and (
        not checks["google_search_api_key"]["present"] or not checks["google_search_cx"]["present"]
    ):
        warnings.append("Google Custom Search is enabled but incomplete; candidate discovery will fall back to Google News RSS.")
    naver_search_enabled = _enabled_or_auto(source, "ENABLE_NAVER_SEARCH", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
    naver_datalab_enabled = _enabled_or_auto(source, "ENABLE_NAVER_DATALAB", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
    if (naver_search_enabled or naver_datalab_enabled) and (
        not checks["naver_client_id"]["present"] or not checks["naver_client_secret"]["present"]
    ):
        warnings.append("Naver search/DataLab is enabled but NAVER_CLIENT_ID or NAVER_CLIENT_SECRET is missing.")
    if _enabled_or_auto(source, "ENABLE_TAVILY_SEARCH", "TAVILY_API_KEY") and not checks["tavily_api_key"]["present"]:
        warnings.append("Tavily search is enabled but TAVILY_API_KEY is missing.")
    if _enabled_or_auto(source, "ENABLE_EXA_SEARCH", "EXA_API_KEY") and not checks["exa_api_key"]["present"]:
        warnings.append("Exa search is enabled but EXA_API_KEY is missing.")
    if _enabled_or_auto(source, "ENABLE_FIRECRAWL_SEARCH", "FIRECRAWL_API_KEY") and not checks["firecrawl_api_key"]["present"]:
        warnings.append("Firecrawl search is enabled but FIRECRAWL_API_KEY is missing.")
    if not checks["openrouter_api_key"]["present"] and not checks["openai_api_key"]["present"]:
        warnings.append("No LLM key is configured; generation will fall back to local template content only.")
    if not checks["ai_image_upload_key"]["present"] and not checks["legacy_imgbb_api_key"]["present"]:
        advisories.append("AI_IMAGE_UPLOAD_KEY is missing; AI cover images will use configured/default fallback URLs only.")

    return {
        "ok": not warnings,
        "checks": checks,
        "provider_chain": provider_chain,
        "warnings": warnings,
        "advisories": advisories,
        "user_required_actions": user_required_actions(source),
    }


def user_required_actions(env: Mapping[str, str] | None = None) -> list[str]:
    source = os.environ if env is None else env
    actions: list[str] = []
    if not str(source.get("OPENROUTER_API_KEY", "")).strip():
        actions.append("Create or register OPENROUTER_API_KEY for primary article generation.")
    if not str(source.get("OPENROUTER_MODEL", "")).strip():
        actions.append("Set OPENROUTER_MODEL to the model slug to use first.")
    if not str(source.get("OPENAI_API_KEY", "")).strip():
        actions.append("Create or register OPENAI_API_KEY as paid fallback.")
    if _publish_mode_active(source):
        blogger_required = {
            "BLOGGER_CLIENT_ID": "Register BLOGGER_CLIENT_ID for scheduled Blogger publishing.",
            "BLOGGER_CLIENT_SECRET": "Register BLOGGER_CLIENT_SECRET for scheduled Blogger publishing.",
            "BLOGGER_REFRESH_TOKEN": "Register BLOGGER_REFRESH_TOKEN for scheduled Blogger publishing.",
            "BLOGGER_BLOG_ID": "Register BLOGGER_BLOG_ID for scheduled Blogger publishing.",
        }
        for name, message in blogger_required.items():
            if not str(source.get(name, "")).strip():
                actions.append(message)
    return actions


def _env_state(env: Mapping[str, str], name: str, *, default: str = "") -> dict[str, Any]:
    raw = str(env.get(name, "") or "").strip()
    value = raw or default
    display_value = value if name.endswith("_MODEL") or name.endswith("_BASE_URL") or name.startswith("ENABLE_") or name.startswith("NEWS_") or name in {
        "ENABLE_GOOGLE_CUSTOM_SEARCH",
        "DRY_RUN",
        "NEWS_PUBLISH_MODE",
        "AUTO_PUBLISH",
    } else ""
    return {
        "env": name,
        "present": bool(raw),
        "value": display_value,
    }


def _publish_mode_active(env: Mapping[str, str]) -> bool:
    dry_run = str(env.get("DRY_RUN", "true")).strip().lower() in {"1", "true", "yes", "on"}
    publish_mode = str(env.get("NEWS_PUBLISH_MODE", "dry_run")).strip().lower() == "publish"
    auto_publish = str(env.get("AUTO_PUBLISH", "false")).strip().lower() in {"1", "true", "yes", "on"}
    return publish_mode and auto_publish and not dry_run


def _enabled_or_auto(env: Mapping[str, str], toggle: str, *key_names: str) -> bool:
    raw = str(env.get(toggle, "") or "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on", "auto"}
    return all(str(env.get(name, "") or "").strip() for name in key_names)


def _provider_model(provider: dict[str, Any], env: Mapping[str, str]) -> str:
    model_env = str(provider.get("model_env") or "").strip()
    if model_env and str(env.get(model_env, "")).strip():
        return str(env[model_env]).strip()
    if provider.get("model") is not None:
        return str(provider["model"])
    return str(env.get("OPENAI_MODEL", "gpt-5-mini")).strip() or "gpt-5-mini"
