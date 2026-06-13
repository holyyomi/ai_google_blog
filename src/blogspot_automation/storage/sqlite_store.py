from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class StorageError(RuntimeError):
    pass


class InvalidStatusTransitionError(StorageError):
    pass


class SQLiteBlogStore:
    def __init__(self, root_dir: Path, db_filename: str = "blog_automation.db") -> None:
        self.root_dir = root_dir.resolve()
        self.data_dir = self.root_dir / "data"
        self.fallback_dir = self.data_dir / "fallback"
        self.db_path = self.data_dir / db_filename

    def initialize(self) -> Path:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.fallback_dir.mkdir(parents=True, exist_ok=True)
            with self.connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                self._apply_migrations(connection)
            return self.db_path
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to initialize SQLite store: {exc}") from exc

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def write_fallback_record(self, *, table_name: str, record_id: str, payload: dict[str, object]) -> Path:
        target_dir = self.fallback_dir / table_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{record_id}.json"
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target_path

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        applied_versions = {
            int(row["version"]) for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migrations: list[tuple[int, str]] = [
            (
                1,
                """
                CREATE TABLE IF NOT EXISTS blog_work_items (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    content_pillar TEXT NOT NULL,
                    topic_title TEXT NOT NULL,
                    primary_keyword TEXT NOT NULL,
                    secondary_keywords_json TEXT NOT NULL DEFAULT '[]',
                    source_urls_json TEXT NOT NULL DEFAULT '[]',
                    source_summary TEXT NOT NULL DEFAULT '',
                    final_title TEXT NOT NULL DEFAULT '',
                    meta_description TEXT NOT NULL DEFAULT '',
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    hashtags_json TEXT NOT NULL DEFAULT '[]',
                    image_prompt TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    article_html TEXT NOT NULL DEFAULT '',
                    json_ld_json TEXT NOT NULL DEFAULT '{}',
                    qa_result TEXT NOT NULL DEFAULT '',
                    qa_issues_json TEXT NOT NULL DEFAULT '[]',
                    publish_status TEXT NOT NULL,
                    blog_url TEXT NOT NULL DEFAULT '',
                    blog_post_id TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT ''
                )
                """,
            ),
            (
                2,
                "CREATE INDEX IF NOT EXISTS idx_blog_work_items_status_updated ON blog_work_items(publish_status, updated_at DESC)",
            ),
            (
                3,
                "CREATE INDEX IF NOT EXISTS idx_blog_work_items_pillar_updated ON blog_work_items(content_pillar, updated_at DESC)",
            ),
            (
                4,
                """
                CREATE TABLE IF NOT EXISTS brief_records (
                    work_item_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    brief_summary TEXT NOT NULL,
                    final_angle TEXT NOT NULL,
                    target_reader TEXT NOT NULL,
                    reader_problem TEXT NOT NULL DEFAULT '',
                    search_intent TEXT NOT NULL,
                    one_line_hook TEXT NOT NULL,
                    why_now TEXT NOT NULL DEFAULT '',
                    outline_sections_json TEXT NOT NULL DEFAULT '[]',
                    key_takeaways_json TEXT NOT NULL DEFAULT '[]',
                    facts_from_sources_json TEXT NOT NULL DEFAULT '[]',
                    hard_facts_from_sources_json TEXT NOT NULL DEFAULT '[]',
                    source_consensus_json TEXT NOT NULL DEFAULT '[]',
                    source_differences_json TEXT NOT NULL DEFAULT '[]',
                    what_it_means_to_reader_json TEXT NOT NULL DEFAULT '[]',
                    cautions_json TEXT NOT NULL DEFAULT '[]',
                    practical_actions_json TEXT NOT NULL DEFAULT '[]',
                    estimated_time_to_start TEXT NOT NULL DEFAULT '',
                    estimated_cost_to_start TEXT NOT NULL DEFAULT '',
                    potential_income_range TEXT NOT NULL DEFAULT '',
                    difficulty_level TEXT NOT NULL DEFAULT '',
                    recommended_for_json TEXT NOT NULL DEFAULT '[]',
                    not_recommended_for_json TEXT NOT NULL DEFAULT '[]',
                    failure_points_json TEXT NOT NULL DEFAULT '[]',
                    monetization_block_idea TEXT NOT NULL DEFAULT '',
                    faq_candidates_json TEXT NOT NULL DEFAULT '[]',
                    faq_items_json TEXT NOT NULL DEFAULT '[]',
                    evidence_points_json TEXT NOT NULL DEFAULT '[]',
                    cta_direction TEXT NOT NULL DEFAULT '',
                    cta_type TEXT NOT NULL DEFAULT '',
                    content_density_status TEXT NOT NULL DEFAULT ''
                )
                """,
            ),
            (
                5,
                """
                CREATE TABLE IF NOT EXISTS content_package_records (
                    work_item_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    title_candidates_json TEXT NOT NULL DEFAULT '[]',
                    final_title TEXT NOT NULL DEFAULT '',
                    meta_description TEXT NOT NULL DEFAULT '',
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    hashtags_json TEXT NOT NULL DEFAULT '[]',
                    image_prompt TEXT NOT NULL DEFAULT '',
                    article_html TEXT NOT NULL DEFAULT '',
                    article_preview_html TEXT NOT NULL DEFAULT '',
                    json_ld_json TEXT NOT NULL DEFAULT '{}'
                )
                """,
            ),
            (
                6,
                """
                CREATE TABLE IF NOT EXISTS qa_review_records (
                    work_item_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    qa_result TEXT NOT NULL,
                    qa_score INTEGER NOT NULL DEFAULT 0,
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    fixes_json TEXT NOT NULL DEFAULT '[]',
                    review_summary TEXT NOT NULL DEFAULT '',
                    requires_manual_approval INTEGER NOT NULL DEFAULT 0
                )
                """,
            ),
            (
                7,
                """
                CREATE TABLE IF NOT EXISTS publish_records (
                    publish_id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    publish_mode TEXT NOT NULL,
                    target_status TEXT NOT NULL,
                    publish_result TEXT NOT NULL,
                    blog_url TEXT NOT NULL DEFAULT '',
                    blog_post_id TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT NOT NULL DEFAULT ''
                )
                """,
            ),
            (
                8,
                "CREATE INDEX IF NOT EXISTS idx_publish_records_work_item_created ON publish_records(work_item_id, created_at DESC)",
            ),
            (
                9,
                "-- topic selection quality columns added via helper",
            ),
            (
                10,
                "-- content quality columns added via helper",
            ),
            (
                11,
                "-- image qa publish lock columns added via helper",
            ),
            (
                12,
                "-- topic discovery debug columns added via helper",
            ),
            (
                13,
                "-- topic discovery retry columns added via helper",
            ),
            (
                14,
                "-- content_type column added via helper",
            ),
        ]
        for version, sql in migrations:
            if version in applied_versions:
                continue
            if version == 9:
                self._apply_topic_quality_columns(connection)
            elif version == 10:
                self._apply_content_quality_columns(connection)
            elif version == 11:
                self._apply_image_publish_columns(connection)
            elif version == 12:
                self._apply_topic_discovery_debug_columns(connection)
            elif version == 13:
                self._apply_topic_discovery_retry_columns(connection)
            elif version == 14:
                self._apply_content_type_column(connection)
            else:
                connection.execute(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES(?, datetime('now'))",
                (version,),
            )

    def _apply_topic_quality_columns(self, connection: sqlite3.Connection) -> None:
        additions = [
            ("selected_pillar", "TEXT NOT NULL DEFAULT ''"),
            ("selected_topic", "TEXT NOT NULL DEFAULT ''"),
            ("why_selected", "TEXT NOT NULL DEFAULT ''"),
            ("source_articles_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("source_count", "INTEGER NOT NULL DEFAULT 0"),
            ("source_domains_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("keyword_set_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("title_candidates_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("title_candidate_types_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("topic_score", "REAL NOT NULL DEFAULT 0"),
            ("source_quality_status", "TEXT NOT NULL DEFAULT ''"),
        ]
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(blog_work_items)").fetchall()
        }
        for name, definition in additions:
            if name in existing:
                continue
            connection.execute(f"ALTER TABLE blog_work_items ADD COLUMN {name} {definition}")

    def _apply_content_quality_columns(self, connection: sqlite3.Connection) -> None:
        work_item_additions = [
            ("estimated_time_to_start", "TEXT NOT NULL DEFAULT ''"),
            ("estimated_cost_to_start", "TEXT NOT NULL DEFAULT ''"),
            ("potential_income_range", "TEXT NOT NULL DEFAULT ''"),
            ("difficulty_level", "TEXT NOT NULL DEFAULT ''"),
            ("recommended_for_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("not_recommended_for_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("failure_points_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("faq_items_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("cta_type", "TEXT NOT NULL DEFAULT ''"),
            ("content_density_status", "TEXT NOT NULL DEFAULT ''"),
        ]
        brief_additions = [
            ("reader_problem", "TEXT NOT NULL DEFAULT ''"),
            ("why_now", "TEXT NOT NULL DEFAULT ''"),
            ("hard_facts_from_sources_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("source_consensus_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("source_differences_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("what_it_means_to_reader_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("estimated_time_to_start", "TEXT NOT NULL DEFAULT ''"),
            ("estimated_cost_to_start", "TEXT NOT NULL DEFAULT ''"),
            ("potential_income_range", "TEXT NOT NULL DEFAULT ''"),
            ("difficulty_level", "TEXT NOT NULL DEFAULT ''"),
            ("recommended_for_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("not_recommended_for_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("failure_points_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("content_density_status", "TEXT NOT NULL DEFAULT ''"),
        ]
        self._apply_column_additions(connection, "blog_work_items", work_item_additions)
        self._apply_column_additions(connection, "brief_records", brief_additions)

    def _apply_image_publish_columns(self, connection: sqlite3.Connection) -> None:
        work_item_additions = [
            ("generated_image_status", "TEXT NOT NULL DEFAULT ''"),
            ("image_error_message", "TEXT NOT NULL DEFAULT ''"),
            ("final_image_url", "TEXT NOT NULL DEFAULT ''"),
            ("publish_block_reason", "TEXT NOT NULL DEFAULT ''"),
            ("approval_required", "INTEGER NOT NULL DEFAULT 0"),
        ]
        self._apply_column_additions(connection, "blog_work_items", work_item_additions)

    def _apply_topic_discovery_debug_columns(self, connection: sqlite3.Connection) -> None:
        work_item_additions = [
            ("discovery_debug_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("raw_candidate_count", "INTEGER NOT NULL DEFAULT 0"),
            ("parsed_candidate_count", "INTEGER NOT NULL DEFAULT 0"),
            ("filtered_candidate_count", "INTEGER NOT NULL DEFAULT 0"),
            ("reject_reason_summary_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("final_discovery_status", "TEXT NOT NULL DEFAULT ''"),
        ]
        self._apply_column_additions(connection, "blog_work_items", work_item_additions)

    def _apply_topic_discovery_retry_columns(self, connection: sqlite3.Connection) -> None:
        work_item_additions = [
            ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("retry_path_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("fallback_strategy_used", "TEXT NOT NULL DEFAULT ''"),
            ("fallback_pillar_used", "TEXT NOT NULL DEFAULT ''"),
            ("discovery_attempts_json", "TEXT NOT NULL DEFAULT '[]'"),
        ]
        self._apply_column_additions(connection, "blog_work_items", work_item_additions)

    def _apply_content_type_column(self, connection: sqlite3.Connection) -> None:
        self._apply_column_additions(
            connection,
            "blog_work_items",
            [("content_type", "TEXT NOT NULL DEFAULT ''")],
        )

    def _apply_column_additions(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        additions: list[tuple[str, str]],
    ) -> None:
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for name, definition in additions:
            if name in existing:
                continue
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")
