"""IndexNow ping client — Naver + Bing concurrent index request.

After a successful Blogger publish, post the live URL to IndexNow so Naver
SearchAdvisor and Microsoft Bing can refresh their crawl queue immediately
instead of waiting for next sitemap pass.

Configuration:
- NAVER_INDEXNOW_KEY: key string issued at Naver SearchAdvisor. Required.
- NAVER_INDEXNOW_KEY_LOCATION: optional URL of the key verification file.
  When omitted IndexNow auto-resolves with `https://<host>/<key>.txt`.

If the key is missing the client silently skips all requests so dry_run
and local environments never fail because of missing credentials.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Iterable
from urllib import error, request
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)


_NAVER_ENDPOINT = "https://searchadvisor.naver.com/indexnow"
_BING_ENDPOINT = "https://www.bing.com/indexnow"
_TIMEOUT_SECONDS = 15


def submit_urls(urls: Iterable[str]) -> dict[str, object]:
    """Submit one or more URLs to Naver + Bing IndexNow endpoints.

    Returns a result dict with per-endpoint status. Never raises — callers
    can log the result without wrapping in try/except.
    """
    key = (os.getenv("NAVER_INDEXNOW_KEY") or "").strip()
    url_list = [u.strip() for u in urls if u and u.strip()]
    if not key:
        return {"status": "skipped", "reason": "no_key_set", "submitted": []}
    if not url_list:
        return {"status": "skipped", "reason": "no_urls", "submitted": []}

    host = urlsplit(url_list[0]).netloc
    key_location = (os.getenv("NAVER_INDEXNOW_KEY_LOCATION") or "").strip()

    payload: dict[str, object] = {
        "host": host,
        "key": key,
        "urlList": url_list,
    }
    if key_location:
        payload["keyLocation"] = key_location

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}

    results = {}
    for label, endpoint in (("naver", _NAVER_ENDPOINT), ("bing", _BING_ENDPOINT)):
        results[label] = _post(endpoint, body, headers)

    return {
        "status": "ok",
        "submitted": url_list,
        "host": host,
        "endpoints": results,
    }


def _post(endpoint: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
            return {
                "endpoint": endpoint,
                "http_status": response.status,
                "ok": 200 <= response.status < 300,
            }
    except error.HTTPError as exc:
        return {
            "endpoint": endpoint,
            "http_status": exc.code,
            "ok": False,
            "error": exc.reason,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("IndexNow %s failed: %s", endpoint, exc)
        return {
            "endpoint": endpoint,
            "http_status": None,
            "ok": False,
            "error": str(exc),
        }
