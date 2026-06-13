from __future__ import annotations

from typing import Any

from blogspot_automation.models.schemas import REQUIRED_BRIEF_KEYS


def normalize_brief_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    for key in ("key_points", "recommended_readers"):
        normalized[key] = _normalize_string_list(normalized.get(key))
    normalized["automation_opportunities"] = _normalize_string_list(
        normalized.get("automation_opportunities")
    )
    normalized["monetization_opportunities"] = _normalize_string_list(
        normalized.get("monetization_opportunities")
    )
    return normalized


def build_brief_model(
    *,
    run_id: str,
    topic_data: dict[str, Any],
    fact_pack: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    missing = [key for key in REQUIRED_BRIEF_KEYS if key not in payload]
    if missing:
        raise KeyError(f"brief payload missing required keys: {', '.join(sorted(missing))}")
    normalized = normalize_brief_payload(payload)
    return {
        "run_id": run_id,
        "brief_id": f"{run_id}-{topic_data.get('topic_id', 'topic')}",
        "topic_id": topic_data.get("topic_id", ""),
        "topic_data": topic_data,
        "fact_pack": fact_pack,
        **normalized,
    }


def normalize_article_sections(sections: Any) -> list[dict[str, Any]]:
    if not sections:
        return []
    normalized: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        item = dict(section)
        item["level"] = _normalize_level(item.get("level"))
        item.setdefault("paragraphs", [])
        item.setdefault("bullets", [])
        normalized.append(item)
    return normalized


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(
                    item.get("title")
                    or item.get("description")
                    or item.get("label")
                    or item.get("name")
                    or ""
                ).strip()
            else:
                text = str(item or "").strip()
            if text:
                items.append(text)
        return items
    return [str(value).strip()] if str(value).strip() else []


def _normalize_level(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"h3", "3", "subsection"}:
        return "h3"
    return "h2"
