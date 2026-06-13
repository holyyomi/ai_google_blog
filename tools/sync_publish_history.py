from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.client import HTTPResponse
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from blogspot_automation.services.publish_history_service import PublishHistoryService


DEFAULT_HISTORY_PATH = Path("data/publish_history.json")
DEFAULT_PUBLISHED_HISTORY_PATH = Path("state/news_published_history.json")
DEFAULT_BACKUP_DIR = Path("data/backups")
MAX_RECORDS = 240
DEAD_POST_NOTE_RE = re.compile(r"\b(?:404|deleted|dereferenced|not\s+found)\b", re.IGNORECASE)

UrlVerifier = Callable[[str], int | None]


@dataclass(slots=True)
class SyncReport:
    history_path: str
    published_history_path: str
    original_records: int
    final_records: int
    backfilled_records: int
    corrected_live_records: int
    skipped_tombstoned_source_records: int
    skipped_existing_source_records: int
    verified_live_urls: int
    failed_live_url_checks: int
    dry_run: bool
    backup_path: str = ""


def sync_publish_history(
    *,
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    published_history_path: str | Path = DEFAULT_PUBLISHED_HISTORY_PATH,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
    verify_live_urls: bool = False,
    dry_run: bool = False,
    max_records: int = MAX_RECORDS,
    now: datetime | None = None,
    url_verifier: UrlVerifier | None = None,
) -> SyncReport:
    history_path = Path(history_path)
    published_history_path = Path(published_history_path)
    backup_dir = Path(backup_dir)
    now = now or datetime.now(timezone.utc)
    normalized_now = now.astimezone(timezone.utc).isoformat(timespec="seconds")

    records = _load_records(history_path)
    original_count = len(records)
    source_records = _load_records(published_history_path)
    verifier = url_verifier or _verify_url_status

    tombstone_keys = _tombstone_keys(records)
    published_keys = _published_keys(records)

    backfilled = 0
    skipped_tombstoned = 0
    skipped_existing = 0
    for source in source_records:
        converted = _convert_published_history_record(
            source,
            source_path=published_history_path,
            normalized_at=normalized_now,
        )
        keys = _record_keys(converted)
        if keys & tombstone_keys:
            skipped_tombstoned += 1
            continue
        if keys & published_keys:
            skipped_existing += 1
            continue
        records.append(converted)
        published_keys.update(keys)
        backfilled += 1

    corrected_live = 0
    verified_live = 0
    failed_checks = 0
    if verify_live_urls:
        for record in records:
            if not _needs_live_correction(record):
                continue
            url = _record_url(record)
            status_code = verifier(url)
            if status_code is None:
                failed_checks += 1
                continue
            record["url_verified_status_code"] = status_code
            record["url_verified_at"] = normalized_now
            if 200 <= status_code < 400:
                verified_live += 1
                _mark_live_corrected(record, normalized_at=normalized_now)
                corrected_live += 1
            else:
                failed_checks += 1

    final_records = _sort_and_trim(records, max_records=max_records)

    backup_path = ""
    if not dry_run:
        backup_path = _backup_history(history_path=history_path, backup_dir=backup_dir, now=now)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps(final_records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return SyncReport(
        history_path=str(history_path),
        published_history_path=str(published_history_path),
        original_records=original_count,
        final_records=len(final_records),
        backfilled_records=backfilled,
        corrected_live_records=corrected_live,
        skipped_tombstoned_source_records=skipped_tombstoned,
        skipped_existing_source_records=skipped_existing,
        verified_live_urls=verified_live,
        failed_live_url_checks=failed_checks,
        dry_run=dry_run,
        backup_path=backup_path,
    )


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("records", "items", "history", "list"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _convert_published_history_record(
    source: dict[str, Any],
    *,
    source_path: Path,
    normalized_at: str,
) -> dict[str, Any]:
    published_at = str(source.get("published_at") or source.get("run_at") or source.get("date") or "").strip()
    run_at = _normalize_datetime_text(published_at)
    title = str(source.get("selected_title") or source.get("title") or source.get("topic") or "").strip()
    topic = str(source.get("selected_topic") or source.get("topic") or title).strip()
    record: dict[str, Any] = {
        "run_at": run_at,
        "date": (run_at or published_at)[:10],
        "title": title,
        "selected_topic": topic,
        "search_demand_topic": str(source.get("topic") or topic).strip(),
        "topic_group": str(source.get("topic_group") or "").strip(),
        "content_type": str(source.get("content_type") or "").strip(),
        "url": str(source.get("url") or source.get("post_url") or source.get("published_url") or "").strip(),
        "post_id": str(source.get("post_id") or source.get("blogger_post_id") or "").strip(),
        "status": "published",
        "published": True,
        "dry_run": False,
        "publish_succeeded": True,
        "post_publish_audit_passed": None,
        "source_type": "news_publish_service",
        "history_backfilled": True,
        "history_backfilled_from": str(source_path),
        "history_backfilled_at": normalized_at,
        "internal_link_targets": [],
    }
    for key in (
        "total_score",
        "click_potential_score",
        "labels",
        "hashtags",
        "permalink_slug",
        "search_description",
    ):
        if key in source:
            record[key] = source.get(key)
    return record


def _normalize_datetime_text(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    parsed_raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(parsed_raw)
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _tombstone_keys(records: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for record in records:
        if _is_tombstone_record(record):
            keys.update(_record_keys(record))
    return keys


def _published_keys(records: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for record in records:
        if PublishHistoryService.is_published_record(record):
            keys.update(_record_keys(record))
    return keys


def _is_tombstone_record(record: dict[str, Any]) -> bool:
    if _record_has_dead_post_note(record):
        return True
    status = str(record.get("status") or "").strip().lower()
    if status == "blocked_by_post_publish_audit" and _as_bool(record.get("published")) is False:
        return True
    if _as_bool(record.get("post_publish_audit_cleanup_deleted")) is True:
        return True
    return False


def _record_has_dead_post_note(record: dict[str, Any]) -> bool:
    note = " ".join(
        str(record.get(key) or "")
        for key in ("note", "reason", "publish_error", "post_publish_audit_error")
    )
    return bool(DEAD_POST_NOTE_RE.search(note))


def _record_keys(record: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    post_id = str(record.get("post_id") or record.get("blogger_post_id") or "").strip()
    if post_id:
        keys.add(f"post_id:{post_id}")
    url = _record_url(record)
    if url:
        keys.add(f"url:{url.rstrip('/')}")
    return keys


def _record_url(record: dict[str, Any]) -> str:
    for key in ("url", "post_url", "published_url", "blogger_url"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _needs_live_correction(record: dict[str, Any]) -> bool:
    if _record_has_dead_post_note(record):
        return False
    if not _record_url(record):
        return False
    status = str(record.get("status") or "").strip().lower()
    if status not in {"published", "trending_published"}:
        return False
    return _as_bool(record.get("dry_run")) is True or _as_bool(record.get("published")) is False


def _mark_live_corrected(record: dict[str, Any], *, normalized_at: str) -> None:
    if "original_dry_run" not in record:
        record["original_dry_run"] = record.get("dry_run")
    record["dry_run"] = False
    record["published"] = True
    record["publish_succeeded"] = True
    record["live_url_verified"] = True
    record["history_normalized_at"] = normalized_at
    notes = record.get("history_normalization_notes")
    if not isinstance(notes, list):
        notes = []
    note = "corrected_dry_run_flag_after_live_url_verification"
    if note not in notes:
        notes.append(note)
    record["history_normalization_notes"] = notes


def _verify_url_status(url: str) -> int | None:
    for method in ("HEAD", "GET"):
        request = Request(
            url,
            method=method,
            headers={"User-Agent": "blogspot-publish-history-sync/1.0"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                return _status_code(response)
        except HTTPError as exc:
            return int(exc.code)
        except (TimeoutError, URLError, OSError):
            if method == "GET":
                return None
    return None


def _status_code(response: HTTPResponse) -> int:
    return int(getattr(response, "status", None) or response.getcode())


def _sort_and_trim(records: list[dict[str, Any]], *, max_records: int) -> list[dict[str, Any]]:
    indexed = list(enumerate(records))
    indexed.sort(key=lambda item: (_parse_sort_datetime(item[1]), item[0]))
    sorted_records = [record for _, record in indexed]
    if max_records > 0 and len(sorted_records) > max_records:
        return sorted_records[-max_records:]
    return sorted_records


def _parse_sort_datetime(record: dict[str, Any]) -> datetime:
    for key in ("run_at", "published_at", "date", "created_at"):
        raw = str(record.get(key) or "").strip()
        if not raw:
            continue
        parsed_raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(parsed_raw)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _backup_history(*, history_path: Path, backup_dir: Path, now: datetime) -> str:
    if not history_path.exists():
        return ""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{history_path.name}.{timestamp}.bak"
    shutil.copy2(history_path, backup_path)
    return str(backup_path)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill and normalize data/publish_history.json safely.")
    parser.add_argument("--history-path", default=str(DEFAULT_HISTORY_PATH))
    parser.add_argument("--published-history-path", default=str(DEFAULT_PUBLISHED_HISTORY_PATH))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--verify-live-urls", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-records", type=int, default=MAX_RECORDS)
    args = parser.parse_args(argv)

    report = sync_publish_history(
        history_path=args.history_path,
        published_history_path=args.published_history_path,
        backup_dir=args.backup_dir,
        verify_live_urls=args.verify_live_urls,
        dry_run=args.dry_run,
        max_records=args.max_records,
    )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
