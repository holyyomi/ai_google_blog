from __future__ import annotations

import io
import json

from blogspot_automation.services import autocomplete_client


class _Resp:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *exc) -> bool:  # noqa: ANN002
        return False


def test_build_url_carries_query_and_locale():
    url = autocomplete_client.build_url("claude code", hl="en")
    assert "suggestqueries.google.com" in url
    assert "q=claude+code" in url
    assert "hl=en" in url


def test_fetch_returns_suggestions_and_success(monkeypatch):
    monkeypatch.setattr(
        autocomplete_client.request,
        "urlopen",
        lambda req, timeout=None: _Resp(["claude code", ["claude code install", "  ", "claude code cli"]]),
    )
    suggestions, ok = autocomplete_client.fetch_suggestions("claude code")
    assert ok is True
    assert suggestions == ["claude code install", "claude code cli"]


def test_network_failure_is_silent_and_flagged(monkeypatch):
    def _boom(req, timeout=None):  # noqa: ANN001
        raise OSError("no network")

    monkeypatch.setattr(autocomplete_client.request, "urlopen", _boom)
    suggestions, ok = autocomplete_client.fetch_suggestions("claude code")
    # 실패는 예외가 아니라 (빈 목록, False)로 표현된다 — 호출부가
    # "수요 없음"과 "측정 실패"를 구분할 수 있어야 하기 때문.
    assert suggestions == []
    assert ok is False


def test_malformed_payload_is_treated_as_failure_not_empty_demand(monkeypatch):
    monkeypatch.setattr(
        autocomplete_client.request, "urlopen", lambda req, timeout=None: _Resp({"unexpected": True})
    )
    suggestions, ok = autocomplete_client.fetch_suggestions("claude code")
    assert suggestions == []
    assert ok is True


def test_empty_query_never_hits_network(monkeypatch):
    def _boom(req, timeout=None):  # noqa: ANN001
        raise AssertionError("should not be called")

    monkeypatch.setattr(autocomplete_client.request, "urlopen", _boom)
    assert autocomplete_client.fetch_suggestions("   ") == ([], False)
