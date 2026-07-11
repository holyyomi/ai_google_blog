from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RECORDS = 240
_MAX_DAYS = 180
_PUBLISHED_STATUSES = {"published", "trending_published"}
_DEAD_POST_NOTE_RE = re.compile(r"\b(?:404|deleted|dereferenced|not\s+found)\b", re.IGNORECASE)


class PublishHistoryService:
    """Persist run history to data/publish_history.json for axis rotation and topic dedup."""

    def __init__(self, *, history_path: str | Path | None = None) -> None:
        self.history_path = Path(history_path or "data/publish_history.json")

    def load(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("publish_history load error: %s | path=%s", exc, self.history_path)
            return []
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
        return []

    def append_record(self, record: dict[str, Any]) -> bool:
        records = self.load()
        records.append(record)
        records = self._trim(records)
        return self._save(records)

    @staticmethod
    def is_published_record(record: dict[str, Any]) -> bool:
        """이 레코드가 '라이브 블로그에 실제 존재하는 글'인지 판정한다.

        주의: 발행 후 감사(post_publish_audit) 결과로 판정하면 안 된다.
        감사가 advisory 이슈로 passed=False여도 글은 라이브에 남는다
        (news_pipeline._execute_publish_flow — 치명 이슈만 삭제 후
        blocked_by_post_publish_audit로 기록). 과거에 여기서
        post_publish_audit_passed=False를 미발행 취급해, 라이브 발행 전건이
        만성 감사 이슈로 dedup·엔티티 쿨다운 이력에서 사라졌고 같은 주제가
        연속 발행됐다(2026-07-10/11 "구글 AI 검색 변화" 동일 주제 2연속 실측).
        감사 품질로 거르고 싶은 소비자(내부링크 후보 등)는 각자
        post_publish_audit_passed를 따로 봐야 한다(seo_policy.py 참고).
        """
        status = str(record.get("status") or "").strip().lower()
        live_verified = _record_has_live_verification(record)
        if _record_has_dead_post_note(record):
            return False
        if _as_bool(record.get("dry_run")) is True and not live_verified:
            return False
        if _as_bool(record.get("published")) is False and not live_verified:
            return False
        return (
            status in _PUBLISHED_STATUSES
            or _as_bool(record.get("published")) is True
            or _as_bool(record.get("publish_succeeded")) is True
            or live_verified
        )

    def recent_records(self, *, limit: int = 14, published_only: bool = False) -> list[dict[str, Any]]:
        records = self.load()
        if published_only:
            records = [record for record in records if self.is_published_record(record)]
        records.sort(
            key=lambda r: str(r.get("run_at") or r.get("date") or ""),
            reverse=True,
        )
        return records[:limit]

    def recent_evergreen_axes(self, *, limit: int = 14) -> list[str]:
        return [
            str(r["evergreen_axis"])
            for r in self.recent_records(limit=limit, published_only=True)
            if r.get("evergreen_axis")
        ]

    def recent_topic_groups(self, *, limit: int = 14) -> list[str]:
        return [
            str(r["topic_group"])
            for r in self.recent_records(limit=limit, published_only=True)
            if r.get("topic_group")
        ]

    def recent_content_types(self, *, limit: int = 14) -> list[str]:
        return [
            str(r["content_type"])
            for r in self.recent_records(limit=limit, published_only=True)
            if r.get("content_type")
        ]

    @staticmethod
    def _trim(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cutoff = (date.today() - timedelta(days=_MAX_DAYS)).isoformat()
        filtered = [
            r for r in records
            if str(r.get("date") or r.get("run_at") or "9999")[:10] >= cutoff
        ]
        return filtered[-_MAX_RECORDS:]

    def _save(self, records: list[dict[str, Any]]) -> bool:
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as exc:
            logger.error("publish_history save error: %s | path=%s", exc, self.history_path)
            return False


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


def _record_has_dead_post_note(record: dict[str, Any]) -> bool:
    note = " ".join(
        str(record.get(key) or "")
        for key in ("note", "reason", "publish_error", "post_publish_audit_error")
    )
    return bool(_DEAD_POST_NOTE_RE.search(note))


def _record_has_live_verification(record: dict[str, Any]) -> bool:
    if _as_bool(record.get("live_url_verified")) is True:
        return True
    status_code = record.get("url_verified_status_code")
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 400
