"""Reddit 회로차단 + 모듈 TTL 캐시 — 2026-08-03.

배경: Reddit 6개 서브레딧이 403 Blocked로 100% 실패하는데도 run_once 재시도
6회마다 sweep을 반복해 실행당 약 40회를 버렸다. HN은 정상 동작하므로 Reddit만
끊고 HN은 살려야 한다.
"""
from __future__ import annotations

import urllib.error

import pytest

from blogspot_automation.services import community_topic_service as cts


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.delenv("COMMUNITY_REDDIT_SUBS", raising=False)
    monkeypatch.delenv("ENABLE_COMMUNITY_TOPIC_SIGNAL", raising=False)
    cts.reset_community_topic_cache()
    yield
    cts.reset_community_topic_cache()


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://www.reddit.com/r/x/hot.json", code=code, msg="blocked", hdrs=None, fp=None
    )


def test_reddit_403_stops_remaining_subreddits(monkeypatch) -> None:
    """첫 403이면 남은 서브레딧을 아예 부르지 않는다 (6회 → 1회)."""
    calls: list[str] = []

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001, ARG001
        calls.append(req.full_url)
        raise _http_error(403)

    monkeypatch.setattr(cts.request, "urlopen", _fake_urlopen)
    topics = cts._fetch_reddit_topics(now=0.0)

    assert topics == []
    assert len(calls) == 1, f"403 후에는 더 호출하면 안 된다 (실제 {len(calls)}회)"


def test_reddit_breaker_persists_across_retries(monkeypatch) -> None:
    """run_once가 6회 반복돼도 차단 이후에는 네트워크 호출이 0이다."""
    calls: list[str] = []

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001, ARG001
        calls.append(req.full_url)
        raise _http_error(403)

    monkeypatch.setattr(cts.request, "urlopen", _fake_urlopen)
    for _ in range(6):
        cts._fetch_reddit_topics(now=0.0)

    assert len(calls) == 1


def test_reddit_server_error_does_not_trip_breaker(monkeypatch) -> None:
    """5xx는 일시 장애 — 남은 서브레딧을 계속 시도한다."""
    calls: list[str] = []

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001, ARG001
        calls.append(req.full_url)
        raise _http_error(503)

    monkeypatch.setattr(cts.request, "urlopen", _fake_urlopen)
    cts._fetch_reddit_topics(now=0.0)

    assert len(calls) == len(cts._DEFAULT_REDDIT_SUBS)
    assert not cts._REDDIT_BREAKER["tripped"]


@pytest.mark.parametrize("token", ["off", "none", "-", "OFF", "disabled"])
def test_env_can_disable_reddit_only(monkeypatch, token: str) -> None:
    """COMMUNITY_REDDIT_SUBS=off 면 Reddit만 꺼지고 HN 신호는 유지된다."""
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", token)
    assert cts._reddit_subs() == ()
    # 신호 자체는 살아있어야 한다 — HN 경로가 계속 돌아야 하기 때문.
    assert cts.is_signal_enabled() is True


def test_blank_env_still_falls_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setenv("COMMUNITY_REDDIT_SUBS", "")
    assert cts._reddit_subs() == cts._DEFAULT_REDDIT_SUBS


def test_collect_is_cached_across_repeated_calls(monkeypatch) -> None:
    """news_pipeline이 재시도마다 직접 호출해도 sweep은 1회만 나간다."""
    sweeps = {"reddit": 0, "hn": 0}

    def _fake_reddit(now):  # noqa: ANN001, ARG001
        sweeps["reddit"] += 1
        return []

    def _fake_hn(now):  # noqa: ANN001, ARG001
        sweeps["hn"] += 1
        return []

    monkeypatch.setattr(cts, "_fetch_reddit_topics", _fake_reddit)
    monkeypatch.setattr(cts, "_fetch_hn_topics", _fake_hn)

    for _ in range(6):
        cts.collect_community_topics(max_items=20)

    assert sweeps == {"reddit": 1, "hn": 1}


def test_force_refresh_bypasses_cache(monkeypatch) -> None:
    sweeps = {"n": 0}

    def _fake_reddit(now):  # noqa: ANN001, ARG001
        sweeps["n"] += 1
        return []

    monkeypatch.setattr(cts, "_fetch_reddit_topics", _fake_reddit)
    monkeypatch.setattr(cts, "_fetch_hn_topics", lambda now: [])  # noqa: ARG005

    cts.collect_community_topics()
    cts.collect_community_topics(force_refresh=True)
    assert sweeps["n"] == 2
