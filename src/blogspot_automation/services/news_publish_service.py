from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

from blogspot_automation.config import Settings
from blogspot_automation.publishing.client import BloggerClient
from blogspot_automation.services.indexnow_client import submit_urls as indexnow_submit_urls
from blogspot_automation.services.cover_image_policy import cover_image_url_from_env, ensure_cover_image_html
from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.seo_policy import (
    append_hashtags_block,
    append_internal_links_block,
    build_english_permalink_slug,
    has_unverified_experience_or_income_claim,
    improve_image_alt_text,
    normalize_hashtags,
    normalize_labels,
    normalize_search_description,
    prepare_blogspot_html,
    strip_external_anchor_links,
)
from blogspot_automation.services.title_integrity_policy import audit_title_integrity
from blogspot_automation.utils.html_meta import extract_meta_description

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NewsPublishOutcome:
    post_id: str
    post_url: str
    status: str
    response_json: dict[str, object]
    is_draft: bool = False
    # 초안일 때 사람이 검토할 Blogger 대시보드 편집 링크.
    # (draft의 post_url은 Blogger가 블로그 홈 URL을 돌려줘 신뢰할 수 없다 — 절대 audit/fetch에 쓰지 말 것.)
    dashboard_url: str = ""


class NewsPublishService:
    """Thin news publisher that reuses the existing Blogger OAuth client."""

    def __init__(
        self,
        *,
        settings: Settings,
        blogger_client: BloggerClient | None = None,
        history_path: str | Path = "state/news_published_history.json",
    ) -> None:
        self.settings = settings
        self.blogger_client = blogger_client
        self.history_path = Path(history_path)

    def publish(
        self,
        *,
        title: str,
        article_html: str,
        labels: list[str],
        meta_description: str = "",
        selected_topic: str = "",
        total_score: int | None = None,
        click_potential_score: int | None = None,
        topic_group: str = "",
        content_type: str = "",
        hashtags: list[str] | None = None,
        image_alt_text: str = "",
        is_draft: bool = False,
        internal_links: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None = None,
        permalink_slug_hint: str = "",
    ) -> NewsPublishOutcome:
        blogger_client = self.blogger_client or BloggerClient(self.settings)
        if has_unverified_experience_or_income_claim(article_html):
            raise ValueError("News publish blocked: unverified experience or income claim detected.")
        normalized_labels = normalize_labels(labels)
        normalized_hashtags = normalize_hashtags(hashtags or normalized_labels)
        _validate_labels(normalized_labels)
        prepared_html = prepare_blogspot_html(
            improve_image_alt_text(article_html, image_alt_text=image_alt_text or title),
            strip_document=True,
        )
        # 내부 링크는 prepare가 기존 섹션을 strip한 뒤에 붙여야 살아남는다.
        # answer_engine tail 블록은 internal-links 섹션 앞에 삽입되므로 순서 안전.
        if internal_links:
            prepared_html = append_internal_links_block(prepared_html, links=internal_links)
        # 단방향 계약(2026-07-08 구조 감사 로드맵 4): 본문 재렌더는 여기서 하지 않는다.
        # 과거 이 지점의 ensure_answer_engine 2차 호출이 파이프라인 단계에서 확정한
        # 본문(faq-item 정규화 등)을 다시 재렌더해 무효화했고, dry_run엔 없는 이
        # 변형이 실발행에서만 최종 계약 크래시를 냈다(PR #29 사건). 이제 GEO 확정은
        # 파이프라인(발행 전 단계)의 책임이고, 여기서는 아래 _validate_publish_contract가
        # "검증만" 한다 — 확정 안 된 본문은 조용히 고쳐지는 대신 시끄럽게 거부된다.
        prepared_html = ensure_cover_image_html(
            prepared_html,
            image_url=cover_image_url_from_env(topic_group=topic_group),
            alt_text=image_alt_text or title,
            title=title,
        )
        prepared_html = append_hashtags_block(
            prepared_html,
            hashtags=normalized_hashtags,
            labels=normalized_labels,
        )
        prepared_html = _strip_internal_h1_for_blogger(prepared_html)
        prepared_html = strip_external_anchor_links(prepared_html)
        resolved_meta_description = normalize_search_description(
            title=title,
            description=meta_description.strip() or extract_meta_description(prepared_html),
            html=prepared_html,
            topic=selected_topic,
        )
        _validate_publish_contract(
            prepared_html,
            title=title,
            topic=selected_topic,
            content_type=content_type,
            topic_group=topic_group,
            labels=normalized_labels,
            hashtags=normalized_hashtags,
        )
        permalink_slug = build_english_permalink_slug(
            title=title,
            topic=selected_topic,
            labels=list(normalized_labels or []) + [topic_group],
            topic_group=topic_group,
            slug_hint=permalink_slug_hint,
        )
        response = blogger_client.publish_post(
            title=title,
            article_html=prepared_html,
            labels=normalized_labels,
            meta_description=resolved_meta_description,
            permalink_slug=permalink_slug,
            is_draft=is_draft,
        )
        _post_id = str(response.get("id") or "")
        outcome = NewsPublishOutcome(
            post_id=_post_id,
            post_url=str(response.get("url") or ""),
            status=str(response.get("status") or ""),
            response_json=response,
            is_draft=is_draft,
            dashboard_url=(
                f"https://www.blogger.com/blog/post/edit/{blogger_client.blog_id}/{_post_id}"
                if is_draft and _post_id
                else ""
            ),
        )
        try:
            self._append_history(
                {
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "topic": selected_topic,
                    "selected_title": title,
                    "title": title,
                    "post_id": outcome.post_id,
                    "url": outcome.post_url,
                    "total_score": total_score,
                    "click_potential_score": click_potential_score,
                    "topic_group": topic_group,
                    "content_type": content_type,
                    "labels": normalized_labels,
                    "hashtags": normalized_hashtags,
                    "permalink_slug": permalink_slug,
                    "search_description": resolved_meta_description,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("news published history update failed: %s", exc)

        if outcome.post_url and not is_draft:
            try:
                index_result = indexnow_submit_urls([outcome.post_url])
                logger.info("indexnow ping result: %s", index_result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("indexnow ping failed (non-fatal): %s", exc)

        return outcome

    def _append_history(self, record: dict[str, Any]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        if self.history_path.exists():
            try:
                raw = json.loads(self.history_path.read_text(encoding="utf-8"))
            except Exception:
                raw = []
            if isinstance(raw, list):
                records = [item for item in raw if isinstance(item, dict)]
            elif isinstance(raw, dict):
                raw_records = raw.get("records")
                if isinstance(raw_records, list):
                    records = [item for item in raw_records if isinstance(item, dict)]
        records.append(record)
        self.history_path.write_text(
            json.dumps(records[-200:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete_post(self, post_id: str) -> bool:
        blogger_client = self.blogger_client or BloggerClient(self.settings)
        deleter = getattr(blogger_client, "delete_post", None)
        if not callable(deleter):
            logger.warning("blogger client does not expose delete_post; post_id=%s", post_id)
            return False
        return bool(deleter(post_id))


def _strip_internal_h1_for_blogger(html: str) -> str:
    """Blogger theme already renders the post title; avoid duplicate visible titles."""
    return re.sub(r"\s*<h1\b[^>]*>.*?</h1>\s*", "\n", html or "", count=1, flags=re.IGNORECASE | re.DOTALL)


def _validate_labels(labels: list[str]) -> None:
    if len(labels) < 2:
        raise ValueError("News publish blocked: at least 2 valid Blogger labels are required.")
    bad = [label for label in labels if _looks_mojibake(label)]
    if bad:
        raise ValueError(f"News publish blocked: Blogger labels look corrupted: {bad!r}")


def _validate_publish_contract(
    html: str,
    *,
    title: str,
    topic: str,
    content_type: str,
    topic_group: str,
    labels: list[str],
    hashtags: list[str],
) -> None:
    content = html or ""
    issues: list[str] = []
    title_integrity = audit_title_integrity(title, content_type=content_type, topic_group=topic_group)
    issues.extend(f"title_integrity:{issue}" for issue in title_integrity.get("blocking_issues", []))
    if re.search(r"<!doctype\b|</?(?:html|head|body)\b|<title\b|<meta\b", content, flags=re.IGNORECASE):
        issues.append("post_content_contains_document_or_meta_tags")
    if not re.search(r'<article\b[^>]*class=["\'][^"\']*\byomi-clean-post\b', content, flags=re.IGNORECASE):
        issues.append("post_content_missing_yomi_clean_article")
    if not hashtags:
        issues.append("content_hashtags_missing")
    audit = audit_final_html_quality(
        content,
        topic=topic or title,
        content_type=content_type,
        topic_group=topic_group,
    )
    issues.extend(str(issue) for issue in audit.get("issues", []))
    if _requires_official_source_links(content_type=content_type, topic_group=topic_group):
        source_block = _source_trust_block(content)
        source_link_count = len(re.findall(r"<a\b[^>]*\bhref=[\"']https?://", source_block, flags=re.IGNORECASE))
        if source_link_count < 2:
            issues.append("official_source_links_below_2")
    if any(_looks_mojibake(label) for label in labels):
        issues.append("labels_contain_mojibake")
    if issues:
        unique = ",".join(dict.fromkeys(issues))
        raise ValueError(f"News publish blocked by final publish contract: {unique}")


def _source_trust_block(html: str) -> str:
    match = re.search(
        r'<section\b(?=[^>]*id=["\']SOURCE_TRUST_BLOCK["\'])[^>]*>(.*?)</section>',
        html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _requires_official_source_links(*, content_type: str, topic_group: str) -> bool:
    haystack = f"{content_type} {topic_group}"
    return any(
        token in haystack
        for token in (
            "consumer",
            "refund",
            "policy",
            "tax",
            "platform_change",
            "delivery_money",
        )
    )


def _looks_mojibake(value: str) -> bool:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return True
    if "\ufffd" in text:
        return True
    if re.fullmatch(r"\?{2,}", text):
        return True
    return len(re.findall(r"[ÃÂìíîïêëð]", text)) >= 2
