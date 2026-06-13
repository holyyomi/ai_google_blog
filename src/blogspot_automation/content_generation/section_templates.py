from __future__ import annotations

from typing import Any

from blogspot_automation.content_generation.validators import normalize_article_sections


def build_article_section_template(
    *,
    topic_data: dict[str, Any],
    fact_pack: dict[str, Any],
) -> list[dict[str, Any]]:
    topic = str(topic_data.get("topic_name") or topic_data.get("candidate_title") or "주제")
    examples = fact_pack.get("examples") if isinstance(fact_pack, dict) else []
    constraints = fact_pack.get("constraints") if isinstance(fact_pack, dict) else []
    return [
        {
            "heading": f"{topic}에서 먼저 확인할 변화",
            "level": "h2",
            "purpose": "핵심 변화 설명",
            "paragraphs": [],
            "bullets": list(examples or [])[:3],
        },
        {
            "heading": "실무 적용 전에 볼 체크포인트",
            "level": "h2",
            "purpose": "적용 기준 설명",
            "paragraphs": [],
            "bullets": list(constraints or [])[:3],
        },
        {
            "heading": "자주 놓치는 리스크",
            "level": "h3",
            "purpose": "주의점 정리",
            "paragraphs": [],
            "bullets": [],
        },
    ]


def apply_article_section_template(
    *,
    template: list[dict[str, Any]],
    generated_sections: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    generated = normalize_article_sections(generated_sections)
    merged: list[dict[str, Any]] = []
    for index, tmpl in enumerate(template):
        item = dict(tmpl)
        if index < len(generated):
            item["paragraphs"] = generated[index].get("paragraphs") or generated[index].get("body") or []
            item["bullets"] = generated[index].get("bullets") or item.get("bullets", [])
        item["level"] = "h3" if str(item.get("level")).lower() == "h3" else "h2"
        merged.append(item)
    return merged
