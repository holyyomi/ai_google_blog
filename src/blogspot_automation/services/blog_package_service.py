from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import os
from pathlib import Path

from blogspot_automation.storage import (
    BlogWorkItemRepository,
    BriefRecordRepository,
    ContentPackageRecord,
    ContentPackageRepository,
)
from blogspot_automation.services.seo_policy import BLOGSPOT_HOME_URL, normalize_hashtags


SECTION_IDS = [
    ("hero", "Hero"),
    ("one-line", "한 줄 결론"),
    ("reader-fit", "이 글이 필요한 사람"),
    ("takeaways", "핵심 요약 3~5개"),
    ("facts", "기사 기반 핵심 사실 정리"),
    ("why-now", "지금 왜 중요한가"),
    ("meaning", "그래서 개인에게 무슨 의미인가"),
    ("steps", "시작 방법 / 실행 단계"),
    ("metrics", "준비물 / 시간 / 비용 / 예상수익"),
    ("fit", "추천 대상 / 비추천 대상"),
    ("failure", "실패 포인트"),
    ("checklist", "실전 체크리스트"),
    ("plan", "7일 실행 플랜 또는 첫 3단계 액션"),
    ("cautions", "주의사항"),
    ("faq", "FAQ"),
    ("cta", "CTA"),
    ("sources", "출처 / 업데이트"),
]


@dataclass(slots=True)
class BlogPackageRecord:
    work_item_id: str
    created_at: str
    updated_at: str
    title_candidates: list[str]
    final_title: str
    meta_description: str
    labels: list[str]
    hashtags: list[str]
    image_prompt: str
    article_html: str
    article_preview_html: str
    json_ld: dict[str, object]


class BloggerPackageService:
    def __init__(
        self,
        *,
        work_item_repository: BlogWorkItemRepository,
        brief_repository: BriefRecordRepository,
        content_package_repository: ContentPackageRepository,
        template_root: Path | None = None,
    ) -> None:
        self.work_item_repository = work_item_repository
        self.brief_repository = brief_repository
        self.content_package_repository = content_package_repository
        self.template_root = template_root or Path(__file__).resolve().parents[3] / "templates" / "html"

    def build_package(self, *, work_item_id: str) -> BlogPackageRecord:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        brief = self.brief_repository.get_by_work_item_id(work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {work_item_id}")
        if brief is None:
            raise ValueError(f"Brief not found for work item: {work_item_id}")

        # 🧠 AI가 미리 생성한 결과물이 있으면 그대로 사용 (pass-through mode)
        ai_generated_html = work_item.article_html.strip() if work_item.article_html else ""
        ai_title_candidates = work_item.title_candidates if work_item.title_candidates else []
        ai_meta_description = work_item.meta_description if work_item.meta_description else ""
        ai_labels = work_item.labels if work_item.labels else []

        if ai_generated_html:
            # Pass-through: AI가 이미 완성한 article_html을 덮어쓰지 않는다
            final_title = (
                work_item.final_title
                or (ai_title_candidates[0] if ai_title_candidates else work_item.topic_title)
            )
            meta_description = ai_meta_description or _build_meta_description(final_title, brief)
            labels = ai_labels or _build_labels(work_item)
            article_html = ai_generated_html
        else:
            # Fallback: 기존 Python 조합 렌더러 사용
            title_candidates = _build_title_candidates(
                topic_title=work_item.topic_title,
                primary_keyword=work_item.primary_keyword,
                existing_titles=work_item.title_candidates,
                title_types=work_item.title_candidate_types,
            )
            final_title = _select_final_title(
                title_candidates=title_candidates,
                primary_keyword=work_item.primary_keyword,
                pillar=work_item.content_pillar,
            )
            meta_description = _build_meta_description(final_title, brief)
            labels = _build_labels(work_item)
            article_html = self._render_article_html(
                pillar_label=work_item.content_pillar,
                final_title=final_title,
                meta_description=meta_description,
                updated_at=brief.updated_at[:10],
                brief=brief,
                work_item=work_item,
            )

        hashtags = _build_hashtags(labels)
        image_prompt = _build_image_prompt(work_item.content_pillar, final_title)
        preview_html = build_preview_html(article_html, final_title)
        json_ld = _build_json_ld(
            final_title=final_title,
            meta_description=meta_description,
            article_html=article_html,
            faq_items=brief.faq_items,
            source_urls=work_item.source_urls,
            updated_at=brief.updated_at,
        )
        self._update_work_item(
            work_item_id=work_item_id,
            final_title=final_title,
            meta_description=meta_description,
            labels=labels,
            hashtags=hashtags,
            image_prompt=image_prompt,
            article_html=article_html,
            json_ld=json_ld,
        )
        timestamp = datetime.now(timezone.utc).isoformat()
        record = ContentPackageRecord(
            work_item_id=work_item_id,
            created_at=timestamp,
            updated_at=timestamp,
            title_candidates=ai_title_candidates or [],
            final_title=final_title,
            meta_description=meta_description,
            labels=labels,
            hashtags=hashtags,
            image_prompt=image_prompt,
            article_html=article_html,
            article_preview_html=preview_html,
            json_ld=json_ld,
        )
        saved = self.content_package_repository.upsert(record)
        return BlogPackageRecord(
            work_item_id=saved.work_item_id,
            created_at=saved.created_at,
            updated_at=saved.updated_at,
            title_candidates=saved.title_candidates,
            final_title=saved.final_title,
            meta_description=saved.meta_description,
            labels=saved.labels,
            hashtags=saved.hashtags,
            image_prompt=saved.image_prompt,
            article_html=saved.article_html,
            article_preview_html=saved.article_preview_html,
            json_ld=saved.json_ld,
        )


    def _render_article_html(
        self,
        *,
        pillar_label: str,
        final_title: str,
        meta_description: str,
        updated_at: str,
        brief,
        work_item,
    ) -> str:
        source_articles = work_item.source_articles or []
        toc_items = "".join(
            f"<li style=\"margin:0 0 8px 0;\"><a href=\"#{section_id}\" style=\"color:#0f766e;text-decoration:none;\">{html.escape(label)}</a></li>"
            for section_id, label in SECTION_IDS
        )
        sections = [
            _hero_section(pillar_label, final_title, meta_description, updated_at, brief),
            _content_box("one-line", "한 줄 결론", [brief.one_line_hook, brief.brief_summary], "summary"),
            _audience_section(brief),
            _list_box("takeaways", "핵심 요약 3~5개", brief.key_takeaways, "summary"),
            _list_box("facts", "기사 기반 핵심 사실 정리", brief.hard_facts_from_sources or brief.facts_from_sources, "facts"),
            _content_box("why-now", "지금 왜 중요한가", [brief.why_now], "highlight"),
            _list_box("meaning", "그래서 개인에게 무슨 의미인가", brief.what_it_means_to_reader, "highlight"),
            _numbered_box("steps", "시작 방법 / 실행 단계", brief.practical_actions, "execution"),
            _metrics_section(brief),
            _fit_section(brief),
            _list_box("failure", "실패 포인트", brief.failure_points, "warning"),
            _list_box("checklist", "실전 체크리스트", _build_checklist(brief), "checklist"),
            _numbered_box("plan", "7일 실행 플랜 또는 첫 3단계 액션", _build_action_plan(brief), "plan"),
            _list_box("cautions", "주의사항", brief.cautions, "warning"),
            _faq_section(brief.faq_items),
            _cta_section(brief),
            _sources_section(updated_at, source_articles),
        ]
        return (
            "<article style=\"max-width:820px;margin:0 auto;padding:20px 14px;background:#f5f7fb;"
            "color:#1f2937;font-family:'Segoe UI',Apple SD Gothic Neo,sans-serif;line-height:1.72;\">"
            "<section style=\"border:1px solid #dbe4f0;border-radius:22px;padding:18px 20px;background:#ffffff;margin-bottom:18px;\">"
            "<h2 style=\"font-size:20px;margin:0 0 12px 0;color:#0f172a;\">목차</h2>"
            f"<ol style=\"margin:0;padding-left:20px;color:#334155;columns:1;\">{toc_items}</ol>"
            "</section>"
            + "".join(sections)
            + "</article>"
        )

    def _update_work_item(
        self,
        *,
        work_item_id: str,
        final_title: str,
        meta_description: str,
        labels: list[str],
        hashtags: list[str],
        image_prompt: str,
        article_html: str,
        json_ld: dict[str, object],
    ) -> None:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {work_item_id}")
        work_item.final_title = final_title
        work_item.meta_description = meta_description
        work_item.labels = labels
        work_item.hashtags = hashtags
        work_item.image_prompt = image_prompt
        work_item.article_html = article_html
        work_item.json_ld = json_ld
        self.work_item_repository.upsert(work_item)


def build_preview_html(article_html: str, final_title: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(final_title)}</title>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<body style=\"margin:0;background:#e5e7eb;padding:16px;\">"
        f"{article_html}"
        "</body></html>"
    )


def _build_title_candidates(
    *,
    topic_title: str,
    primary_keyword: str,
    existing_titles: list[str],
    title_types: list[str],
) -> list[str]:
    del existing_titles, title_types
    base = _title_base(topic_title, primary_keyword)
    generated = [
        f"{base}, 지금 안 보면 놓치기 쉬운 문제 3가지",
        f"초보도 이해하는 {base} 시작 기준",
        f"{base} 바로 실행하려면 오늘 무엇부터 해야 하나",
        f"{base} 직접 하기 vs 도구 활용, 어디서 차이가 나는가",
        topic_title.strip(),
    ]
    seen: set[str] = set()
    output: list[str] = []
    for item in generated:
        normalized = " ".join(item.split())
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        output.append(normalized)
    return output[:5]


def _title_base(topic_title: str, primary_keyword: str) -> str:
    candidate = " ".join(primary_keyword.split()).strip()
    if not candidate or len(candidate) < 4:
        return _condense_topic_title(topic_title)
    if candidate.isascii() and len(candidate.split()) <= 2:
        return _condense_topic_title(topic_title)
    return candidate


def _condense_topic_title(topic_title: str) -> str:
    compact = topic_title.strip()
    replacements = [
        "흐름에서 찾은 ",
        "이슈로 보는 ",
        "무엇을 봐야 하나",
        "실전 적용 포인트",
        "실수 방지 가이드",
        "초보 체크포인트",
    ]
    for token in replacements:
        compact = compact.replace(token, "")
    tokens: list[str] = []
    seen: set[str] = set()
    for token in compact.replace("/", " ").split():
        normalized = "AI" if token.lower() == "ai" else token
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(normalized)
    compact = " ".join(tokens).strip(" -,:")
    return compact or topic_title.strip()


def _select_final_title(*, title_candidates: list[str], primary_keyword: str, pillar: str) -> str:
    scored: list[tuple[float, str]] = []
    keyword = primary_keyword.lower().strip()
    for title in title_candidates:
        lowered = title.lower()
        score = 0.0
        if keyword and keyword in lowered:
            score += 3.0
        if any(token in lowered for token in ["방법", "기준", "체크", "실행", "해설", "비교"]):
            score += 2.2
        if 18 <= len(title) <= 42:
            score += 1.5
        if pillar == "한국뉴스 기반 관심 한국주식 해설" and "해설" in title:
            score += 2.0
        if pillar == "AI 부업 / 온라인 수익화 실전" and any(token in title for token in ["실행", "시작", "체크"]):
            score += 2.0
        scored.append((score, title))
    return max(scored, key=lambda item: item[0])[1]


def _build_meta_description(final_title: str, brief) -> str:
    base = (
        f"{final_title}. 시간 {brief.estimated_time_to_start}, 비용 {brief.estimated_cost_to_start}, "
        f"난이도 {brief.difficulty_level}, 수익 범위 {brief.potential_income_range}. "
        f"{brief.one_line_hook}"
    )
    compact = " ".join(base.split())
    if len(compact) <= 155:
        return compact
    return compact[:152].rstrip(" .,") + "..."


def _build_labels(work_item) -> list[str]:
    labels = [work_item.content_pillar, work_item.primary_keyword]
    labels.extend(work_item.secondary_keywords[:3])
    return list(dict.fromkeys(label.strip() for label in labels if label.strip()))[:5]


def _build_hashtags(labels: list[str]) -> list[str]:
    return normalize_hashtags([f"#{label.replace(' ', '')}" for label in labels])


def _build_image_prompt(pillar: str, final_title: str) -> str:
    return (
        f"Editorial blogger cover, practical and trustworthy tone, mobile readable layout, "
        f"Korean office worker audience, topic: {pillar}, title idea: {final_title}"
    )


def _hero_section(pillar_label: str, final_title: str, meta_description: str, updated_at: str, brief) -> str:
    badges = [
        ("예상 시간", brief.estimated_time_to_start),
        ("예상 비용", brief.estimated_cost_to_start),
        ("예상 수익", brief.potential_income_range),
        ("난이도", brief.difficulty_level),
    ]
    badge_html = "".join(
        f"<span style=\"display:inline-block;margin:0 8px 8px 0;padding:8px 12px;border-radius:999px;background:#ecfeff;"
        f"border:1px solid #a5f3fc;color:#155e75;font-size:13px;font-weight:600;\">{html.escape(label)}: {html.escape(value)}</span>"
        for label, value in badges
    )
    return (
        "<section id=\"hero\" style=\"padding:26px 22px;border:1px solid #cbd5e1;border-radius:24px;"
        "background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%);margin-bottom:18px;\">"
        f"<div style=\"font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#0f766e;margin-bottom:10px;\">{html.escape(pillar_label)}</div>"
        f"<h1 style=\"font-size:31px;line-height:1.3;margin:0 0 12px 0;color:#0f172a;\">{html.escape(final_title)}</h1>"
        f"<p style=\"font-size:16px;margin:0 0 14px 0;color:#334155;\">{html.escape(meta_description)}</p>"
        f"<div style=\"margin-bottom:10px;\">{badge_html}</div>"
        f"<div style=\"font-size:13px;color:#64748b;\">업데이트: {html.escape(updated_at)}</div>"
        "</section>"
    )


def _content_box(section_id: str, title: str, paragraphs: list[str], tone: str) -> str:
    palette = _palette(tone)
    content = "".join(
        f"<p style=\"margin:0 0 12px 0;font-size:16px;color:{palette['text']};\">{html.escape(paragraph)}</p>"
        for paragraph in paragraphs
        if paragraph.strip()
    )
    return _wrap_section(section_id, title, content, palette)


def _list_box(section_id: str, title: str, items: list[str], tone: str) -> str:
    palette = _palette(tone)
    content = "<ul style=\"margin:0;padding-left:20px;\">" + "".join(
        f"<li style=\"margin:0 0 10px 0;color:{palette['text']};font-size:16px;\">{html.escape(item)}</li>"
        for item in items
        if item.strip()
    ) + "</ul>"
    return _wrap_section(section_id, title, content, palette)


def _numbered_box(section_id: str, title: str, items: list[str], tone: str) -> str:
    palette = _palette(tone)
    content = "<ol style=\"margin:0;padding-left:22px;\">" + "".join(
        f"<li style=\"margin:0 0 12px 0;color:{palette['text']};font-size:16px;\">{html.escape(item)}</li>"
        for item in items
        if item.strip()
    ) + "</ol>"
    return _wrap_section(section_id, title, content, palette)


def _audience_section(brief) -> str:
    content = (
        f"<p style=\"margin:0 0 12px 0;font-size:16px;color:#334155;\">{html.escape(brief.target_reader)}</p>"
        f"<p style=\"margin:0;font-size:16px;color:#475569;\">독자 문제: {html.escape(brief.reader_problem)}</p>"
    )
    return _wrap_section("reader-fit", "이 글이 필요한 사람", content, _palette("summary"))


def _metrics_section(brief) -> str:
    cards = [
        ("준비 시간", brief.estimated_time_to_start),
        ("준비 비용", brief.estimated_cost_to_start),
        ("예상 수익 범위", brief.potential_income_range),
        ("난이도", brief.difficulty_level),
    ]
    grid = "".join(
        "<div style=\"flex:1 1 180px;border:1px solid #bfdbfe;background:#ffffff;border-radius:16px;padding:14px;\">"
        f"<div style=\"font-size:13px;color:#1d4ed8;font-weight:700;margin-bottom:6px;\">{html.escape(label)}</div>"
        f"<div style=\"font-size:18px;color:#0f172a;font-weight:700;\">{html.escape(value)}</div>"
        "</div>"
        for label, value in cards
    )
    extra = (
        f"<p style=\"margin:14px 0 0 0;color:#334155;font-size:15px;\">검색 의도: {html.escape(brief.search_intent)}</p>"
        f"<p style=\"margin:8px 0 0 0;color:#334155;font-size:15px;\">현실성 기준: 출처 없는 숫자는 넣지 않고, 바로 시작 가능한 범위만 제안한다.</p>"
    )
    return _wrap_section(
        "metrics",
        "준비물 / 시간 / 비용 / 예상수익",
        f"<div style=\"display:flex;flex-wrap:wrap;gap:12px;\">{grid}</div>{extra}",
        _palette("facts"),
    )


def _fit_section(brief) -> str:
    content = (
        "<div style=\"display:flex;flex-wrap:wrap;gap:14px;\">"
        "<div style=\"flex:1 1 240px;border:1px solid #bbf7d0;background:#f0fdf4;border-radius:16px;padding:16px;\">"
        "<h3 style=\"margin:0 0 10px 0;font-size:18px;color:#166534;\">추천 대상</h3>"
        + "".join(f"<p style=\"margin:0 0 8px 0;color:#166534;\">- {html.escape(item)}</p>" for item in brief.recommended_for)
        + "</div>"
        "<div style=\"flex:1 1 240px;border:1px solid #fecaca;background:#fff1f2;border-radius:16px;padding:16px;\">"
        "<h3 style=\"margin:0 0 10px 0;font-size:18px;color:#9f1239;\">비추천 대상</h3>"
        + "".join(f"<p style=\"margin:0 0 8px 0;color:#9f1239;\">- {html.escape(item)}</p>" for item in brief.not_recommended_for)
        + "</div>"
        "</div>"
    )
    return _wrap_section("fit", "추천 대상 / 비추천 대상", content, _palette("summary"))


def _faq_section(faq_items: list[dict[str, str]]) -> str:
    blocks = "".join(
        "<div style=\"padding:14px 0;border-top:1px solid #dbe4f0;\">"
        f"<h3 style=\"font-size:18px;margin:0 0 8px 0;color:#0f172a;\">{html.escape(item.get('question', ''))}</h3>"
        f"<p style=\"margin:0;color:#334155;font-size:16px;\">{html.escape(item.get('answer', ''))}</p>"
        "</div>"
        for item in faq_items
    )
    return _wrap_section("faq", "FAQ", blocks, _palette("summary"))


def _cta_section(brief) -> str:
    cards = [
        ("오늘 할 1단계", brief.practical_actions[0] if brief.practical_actions else brief.cta_direction),
        ("지금 체크할 항목", brief.failure_points[0] if brief.failure_points else brief.difficulty_level),
        ("다음 읽을 방향", brief.cta_direction),
    ]
    card_html = "".join(
        "<div style=\"flex:1 1 210px;border:1px solid #93c5fd;background:#ffffff;border-radius:18px;padding:14px;\">"
        f"<div style=\"font-size:13px;color:#1d4ed8;font-weight:700;margin-bottom:8px;\">{html.escape(title)}</div>"
        f"<div style=\"font-size:16px;color:#1e293b;line-height:1.6;\">{html.escape(body)}</div>"
        "</div>"
        for title, body in cards
    )
    content = (
        f"<p style=\"margin:0 0 14px 0;font-size:16px;color:#1e3a8a;\">{html.escape(brief.cta_direction)}</p>"
        f"<div style=\"display:flex;flex-wrap:wrap;gap:12px;\">{card_html}</div>"
    )
    return _wrap_section("cta", "CTA", content, _palette("cta"))


def _sources_section(updated_at: str, source_articles: list[dict[str, object]]) -> str:
    items = "".join(
        "<div style=\"padding:12px 0;border-top:1px solid #e2e8f0;\">"
        f"<div style=\"font-size:14px;color:#0f172a;font-weight:700;\">{html.escape(str(article.get('title', '')))}</div>"
        f"<div style=\"font-size:14px;color:#475569;margin-top:6px;\">{html.escape(str(article.get('summary', '')))}</div>"
        f"<div style=\"font-size:13px;color:#64748b;margin-top:6px;\">{html.escape(str(article.get('article_url', '')))}</div>"
        "</div>"
        for article in source_articles
        if str(article.get("article_url", "")).strip()
    )
    if not items:
        items = "<p style=\"margin:0;color:#475569;\">실제 출처 기사만 표시되므로 현재 표시할 항목이 없습니다.</p>"
    content = (
        "<p style=\"margin:0 0 12px 0;color:#475569;font-size:15px;\">아래 출처는 실제 수집된 기사만 사용한다. placeholder URL은 포함하지 않는다.</p>"
        f"{items}<div style=\"font-size:13px;color:#64748b;margin-top:10px;\">마지막 업데이트: {html.escape(updated_at)}</div>"
    )
    return _wrap_section("sources", "출처 / 업데이트", content, _palette("sources"))


def _build_checklist(brief) -> list[str]:
    checklist = [
        "시작 전에 하루 투입 가능 시간을 먼저 적었다.",
        f"예상 비용 {brief.estimated_cost_to_start}를 감당 가능한 범위인지 확인했다.",
        f"난이도 {brief.difficulty_level}에 맞는지 판단했다.",
    ]
    checklist.extend(brief.practical_actions[:2])
    return checklist[:5]


def _build_action_plan(brief) -> list[str]:
    actions = brief.practical_actions[:3]
    if len(actions) >= 3:
        return [
            f"1일차: {actions[0]}",
            f"2~3일차: {actions[1]}",
            f"4~7일차: {actions[2]}",
        ]
    return actions


def _build_json_ld(
    *,
    final_title: str,
    meta_description: str,
    article_html: str,
    faq_items: list[dict[str, str]],
    source_urls: list[str],
    updated_at: str,
) -> dict[str, object]:
    blog_posting: dict[str, object] = {
        "@type": "BlogPosting",
        "headline": final_title,
        "description": meta_description,
        "datePublished": updated_at,
        "dateModified": updated_at,
        "author": {
            "@type": "Person",
            "name": os.getenv("BLOG_AUTHOR_NAME", "holyyomi AI"),
            "url": BLOGSPOT_HOME_URL,
        },
        "publisher": {
            "@type": "Organization",
            "name": os.getenv("BLOG_BRAND_NAME", "holyyomi AI"),
            "url": BLOGSPOT_HOME_URL.rstrip("/"),
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": BLOGSPOT_HOME_URL.rstrip("/"),
        },
        "inLanguage": "ko-KR",
        "articleBody": _strip_tags(article_html),
    }
    if source_urls:
        blog_posting["citation"] = source_urls

    graph: list[dict[str, object]] = [blog_posting]

    # FAQPage (Google FAQ Rich Snippet)
    faq_entities = [
        {
            "@type": "Question",
            "name": item.get("question", ""),
            "acceptedAnswer": {
                "@type": "Answer",
                "text": item.get("answer", ""),
            },
        }
        for item in faq_items
        if item.get("question", "").strip() and item.get("answer", "").strip()
    ]
    if faq_entities:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": faq_entities,
        })

    return {
        "@context": "https://schema.org",
        "@graph": graph,
    }


def _wrap_section(section_id: str, title: str, content: str, palette: dict[str, str]) -> str:
    return (
        f"<section id=\"{section_id}\" style=\"margin-bottom:18px;padding:20px 18px;border:1px solid {palette['border']};"
        f"border-radius:20px;background:{palette['background']};\">"
        f"<h2 style=\"font-size:24px;line-height:1.35;margin:0 0 12px 0;color:{palette['heading']};\">{html.escape(title)}</h2>"
        f"{content}</section>"
    )


def _palette(tone: str) -> dict[str, str]:
    palettes = {
        "summary": {"background": "#ffffff", "border": "#dbe4f0", "heading": "#0f172a", "text": "#334155"},
        "facts": {"background": "#f8fbff", "border": "#bfdbfe", "heading": "#1d4ed8", "text": "#1e3a8a"},
        "highlight": {"background": "#f0fdfa", "border": "#99f6e4", "heading": "#115e59", "text": "#134e4a"},
        "execution": {"background": "#f0fdf4", "border": "#bbf7d0", "heading": "#166534", "text": "#166534"},
        "warning": {"background": "#fff7ed", "border": "#fdba74", "heading": "#9a3412", "text": "#9a3412"},
        "checklist": {"background": "#f7fee7", "border": "#bef264", "heading": "#3f6212", "text": "#3f6212"},
        "plan": {"background": "#eef2ff", "border": "#c7d2fe", "heading": "#4338ca", "text": "#3730a3"},
        "cta": {"background": "#eff6ff", "border": "#93c5fd", "heading": "#1d4ed8", "text": "#1e3a8a"},
        "sources": {"background": "#fafafa", "border": "#e2e8f0", "heading": "#0f172a", "text": "#475569"},
    }
    return palettes[tone]


def _strip_tags(value: str) -> str:
    output: list[str] = []
    inside_tag = False
    for char in value:
        if char == "<":
            inside_tag = True
            output.append(" ")
            continue
        if char == ">":
            inside_tag = False
            continue
        if not inside_tag:
            output.append(char)
    return " ".join("".join(output).split())


_BLOG_DEFAULT_URL = BLOGSPOT_HOME_URL
_PLACEHOLDER_REPLACEMENTS = (
    ("{{YOUTUBE_VIDEO}}", ""),
    ("{{IMG_2}}", ""),
    ("{{IMG_3}}", ""),
    ("{{INTERNAL_LINK_1}}", _BLOG_DEFAULT_URL),
    ("{{INTERNAL_LINK_2}}", _BLOG_DEFAULT_URL),
    ("{{AFFILIATE_LINK}}", _BLOG_DEFAULT_URL),
    ("{{BLOG_URL}}", _BLOG_DEFAULT_URL),
)


def cleanup_blogger_placeholders(html: str) -> str:
    """Strip image/video placeholders and replace internal-link tokens.

    네이버/AI 양 플로우에서 발행 직전 article_html에 남아 있는 빈 IMG_2/IMG_3 요소,
    유튜브 임시 섹션, 그리고 {{INTERNAL_LINK_*}}/{{AFFILIATE_LINK}}/{{BLOG_URL}} 토큰을
    동일 규칙으로 정리한다.
    """
    import re as _re

    cleaned = _re.sub(r'<img[^>]*src="\{\{IMG_[23]\}\}"[^>]*>', "", html)
    cleaned = _re.sub(
        r"<section>\s*<h2[^>]*>📺 시각적인 이해가 필요하다면\?</h2>.*?</section>",
        "",
        cleaned,
        flags=_re.DOTALL,
    )
    for token, value in _PLACEHOLDER_REPLACEMENTS:
        cleaned = cleaned.replace(token, value)
    return cleaned
