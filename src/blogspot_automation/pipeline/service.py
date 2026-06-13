from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from blogspot_automation.config.settings import Settings
from blogspot_automation.content_generation.service import build_blog_package, refine_content
from blogspot_automation.image_generation.service import generate_cover_image
from blogspot_automation.publishing.service import publish_topic
from blogspot_automation.qa.service import prepare_final_ready_package, review_article_package
from blogspot_automation.storage import StateStore


@dataclass(slots=True)
class FullPipelineResult:
    topic_id: str
    status: str
    final_title: str | None
    meta_description: str | None
    publish_ready_html_path: str
    publish_ready_meta_path: str
    run_log_path: str
    step_logs: list[dict[str, Any]]
    blogger_post_url: str | None = None


def run_full_pipeline(
    *,
    topic_id: str,
    store: StateStore,
    settings: Settings,
    dry_run_only: bool,
    auto_approve: bool,
    content_client: Any,
    image_client: Any,
    publish_client: Any | None = None,
    skip_refine_on_timeout: bool = False,
    qa_soft_fail: bool = False,
) -> FullPipelineResult:
    del auto_approve
    step_logs: list[dict[str, Any]] = []
    timed_out_refine = False

    _run_step(
        step_logs,
        "build_blog_package",
        lambda: build_blog_package(
            topic_id=topic_id,
            store=store,
            settings=settings,
            client=content_client,
        ),
    )
    _run_step(
        step_logs,
        "generate_cover_image",
        lambda: generate_cover_image(
            topic_id=topic_id,
            store=store,
            settings=settings,
            client=image_client,
        ),
    )
    qa_result = _run_step(
        step_logs,
        "review_article_package",
        lambda: review_article_package(topic_id=topic_id, store=store),
    )

    if getattr(qa_result, "qa_result", "") != "PASS":
        try:
            started_at = _utc_now()
            refine_result = refine_content(
                    topic_id=topic_id,
                    store=store,
                    settings=settings,
                    client=content_client,
            )
            step_logs.append(
                {
                    "step": "refine_content",
                    "status": "completed",
                    "details": _result_details(refine_result),
                    "created_at": started_at,
                }
            )
            qa_result = _run_step(
                step_logs,
                "review_article_package_after_refine",
                lambda: review_article_package(topic_id=topic_id, store=store),
            )
        except TimeoutError as exc:
            timed_out_refine = True
            if not skip_refine_on_timeout:
                raise
            step_logs.append(
                {
                    "step": "refine_content",
                    "status": "warning",
                    "details": {
                        "error_class": exc.__class__.__name__,
                        "message": str(exc),
                        "timeout_seconds": 180,
                    },
                    "created_at": _utc_now(),
                }
            )

    if getattr(qa_result, "qa_result", "") != "PASS" and not qa_soft_fail:
        raise RuntimeError("QA failed and qa_soft_fail is disabled.")

    if getattr(qa_result, "qa_result", "") != "PASS" and qa_soft_fail:
        _mark_qa_pass_for_soft_fail(topic_id=topic_id, store=store)

    _run_step(
        step_logs,
        "prepare_final_ready_package",
        lambda: prepare_final_ready_package(
            topic_id=topic_id,
            store=store,
            reviewer_notes="Auto-approved local pipeline run.",
        ),
    )
    publish_result = _run_step(
        step_logs,
        "publish_topic",
        lambda: publish_topic(
            topic_id=topic_id,
            store=store,
            settings=settings,
            client=publish_client,
            dry_run=dry_run_only,
        ),
    )

    package_payload = store.load_blog_package(topic_id)
    package = dict(package_payload.get("blog_package") or {})
    status = "dry_run_completed" if dry_run_only else "published"
    if timed_out_refine and not dry_run_only:
        status = "published_with_timeout_fallback"

    run_log_path = _write_run_log(store=store, topic_id=topic_id, status=status, step_logs=step_logs)
    return FullPipelineResult(
        topic_id=topic_id,
        status=status,
        final_title=str(package.get("final_title") or "") or None,
        meta_description=str(package.get("meta_description") or "") or None,
        publish_ready_html_path=publish_result.publish_ready_html_path,
        publish_ready_meta_path=publish_result.publish_ready_meta_path,
        run_log_path=str(run_log_path),
        step_logs=step_logs,
        blogger_post_url=publish_result.blogger_post_url,
    )


def _run_step(
    step_logs: list[dict[str, Any]],
    step: str,
    callback: Callable[[], Any],
) -> Any:
    started_at = _utc_now()
    try:
        result = callback()
    except Exception as exc:
        step_logs.append(
            {
                "step": step,
                "status": "failed",
                "details": {
                    "error_class": exc.__class__.__name__,
                    "message": str(exc),
                },
                "created_at": started_at,
            }
        )
        raise
    step_logs.append(
        {
            "step": step,
            "status": "completed",
            "details": _result_details(result),
            "created_at": started_at,
        }
    )
    return result


def _mark_qa_pass_for_soft_fail(*, topic_id: str, store: StateStore) -> None:
    report = store.try_load_qa_report(topic_id) or {"topic_id": topic_id}
    report = {
        **report,
        "qa_result": "PASS",
        "approved": True,
        "soft_fail_override": True,
        "overridden_at": _utc_now(),
    }
    store.save_qa_report(topic_id, report)


def _write_run_log(
    *,
    store: StateStore,
    topic_id: str,
    status: str,
    step_logs: list[dict[str, Any]],
) -> Path:
    run_dir = store.paths.runs_dir / f"legacy_pipeline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{topic_id}.json"
    path.write_text(
        json.dumps(
            {
                "topic_id": topic_id,
                "status": status,
                "step_logs": step_logs,
                "created_at": _utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _result_details(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if hasattr(result, "__dataclass_fields__"):
        return {
            key: str(value) if isinstance(value, Path) else value
            for key, value in ((field.name, getattr(result, field.name)) for field in fields(result))
            if isinstance(value, (str, int, float, bool, type(None), list, dict))
        }
    return {"result": str(result)}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
