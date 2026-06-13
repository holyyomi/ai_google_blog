from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from blogspot_automation.config import Settings
from blogspot_automation.models import TopicCandidate


class StateStore:
    """Minimal local SQLite state store for idempotency and tracking."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.paths = settings.app_paths()

    @property
    def db_path(self) -> Path:
        return self.paths.sqlite_path

    def initialize(self) -> None:
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.paths.contents_dir.mkdir(parents=True, exist_ok=True)
        self.paths.runs_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_path TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_candidates (
                    topic_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    ai_name TEXT NOT NULL,
                    topic_name TEXT NOT NULL,
                    topic_type TEXT NOT NULL,
                    topic_angle TEXT NOT NULL,
                    keyword_primary TEXT NOT NULL,
                    keyword_secondary TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_published_at TEXT,
                    candidate_title TEXT NOT NULL,
                    candidate_summary TEXT NOT NULL,
                    trend_score REAL NOT NULL,
                    score_breakdown TEXT NOT NULL,
                    duplicate_key TEXT NOT NULL UNIQUE,
                    selected_reason TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            self._ensure_topic_candidate_columns(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS published_topics (
                    topic_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    blogger_post_id TEXT,
                    blogger_post_url TEXT,
                    published_at TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    response_path TEXT,
                    request_path TEXT,
                    published_post_path TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS publish_history (
                    history_id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    blogger_post_id TEXT,
                    blogger_post_url TEXT,
                    created_at TEXT NOT NULL,
                    request_path TEXT,
                    response_path TEXT,
                    published_post_path TEXT
                )
                """
            )

    def status_summary(self) -> dict[str, str]:
        self.initialize()
        exists = self.db_path.exists()
        planned_count = "0"
        published_count = "0"
        if exists:
            with sqlite3.connect(self.db_path) as connection:
                row = connection.execute(
                    "SELECT COUNT(*) FROM topic_candidates WHERE status = 'planned'"
                ).fetchone()
                planned_count = str(row[0]) if row else "0"
                published_row = connection.execute(
                    "SELECT COUNT(*) FROM published_topics WHERE status = 'published'"
                ).fetchone()
                published_count = str(published_row[0]) if published_row else "0"
        return {
            "sqlite_path": str(self.db_path),
            "exists": str(exists).lower(),
            "planned_topics": planned_count,
            "published_topics": published_count,
        }

    def has_duplicate_key(self, duplicate_key: str) -> bool:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM topic_candidates WHERE duplicate_key = ? LIMIT 1",
                (duplicate_key,),
            ).fetchone()
        return row is not None

    def save_topic_candidates(self, candidates: list[TopicCandidate]) -> int:
        self.initialize()
        if not candidates:
            return 0

        with sqlite3.connect(self.db_path) as connection:
            for candidate in candidates:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO topic_candidates (
                        topic_id, run_id, created_at, ai_name, topic_name, topic_type,
                        topic_angle, keyword_primary, keyword_secondary, topic_cluster,
                        topic_subcluster, content_mode, main_keyword, supporting_keywords,
                        user_intent, audience_level, geo_targeting_hint, age_targeting_hint,
                        search_angle, monetization_angle, automation_angle, source_name,
                        source_type, source_url, source_published_at, candidate_title,
                        candidate_summary, trend_score, score_breakdown, duplicate_key,
                        selected_reason, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.topic_id,
                        candidate.run_id,
                        candidate.created_at,
                        candidate.ai_name,
                        candidate.topic_name,
                        candidate.topic_type,
                        candidate.topic_angle,
                        candidate.keyword_primary,
                        json.dumps(candidate.keyword_secondary, ensure_ascii=True),
                        candidate.topic_cluster,
                        candidate.topic_subcluster,
                        candidate.content_mode,
                        candidate.main_keyword,
                        json.dumps(candidate.supporting_keywords, ensure_ascii=True),
                        candidate.user_intent,
                        candidate.audience_level,
                        candidate.geo_targeting_hint,
                        candidate.age_targeting_hint,
                        candidate.search_angle,
                        candidate.monetization_angle,
                        candidate.automation_angle,
                        candidate.source_name,
                        candidate.source_type,
                        candidate.source_url,
                        candidate.source_published_at,
                        candidate.candidate_title,
                        candidate.candidate_summary,
                        candidate.trend_score,
                        json.dumps(candidate.score_breakdown.to_dict(), ensure_ascii=True),
                        candidate.duplicate_key,
                        candidate.selected_reason,
                        candidate.status.value,
                    ),
                )
            saved_count = connection.total_changes

        self.export_planned_topics()
        return saved_count

    def list_planned_topics(self) -> list[dict[str, object]]:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT *
                FROM topic_candidates
                WHERE status = 'planned'
                ORDER BY trend_score DESC, created_at DESC
                """
            ).fetchall()
        return [self._row_to_topic_dict(row) for row in rows]

    def export_planned_topics(self) -> Path:
        planned_topics_path = self.paths.contents_dir / "planned_topics.json"
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "planned_topics": self.list_planned_topics(),
        }
        planned_topics_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return planned_topics_path

    def get_planned_topic(self, topic_id: str) -> dict[str, object]:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT *
                FROM topic_candidates
                WHERE topic_id = ? AND status = 'planned'
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Planned topic not found for topic_id={topic_id}")
        return self._row_to_topic_dict(row)

    def get_topic_by_id(self, topic_id: str) -> dict[str, object]:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT *
                FROM topic_candidates
                WHERE topic_id = ?
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Topic not found for topic_id={topic_id}")
        return self._row_to_topic_dict(row)

    def topic_output_dir(self, topic_id: str) -> Path:
        output_dir = self.paths.contents_dir / topic_id
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def load_brief(self, topic_id: str) -> dict[str, object]:
        brief_path = self.topic_output_dir(topic_id) / "brief.json"
        if not brief_path.exists():
            raise FileNotFoundError(f"Brief file not found: {brief_path}")
        return json.loads(brief_path.read_text(encoding="utf-8"))

    def load_blog_package(self, topic_id: str) -> dict[str, object]:
        blog_package_path = self.topic_output_dir(topic_id) / "blog_package.json"
        if not blog_package_path.exists():
            raise FileNotFoundError(f"Blog package file not found: {blog_package_path}")
        return json.loads(blog_package_path.read_text(encoding="utf-8"))

    def try_load_blog_package(self, topic_id: str) -> dict[str, object] | None:
        blog_package_path = self.topic_output_dir(topic_id) / "blog_package.json"
        if not blog_package_path.exists():
            return None
        return json.loads(blog_package_path.read_text(encoding="utf-8"))

    def save_blog_package(self, topic_id: str, payload: dict[str, object]) -> None:
        blog_package_path = self.topic_output_dir(topic_id) / "blog_package.json"
        blog_package_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_metadata(self, topic_id: str) -> dict[str, object]:
        metadata_path = self.topic_output_dir(topic_id) / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def save_metadata(self, topic_id: str, payload: dict[str, object]) -> None:
        metadata_path = self.topic_output_dir(topic_id) / "metadata.json"
        metadata_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def topic_image_dir(self, topic_id: str) -> Path:
        image_dir = self.paths.images_dir / topic_id
        image_dir.mkdir(parents=True, exist_ok=True)
        return image_dir

    def try_load_image_meta(self, topic_id: str) -> dict[str, object] | None:
        image_meta_path = self.topic_image_dir(topic_id) / "image_meta.json"
        if not image_meta_path.exists():
            return None
        return json.loads(image_meta_path.read_text(encoding="utf-8"))

    def topic_publish_dir(self, topic_id: str) -> Path:
        publish_dir = self.topic_output_dir(topic_id) / "publish"
        publish_dir.mkdir(parents=True, exist_ok=True)
        return publish_dir

    def topic_qa_dir(self, topic_id: str) -> Path:
        qa_dir = self.topic_output_dir(topic_id) / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        return qa_dir

    def load_final_ready_package(self, topic_id: str) -> dict[str, object]:
        final_ready_path = self.topic_output_dir(topic_id) / "final_ready_package.json"
        if not final_ready_path.exists():
            raise FileNotFoundError(
                f"final_ready_package.json is required before publishing: {final_ready_path}"
            )
        return json.loads(final_ready_path.read_text(encoding="utf-8"))

    def save_final_ready_package(self, topic_id: str, payload: dict[str, object]) -> None:
        final_ready_path = self.topic_output_dir(topic_id) / "final_ready_package.json"
        final_ready_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def try_load_final_ready_package(self, topic_id: str) -> dict[str, object] | None:
        final_ready_path = self.topic_output_dir(topic_id) / "final_ready_package.json"
        if not final_ready_path.exists():
            return None
        return json.loads(final_ready_path.read_text(encoding="utf-8"))

    def save_qa_report(self, topic_id: str, payload: dict[str, object]) -> None:
        qa_report_path = self.topic_qa_dir(topic_id) / "qa_report.json"
        qa_report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_qa_report(self, topic_id: str) -> dict[str, object]:
        qa_report_path = self.topic_qa_dir(topic_id) / "qa_report.json"
        if not qa_report_path.exists():
            raise FileNotFoundError(f"QA report file not found: {qa_report_path}")
        return json.loads(qa_report_path.read_text(encoding="utf-8"))

    def try_load_qa_report(self, topic_id: str) -> dict[str, object] | None:
        qa_report_path = self.topic_qa_dir(topic_id) / "qa_report.json"
        if not qa_report_path.exists():
            return None
        return json.loads(qa_report_path.read_text(encoding="utf-8"))

    def save_qa_revision_payload(self, topic_id: str, payload: dict[str, object]) -> None:
        revision_path = self.topic_qa_dir(topic_id) / "revision_payload.json"
        revision_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_qa_revision_payload(self, topic_id: str) -> dict[str, object]:
        revision_path = self.topic_qa_dir(topic_id) / "revision_payload.json"
        if not revision_path.exists():
            raise FileNotFoundError(f"QA revision payload file not found: {revision_path}")
        return json.loads(revision_path.read_text(encoding="utf-8"))

    def get_publish_status(self, topic_id: str) -> dict[str, object] | None:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT topic_id, status, blogger_post_id, blogger_post_url, published_at,
                       dry_run, response_path, request_path, published_post_path
                FROM published_topics
                WHERE topic_id = ?
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "topic_id": row["topic_id"],
            "status": row["status"],
            "blogger_post_id": row["blogger_post_id"],
            "blogger_post_url": row["blogger_post_url"],
            "published_at": row["published_at"],
            "dry_run": bool(row["dry_run"]),
            "response_path": row["response_path"],
            "request_path": row["request_path"],
            "published_post_path": row["published_post_path"],
        }

    def save_publish_status(
        self,
        *,
        topic_id: str,
        status: str,
        blogger_post_id: str | None,
        blogger_post_url: str | None,
        published_at: str,
        dry_run: bool,
        response_path: str | None,
        request_path: str,
        published_post_path: str | None,
    ) -> None:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO published_topics (
                    topic_id, status, blogger_post_id, blogger_post_url, published_at,
                    dry_run, response_path, request_path, published_post_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                    status = excluded.status,
                    blogger_post_id = excluded.blogger_post_id,
                    blogger_post_url = excluded.blogger_post_url,
                    published_at = excluded.published_at,
                    dry_run = excluded.dry_run,
                    response_path = excluded.response_path,
                    request_path = excluded.request_path,
                    published_post_path = excluded.published_post_path
                """,
                (
                    topic_id,
                    status,
                    blogger_post_id,
                    blogger_post_url,
                    published_at,
                    1 if dry_run else 0,
                    response_path,
                    request_path,
                    published_post_path,
                ),
            )

    def save_publish_history(
        self,
        *,
        history_id: str,
        topic_id: str,
        status: str,
        dry_run: bool,
        blogger_post_id: str | None,
        blogger_post_url: str | None,
        created_at: str,
        request_path: str | None,
        response_path: str | None,
        published_post_path: str | None,
    ) -> None:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO publish_history (
                    history_id, topic_id, status, dry_run, blogger_post_id, blogger_post_url,
                    created_at, request_path, response_path, published_post_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    topic_id,
                    status,
                    1 if dry_run else 0,
                    blogger_post_id,
                    blogger_post_url,
                    created_at,
                    request_path,
                    response_path,
                    published_post_path,
                ),
            )

    def list_recent_publish_history(self, limit: int = 10) -> list[dict[str, object]]:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT history_id, topic_id, status, dry_run, blogger_post_id, blogger_post_url,
                       created_at, request_path, response_path, published_post_path
                FROM publish_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "history_id": row["history_id"],
                "topic_id": row["topic_id"],
                "status": row["status"],
                "dry_run": bool(row["dry_run"]),
                "blogger_post_id": row["blogger_post_id"],
                "blogger_post_url": row["blogger_post_url"],
                "created_at": row["created_at"],
                "request_path": row["request_path"],
                "response_path": row["response_path"],
                "published_post_path": row["published_post_path"],
            }
            for row in rows
        ]

    def update_topic_candidate_status(self, topic_id: str, status: str) -> None:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE topic_candidates SET status = ? WHERE topic_id = ?",
                (status, topic_id),
            )

    def save_fact_pack(self, topic_id: str, payload: dict[str, object]) -> None:
        fact_pack_path = self.topic_output_dir(topic_id) / "fact_pack.json"
        fact_pack_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_fact_pack(self, topic_id: str) -> dict[str, object]:
        fact_pack_path = self.topic_output_dir(topic_id) / "fact_pack.json"
        if not fact_pack_path.exists():
            raise FileNotFoundError(f"Fact pack file not found: {fact_pack_path}")
        return json.loads(fact_pack_path.read_text(encoding="utf-8"))

    def save_source_pack(self, topic_id: str, payload: dict[str, object]) -> None:
        source_pack_path = self.topic_output_dir(topic_id) / "source_pack.json"
        source_pack_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_source_pack(self, topic_id: str) -> dict[str, object]:
        source_pack_path = self.topic_output_dir(topic_id) / "source_pack.json"
        if not source_pack_path.exists():
            raise FileNotFoundError(f"Source pack file not found: {source_pack_path}")
        return json.loads(source_pack_path.read_text(encoding="utf-8"))

    @staticmethod
    def _row_to_topic_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "run_id": row["run_id"],
            "topic_id": row["topic_id"],
            "created_at": row["created_at"],
            "ai_name": row["ai_name"],
            "topic_name": row["topic_name"],
            "topic_type": row["topic_type"],
            "topic_angle": row["topic_angle"],
            "keyword_primary": row["keyword_primary"],
            "keyword_secondary": json.loads(row["keyword_secondary"]),
            "topic_cluster": row["topic_cluster"],
            "topic_subcluster": row["topic_subcluster"],
            "content_mode": row["content_mode"],
            "main_keyword": row["main_keyword"],
            "supporting_keywords": json.loads(row["supporting_keywords"]),
            "user_intent": row["user_intent"],
            "audience_level": row["audience_level"],
            "geo_targeting_hint": row["geo_targeting_hint"],
            "age_targeting_hint": row["age_targeting_hint"],
            "search_angle": row["search_angle"],
            "monetization_angle": row["monetization_angle"],
            "automation_angle": row["automation_angle"],
            "source_name": row["source_name"],
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "source_published_at": row["source_published_at"],
            "candidate_title": row["candidate_title"],
            "candidate_summary": row["candidate_summary"],
            "trend_score": row["trend_score"],
            "score_breakdown": json.loads(row["score_breakdown"]),
            "duplicate_key": row["duplicate_key"],
            "selected_reason": row["selected_reason"],
            "status": row["status"],
        }

    @staticmethod
    def _ensure_topic_candidate_columns(connection: sqlite3.Connection) -> None:
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(topic_candidates)").fetchall()
        }
        required_columns = {
            "topic_cluster": "TEXT NOT NULL DEFAULT ''",
            "topic_subcluster": "TEXT NOT NULL DEFAULT ''",
            "content_mode": "TEXT NOT NULL DEFAULT ''",
            "main_keyword": "TEXT NOT NULL DEFAULT ''",
            "supporting_keywords": "TEXT NOT NULL DEFAULT '[]'",
            "user_intent": "TEXT NOT NULL DEFAULT ''",
            "audience_level": "TEXT NOT NULL DEFAULT ''",
            "geo_targeting_hint": "TEXT NOT NULL DEFAULT ''",
            "age_targeting_hint": "TEXT NOT NULL DEFAULT ''",
            "search_angle": "TEXT NOT NULL DEFAULT ''",
            "monetization_angle": "TEXT NOT NULL DEFAULT ''",
            "automation_angle": "TEXT NOT NULL DEFAULT ''",
        }
        for column_name, definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE topic_candidates ADD COLUMN {column_name} {definition}"
                )
