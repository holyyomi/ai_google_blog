from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from blogspot_automation.app import ServiceRuntime, build_service_runtime
from blogspot_automation.pipelines import run_topic_selection_pipeline
from blogspot_automation.services import SelectedTopicResult
from blogspot_automation.services.blog_package_service import (
    build_preview_html,
    cleanup_blogger_placeholders,
)


@dataclass(slots=True)
class UIServiceBundle:
    runtime: ServiceRuntime


def build_ui_services(root_dir: Path) -> UIServiceBundle:
    return UIServiceBundle(runtime=build_service_runtime(root_dir=root_dir))


def find_today_topic(*, root_dir: Path) -> dict[str, Any]:
    result = run_topic_selection_pipeline(root_dir=root_dir)
    return asdict(result)


def generate_content(
    *,
    root_dir: Path,
    selected_payload: dict[str, Any] | None,
    work_item_id: str | None,
) -> dict[str, Any]:
    services = build_ui_services(root_dir).runtime

    # If a specific work_item_id is provided that already has generated content,
    # allow re-generation skipping the status guard (useful for re-running after errors).
    if work_item_id:
        existing = services.work_repo.get_by_id(work_item_id)
        if existing and existing.article_html:
            # Already generated — just rebuild from existing state
            payload = selected_payload or _load_selection_payload(services=services, work_item_id=work_item_id)
            if payload is None:
                raise ValueError("먼저 오늘 주제를 선택해야 합니다.")
            selection = SelectedTopicResult(**payload)
            package = services.package_repo.get_by_work_item_id(work_item_id)
            image_result = services.image_service.process_cover_image(
                work_item_id=work_item_id,
                allow_publish_without_image=True,
            )
            work_item = services.work_repo.get_by_id(work_item_id)
            return {
                "work_item_id": work_item_id,
                "brief": {},
                "package": package.to_dict() if package else {},
                "image": {"status": image_result.status if image_result else ""},
                "work_item": work_item.to_dict() if work_item else {},
            }

    payload = selected_payload or _load_selection_payload(services=services, work_item_id=work_item_id)
    if payload is None:
        raise ValueError("먼저 오늘 주제를 선택해야 합니다.")
    if payload.get("publish_status") != "planned":
        raise ValueError(
            f"실제 기사 부족 또는 중복으로 생성이 중단된 주제입니다: {payload.get('stop_reason') or payload.get('why_selected')}"
        )
    if payload.get("source_quality_status") != "sufficient" or int(payload.get("source_count") or 0) < 3:
        raise ValueError("실제 기사 3개 이상이 검증되지 않아 콘텐츠 생성을 진행할 수 없습니다.")

    selection = SelectedTopicResult(**payload)

    # 🧠 우선순위 1: 진짜 AI (AiContentService - Yomi 페르소나)
    # Fallback: 기존 brief_service
    if services.ai_content_service is not None:
        brief = services.ai_content_service.generate_from_selected_topic(selection)
    else:
        brief = services.brief_service.generate_from_selected_topic(selection)

    package = services.package_service.build_package(work_item_id=selection.saved_work_item_id)

    # 🖼️ 커버 이미지: OpenAI DALL-E -> Imgbb 업로드 -> 엑박 없는 영구 URL 확보
    image_result = services.image_service.process_cover_image(
        work_item_id=selection.saved_work_item_id,
        allow_publish_without_image=True,
    )

    # 이미지 URL이 생성됐으면 article_html 상단에 삽입
    work_item = services.work_repo.get_by_id(selection.saved_work_item_id)
    if work_item is None:
        raise ValueError(f"작업 항목을 다시 불러오지 못했습니다: {selection.saved_work_item_id}")

    if work_item.article_html:
        html_content = cleanup_blogger_placeholders(work_item.article_html)

        work_item.article_html = html_content
        services.work_repo.upsert(work_item)

        # 패키지 업데이트: UI 프리뷰에 실시간 반영되도록 동기화
        pkg_record = services.package_repo.get_by_work_item_id(selection.saved_work_item_id)
        if pkg_record:
            pkg_record.article_html = html_content
            pkg_record.article_preview_html = build_preview_html(html_content, pkg_record.final_title)
            services.package_repo.upsert(pkg_record)
            package = package.__class__(**pkg_record.to_dict()) if hasattr(package, "to_dict") else pkg_record

    return {
        "work_item_id": selection.saved_work_item_id,
        "brief": brief.to_dict(),
        "package": asdict(package) if hasattr(package, "__dataclass_fields__") else package.to_dict(),
        "image": asdict(image_result),
        "work_item": work_item.to_dict(),
    }



def run_qa(*, root_dir: Path, work_item_id: str) -> dict[str, Any]:
    services = build_ui_services(root_dir).runtime
    review = services.qa_service.qa_review(work_item_id=work_item_id)
    work_item = services.work_repo.get_by_id(work_item_id)
    return {
        "review": asdict(review),
        "work_item": work_item.to_dict() if work_item else {},
    }


def publish_content(
    *,
    root_dir: Path,
    work_item_id: str,
    publish_mode: str = "public",
    manual_soft_fail_approval: bool = False,
) -> dict[str, Any]:
    services = build_ui_services(root_dir).runtime
    outcome = services.publish_service.publish(
        work_item_id=work_item_id,
        publish_mode=publish_mode,
        manual_soft_fail_approval=manual_soft_fail_approval,
    )
    status = services.publish_service.get_publish_status(work_item_id=work_item_id)
    return {
        "outcome": asdict(outcome),
        "status": status,
    }


def get_recent_work_items(*, root_dir: Path, limit: int = 10) -> list[dict[str, Any]]:
    services = build_ui_services(root_dir).runtime
    return services.work_repo.list_recent_for_streamlit(limit=limit)


def get_work_item_snapshot(*, root_dir: Path, work_item_id: str | None) -> dict[str, Any] | None:
    if not work_item_id:
        return None
    services = build_ui_services(root_dir).runtime
    work_item = services.work_repo.get_by_id(work_item_id)
    if work_item is None:
        return None
    package = services.package_repo.get_by_work_item_id(work_item_id)
    review = services.qa_repo.get_by_work_item_id(work_item_id)
    publish_records = services.publish_repo.list_for_work_item(work_item_id, limit=3)
    return {
        "work_item": work_item.to_dict(),
        "package": package.to_dict() if package else None,
        "qa": review.to_dict() if review else None,
        "publish_records": [record.to_dict() for record in publish_records],
    }


def _load_selection_payload(*, services: ServiceRuntime, work_item_id: str | None) -> dict[str, Any] | None:
    candidate_id = work_item_id
    if not candidate_id:
        recent = services.work_repo.list_recent(limit=1)
        candidate_id = recent[0].id if recent else None
    if not candidate_id:
        return None
    work_item = services.work_repo.get_by_id(candidate_id)
    if work_item is None:
        return None

    notes_payload: dict[str, Any] = {}
    if work_item.notes.strip():
        try:
            loaded = json.loads(work_item.notes)
            if isinstance(loaded, dict):
                notes_payload = loaded
        except json.JSONDecodeError:
            notes_payload = {}

    return {
        "selected_pillar": work_item.selected_pillar or notes_payload.get("selected_pillar") or work_item.content_pillar,
        "selected_topic": work_item.selected_topic or notes_payload.get("selected_topic") or work_item.topic_title,
        "why_selected": work_item.why_selected or notes_payload.get("why_selected") or work_item.source_summary,
        "source_articles": work_item.source_articles or notes_payload.get("source_articles") or [],
        "source_count": work_item.source_count,
        "source_domains": work_item.source_domains or notes_payload.get("source_domains") or [],
        "keyword_set": work_item.keyword_set or notes_payload.get("keyword_set") or {},
        "title_candidates": work_item.title_candidates or notes_payload.get("title_candidates") or [],
        "title_candidate_types": work_item.title_candidate_types or notes_payload.get("title_candidate_types") or [],
        "article_pack": notes_payload.get("article_pack")
        or {
            "selected_pillar": work_item.selected_pillar or notes_payload.get("selected_pillar") or work_item.content_pillar,
            "selected_topic": work_item.selected_topic or notes_payload.get("selected_topic") or work_item.topic_title,
            "why_selected": work_item.why_selected or notes_payload.get("why_selected") or work_item.source_summary,
            "source_articles": work_item.source_articles or notes_payload.get("source_articles") or [],
            "source_domains": work_item.source_domains or notes_payload.get("source_domains") or [],
            "source_count": work_item.source_count,
            "keyword_set": work_item.keyword_set or notes_payload.get("keyword_set") or {},
            "search_intent_guess": "",
            "source_consensus": [],
            "source_differences": [],
            "hard_facts": [],
            "reader_relevance": [],
            "title_candidates": work_item.title_candidates or notes_payload.get("title_candidates") or [],
            "title_candidate_types": work_item.title_candidate_types or notes_payload.get("title_candidate_types") or [],
        },
        "topic_score": float(work_item.topic_score or notes_payload.get("topic_score") or 0.0),
        "source_quality_status": work_item.source_quality_status or notes_payload.get("source_quality_status") or "",
        "discovery_debug": work_item.discovery_debug or notes_payload.get("discovery_debug") or {},
        "raw_candidate_count": int(work_item.raw_candidate_count or notes_payload.get("raw_candidate_count") or 0),
        "parsed_candidate_count": int(work_item.parsed_candidate_count or notes_payload.get("parsed_candidate_count") or 0),
        "filtered_candidate_count": int(work_item.filtered_candidate_count or notes_payload.get("filtered_candidate_count") or 0),
        "reject_reason_summary": work_item.reject_reason_summary or notes_payload.get("reject_reason_summary") or {},
        "final_discovery_status": work_item.final_discovery_status or notes_payload.get("final_discovery_status") or "",
        "retry_count": int(work_item.retry_count or notes_payload.get("retry_count") or 0),
        "retry_path": work_item.retry_path or notes_payload.get("retry_path") or [],
        "fallback_strategy_used": work_item.fallback_strategy_used or notes_payload.get("fallback_strategy_used") or "",
        "fallback_pillar_used": work_item.fallback_pillar_used or notes_payload.get("fallback_pillar_used") or "",
        "discovery_attempts": work_item.discovery_attempts or notes_payload.get("discovery_attempts") or [],
        "publish_status": work_item.publish_status,
        "stop_reason": notes_payload.get("stop_reason") or "",
        "saved_work_item_id": work_item.id,
    }
