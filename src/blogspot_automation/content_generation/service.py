from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
import re
from typing import Any

from blogspot_automation.config.settings import Settings
from blogspot_automation.content_generation.validators import (
    build_brief_model,
    normalize_article_sections,
)
from blogspot_automation.storage import StateStore


@dataclass(slots=True)
class BlogPackageBuildResult:
    topic_id: str
    blog_package_path: str
    article_html_path: str
    metadata_path: str


def build_blog_package(
    *,
    topic_id: str,
    store: StateStore,
    settings: Settings,
    client: Any,
) -> BlogPackageBuildResult:
    del settings
    topic_data = store.get_topic_by_id(topic_id)
    fact_pack_payload = store.load_fact_pack(topic_id)
    fact_pack = fact_pack_payload.get("fact_pack", fact_pack_payload)

    brief_payload = _loads(client.create_chat_completion(system_prompt="", user_prompt="brief"))
    brief = build_brief_model(
        run_id=f"brief-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        topic_data=topic_data,
        fact_pack=fact_pack_payload,
        payload=brief_payload,
    )

    package_payload = _loads(client.create_chat_completion(system_prompt="", user_prompt="article"))
    title_payload = _loads(client.create_chat_completion(system_prompt="", user_prompt="title"))
    blog_package = _build_package_dict(
        topic_id=topic_id,
        topic_data=topic_data,
        fact_pack=fact_pack_payload,
        brief=brief,
        payload=package_payload,
        final_title=str(title_payload.get("final_title") or ""),
    )
    _write_package_files(store=store, topic_id=topic_id, topic_data=topic_data, fact_pack=fact_pack_payload, brief=brief, blog_package=blog_package)
    output_dir = store.topic_output_dir(topic_id)
    return BlogPackageBuildResult(
        topic_id=topic_id,
        blog_package_path=str(output_dir / "blog_package.json"),
        article_html_path=str(output_dir / "article.html"),
        metadata_path=str(output_dir / "metadata.json"),
    )


def refine_content(
    *,
    topic_id: str,
    store: StateStore,
    settings: Settings,
    client: Any,
) -> BlogPackageBuildResult:
    del settings
    existing = store.load_blog_package(topic_id)
    topic_data = dict(existing.get("topic_data") or {})
    fact_pack = dict(existing.get("fact_pack") or {})
    brief = dict(existing.get("brief") or {})
    package_payload = _loads(client.create_chat_completion(system_prompt="", user_prompt="refine"))
    title_payload = _loads(client.create_chat_completion(system_prompt="", user_prompt="title"))
    blog_package = _build_package_dict(
        topic_id=topic_id,
        topic_data=topic_data,
        fact_pack=fact_pack,
        brief=brief,
        payload=package_payload,
        final_title=str(title_payload.get("final_title") or ""),
    )
    _write_package_files(store=store, topic_id=topic_id, topic_data=topic_data, fact_pack=fact_pack, brief=brief, blog_package=blog_package)
    output_dir = store.topic_output_dir(topic_id)
    return BlogPackageBuildResult(
        topic_id=topic_id,
        blog_package_path=str(output_dir / "blog_package.json"),
        article_html_path=str(output_dir / "article.html"),
        metadata_path=str(output_dir / "metadata.json"),
    )


def _build_package_dict(
    *,
    topic_id: str,
    topic_data: dict[str, Any],
    fact_pack: dict[str, Any],
    brief: dict[str, Any],
    payload: dict[str, Any],
    final_title: str,
) -> dict[str, Any]:
    sections = normalize_article_sections(payload.get("article_sections"))
    title = final_title or _first(payload.get("title_candidates")) or str(topic_data.get("candidate_title") or "제목")
    meta = _normalize_meta_description(str(payload.get("meta_description") or title))
    article_html = _render_article_html(title=title, intro=str(payload.get("intro_paragraph") or ""), sections=sections, payload=payload)
    article_markdown = _render_article_markdown(title=title, intro=str(payload.get("intro_paragraph") or ""), sections=sections, payload=payload)
    json_ld = {
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": title,
                "description": meta,
                "author": {"@type": "Person", "name": "Yomi"},
            }
        ]
    }
    return {
        "package_id": f"package-{topic_id}",
        "topic_id": topic_id,
        "topic_data": topic_data,
        "fact_pack": fact_pack,
        "brief": brief,
        "ai_name": topic_data.get("ai_name", ""),
        "topic_name": topic_data.get("topic_name", ""),
        "topic_type": topic_data.get("topic_type", ""),
        "topic_angle": topic_data.get("topic_angle", ""),
        "keyword_primary": topic_data.get("keyword_primary", ""),
        "keyword_secondary": topic_data.get("keyword_secondary", []),
        "source_name": topic_data.get("source_name", ""),
        "source_type": topic_data.get("source_type", ""),
        "source_url": topic_data.get("source_url", ""),
        "source_published_at": topic_data.get("source_published_at"),
        "title_candidates": list(payload.get("title_candidates") or []),
        "final_title": title,
        "slug": _slugify(title),
        "meta_description": meta,
        "excerpt": str(payload.get("excerpt") or ""),
        "intro_paragraph": str(payload.get("intro_paragraph") or ""),
        "article_outline": list(payload.get("article_outline") or []),
        "article_body": {
            "key_takeaways": list(payload.get("key_takeaways") or []),
            "article_sections": sections,
            "practical_checklist": payload.get("practical_checklist") or {},
            "conclusion": str(payload.get("conclusion") or ""),
        },
        "labels": list(payload.get("labels") or []),
        "hashtags": list(payload.get("hashtags") or []),
        "faq_items": list(payload.get("faq_items") or []),
        "internal_links": list(payload.get("internal_links") or []),
        "external_sources": list(payload.get("external_citation_placeholders") or []),
        "author_note": str(payload.get("author_note") or ""),
        "update_date": datetime.now(timezone.utc).date().isoformat(),
        "cta_text": str(payload.get("cta_text") or ""),
        "content_sections": sections,
        "cover_image_prompt": str(payload.get("image_prompt") or ""),
        "image_prompt": str(payload.get("image_prompt") or ""),
        "image_alt": list(payload.get("alt_text_candidates") or []),
        "article_html": article_html,
        "article_markdown": article_markdown,
        "json_ld_inputs": {},
        "json_ld": json_ld,
        "image_assets": {},
        "status": "generated",
    }


def _write_package_files(
    *,
    store: StateStore,
    topic_id: str,
    topic_data: dict[str, Any],
    fact_pack: dict[str, Any],
    brief: dict[str, Any],
    blog_package: dict[str, Any],
) -> None:
    output_dir = store.topic_output_dir(topic_id)
    (output_dir / "brief.json").write_text(
        json.dumps({"topic_data": topic_data, "fact_pack": fact_pack, "brief": brief}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store.save_blog_package(
        topic_id,
        {"topic_data": topic_data, "fact_pack": fact_pack, "brief": brief, "blog_package": blog_package},
    )
    (output_dir / "article.html").write_text(str(blog_package["article_html"]), encoding="utf-8")
    (output_dir / "article.md").write_text(str(blog_package["article_markdown"]), encoding="utf-8")
    store.save_metadata(
        topic_id,
        {
            "final_title": blog_package["final_title"],
            "meta_description": blog_package["meta_description"],
            "cover_image_prompt": blog_package["cover_image_prompt"],
        },
    )


def _render_article_html(
    *,
    title: str,
    intro: str,
    sections: list[dict[str, Any]],
    payload: dict[str, Any],
) -> str:
    parts = [f"<article><h1>{escape(title)}</h1>"]
    if intro:
        parts.append(f"<p>{escape(intro)}</p>")
    for section in sections:
        level = "h3" if section.get("level") == "h3" else "h2"
        parts.append(f"<{level}>{escape(str(section.get('heading') or '섹션'))}</{level}>")
        for paragraph in section.get("paragraphs") or []:
            parts.append(f"<p>{escape(str(paragraph))}</p>")
        bullets = section.get("bullets") or []
        if bullets:
            parts.append("<ul>")
            parts.extend(f"<li>{escape(str(item))}</li>" for item in bullets)
            parts.append("</ul>")
    checklist = payload.get("practical_checklist") or {}
    if isinstance(checklist, dict) and checklist.get("items"):
        parts.append(f"<h2>{escape(str(checklist.get('heading') or '체크리스트'))}</h2><ul>")
        parts.extend(f"<li>{escape(str(item))}</li>" for item in checklist.get("items") or [])
        parts.append("</ul>")
    if payload.get("faq_items"):
        parts.append("<section class=\"faq\"><h2>FAQ</h2>")
        for item in payload.get("faq_items") or []:
            parts.append(f"<h3>{escape(str(item.get('question') or '질문'))}</h3>")
            parts.append(f"<p>{escape(str(item.get('answer') or '답변'))}</p>")
        parts.append("</section>")
    if payload.get("conclusion"):
        parts.append(f"<p>{escape(str(payload.get('conclusion')))}</p>")
    parts.append("</article>")
    return "\n".join(parts)


def _render_article_markdown(
    *,
    title: str,
    intro: str,
    sections: list[dict[str, Any]],
    payload: dict[str, Any],
) -> str:
    lines = [f"# {title}", "", intro, ""]
    for section in sections:
        prefix = "###" if section.get("level") == "h3" else "##"
        lines.append(f"{prefix} {section.get('heading') or '섹션'}")
        lines.extend(str(paragraph) for paragraph in section.get("paragraphs") or [])
        lines.extend(f"- {item}" for item in section.get("bullets") or [])
        lines.append("")
    if payload.get("conclusion"):
        lines.append(str(payload.get("conclusion")))
    return "\n".join(lines)


def _normalize_meta_description(value: str) -> str:
    text = " ".join(value.split()).strip()
    if len(text) < 110:
        text = f"{text} 핵심 변화와 적용 조건, 실무 체크포인트를 공식 정보 기반으로 차분하게 정리했습니다."
    if len(text) > 140:
        text = text[:140].rsplit(" ", 1)[0].rstrip(" .,")
    return text


def _slugify(value: str) -> str:
    ascii_tokens = re.findall(r"[A-Za-z0-9]+", value.lower())
    base = "-".join(ascii_tokens[:8]) or "blog-post"
    return base[:60].strip("-") or "blog-post"


def _loads(value: str) -> dict[str, Any]:
    return json.loads(value)


def _first(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return ""
