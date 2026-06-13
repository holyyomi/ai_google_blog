from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_INTERVAL_MINUTES = 483
DEFAULT_FAILURE_RETRY_MINUTES = 30
HISTORY_PATH = Path(os.getenv("PUBLISH_HISTORY_PATH", "data/publish_history.json"))
SUCCESS_STATUSES = {
    "published",
    "trending_published",
}
RETRY_STATUSES = {
    "blocked_by_quality_gate",
    "blocked_fallback_candidate",
    "held_for_review",
    "held_no_real_news_publish_candidate",
    "skipped",
    "skipped_after_retry_limit",
    "skipped_duplicate",
    "trending_held_for_review",
    "trending_publish_failed",
    "failed",
}
SCHEDULE_STATUSES = SUCCESS_STATUSES | RETRY_STATUSES
DEAD_POST_NOTE_RE = re.compile(r"\b(?:404|deleted|dereferenced|not\s+found)\b", re.IGNORECASE)


def main() -> int:
    slots = _schedule_slots()
    if slots:
        return _run_fixed_slot_gate(slots)
    return _run_interval_gate()


def _run_interval_gate() -> int:
    interval_minutes = _interval_minutes()
    failure_retry_minutes = _failure_retry_minutes()
    now = datetime.now(timezone.utc)
    last_record = _latest_schedule_record(_load_history(HISTORY_PATH))

    if last_record is None:
        _set_outputs(
            should_run=True,
            reason="no_schedule_history",
            interval_minutes=interval_minutes,
            last_run_at="",
            next_run_at=now.isoformat(timespec="seconds"),
            elapsed_minutes="",
        )
        return 0

    last_run_at = _parse_datetime(str(last_record.get("run_at") or ""))
    last_status = str(last_record.get("status") or "").strip()
    active_interval_minutes = _interval_for_status(
        status=last_status,
        success_interval_minutes=interval_minutes,
        failure_retry_minutes=failure_retry_minutes,
    )
    if last_run_at is None:
        _set_outputs(
            should_run=True,
            reason="invalid_last_run_at",
            interval_minutes=active_interval_minutes,
            last_run_at=str(last_record.get("run_at") or ""),
            next_run_at=now.isoformat(timespec="seconds"),
            elapsed_minutes="",
        )
        return 0

    next_run_at = last_run_at + timedelta(minutes=active_interval_minutes)
    elapsed_minutes = int((now - last_run_at).total_seconds() // 60)
    should_run = now >= next_run_at
    is_success_cooldown = last_status in SUCCESS_STATUSES
    _set_outputs(
        should_run=should_run,
        reason=(
            "due"
            if should_run and is_success_cooldown
            else "not_due"
            if is_success_cooldown
            else "failure_retry_due"
            if should_run
            else "failure_retry_not_due"
        ),
        interval_minutes=active_interval_minutes,
        last_run_at=last_run_at.isoformat(timespec="seconds"),
        next_run_at=next_run_at.isoformat(timespec="seconds"),
        elapsed_minutes=str(elapsed_minutes),
    )
    return 0


def _run_fixed_slot_gate(slots: list[time]) -> int:
    failure_retry_minutes = _failure_retry_minutes()
    now = datetime.now(timezone.utc)
    timezone_name = os.getenv("NEWS_SCHEDULE_TIMEZONE", "Asia/Seoul").strip() or "Asia/Seoul"
    try:
        schedule_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        schedule_tz = ZoneInfo("Asia/Seoul")
        timezone_name = "Asia/Seoul"

    current_slot_start, next_slot_start = _current_slot_window(
        now=now,
        slots=slots,
        schedule_tz=schedule_tz,
    )
    records = _load_history(HISTORY_PATH)
    local_day_start, local_day_end = _local_day_window(now=now, schedule_tz=schedule_tz)
    due_slot_count = _due_slot_count(now=now, slots=slots, schedule_tz=schedule_tz)
    daily_target = _daily_publish_target(default=len(slots))
    due_publish_count = min(daily_target, due_slot_count)
    daily_success_records = [
        record
        for record in records
        if _record_in_window(record, start=local_day_start, end=local_day_end)
        and _is_success_record(record)
    ]
    slot_records = [
        record
        for record in records
        if _record_in_window(record, start=current_slot_start, end=next_slot_start)
        and _is_schedule_record(record)
    ]
    slot_records.sort(
        key=lambda record: _parse_datetime(str(record.get("run_at") or "")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    current_slot_has_success = any(
        _is_success_record(record)
        for record in slot_records
    )
    daily_success_count = len(daily_success_records)

    if current_slot_has_success and daily_success_count < due_publish_count:
        _set_outputs(
            should_run=True,
            reason="daily_catchup_due",
            interval_minutes=failure_retry_minutes,
            last_run_at=_format_latest_run_at(slot_records),
            next_run_at=now.isoformat(timespec="seconds"),
            elapsed_minutes=_elapsed_minutes(now, slot_records),
            slot_start_at=current_slot_start.isoformat(timespec="seconds"),
            slot_end_at=next_slot_start.isoformat(timespec="seconds"),
            schedule_timezone=timezone_name,
        )
        return 0

    if current_slot_has_success:
        _set_outputs(
            should_run=False,
            reason="slot_already_published",
            interval_minutes=failure_retry_minutes,
            last_run_at=_format_latest_run_at(slot_records),
            next_run_at=next_slot_start.isoformat(timespec="seconds"),
            elapsed_minutes=_elapsed_minutes(now, slot_records),
            slot_start_at=current_slot_start.isoformat(timespec="seconds"),
            slot_end_at=next_slot_start.isoformat(timespec="seconds"),
            schedule_timezone=timezone_name,
        )
        return 0

    if slot_records:
        last_run_at = _parse_datetime(str(slot_records[0].get("run_at") or ""))
        next_retry_at = (last_run_at + timedelta(minutes=failure_retry_minutes)) if last_run_at else now
        should_run = now >= next_retry_at
        _set_outputs(
            should_run=should_run,
            reason="slot_retry_due" if should_run else "slot_retry_not_due",
            interval_minutes=failure_retry_minutes,
            last_run_at=last_run_at.isoformat(timespec="seconds") if last_run_at else "",
            next_run_at=next_retry_at.isoformat(timespec="seconds"),
            elapsed_minutes=str(int((now - last_run_at).total_seconds() // 60)) if last_run_at else "",
            slot_start_at=current_slot_start.isoformat(timespec="seconds"),
            slot_end_at=next_slot_start.isoformat(timespec="seconds"),
            schedule_timezone=timezone_name,
        )
        return 0

    _set_outputs(
        should_run=True,
        reason="slot_due",
        interval_minutes=failure_retry_minutes,
        last_run_at="",
        next_run_at=now.isoformat(timespec="seconds"),
        elapsed_minutes="",
        slot_start_at=current_slot_start.isoformat(timespec="seconds"),
        slot_end_at=next_slot_start.isoformat(timespec="seconds"),
        schedule_timezone=timezone_name,
    )
    return 0


def _interval_minutes() -> int:
    raw = os.getenv("NEWS_SCHEDULE_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_INTERVAL_MINUTES
    return max(1, value)


def _failure_retry_minutes() -> int:
    raw = os.getenv("NEWS_FAILED_SCHEDULE_INTERVAL_MINUTES", str(DEFAULT_FAILURE_RETRY_MINUTES)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_FAILURE_RETRY_MINUTES
    return max(1, value)


def _daily_publish_target(*, default: int) -> int:
    raw = os.getenv("NEWS_DAILY_PUBLISH_TARGET", str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return max(1, default)
    return max(1, value)


def _schedule_slots() -> list[time]:
    raw = os.getenv("NEWS_SCHEDULE_SLOTS", "").strip()
    if not raw:
        return []
    slots: list[time] = []
    for item in raw.split(","):
        part = item.strip()
        if not part:
            continue
        try:
            hour_text, minute_text = part.split(":", 1)
            slot = time(hour=int(hour_text), minute=int(minute_text))
        except (TypeError, ValueError):
            continue
        if slot not in slots:
            slots.append(slot)
    return sorted(slots)


def _current_slot_window(
    *,
    now: datetime,
    slots: list[time],
    schedule_tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    local_now = now.astimezone(schedule_tz)
    today = local_now.date()
    local_starts = [
        datetime.combine(today, slot, tzinfo=schedule_tz)
        for slot in slots
    ]
    current_index = -1
    for index, slot_start in enumerate(local_starts):
        if local_now >= slot_start:
            current_index = index
        else:
            break

    if current_index >= 0:
        current_start = local_starts[current_index]
        if current_index + 1 < len(local_starts):
            next_start = local_starts[current_index + 1]
        else:
            next_start = datetime.combine(today + timedelta(days=1), slots[0], tzinfo=schedule_tz)
    else:
        current_start = datetime.combine(today - timedelta(days=1), slots[-1], tzinfo=schedule_tz)
        next_start = local_starts[0]

    return current_start.astimezone(timezone.utc), next_start.astimezone(timezone.utc)


def _local_day_window(*, now: datetime, schedule_tz: ZoneInfo) -> tuple[datetime, datetime]:
    local_now = now.astimezone(schedule_tz)
    local_start = datetime.combine(local_now.date(), time(0, 0), tzinfo=schedule_tz)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _due_slot_count(*, now: datetime, slots: list[time], schedule_tz: ZoneInfo) -> int:
    local_now = now.astimezone(schedule_tz)
    today = local_now.date()
    return sum(
        1
        for slot in slots
        if local_now >= datetime.combine(today, slot, tzinfo=schedule_tz)
    )


def _interval_for_status(
    *,
    status: str,
    success_interval_minutes: int,
    failure_retry_minutes: int,
) -> int:
    return success_interval_minutes if status in SUCCESS_STATUSES else failure_retry_minutes


def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _latest_schedule_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    scheduled = [
        record
        for record in records
        if _is_schedule_record(record)
    ]
    scheduled.sort(
        key=lambda record: _parse_datetime(str(record.get("run_at") or "")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return scheduled[0] if scheduled else None


def _is_schedule_record(record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").strip()
    return status in RETRY_STATUSES or _is_success_record(record)


def _is_success_record(record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").strip()
    live_verified = _has_live_verification(record)
    note = " ".join(
        str(record.get(key) or "")
        for key in ("note", "reason", "publish_error", "post_publish_audit_error")
    )
    if DEAD_POST_NOTE_RE.search(note):
        return False
    if _as_bool(record.get("dry_run")) is True and not live_verified:
        return False
    if _as_bool(record.get("published")) is False and not live_verified:
        return False
    if _as_bool(record.get("post_publish_audit_passed")) is False and not live_verified:
        return False
    has_success_signal = (
        status in SUCCESS_STATUSES
        or _as_bool(record.get("published")) is True
        or _as_bool(record.get("publish_succeeded")) is True
    )
    if not has_success_signal:
        return False
    return True


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _has_live_verification(record: dict[str, Any]) -> bool:
    if _as_bool(record.get("live_url_verified")) is True:
        return True
    try:
        code = int(record.get("url_verified_status_code"))
    except (TypeError, ValueError):
        return False
    return 200 <= code < 400


def _record_in_window(record: dict[str, Any], *, start: datetime, end: datetime) -> bool:
    run_at = _parse_datetime(str(record.get("run_at") or ""))
    return bool(run_at and start <= run_at < end)


def _format_latest_run_at(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    run_at = _parse_datetime(str(records[0].get("run_at") or ""))
    return run_at.isoformat(timespec="seconds") if run_at else str(records[0].get("run_at") or "")


def _elapsed_minutes(now: datetime, records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    run_at = _parse_datetime(str(records[0].get("run_at") or ""))
    return str(int((now - run_at).total_seconds() // 60)) if run_at else ""


def _parse_datetime(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _set_outputs(
    *,
    should_run: bool,
    reason: str,
    interval_minutes: int,
    last_run_at: str,
    next_run_at: str,
    elapsed_minutes: str,
    slot_start_at: str = "",
    slot_end_at: str = "",
    schedule_timezone: str = "",
) -> None:
    values = {
        "should_run": "true" if should_run else "false",
        "reason": reason,
        "interval_minutes": str(interval_minutes),
        "last_run_at": last_run_at,
        "next_run_at": next_run_at,
        "elapsed_minutes": elapsed_minutes,
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
        "schedule_timezone": schedule_timezone,
    }
    for key, value in values.items():
        print(f"{key}={value}")

    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


if __name__ == "__main__":
    raise SystemExit(main())
