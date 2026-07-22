"""내부링크(Related guides) 생존검사 테스트 (2026-07-22).

2026-07-21 라이브 실측: 발행 글의 Related guides가 전날 삭제된 글 2건을
가리켰다(Blogger는 HEAD엔 200을 주지만 GET은 404 — 실측). 발행 원장은 API
직접 삭제를 모르므로 링크 대상의 생존을 발행 시점에 확인해야 한다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services import seo_policy


@pytest.fixture(autouse=True)
def _reset_cache():
    seo_policy._LIVENESS_CACHE.clear()
    yield
    seo_policy._LIVENESS_CACHE.clear()


def _records():
    return [
        {
            "title": f"AI guide number {i} for daily automation work",
            "blogger_url": f"https://holyyomiai.blogspot.com/2026/07/ai-guide-{i}-news.html",
            "status": "published",
            "topic_group": "ai_work",
            "content_type": "ai_work_tip",
            "run_at": f"2026-07-{10 + i}T00:00:00+00:00",
            "selected_topic": f"ai guide {i}",
        }
        for i in range(1, 5)
    ]


def test_dead_links_are_skipped(monkeypatch):
    dead_url = "https://holyyomiai.blogspot.com/2026/07/ai-guide-4-news.html"
    monkeypatch.setattr(seo_policy, "_liveness_check_enabled", lambda: True)
    monkeypatch.setattr(
        seo_policy, "_blogspot_post_url_is_live", lambda url, **kw: url != dead_url
    )
    links = seo_policy.build_internal_links_from_history(
        _records(), current_title="new post", current_topic="ai work", limit=3
    )
    urls = [url for _, url in links]
    assert dead_url not in urls
    assert len(urls) >= 1


def test_all_live_links_kept(monkeypatch):
    monkeypatch.setattr(seo_policy, "_liveness_check_enabled", lambda: True)
    monkeypatch.setattr(seo_policy, "_blogspot_post_url_is_live", lambda url, **kw: True)
    links = seo_policy.build_internal_links_from_history(
        _records(), current_title="new post", current_topic="ai work", limit=3
    )
    assert len(links) == 3


def test_liveness_disabled_under_pytest_by_default():
    # PYTEST_CURRENT_TEST가 설정된 상태에서는 자동 비활성 — 기존 테스트 픽스처
    # (실도메인 가상 URL)가 네트워크에 의존하지 않는다.
    assert seo_policy._liveness_check_enabled() is False


def test_liveness_env_kill_switch(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ENABLE_INTERNAL_LINK_LIVENESS_CHECK", "false")
    assert seo_policy._liveness_check_enabled() is False
    monkeypatch.setenv("ENABLE_INTERNAL_LINK_LIVENESS_CHECK", "true")
    assert seo_policy._liveness_check_enabled() is True
