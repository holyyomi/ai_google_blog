"""클러스터 연속 발행 상한 회귀 테스트 (2026-09-10 신설).

배경: 8/31~9/4에 chatgpt_free_limit_* 슬롯이 5일 연속 발행돼 제목 자카드가
0.67~0.80으로 수렴했고, 해당 블로그 47편이 구글 색인 0편이었다. 클러스터의
dedup 면제 자체는 유지하되(7슬롯이 서로를 막으면 기능이 성립하지 않는다)
연속 편수만 끊는다.
"""

from __future__ import annotations

import os
from unittest import mock

from blogspot_automation.services.topic_dedup_service import TopicDedupService


def _published(day: str, *, slot: str | None = None, title: str = "t") -> dict:
    rec: dict = {
        "run_at": f"2026-09-{day}T12:31:00+00:00",
        "date": f"2026-09-{day}",
        "status": "published",
        "publish_succeeded": True,
        "title": title,
    }
    if slot:
        rec["cluster_slot"] = slot
    return rec


def test_streak_counts_only_consecutive_cluster_posts() -> None:
    svc = TopicDedupService()
    history = [
        _published("01", slot="a"),
        _published("02", slot="b"),
        _published("03", slot="c"),
    ]
    assert svc._cluster_publish_streak(history) == 3


def test_streak_breaks_at_first_non_cluster_post() -> None:
    svc = TopicDedupService()
    history = [
        _published("01", slot="a"),
        _published("02"),  # 뉴스 — 여기서 끊긴다
        _published("03", slot="c"),
    ]
    assert svc._cluster_publish_streak(history) == 1


def test_streak_ignores_history_list_order() -> None:
    """원장 나열 순서가 아니라 시간 필드로 정렬해야 한다."""
    svc = TopicDedupService()
    history = [
        _published("03", slot="c"),
        _published("01", slot="a"),
        _published("02", slot="b"),
    ]
    assert svc._cluster_publish_streak(history) == 3


def test_blocked_and_skipped_records_do_not_count() -> None:
    """실패·차단 레코드까지 세면 실패만으로 클러스터가 봉쇄된다."""
    svc = TopicDedupService()
    history = [
        _published("01", slot="a"),
        {
            "run_at": "2026-09-02T12:31:00+00:00",
            "status": "blocked_by_quality_gate",
            "publish_succeeded": False,
            "cluster_slot": "b",
        },
        {
            "run_at": "2026-09-03T12:31:00+00:00",
            "status": "skipped",
            "publish_succeeded": False,
            "cluster_slot": "c",
        },
    ]
    assert svc._cluster_publish_streak(history) == 1


def test_empty_history_has_no_streak() -> None:
    assert TopicDedupService()._cluster_publish_streak([]) == 0


def test_cap_default_is_two() -> None:
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CLUSTER_MAX_CONSECUTIVE", None)
        assert TopicDedupService.cluster_max_consecutive() == 2


def test_cap_is_env_overridable() -> None:
    with mock.patch.dict(os.environ, {"CLUSTER_MAX_CONSECUTIVE": "4"}):
        assert TopicDedupService.cluster_max_consecutive() == 4


def test_cap_zero_disables_the_rule() -> None:
    """0이면 종전 동작(상한 없음)으로 되돌린다."""
    with mock.patch.dict(os.environ, {"CLUSTER_MAX_CONSECUTIVE": "0"}):
        assert TopicDedupService.cluster_max_consecutive() == 0


def test_real_september_streak_would_have_been_blocked() -> None:
    """실측 재현: 9/1 시점에 이미 상한(2)에 걸렸어야 한다.

    실제로는 8/31·9/1·9/2·9/3·9/4가 전부 나갔다.
    """
    svc = TopicDedupService()
    history = [
        _published("29", slot="nvidia_nim_free_limits", title="NVIDIA NIM Free API Limits"),
        _published("30", slot="chatgpt_free_limits_per_day", title="ChatGPT Free Version Limits 2026"),
    ]
    # run_at을 8월로 보정
    for rec in history:
        rec["run_at"] = rec["run_at"].replace("2026-09", "2026-08")
        rec["date"] = rec["date"].replace("2026-09", "2026-08")

    assert svc._cluster_publish_streak(history) == 2
    assert svc._cluster_publish_streak(history) >= svc.cluster_max_consecutive()
