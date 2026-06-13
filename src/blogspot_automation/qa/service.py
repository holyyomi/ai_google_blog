from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from blogspot_automation.storage import StateStore


@dataclass(slots=True)
class QAReviewResult:
    topic_id: str
    qa_result: str
    issues: list[str]
    revision_payload_path: str | None = None


@dataclass(slots=True)
class FinalReadyResult:
    topic_id: str
    status: str
    final_ready_path: str


def review_article_package(*, topic_id: str, store: StateStore) -> QAReviewResult:
    payload = store.load_blog_package(topic_id)
    package = dict(payload.get("blog_package") or {})
    html = str(package.get("article_html") or "")
    plain = _strip_html(html)
    issues: list[str] = []
    if len(plain) < 120:
        issues.append("article_body_too_short")
    if plain.count("혁신적인") >= 3:
        issues.append("repeated_hype_phrase")
    if len(package.get("faq_items") or []) < 2:
        issues.append("faq_items_below_2")
    qa_result = "FIX_REQUIRED" if issues else "PASS"
    report = {
        "topic_id": topic_id,
        "status": "reviewed",
        "qa_result": qa_result,
        "approved": qa_result == "PASS",
        "issues": issues,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    store.save_qa_report(topic_id, report)
    revision_payload_path = None
    if issues:
        revision_payload = {
            "topic_id": topic_id,
            "issues": issues,
            "instruction": "Revise article package to address QA issues.",
        }
        store.save_qa_revision_payload(topic_id, revision_payload)
        revision_payload_path = str(store.topic_qa_dir(topic_id) / "revision_payload.json")
    return QAReviewResult(
        topic_id=topic_id,
        qa_result=qa_result,
        issues=issues,
        revision_payload_path=revision_payload_path,
    )


def prepare_final_ready_package(
    *,
    topic_id: str,
    store: StateStore,
    reviewer_notes: str = "",
) -> FinalReadyResult:
    payload = store.load_blog_package(topic_id)
    qa_report = store.load_qa_report(topic_id)
    if qa_report.get("qa_result") != "PASS":
        raise RuntimeError("QA must pass before preparing final ready package.")
    package = dict(payload.get("blog_package") or {})
    final_ready = {
        "title": package.get("final_title", ""),
        "article_html": package.get("article_html", ""),
        "labels": package.get("labels", []),
        "meta_description": package.get("meta_description", ""),
        "status": "final_ready",
    }
    final_payload = {
        "topic_data": payload.get("topic_data") or package.get("topic_data") or {},
        "brief": payload.get("brief") or package.get("brief") or {},
        "blog_package": package,
        "qa": {
            **qa_report,
            "reviewer_notes": reviewer_notes,
        },
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "publish_target": "blogger",
        "final_ready_package": final_ready,
    }
    store.save_final_ready_package(topic_id, final_payload)
    return FinalReadyResult(
        topic_id=topic_id,
        status="final_ready",
        final_ready_path=str(store.topic_output_dir(topic_id) / "final_ready_package.json"),
    )


def qa_status(*, topic_id: str, store: StateStore) -> dict[str, Any]:
    publish_status = store.get_publish_status(topic_id)
    if publish_status:
        return publish_status
    qa_report = store.try_load_qa_report(topic_id)
    if qa_report:
        return qa_report
    final_ready = store.try_load_final_ready_package(topic_id)
    if final_ready:
        return {"topic_id": topic_id, "status": "final_ready"}
    return {"topic_id": topic_id, "status": "not_started"}


def _strip_html(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())
