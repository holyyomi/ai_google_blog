"""check_published_today.py — GHA/Cloud Run 공용 이중 발행 가드 판정 테스트.

핵심 계약: "오늘(KST) 라이브 발행"만 true. 리허설 초안(blogger.com/edit URL),
게이트 차단 실행(url 빈 값), 어제 발행, published=false는 전부 false —
가드가 오탐으로 정상 발행을 막으면 그날 발행 0건이 되므로 (2026-07-10
NEWS_MAX_PUBLISH_ATTEMPTS 사건과 같은 계열) 판정 기준을 좁게 고정한다.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_SPEC = importlib.util.spec_from_file_location(
    "check_published_today",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "check_published_today.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules["check_published_today"] = _MOD
_SPEC.loader.exec_module(_MOD)

published_today = _MOD.published_today

TODAY = "2026-07-24"


def _entry(**kwargs):
    base = {
        "run_at": "2026-07-24T12:56:31+00:00",  # 21:56 KST — 오늘
        "date": "2026-07-24",
        "published": True,
        "dry_run": False,
        "url": "https://holyyomiai.blogspot.com/2026/07/some-post.html",
    }
    base.update(kwargs)
    return base


def test_live_post_today_is_true():
    assert published_today([_entry()], TODAY) is True


def test_draft_rehearsal_today_is_false():
    # publish_draft 리허설은 blogger.com 편집 URL — 라이브 아님
    entry = _entry(
        published=False,
        url="https://www.blogger.com/blog/post/edit/5120841417195307917/123",
    )
    assert published_today([entry], TODAY) is False


def test_published_flag_with_draft_url_is_false():
    # published=true라도 URL이 라이브 blogspot이 아니면 세지 않는다
    entry = _entry(url="https://www.blogger.com/blog/post/edit/5120841417195307917/123")
    assert published_today([entry], TODAY) is False


def test_blocked_run_empty_url_is_false():
    entry = _entry(published=False, url="")
    assert published_today([entry], TODAY) is False


def test_yesterday_live_post_is_false():
    # 어제 12:56 UTC(어제 21:56 KST) 발행 — 오늘 슬롯을 막으면 안 된다
    entry = _entry(run_at="2026-07-23T12:56:31+00:00", date="2026-07-23")
    assert published_today([entry], TODAY) is False


def test_kst_day_boundary_uses_kst_not_utc():
    # 2026-07-23T16:00 UTC = 2026-07-24 01:00 KST → KST 기준 "오늘"로 세야 한다
    entry = _entry(run_at="2026-07-23T16:00:00+00:00", date="2026-07-23")
    assert published_today([entry], TODAY) is True


def test_broken_run_at_falls_back_to_date_field():
    entry = _entry(run_at="not-a-timestamp", date="2026-07-24")
    assert published_today([entry], TODAY) is True


def test_empty_or_malformed_entries_are_false():
    assert published_today([], TODAY) is False
    assert published_today([None, "junk", 42], TODAY) is False
