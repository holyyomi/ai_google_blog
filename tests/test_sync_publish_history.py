from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from tools.sync_publish_history import sync_publish_history


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sync_backfills_news_published_history_with_backup(tmp_path) -> None:
    history_path = tmp_path / "publish_history.json"
    published_path = tmp_path / "news_published_history.json"
    backup_dir = tmp_path / "backups"
    history_path.write_text("[]", encoding="utf-8")
    published_path.write_text(
        json.dumps(
            [
                {
                    "published_at": "2026-06-08T07:46:31.617812+00:00",
                    "topic": "길드워3 공식 공개와 한국어·PS5·베타 일정",
                    "selected_title": "길드워3 공식 공개: 한국어 지원·PS5 동시 출시·2027 베타 핵심 정리",
                    "post_id": "3376259167831451962",
                    "url": "https://holyeverymoments.blogspot.com/2026/06/ps5-today-issue-update-e62a0-news-b2b0ed.html",
                    "topic_group": "today_issue",
                    "content_type": "today_issue_explainer",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = sync_publish_history(
        history_path=history_path,
        published_history_path=published_path,
        backup_dir=backup_dir,
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    records = _read(history_path)
    assert report.backfilled_records == 1
    assert report.final_records == 1
    assert report.backup_path
    assert Path(report.backup_path).exists()
    assert records[0]["status"] == "published"
    assert records[0]["published"] is True
    assert records[0]["dry_run"] is False
    assert records[0]["publish_succeeded"] is True
    assert records[0]["history_backfilled"] is True
    assert records[0]["run_at"] == "2026-06-08T07:46:31+00:00"


def test_sync_does_not_revive_tombstoned_source_record(tmp_path) -> None:
    history_path = tmp_path / "publish_history.json"
    published_path = tmp_path / "news_published_history.json"
    url = "https://holyeverymoments.blogspot.com/2026/06/deleted.html"
    history_path.write_text(
        json.dumps(
            [
                {
                    "run_at": "2026-06-08T06:27:50+00:00",
                    "status": "published",
                    "published": False,
                    "post_id": "post-1",
                    "url": url,
                    "note": "post_deleted_by_user (404, dereferenced 2026-06-11)",
                }
            ]
        ),
        encoding="utf-8",
    )
    published_path.write_text(
        json.dumps(
            [
                {
                    "published_at": "2026-06-08T06:27:50+00:00",
                    "title": "deleted source",
                    "post_id": "post-1",
                    "url": url,
                }
            ]
        ),
        encoding="utf-8",
    )

    report = sync_publish_history(
        history_path=history_path,
        published_history_path=published_path,
        backup_dir=tmp_path / "backups",
    )

    records = _read(history_path)
    assert report.backfilled_records == 0
    assert report.skipped_tombstoned_source_records == 1
    assert len(records) == 1
    assert records[0]["published"] is False


def test_sync_corrects_verified_live_dry_run_record(tmp_path) -> None:
    history_path = tmp_path / "publish_history.json"
    published_path = tmp_path / "news_published_history.json"
    url = "https://holyeverymoments.blogspot.com/2026/06/live.html"
    history_path.write_text(
        json.dumps(
            [
                {
                    "run_at": "2026-06-10T17:38:03+00:00",
                    "status": "trending_published",
                    "published": True,
                    "dry_run": True,
                    "post_publish_audit_passed": False,
                    "title": "live post",
                    "url": url,
                }
            ]
        ),
        encoding="utf-8",
    )
    published_path.write_text("[]", encoding="utf-8")

    report = sync_publish_history(
        history_path=history_path,
        published_history_path=published_path,
        backup_dir=tmp_path / "backups",
        verify_live_urls=True,
        url_verifier=lambda checked_url: 200 if checked_url == url else None,
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    record = _read(history_path)[0]
    assert report.corrected_live_records == 1
    assert record["dry_run"] is False
    assert record["published"] is True
    assert record["publish_succeeded"] is True
    assert record["live_url_verified"] is True
    assert record["url_verified_status_code"] == 200
    assert record["original_dry_run"] is True
