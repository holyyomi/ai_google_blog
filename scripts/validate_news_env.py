from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from blogspot_automation.config.settings import Settings
from blogspot_automation.services.news_env_diagnostics import build_news_env_diagnostics
from blogspot_automation.services.news_topic_service import _google_api_error_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate news automation environment without printing secrets.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when required operator actions remain.")
    parser.add_argument("--live-search", action="store_true", help="Make one Google Custom Search request.")
    parser.add_argument("--live-llm", action="store_true", help="Make tiny Gemini/OpenAI validation requests.")
    args = parser.parse_args()

    Settings.from_env()
    diagnostics = build_news_env_diagnostics()
    if args.live_search:
        diagnostics["live_search"] = _live_google_custom_search_check()
    if args.live_llm:
        diagnostics["live_llm"] = _live_llm_checks()
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    if args.live_search and not diagnostics.get("live_search", {}).get("ok"):
        return 1
    if args.live_llm and not all(item.get("ok") for item in diagnostics.get("live_llm", {}).values()):
        return 1
    if args.strict and diagnostics["user_required_actions"]:
        return 1
    return 0


def _live_google_custom_search_check() -> dict[str, object]:
    import os

    api_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_SEARCH_CX", "").strip()
    if not api_key or not cx:
        return {"ok": False, "error": "GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX are required."}
    params = {
        "key": api_key,
        "cx": cx,
        "q": "site:holyeverymoments.blogspot.com",
        "num": 1,
        "hl": "ko",
    }
    request = urllib.request.Request(
        f"https://www.googleapis.com/customsearch/v1?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        return {
            "ok": True,
            "total_results": str(payload.get("searchInformation", {}).get("totalResults", "")),
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "error": f"HTTP {exc.code}: {_google_api_error_summary(exc)}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _live_llm_checks() -> dict[str, dict[str, object]]:
    return {
        "gemini": _live_gemini_check(),
        "openai": _live_openai_check(),
    }


def _live_gemini_check() -> dict[str, object]:
    api_key = os.getenv("GOOGLE_AI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite"
    if not api_key:
        return {"ok": False, "model": model, "error": "GOOGLE_AI_API_KEY is missing."}

    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with OK only."}]}],
        "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
    }
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8", errors="ignore"))
        candidates = body.get("candidates") if isinstance(body, dict) else None
        return {"ok": bool(candidates), "model": model, "status": "reachable"}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "model": model,
            "error": f"HTTP {exc.code}: {_summarize_json_error(exc, [api_key])}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": model, "error": _redact_secret_text(str(exc), [api_key])}


def _live_openai_check() -> dict[str, object]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    if not api_key:
        return {"ok": False, "model": model, "error": "OPENAI_API_KEY is missing."}
    if not base_url.endswith("/chat/completions"):
        base_url = f"{base_url}/chat/completions"

    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK only."}],
    }
    if "api.openai.com" in base_url and model.startswith("gpt-5"):
        payload["max_completion_tokens"] = 8
    else:
        payload["max_tokens"] = 8
        payload["temperature"] = 0
    request = urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8", errors="ignore"))
        choices = body.get("choices") if isinstance(body, dict) else None
        return {"ok": bool(choices), "model": model, "status": "reachable"}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "model": model,
            "error": f"HTTP {exc.code}: {_summarize_json_error(exc, [api_key])}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": model, "error": _redact_secret_text(str(exc), [api_key])}


def _summarize_json_error(exc: urllib.error.HTTPError, secrets: list[str]) -> str:
    raw = exc.read().decode("utf-8", errors="ignore")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _redact_secret_text(raw[:500] or exc.reason, secrets)
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        parts = [
            str(error.get("status") or error.get("type") or "").strip(),
            str(error.get("code") or "").strip(),
            str(error.get("message") or "").strip(),
        ]
        summary = " | ".join(part for part in parts if part)
        return _redact_secret_text(summary or raw[:500], secrets)
    return _redact_secret_text(raw[:500], secrets)


def _redact_secret_text(text: str, secrets: list[str]) -> str:
    safe = text
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[redacted]")
    safe = re.sub(r"AIza[0-9A-Za-z_-]+", "AIza[redacted]", safe)
    safe = re.sub(r"sk-[0-9A-Za-z_-]+", "sk-[redacted]", safe)
    safe = re.sub(
        r"(Incorrect API key provided:\s*)[^.]+",
        r"\1[redacted]",
        safe,
        flags=re.IGNORECASE,
    )
    return safe


if __name__ == "__main__":
    raise SystemExit(main())
