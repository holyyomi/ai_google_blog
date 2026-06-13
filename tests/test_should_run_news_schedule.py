from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "should_run_news_schedule.py"
_SPEC = importlib.util.spec_from_file_location("should_run_news_schedule", _SCRIPT_PATH)
assert _SPEC is not None
gate = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(gate)


def _run_gate(monkeypatch, tmp_path, capsys, *, records: list[dict], now: datetime) -> dict[str, str]:
    history_path = tmp_path / "publish_history.json"
    history_path.write_text(json.dumps(records), encoding="utf-8")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(gate, "HISTORY_PATH", history_path)
    monkeypatch.setattr(gate, "datetime", FrozenDateTime)
    monkeypatch.setenv("NEWS_SCHEDULE_INTERVAL_MINUTES", "483")
    monkeypatch.setenv("NEWS_FAILED_SCHEDULE_INTERVAL_MINUTES", "60")

    assert gate.main() == 0
    return dict(
        line.split("=", 1)
        for line in capsys.readouterr().out.splitlines()
        if "=" in line
    )


def _run_slot_gate(monkeypatch, tmp_path, capsys, *, records: list[dict], now: datetime) -> dict[str, str]:
    history_path = tmp_path / "publish_history.json"
    history_path.write_text(json.dumps(records), encoding="utf-8")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(gate, "HISTORY_PATH", history_path)
    monkeypatch.setattr(gate, "datetime", FrozenDateTime)
    monkeypatch.setenv("NEWS_SCHEDULE_TIMEZONE", "Asia/Seoul")
    monkeypatch.setenv("NEWS_SCHEDULE_SLOTS", "00:13,08:13,16:13")
    monkeypatch.setenv("NEWS_DAILY_PUBLISH_TARGET", "3")
    monkeypatch.setenv("NEWS_FAILED_SCHEDULE_INTERVAL_MINUTES", "20")

    assert gate.main() == 0
    return dict(
        line.split("=", 1)
        for line in capsys.readouterr().out.splitlines()
        if "=" in line
    )


def test_fixed_slot_runs_even_if_previous_slot_was_published(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-02T02:16:46+00:00", "status": "published"},
        ],
        now=datetime(2026, 6, 2, 7, 48, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "true"
    assert outputs["reason"] == "slot_due"
    assert outputs["slot_start_at"] == "2026-06-02T07:13:00+00:00"
    assert outputs["slot_end_at"] == "2026-06-02T15:13:00+00:00"


def test_fixed_slot_skips_before_first_due_slot(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[],
        now=datetime(2026, 6, 1, 15, 5, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "before_first_slot"
    assert outputs["next_run_at"] == "2026-06-01T15:13:00+00:00"


def test_fixed_slot_skips_when_current_slot_was_published(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-01T15:20:00+00:00", "status": "published"},
            {"run_at": "2026-06-01T23:20:00+00:00", "status": "published"},
            {"run_at": "2026-06-02T07:20:00+00:00", "status": "published"},
        ],
        now=datetime(2026, 6, 2, 7, 48, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "slot_already_published"


def test_fixed_slot_ignores_dry_run_deleted_trending_success(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {
                "run_at": "2026-06-02T07:20:00+00:00",
                "status": "trending_published",
                "published": False,
                "dry_run": True,
                "note": "post_deleted_by_user (404, dereferenced 2026-06-02)",
            },
        ],
        now=datetime(2026, 6, 2, 7, 48, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "true"
    assert outputs["reason"] == "slot_due"


def test_fixed_slot_counts_live_verified_trending_success(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-01T15:20:00+00:00", "status": "published"},
            {"run_at": "2026-06-02T00:20:00+00:00", "status": "published"},
            {
                "run_at": "2026-06-02T07:20:00+00:00",
                "status": "trending_published",
                "published": True,
                "dry_run": True,
                "post_publish_audit_passed": False,
                "url_verified_status_code": 200,
                "live_url_verified": True,
            },
        ],
        now=datetime(2026, 6, 2, 7, 48, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "slot_already_published"


def test_fixed_slot_runs_catchup_when_earlier_due_slot_was_missed(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-02T00:20:00+00:00", "status": "published"},
        ],
        now=datetime(2026, 6, 2, 0, 47, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "true"
    assert outputs["reason"] == "daily_catchup_due"
    assert outputs["slot_start_at"] == "2026-06-01T23:13:00+00:00"
    assert outputs["slot_end_at"] == "2026-06-02T07:13:00+00:00"


def test_fixed_slot_skips_when_due_daily_publish_count_is_filled(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-01T15:20:00+00:00", "status": "published"},
            {"run_at": "2026-06-02T00:20:00+00:00", "status": "published"},
        ],
        now=datetime(2026, 6, 2, 0, 47, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "slot_already_published"


def test_fixed_slot_retries_failed_slot_at_second_wake_up(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-02T07:20:00+00:00", "status": "blocked_by_quality_gate"},
        ],
        now=datetime(2026, 6, 2, 7, 47, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "true"
    assert outputs["reason"] == "slot_retry_due"
    assert outputs["next_run_at"] == "2026-06-02T07:40:00+00:00"


def test_fixed_slot_waits_before_retrying_failed_slot(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_slot_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-06-02T07:20:00+00:00", "status": "blocked_by_quality_gate"},
        ],
        now=datetime(2026, 6, 2, 7, 35, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "slot_retry_not_due"
    assert outputs["next_run_at"] == "2026-06-02T07:40:00+00:00"


def test_recent_retry_limit_failure_uses_short_retry_interval(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-05-27T10:00:00+00:00", "status": "published"},
            {"run_at": "2026-05-27T19:52:56+00:00", "status": "skipped_after_retry_limit"},
        ],
        now=datetime(2026, 5, 27, 20, 30, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "failure_retry_not_due"
    assert outputs["interval_minutes"] == "60"
    assert outputs["next_run_at"] == "2026-05-27T20:52:56+00:00"


def test_generic_failed_run_uses_short_retry_interval(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-05-27T10:00:00+00:00", "status": "published"},
            {"run_at": "2026-05-27T19:52:56+00:00", "status": "failed"},
        ],
        now=datetime(2026, 5, 27, 20, 30, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "failure_retry_not_due"
    assert outputs["interval_minutes"] == "60"


def test_retry_limit_failure_runs_after_short_retry_interval(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-05-27T10:00:00+00:00", "status": "published"},
            {"run_at": "2026-05-27T19:52:56+00:00", "status": "skipped_after_retry_limit"},
        ],
        now=datetime(2026, 5, 27, 20, 55, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "true"
    assert outputs["reason"] == "failure_retry_due"
    assert outputs["interval_minutes"] == "60"


def test_recent_success_keeps_full_publish_interval(monkeypatch, tmp_path, capsys) -> None:
    outputs = _run_gate(
        monkeypatch,
        tmp_path,
        capsys,
        records=[
            {"run_at": "2026-05-27T19:00:00+00:00", "status": "skipped_after_retry_limit"},
            {"run_at": "2026-05-27T19:52:56+00:00", "status": "published"},
        ],
        now=datetime(2026, 5, 27, 20, 55, tzinfo=timezone.utc),
    )

    assert outputs["should_run"] == "false"
    assert outputs["reason"] == "not_due"
    assert outputs["interval_minutes"] == "483"
    assert outputs["next_run_at"] == "2026-05-28T03:55:56+00:00"
