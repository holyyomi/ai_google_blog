from __future__ import annotations

import json
import sqlite3
from typing import Any

from blogspot_automation.storage.blog_records import (
    BriefRecord,
    DEFAULT_STATUS_TRANSITIONS,
    BlogWorkItem,
    ContentPackageRecord,
    PublishRecord,
    PublishStatus,
    QAReviewRecord,
    now_iso,
)
from blogspot_automation.storage.sqlite_store import (
    InvalidStatusTransitionError,
    SQLiteBlogStore,
    StorageError,
)


def _load_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def _load_json_object(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


class BlogWorkItemRepository:
    def __init__(self, store: SQLiteBlogStore) -> None:
        self.store = store
        self.store.initialize()

    def upsert(self, item: BlogWorkItem) -> BlogWorkItem:
        payload = item.to_dict()
        payload["updated_at"] = now_iso()
        try:
            with self.store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO blog_work_items (
                        id, created_at, updated_at, content_pillar, topic_title, primary_keyword,
                        secondary_keywords_json, source_urls_json, source_summary, selected_pillar,
                        selected_topic, why_selected, source_articles_json, source_count,
                        source_domains_json, keyword_set_json, title_candidates_json,
                        title_candidate_types_json, topic_score, source_quality_status,
                        discovery_debug_json, raw_candidate_count, parsed_candidate_count,
                        filtered_candidate_count, reject_reason_summary_json, final_discovery_status,
                        retry_count, retry_path_json, fallback_strategy_used, fallback_pillar_used,
                        discovery_attempts_json,
                        estimated_time_to_start, estimated_cost_to_start, potential_income_range,
                        difficulty_level, recommended_for_json, not_recommended_for_json,
                        failure_points_json, faq_items_json, cta_type, content_density_status,
                        generated_image_status, image_error_message, final_image_url,
                        publish_block_reason, approval_required, final_title,
                        meta_description, labels_json, hashtags_json, image_prompt, image_url,
                        article_html, json_ld_json, qa_result, qa_issues_json, publish_status,
                        blog_url, blog_post_id, notes, content_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        content_pillar=excluded.content_pillar,
                        topic_title=excluded.topic_title,
                        primary_keyword=excluded.primary_keyword,
                        secondary_keywords_json=excluded.secondary_keywords_json,
                        source_urls_json=excluded.source_urls_json,
                        source_summary=excluded.source_summary,
                        selected_pillar=excluded.selected_pillar,
                        selected_topic=excluded.selected_topic,
                        why_selected=excluded.why_selected,
                        source_articles_json=excluded.source_articles_json,
                        source_count=excluded.source_count,
                        source_domains_json=excluded.source_domains_json,
                        keyword_set_json=excluded.keyword_set_json,
                        title_candidates_json=excluded.title_candidates_json,
                        title_candidate_types_json=excluded.title_candidate_types_json,
                        topic_score=excluded.topic_score,
                        source_quality_status=excluded.source_quality_status,
                        discovery_debug_json=excluded.discovery_debug_json,
                        raw_candidate_count=excluded.raw_candidate_count,
                        parsed_candidate_count=excluded.parsed_candidate_count,
                        filtered_candidate_count=excluded.filtered_candidate_count,
                        reject_reason_summary_json=excluded.reject_reason_summary_json,
                        final_discovery_status=excluded.final_discovery_status,
                        retry_count=excluded.retry_count,
                        retry_path_json=excluded.retry_path_json,
                        fallback_strategy_used=excluded.fallback_strategy_used,
                        fallback_pillar_used=excluded.fallback_pillar_used,
                        discovery_attempts_json=excluded.discovery_attempts_json,
                        estimated_time_to_start=excluded.estimated_time_to_start,
                        estimated_cost_to_start=excluded.estimated_cost_to_start,
                        potential_income_range=excluded.potential_income_range,
                        difficulty_level=excluded.difficulty_level,
                        recommended_for_json=excluded.recommended_for_json,
                        not_recommended_for_json=excluded.not_recommended_for_json,
                        failure_points_json=excluded.failure_points_json,
                        faq_items_json=excluded.faq_items_json,
                        cta_type=excluded.cta_type,
                        content_density_status=excluded.content_density_status,
                        generated_image_status=excluded.generated_image_status,
                        image_error_message=excluded.image_error_message,
                        final_image_url=excluded.final_image_url,
                        publish_block_reason=excluded.publish_block_reason,
                        approval_required=excluded.approval_required,
                        final_title=excluded.final_title,
                        meta_description=excluded.meta_description,
                        labels_json=excluded.labels_json,
                        hashtags_json=excluded.hashtags_json,
                        image_prompt=excluded.image_prompt,
                        image_url=excluded.image_url,
                        article_html=excluded.article_html,
                        json_ld_json=excluded.json_ld_json,
                        qa_result=excluded.qa_result,
                        qa_issues_json=excluded.qa_issues_json,
                        publish_status=excluded.publish_status,
                        blog_url=excluded.blog_url,
                        blog_post_id=excluded.blog_post_id,
                        notes=excluded.notes,
                        content_type=excluded.content_type
                    """,
                    (
                        payload["id"],
                        payload["created_at"],
                        payload["updated_at"],
                        payload["content_pillar"],
                        payload["topic_title"],
                        payload["primary_keyword"],
                        json.dumps(payload["secondary_keywords"], ensure_ascii=False),
                        json.dumps(payload["source_urls"], ensure_ascii=False),
                        payload["source_summary"],
                        payload["selected_pillar"],
                        payload["selected_topic"],
                        payload["why_selected"],
                        json.dumps(payload["source_articles"], ensure_ascii=False),
                        payload["source_count"],
                        json.dumps(payload["source_domains"], ensure_ascii=False),
                        json.dumps(payload["keyword_set"], ensure_ascii=False),
                        json.dumps(payload["title_candidates"], ensure_ascii=False),
                        json.dumps(payload["title_candidate_types"], ensure_ascii=False),
                        payload["topic_score"],
                        payload["source_quality_status"],
                        json.dumps(payload["discovery_debug"], ensure_ascii=False),
                        payload["raw_candidate_count"],
                        payload["parsed_candidate_count"],
                        payload["filtered_candidate_count"],
                        json.dumps(payload["reject_reason_summary"], ensure_ascii=False),
                        payload["final_discovery_status"],
                        payload["retry_count"],
                        json.dumps(payload["retry_path"], ensure_ascii=False),
                        payload["fallback_strategy_used"],
                        payload["fallback_pillar_used"],
                        json.dumps(payload["discovery_attempts"], ensure_ascii=False),
                        payload["estimated_time_to_start"],
                        payload["estimated_cost_to_start"],
                        payload["potential_income_range"],
                        payload["difficulty_level"],
                        json.dumps(payload["recommended_for"], ensure_ascii=False),
                        json.dumps(payload["not_recommended_for"], ensure_ascii=False),
                        json.dumps(payload["failure_points"], ensure_ascii=False),
                        json.dumps(payload["faq_items"], ensure_ascii=False),
                        payload["cta_type"],
                        payload["content_density_status"],
                        payload["generated_image_status"],
                        payload["image_error_message"],
                        payload["final_image_url"],
                        payload["publish_block_reason"],
                        1 if payload["approval_required"] else 0,
                        payload["final_title"],
                        payload["meta_description"],
                        json.dumps(payload["labels"], ensure_ascii=False),
                        json.dumps(payload["hashtags"], ensure_ascii=False),
                        payload["image_prompt"],
                        payload["image_url"],
                        payload["article_html"],
                        json.dumps(payload["json_ld"], ensure_ascii=False),
                        payload["qa_result"],
                        json.dumps(payload["qa_issues"], ensure_ascii=False),
                        payload["publish_status"],
                        payload["blog_url"],
                        payload["blog_post_id"],
                        payload["notes"],
                        payload.get("content_type", ""),
                    ),
                )
        except sqlite3.Error as exc:
            self.store.write_fallback_record(table_name="blog_work_items", record_id=item.id, payload=payload)
            raise StorageError(f"Failed to save work item id={item.id}: {exc}") from exc
        saved = self.get_by_id(item.id)
        if saved is None:
            raise StorageError(f"Saved work item id={item.id} could not be reloaded.")
        return saved

    def get_by_id(self, item_id: str) -> BlogWorkItem | None:
        try:
            with self.store.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM blog_work_items WHERE id = ? LIMIT 1",
                    (item_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to load work item id={item_id}: {exc}") from exc
        return self._row_to_item(row) if row is not None else None

    def list_recent(self, limit: int = 20) -> list[BlogWorkItem]:
        try:
            with self.store.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM blog_work_items
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to list recent work items: {exc}") from exc
        return [self._row_to_item(row) for row in rows]

    def list_recent_by_status(self, *, statuses: list[PublishStatus], limit: int = 20) -> list[BlogWorkItem]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        status_values = [status.value for status in statuses]
        try:
            with self.store.connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT *
                    FROM blog_work_items
                    WHERE publish_status IN ({placeholders})
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (*status_values, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to list recent work items by status: {exc}") from exc
        return [self._row_to_item(row) for row in rows]

    def list_recent_for_streamlit(self, limit: int = 20) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "content_pillar": item.content_pillar,
                "topic_title": item.topic_title,
                "final_title": item.final_title,
                "publish_status": item.publish_status,
                "selected_pillar": item.selected_pillar,
                "selected_topic": item.selected_topic,
                "source_count": item.source_count,
                "source_domains": item.source_domains,
                "source_quality_status": item.source_quality_status,
                "discovery_debug": item.discovery_debug,
                "raw_candidate_count": item.raw_candidate_count,
                "parsed_candidate_count": item.parsed_candidate_count,
                "filtered_candidate_count": item.filtered_candidate_count,
                "reject_reason_summary": item.reject_reason_summary,
                "final_discovery_status": item.final_discovery_status,
                "retry_count": item.retry_count,
                "retry_path": item.retry_path,
                "fallback_strategy_used": item.fallback_strategy_used,
                "fallback_pillar_used": item.fallback_pillar_used,
                "discovery_attempts": item.discovery_attempts,
                "estimated_time_to_start": item.estimated_time_to_start,
                "estimated_cost_to_start": item.estimated_cost_to_start,
                "potential_income_range": item.potential_income_range,
                "difficulty_level": item.difficulty_level,
                "content_density_status": item.content_density_status,
                "generated_image_status": item.generated_image_status,
                "image_error_message": item.image_error_message,
                "final_image_url": item.final_image_url,
                "publish_block_reason": item.publish_block_reason,
                "approval_required": item.approval_required,
                "title_candidates": item.title_candidates,
                "title_candidate_types": item.title_candidate_types,
                "topic_score": item.topic_score,
                "qa_result": item.qa_result,
                "blog_url": item.blog_url,
                "updated_at": item.updated_at,
                "notes": item.notes,
                "qa_issues": item.qa_issues,
            }
            for item in self.list_recent(limit=limit)
        ]

    def transition_status(self, *, item_id: str, next_status: PublishStatus, notes: str | None = None) -> BlogWorkItem:
        item = self.get_by_id(item_id)
        if item is None:
            raise StorageError(f"Work item not found: id={item_id}")
        current_status = PublishStatus(item.publish_status)
        if current_status == next_status:
            if notes:
                item.notes = notes if not item.notes else f"{item.notes}\n{notes}"
                return self.upsert(item)
            return item
        allowed_statuses = DEFAULT_STATUS_TRANSITIONS[current_status]
        if next_status not in allowed_statuses:
            raise InvalidStatusTransitionError(
                f"Invalid status transition for id={item_id}: {current_status.value} -> {next_status.value}"
            )
        item.publish_status = next_status.value
        if notes:
            item.notes = notes if not item.notes else f"{item.notes}\n{notes}"
        return self.upsert(item)

    def create_sample_record(self) -> BlogWorkItem:
        from blogspot_automation.storage.blog_records import create_sample_work_item

        return self.upsert(create_sample_work_item())

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> BlogWorkItem:
        return BlogWorkItem(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            content_pillar=row["content_pillar"],
            topic_title=row["topic_title"],
            primary_keyword=row["primary_keyword"],
            secondary_keywords=_load_json_list(row["secondary_keywords_json"]),
            source_urls=_load_json_list(row["source_urls_json"]),
            source_summary=row["source_summary"],
            selected_pillar=row["selected_pillar"] if "selected_pillar" in row.keys() else "",
            selected_topic=row["selected_topic"] if "selected_topic" in row.keys() else "",
            why_selected=row["why_selected"] if "why_selected" in row.keys() else "",
            source_articles=_load_json_list(row["source_articles_json"]) if "source_articles_json" in row.keys() else [],
            source_count=row["source_count"] if "source_count" in row.keys() else 0,
            source_domains=_load_json_list(row["source_domains_json"]) if "source_domains_json" in row.keys() else [],
            keyword_set=_load_json_object(row["keyword_set_json"]) if "keyword_set_json" in row.keys() else {},
            title_candidates=_load_json_list(row["title_candidates_json"]) if "title_candidates_json" in row.keys() else [],
            title_candidate_types=_load_json_list(row["title_candidate_types_json"]) if "title_candidate_types_json" in row.keys() else [],
            topic_score=float(row["topic_score"]) if "topic_score" in row.keys() else 0.0,
            source_quality_status=row["source_quality_status"] if "source_quality_status" in row.keys() else "",
            discovery_debug=_load_json_object(row["discovery_debug_json"]) if "discovery_debug_json" in row.keys() else {},
            raw_candidate_count=row["raw_candidate_count"] if "raw_candidate_count" in row.keys() else 0,
            parsed_candidate_count=row["parsed_candidate_count"] if "parsed_candidate_count" in row.keys() else 0,
            filtered_candidate_count=row["filtered_candidate_count"] if "filtered_candidate_count" in row.keys() else 0,
            reject_reason_summary=_load_json_object(row["reject_reason_summary_json"]) if "reject_reason_summary_json" in row.keys() else {},
            final_discovery_status=row["final_discovery_status"] if "final_discovery_status" in row.keys() else "",
            retry_count=row["retry_count"] if "retry_count" in row.keys() else 0,
            retry_path=_load_json_list(row["retry_path_json"]) if "retry_path_json" in row.keys() else [],
            fallback_strategy_used=row["fallback_strategy_used"] if "fallback_strategy_used" in row.keys() else "",
            fallback_pillar_used=row["fallback_pillar_used"] if "fallback_pillar_used" in row.keys() else "",
            discovery_attempts=_load_json_list(row["discovery_attempts_json"]) if "discovery_attempts_json" in row.keys() else [],
            estimated_time_to_start=row["estimated_time_to_start"] if "estimated_time_to_start" in row.keys() else "",
            estimated_cost_to_start=row["estimated_cost_to_start"] if "estimated_cost_to_start" in row.keys() else "",
            potential_income_range=row["potential_income_range"] if "potential_income_range" in row.keys() else "",
            difficulty_level=row["difficulty_level"] if "difficulty_level" in row.keys() else "",
            recommended_for=_load_json_list(row["recommended_for_json"]) if "recommended_for_json" in row.keys() else [],
            not_recommended_for=_load_json_list(row["not_recommended_for_json"]) if "not_recommended_for_json" in row.keys() else [],
            failure_points=_load_json_list(row["failure_points_json"]) if "failure_points_json" in row.keys() else [],
            faq_items=_load_json_list(row["faq_items_json"]) if "faq_items_json" in row.keys() else [],
            cta_type=row["cta_type"] if "cta_type" in row.keys() else "",
            content_density_status=row["content_density_status"] if "content_density_status" in row.keys() else "",
            generated_image_status=row["generated_image_status"] if "generated_image_status" in row.keys() else "",
            image_error_message=row["image_error_message"] if "image_error_message" in row.keys() else "",
            final_image_url=row["final_image_url"] if "final_image_url" in row.keys() else "",
            final_title=row["final_title"],
            meta_description=row["meta_description"],
            labels=_load_json_list(row["labels_json"]),
            hashtags=_load_json_list(row["hashtags_json"]),
            image_prompt=row["image_prompt"],
            image_url=row["image_url"],
            article_html=row["article_html"],
            json_ld=_load_json_object(row["json_ld_json"]),
            qa_result=row["qa_result"],
            qa_issues=_load_json_list(row["qa_issues_json"]),
            publish_block_reason=row["publish_block_reason"] if "publish_block_reason" in row.keys() else "",
            approval_required=bool(row["approval_required"]) if "approval_required" in row.keys() else False,
            publish_status=row["publish_status"],
            blog_url=row["blog_url"],
            blog_post_id=row["blog_post_id"],
            notes=row["notes"],
            content_type=row["content_type"] if "content_type" in row.keys() else "",
        )


class BriefRecordRepository:
    def __init__(self, store: SQLiteBlogStore) -> None:
        self.store = store
        self.store.initialize()

    def upsert(self, brief: BriefRecord) -> BriefRecord:
        payload = brief.to_dict()
        payload["updated_at"] = now_iso()
        try:
            with self.store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO brief_records (
                        work_item_id, created_at, updated_at, brief_summary, final_angle,
                        target_reader, reader_problem, search_intent, one_line_hook, why_now,
                        outline_sections_json, key_takeaways_json, facts_from_sources_json,
                        hard_facts_from_sources_json, source_consensus_json, source_differences_json,
                        what_it_means_to_reader_json, cautions_json, practical_actions_json,
                        estimated_time_to_start, estimated_cost_to_start, potential_income_range,
                        difficulty_level, recommended_for_json, not_recommended_for_json,
                        failure_points_json, monetization_block_idea, faq_candidates_json,
                        faq_items_json, evidence_points_json, cta_direction, cta_type, content_density_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        brief_summary=excluded.brief_summary,
                        final_angle=excluded.final_angle,
                        target_reader=excluded.target_reader,
                        reader_problem=excluded.reader_problem,
                        search_intent=excluded.search_intent,
                        one_line_hook=excluded.one_line_hook,
                        why_now=excluded.why_now,
                        outline_sections_json=excluded.outline_sections_json,
                        key_takeaways_json=excluded.key_takeaways_json,
                        facts_from_sources_json=excluded.facts_from_sources_json,
                        hard_facts_from_sources_json=excluded.hard_facts_from_sources_json,
                        source_consensus_json=excluded.source_consensus_json,
                        source_differences_json=excluded.source_differences_json,
                        what_it_means_to_reader_json=excluded.what_it_means_to_reader_json,
                        cautions_json=excluded.cautions_json,
                        practical_actions_json=excluded.practical_actions_json,
                        estimated_time_to_start=excluded.estimated_time_to_start,
                        estimated_cost_to_start=excluded.estimated_cost_to_start,
                        potential_income_range=excluded.potential_income_range,
                        difficulty_level=excluded.difficulty_level,
                        recommended_for_json=excluded.recommended_for_json,
                        not_recommended_for_json=excluded.not_recommended_for_json,
                        failure_points_json=excluded.failure_points_json,
                        monetization_block_idea=excluded.monetization_block_idea,
                        faq_candidates_json=excluded.faq_candidates_json,
                        faq_items_json=excluded.faq_items_json,
                        evidence_points_json=excluded.evidence_points_json,
                        cta_direction=excluded.cta_direction,
                        cta_type=excluded.cta_type,
                        content_density_status=excluded.content_density_status
                    """,
                    (
                        payload["work_item_id"],
                        payload["created_at"],
                        payload["updated_at"],
                        payload["brief_summary"],
                        payload["final_angle"],
                        payload["target_reader"],
                        payload["reader_problem"],
                        payload["search_intent"],
                        payload["one_line_hook"],
                        payload["why_now"],
                        json.dumps(payload["outline_sections"], ensure_ascii=False),
                        json.dumps(payload["key_takeaways"], ensure_ascii=False),
                        json.dumps(payload["facts_from_sources"], ensure_ascii=False),
                        json.dumps(payload["hard_facts_from_sources"], ensure_ascii=False),
                        json.dumps(payload["source_consensus"], ensure_ascii=False),
                        json.dumps(payload["source_differences"], ensure_ascii=False),
                        json.dumps(payload["what_it_means_to_reader"], ensure_ascii=False),
                        json.dumps(payload["cautions"], ensure_ascii=False),
                        json.dumps(payload["practical_actions"], ensure_ascii=False),
                        payload["estimated_time_to_start"],
                        payload["estimated_cost_to_start"],
                        payload["potential_income_range"],
                        payload["difficulty_level"],
                        json.dumps(payload["recommended_for"], ensure_ascii=False),
                        json.dumps(payload["not_recommended_for"], ensure_ascii=False),
                        json.dumps(payload["failure_points"], ensure_ascii=False),
                        payload["monetization_block_idea"],
                        json.dumps(payload["faq_candidates"], ensure_ascii=False),
                        json.dumps(payload["faq_items"], ensure_ascii=False),
                        json.dumps(payload["evidence_points"], ensure_ascii=False),
                        payload["cta_direction"],
                        payload["cta_type"],
                        payload["content_density_status"],
                    ),
                )
        except sqlite3.Error as exc:
            self.store.write_fallback_record(table_name="brief_records", record_id=brief.work_item_id, payload=payload)
            raise StorageError(f"Failed to save brief for work_item_id={brief.work_item_id}: {exc}") from exc
        saved = self.get_by_work_item_id(brief.work_item_id)
        if saved is None:
            raise StorageError(f"Saved brief could not be reloaded: work_item_id={brief.work_item_id}")
        return saved

    def get_by_work_item_id(self, work_item_id: str) -> BriefRecord | None:
        try:
            with self.store.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM brief_records WHERE work_item_id = ? LIMIT 1",
                    (work_item_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to load brief for work_item_id={work_item_id}: {exc}") from exc
        if row is None:
            return None
        return BriefRecord(
            work_item_id=row["work_item_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            brief_summary=row["brief_summary"],
            final_angle=row["final_angle"],
            target_reader=row["target_reader"],
            reader_problem=row["reader_problem"] if "reader_problem" in row.keys() else "",
            search_intent=row["search_intent"],
            one_line_hook=row["one_line_hook"],
            why_now=row["why_now"] if "why_now" in row.keys() else "",
            outline_sections=_load_json_list(row["outline_sections_json"]),
            key_takeaways=_load_json_list(row["key_takeaways_json"]),
            facts_from_sources=_load_json_list(row["facts_from_sources_json"]),
            hard_facts_from_sources=_load_json_list(row["hard_facts_from_sources_json"]) if "hard_facts_from_sources_json" in row.keys() else [],
            source_consensus=_load_json_list(row["source_consensus_json"]) if "source_consensus_json" in row.keys() else [],
            source_differences=_load_json_list(row["source_differences_json"]) if "source_differences_json" in row.keys() else [],
            what_it_means_to_reader=_load_json_list(row["what_it_means_to_reader_json"]) if "what_it_means_to_reader_json" in row.keys() else [],
            cautions=_load_json_list(row["cautions_json"]),
            practical_actions=_load_json_list(row["practical_actions_json"]),
            estimated_time_to_start=row["estimated_time_to_start"] if "estimated_time_to_start" in row.keys() else "",
            estimated_cost_to_start=row["estimated_cost_to_start"] if "estimated_cost_to_start" in row.keys() else "",
            potential_income_range=row["potential_income_range"] if "potential_income_range" in row.keys() else "",
            difficulty_level=row["difficulty_level"] if "difficulty_level" in row.keys() else "",
            recommended_for=_load_json_list(row["recommended_for_json"]) if "recommended_for_json" in row.keys() else [],
            not_recommended_for=_load_json_list(row["not_recommended_for_json"]) if "not_recommended_for_json" in row.keys() else [],
            failure_points=_load_json_list(row["failure_points_json"]) if "failure_points_json" in row.keys() else [],
            monetization_block_idea=row["monetization_block_idea"],
            faq_candidates=_load_json_list(row["faq_candidates_json"]),
            faq_items=_load_json_list(row["faq_items_json"]),
            evidence_points=_load_json_list(row["evidence_points_json"]),
            cta_direction=row["cta_direction"],
            cta_type=row["cta_type"],
            content_density_status=row["content_density_status"] if "content_density_status" in row.keys() else "",
        )


class ContentPackageRepository:
    def __init__(self, store: SQLiteBlogStore) -> None:
        self.store = store
        self.store.initialize()

    def upsert(self, package: ContentPackageRecord) -> ContentPackageRecord:
        payload = package.to_dict()
        payload["updated_at"] = now_iso()
        try:
            with self.store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO content_package_records (
                        work_item_id, created_at, updated_at, title_candidates_json,
                        final_title, meta_description, labels_json, hashtags_json,
                        image_prompt, article_html, article_preview_html, json_ld_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        title_candidates_json=excluded.title_candidates_json,
                        final_title=excluded.final_title,
                        meta_description=excluded.meta_description,
                        labels_json=excluded.labels_json,
                        hashtags_json=excluded.hashtags_json,
                        image_prompt=excluded.image_prompt,
                        article_html=excluded.article_html,
                        article_preview_html=excluded.article_preview_html,
                        json_ld_json=excluded.json_ld_json
                    """,
                    (
                        payload["work_item_id"],
                        payload["created_at"],
                        payload["updated_at"],
                        json.dumps(payload["title_candidates"], ensure_ascii=False),
                        payload["final_title"],
                        payload["meta_description"],
                        json.dumps(payload["labels"], ensure_ascii=False),
                        json.dumps(payload["hashtags"], ensure_ascii=False),
                        payload["image_prompt"],
                        payload["article_html"],
                        payload["article_preview_html"],
                        json.dumps(payload["json_ld"], ensure_ascii=False),
                    ),
                )
        except sqlite3.Error as exc:
            self.store.write_fallback_record(
                table_name="content_package_records",
                record_id=package.work_item_id,
                payload=payload,
            )
            raise StorageError(f"Failed to save content package for work_item_id={package.work_item_id}: {exc}") from exc
        saved = self.get_by_work_item_id(package.work_item_id)
        if saved is None:
            raise StorageError(f"Saved content package could not be reloaded: work_item_id={package.work_item_id}")
        return saved

    def get_by_work_item_id(self, work_item_id: str) -> ContentPackageRecord | None:
        try:
            with self.store.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM content_package_records WHERE work_item_id = ? LIMIT 1",
                    (work_item_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to load content package for work_item_id={work_item_id}: {exc}") from exc
        if row is None:
            return None
        return ContentPackageRecord(
            work_item_id=row["work_item_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            title_candidates=_load_json_list(row["title_candidates_json"]),
            final_title=row["final_title"],
            meta_description=row["meta_description"],
            labels=_load_json_list(row["labels_json"]),
            hashtags=_load_json_list(row["hashtags_json"]),
            image_prompt=row["image_prompt"],
            article_html=row["article_html"],
            article_preview_html=row["article_preview_html"],
            json_ld=_load_json_object(row["json_ld_json"]),
        )


class QAReviewRepository:
    def __init__(self, store: SQLiteBlogStore) -> None:
        self.store = store
        self.store.initialize()

    def upsert(self, review: QAReviewRecord) -> QAReviewRecord:
        payload = review.to_dict()
        payload["updated_at"] = now_iso()
        try:
            with self.store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO qa_review_records (
                        work_item_id, created_at, updated_at, qa_result, qa_score,
                        issues_json, fixes_json, review_summary, requires_manual_approval
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        qa_result=excluded.qa_result,
                        qa_score=excluded.qa_score,
                        issues_json=excluded.issues_json,
                        fixes_json=excluded.fixes_json,
                        review_summary=excluded.review_summary,
                        requires_manual_approval=excluded.requires_manual_approval
                    """,
                    (
                        payload["work_item_id"],
                        payload["created_at"],
                        payload["updated_at"],
                        payload["qa_result"],
                        payload["qa_score"],
                        json.dumps(payload["issues"], ensure_ascii=False),
                        json.dumps(payload["fixes"], ensure_ascii=False),
                        payload["review_summary"],
                        1 if payload["requires_manual_approval"] else 0,
                    ),
                )
        except sqlite3.Error as exc:
            self.store.write_fallback_record(
                table_name="qa_review_records",
                record_id=review.work_item_id,
                payload=payload,
            )
            raise StorageError(f"Failed to save QA review for work_item_id={review.work_item_id}: {exc}") from exc
        saved = self.get_by_work_item_id(review.work_item_id)
        if saved is None:
            raise StorageError(f"Saved QA review could not be reloaded: work_item_id={review.work_item_id}")
        return saved

    def get_by_work_item_id(self, work_item_id: str) -> QAReviewRecord | None:
        try:
            with self.store.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM qa_review_records WHERE work_item_id = ? LIMIT 1",
                    (work_item_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to load QA review for work_item_id={work_item_id}: {exc}") from exc
        if row is None:
            return None
        return QAReviewRecord(
            work_item_id=row["work_item_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            qa_result=row["qa_result"],
            qa_score=int(row["qa_score"]),
            issues=_load_json_list(row["issues_json"]),
            fixes=_load_json_list(row["fixes_json"]),
            review_summary=row["review_summary"],
            requires_manual_approval=bool(row["requires_manual_approval"]),
        )


class PublishRecordRepository:
    def __init__(self, store: SQLiteBlogStore) -> None:
        self.store = store
        self.store.initialize()

    def insert(self, record: PublishRecord) -> PublishRecord:
        payload = record.to_dict()
        payload["updated_at"] = now_iso()
        try:
            with self.store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO publish_records (
                        publish_id, work_item_id, created_at, updated_at, publish_mode,
                        target_status, publish_result, blog_url, blog_post_id,
                        response_json, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["publish_id"],
                        payload["work_item_id"],
                        payload["created_at"],
                        payload["updated_at"],
                        payload["publish_mode"],
                        payload["target_status"],
                        payload["publish_result"],
                        payload["blog_url"],
                        payload["blog_post_id"],
                        json.dumps(payload["response_json"], ensure_ascii=False),
                        payload["error_message"],
                    ),
                )
        except sqlite3.Error as exc:
            self.store.write_fallback_record(
                table_name="publish_records",
                record_id=record.publish_id,
                payload=payload,
            )
            raise StorageError(f"Failed to save publish record id={record.publish_id}: {exc}") from exc
        saved = self.get_by_id(record.publish_id)
        if saved is None:
            raise StorageError(f"Saved publish record could not be reloaded: publish_id={record.publish_id}")
        return saved

    def get_by_id(self, publish_id: str) -> PublishRecord | None:
        try:
            with self.store.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM publish_records WHERE publish_id = ? LIMIT 1",
                    (publish_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to load publish record id={publish_id}: {exc}") from exc
        if row is None:
            return None
        return PublishRecord(
            publish_id=row["publish_id"],
            work_item_id=row["work_item_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            publish_mode=row["publish_mode"],
            target_status=row["target_status"],
            publish_result=row["publish_result"],
            blog_url=row["blog_url"],
            blog_post_id=row["blog_post_id"],
            response_json=_load_json_object(row["response_json"]),
            error_message=row["error_message"],
        )

    def list_for_work_item(self, work_item_id: str, limit: int = 20) -> list[PublishRecord]:
        try:
            with self.store.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM publish_records
                    WHERE work_item_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (work_item_id, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to list publish records for work_item_id={work_item_id}: {exc}") from exc
        return [
            PublishRecord(
                publish_id=row["publish_id"],
                work_item_id=row["work_item_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                publish_mode=row["publish_mode"],
                target_status=row["target_status"],
                publish_result=row["publish_result"],
                blog_url=row["blog_url"],
                blog_post_id=row["blog_post_id"],
                response_json=_load_json_object(row["response_json"]),
                error_message=row["error_message"],
            )
            for row in rows
        ]
