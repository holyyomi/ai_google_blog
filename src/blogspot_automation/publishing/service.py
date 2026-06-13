from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from blogspot_automation.config.settings import Settings
from blogspot_automation.publishing.client import BloggerClient
from blogspot_automation.storage import StateStore


@dataclass(slots=True)
class PublishResult:
    topic_id: str
    status: str
    request_path: str
    response_path: str
    publish_ready_html_path: str
    publish_ready_meta_path: str
    blogger_post_id: str | None = None
    blogger_post_url: str | None = None
    published_post_path: str | None = None


def publish_topic(
    *,
    topic_id: str,
    store: StateStore,
    settings: Settings,
    client: Any | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> PublishResult:
    final_payload = store.load_final_ready_package(topic_id)
    qa_payload = dict(final_payload.get("qa") or {})
    if not force and qa_payload.get("qa_result") != "PASS":
        raise RuntimeError("QA must pass before publishing.")

    existing_status = store.get_publish_status(topic_id)
    if (
        not force
        and existing_status
        and existing_status.get("status") == "published"
        and not bool(existing_status.get("dry_run"))
    ):
        raise RuntimeError(f"Topic already published: {topic_id}")

    package = dict(final_payload.get("final_ready_package") or {})
    title = str(package.get("title") or "")
    article_html = str(package.get("article_html") or "")
    labels = [str(item) for item in package.get("labels") or []]
    blog_package = dict(final_payload.get("blog_package") or {})
    meta_description = str(package.get("meta_description") or blog_package.get("meta_description") or "")
    permalink_slug = str(package.get("slug") or blog_package.get("slug") or "")

    publish_dir = store.topic_publish_dir(topic_id)
    html_path = publish_dir / "publish_ready.html"
    metadata_path = publish_dir / "publish_ready_metadata.json"
    request_path = publish_dir / "publish_request.json"
    response_path = publish_dir / "publish_response.json"
    log_path = publish_dir / "publish_log.jsonl"

    html_path.write_text(article_html, encoding="utf-8")
    metadata = {
        "topic_id": topic_id,
        "title": title,
        "labels": labels,
        "meta_description": meta_description,
        "permalink_slug": permalink_slug,
        "prepared_at": _utc_now(),
    }
    _write_json(metadata_path, metadata)

    request_payload = {
        "topic_id": topic_id,
        "blog_id": settings.blogger_blog_id,
        "title": title,
        "article_html": article_html,
        "labels": labels,
        "meta_description": meta_description,
        "permalink_slug": permalink_slug,
        "is_draft": False,
        "dry_run": dry_run,
    }
    _write_json(request_path, request_payload)

    if dry_run:
        response_payload: dict[str, Any] = {
            "status": "dry_run",
            "blogger_post_id": None,
            "blogger_post_url": None,
            "message": "Publish request prepared but not sent.",
        }
        _write_json(response_path, response_payload)
        _append_jsonl(log_path, {"event": "dry_run", "topic_id": topic_id, "created_at": _utc_now()})
        store.save_publish_status(
            topic_id=topic_id,
            status="dry_run",
            blogger_post_id=None,
            blogger_post_url=None,
            published_at=_utc_now(),
            dry_run=True,
            response_path=str(response_path),
            request_path=str(request_path),
            published_post_path=None,
        )
        store.save_publish_history(
            history_id=f"publish-{uuid4().hex}",
            topic_id=topic_id,
            status="dry_run",
            dry_run=True,
            blogger_post_id=None,
            blogger_post_url=None,
            created_at=_utc_now(),
            request_path=str(request_path),
            response_path=str(response_path),
            published_post_path=None,
        )
        return PublishResult(
            topic_id=topic_id,
            status="dry_run",
            request_path=str(request_path),
            response_path=str(response_path),
            publish_ready_html_path=str(html_path),
            publish_ready_meta_path=str(metadata_path),
        )

    publisher = client or BloggerClient(settings)
    response_payload = dict(
        publisher.publish_post(
            title=title,
            article_html=article_html,
            labels=labels,
            meta_description=meta_description,
            permalink_slug=permalink_slug,
            is_draft=False,
        )
    )
    _write_json(response_path, response_payload)

    post_url = str(response_payload.get("url") or "")
    verified_status_code = None
    if post_url and hasattr(publisher, "verify_public_url"):
        verified_status_code = publisher.verify_public_url(post_url)

    published_post_path = publish_dir / "published_post.json"
    published_payload = {
        "topic_id": topic_id,
        "blogger_post_id": response_payload.get("id"),
        "blogger_post_url": response_payload.get("url"),
        "response_status": response_payload.get("status"),
        "verified_status_code": verified_status_code,
        "published_at": response_payload.get("published") or _utc_now(),
        "response": response_payload,
    }
    _write_json(published_post_path, published_payload)
    _append_jsonl(
        log_path,
        {
            "event": "published",
            "topic_id": topic_id,
            "blogger_post_id": response_payload.get("id"),
            "blogger_post_url": response_payload.get("url"),
            "created_at": _utc_now(),
        },
    )

    history_dir = publish_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}.json"
    _write_json(history_path, published_payload)

    final_payload["final_ready_package"] = {
        **package,
        "status": "published",
        "published_at": published_payload["published_at"],
        "blogger_post_id": response_payload.get("id"),
        "blogger_post_url": response_payload.get("url"),
    }
    store.save_final_ready_package(topic_id, final_payload)
    store.save_publish_status(
        topic_id=topic_id,
        status="published",
        blogger_post_id=str(response_payload.get("id") or ""),
        blogger_post_url=str(response_payload.get("url") or ""),
        published_at=str(published_payload["published_at"]),
        dry_run=False,
        response_path=str(response_path),
        request_path=str(request_path),
        published_post_path=str(published_post_path),
    )
    store.save_publish_history(
        history_id=f"publish-{uuid4().hex}",
        topic_id=topic_id,
        status="published",
        dry_run=False,
        blogger_post_id=str(response_payload.get("id") or ""),
        blogger_post_url=str(response_payload.get("url") or ""),
        created_at=_utc_now(),
        request_path=str(request_path),
        response_path=str(response_path),
        published_post_path=str(published_post_path),
    )
    return PublishResult(
        topic_id=topic_id,
        status="published",
        request_path=str(request_path),
        response_path=str(response_path),
        publish_ready_html_path=str(html_path),
        publish_ready_meta_path=str(metadata_path),
        blogger_post_id=str(response_payload.get("id") or ""),
        blogger_post_url=str(response_payload.get("url") or ""),
        published_post_path=str(published_post_path),
    )


def publish_status(*, topic_id: str, store: StateStore) -> dict[str, Any]:
    status = store.get_publish_status(topic_id)
    if status:
        return status
    return {"topic_id": topic_id, "status": "not_published"}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
