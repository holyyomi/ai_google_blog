from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import re
from uuid import uuid4

logger = logging.getLogger(__name__)

from blogspot_automation.config import Settings
from blogspot_automation.publishing.client import BloggerClient
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    ContentPackageRepository,
    PublishRecord,
    PublishRecordRepository,
    PublishStatus,
    QAResult,
    QAReviewRepository,
)
from blogspot_automation.services.seo_policy import (
    BLOGSPOT_HOME_URL,
    has_unverified_experience_or_income_claim,
    improve_image_alt_text,
    normalize_hashtags,
    normalize_labels,
    prepare_blogspot_html,
)


@dataclass(slots=True)
class PublishOutcome:
    work_item_id: str
    publish_result: str
    publish_mode: str
    blog_post_id: str
    blog_url: str
    response_json: dict[str, object]
    message: str


class BloggerPublishService:
    def __init__(
        self,
        *,
        work_item_repository: BlogWorkItemRepository,
        content_package_repository: ContentPackageRepository,
        qa_review_repository: QAReviewRepository,
        publish_record_repository: PublishRecordRepository,
        settings: Settings,
        blogger_client: BloggerClient | None = None,
    ) -> None:
        self.work_item_repository = work_item_repository
        self.content_package_repository = content_package_repository
        self.qa_review_repository = qa_review_repository
        self.publish_record_repository = publish_record_repository
        self.settings = settings
        self.blogger_client = blogger_client or BloggerClient(settings)

    def publish(
        self,
        *,
        work_item_id: str,
        publish_mode: str = "public",
        manual_soft_fail_approval: bool = False,
    ) -> PublishOutcome:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        package = self.content_package_repository.get_by_work_item_id(work_item_id)
        review = self.qa_review_repository.get_by_work_item_id(work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {work_item_id}")
        if package is None:
            raise ValueError(f"Content package not found for work item: {work_item_id}")
        if review is None:
            raise ValueError(f"QA review not found for work item: {work_item_id}")

        self._guard_qa(work_item_id=work_item_id, manual_soft_fail_approval=manual_soft_fail_approval)
        self._sanity_check(work_item_id=work_item_id, manual_soft_fail_approval=manual_soft_fail_approval)

        is_draft = publish_mode == "draft"
        response: dict[str, object] = {}
        error_message = ""
        target_status = "draft" if is_draft else "public"
        publish_result = "failed"
        try:
            _banned = {
                "머신러닝 및 인공지능", "머신러닝및인공지능", "인공지능",
                "딥러닝", "빅데이터", "IT", "프로그래밍", "경영",
            }
            _raw_labels = package.labels or work_item.labels or []
            labels = normalize_labels([lb for lb in _raw_labels if lb not in _banned])
            meta_description = package.meta_description or work_item.meta_description or ""
            _title = package.final_title or work_item.final_title
            _raw_html = work_item.article_html or package.article_html
            _date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            # FAQ 아이템 추출 (JSON-LD FAQPage용)
            _faq_items = work_item.faq_items if work_item.faq_items else []
            # JSON-LD 삽입 (BlogPosting + FAQPage 복합 구조화 데이터)
            _json_ld = _build_json_ld(
                title=_title,
                date_iso=_date_iso,
                meta_description=meta_description,
                labels=labels,
                faq_items=_faq_items,
            )
            logger.info("JSON-LD 삽입: %s", _json_ld[:200])
            # imageanchor / caption 제거 후 전송
            _clean_html = prepare_blogspot_html(
                improve_image_alt_text(_clean_blogger_html(_raw_html), image_alt_text=_title)
            )
            _article_html = _json_ld + _clean_html
            response = self.blogger_client.publish_post(
                title=_title,
                article_html=_article_html,
                labels=labels,
                meta_description=meta_description,
                is_draft=is_draft,
            )
            publish_result = "published"
        except Exception as exc:  # noqa: BLE001
            error_message = f"{type(exc).__name__}: {exc}"

        self.publish_record_repository.insert(
            PublishRecord(
                publish_id=f"publish-{uuid4().hex[:12]}",
                work_item_id=work_item_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
                publish_mode=publish_mode,
                target_status=target_status,
                publish_result=publish_result,
                blog_url=str(response.get("url") or ""),
                blog_post_id=str(response.get("id") or ""),
                response_json=response,
                error_message=error_message,
            )
        )

        if publish_result != "published":
            work_item.publish_status = PublishStatus.FAILED.value
            work_item.publish_block_reason = error_message or "Blogger publish failed."
            work_item.notes = _append_note(work_item.notes, f"publish failed: {work_item.publish_block_reason}")
            self.work_item_repository.upsert(work_item)
            raise RuntimeError(work_item.publish_block_reason)

        work_item.publish_status = PublishStatus.PUBLISHED.value
        work_item.blog_post_id = str(response.get("id") or "")
        work_item.blog_url = str(response.get("url") or "")
        work_item.publish_block_reason = ""
        work_item.approval_required = False
        work_item.notes = _append_note(
            work_item.notes,
            f"published via blogger mode={publish_mode} status={response.get('status') or target_status}",
        )
        self.work_item_repository.upsert(work_item)

        return PublishOutcome(
            work_item_id=work_item_id,
            publish_result=publish_result,
            publish_mode=publish_mode,
            blog_post_id=work_item.blog_post_id,
            blog_url=work_item.blog_url,
            response_json=response,
            message="Blogger publish completed.",
        )

    def get_publish_status(self, *, work_item_id: str) -> dict[str, object]:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {work_item_id}")
        latest_record = None
        records = self.publish_record_repository.list_for_work_item(work_item_id, limit=1)
        if records:
            latest_record = records[0]
        return {
            "work_item_id": work_item.id,
            "publish_status": work_item.publish_status,
            "blog_post_id": work_item.blog_post_id,
            "blog_url": work_item.blog_url,
            "qa_result": work_item.qa_result,
            "generated_image_status": work_item.generated_image_status,
            "image_error_message": work_item.image_error_message,
            "final_image_url": work_item.final_image_url,
            "publish_block_reason": work_item.publish_block_reason,
            "approval_required": work_item.approval_required,
            "latest_publish_mode": latest_record.publish_mode if latest_record else None,
            "latest_publish_result": latest_record.publish_result if latest_record else None,
            "failure_reason": latest_record.error_message if latest_record else "",
            "notes": work_item.notes,
        }

    def _sanity_check(self, *, work_item_id: str, manual_soft_fail_approval: bool) -> None:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        package = self.content_package_repository.get_by_work_item_id(work_item_id)
        review = self.qa_review_repository.get_by_work_item_id(work_item_id)
        if work_item is None or package is None or review is None:
            raise ValueError("Publish sanity check failed because required records are missing.")
        if review.qa_result == QAResult.SOFT_FAIL.value and not manual_soft_fail_approval:
            raise ValueError("Publish sanity check failed because SOFT_FAIL requires manual approval.")
        if review.qa_result not in {QAResult.PASS.value, QAResult.SOFT_FAIL.value} and not manual_soft_fail_approval:
            raise ValueError(f"Publish sanity check failed because qa_result={review.qa_result}.")
        if work_item.source_count < 3 or work_item.source_quality_status != "sufficient":
            raise ValueError("Publish sanity check failed because source quality is not sufficient.")
        if not (package.final_title or work_item.final_title).strip():
            raise ValueError("Publish sanity check failed because final_title is empty.")
        if len((work_item.article_html or package.article_html).strip()) < 1000:
            raise ValueError("Publish sanity check failed because article_html is too short.")
        if has_unverified_experience_or_income_claim(work_item.article_html or package.article_html):
            raise ValueError("Publish sanity check failed because article_html contains unverified experience or income claims.")
        if not (package.meta_description or work_item.meta_description).strip():
            raise ValueError("Publish sanity check failed because meta_description is empty.")
        if work_item.publish_block_reason and review.qa_result != QAResult.PASS.value and not manual_soft_fail_approval:
            raise ValueError(f"Publish sanity check failed: {work_item.publish_block_reason}")

    def _guard_qa(self, *, work_item_id: str, manual_soft_fail_approval: bool) -> None:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        review = self.qa_review_repository.get_by_work_item_id(work_item_id)
        if work_item is None or review is None:
            raise ValueError("Publish blocked because work item or QA review is missing.")
        if review.qa_result == QAResult.PASS.value:
            work_item.publish_block_reason = ""
            work_item.approval_required = False
            self.work_item_repository.upsert(work_item)
            return
        if review.qa_result == QAResult.SOFT_FAIL.value:
            work_item.approval_required = True
            work_item.publish_block_reason = "SOFT_FAIL requires manual approval in Streamlit UI."
            self.work_item_repository.upsert(work_item)
            if manual_soft_fail_approval:
                return
            raise ValueError("Publish blocked because qa_result=SOFT_FAIL. Manual approval is required.")
        if manual_soft_fail_approval:
            return
        work_item.approval_required = False
        work_item.publish_block_reason = f"Publish blocked because qa_result={review.qa_result}."
        self.work_item_repository.upsert(work_item)
        raise ValueError(f"Publish blocked because qa_result={review.qa_result}. PASS only publishing is enabled.")


def _append_note(existing: str, new_note: str) -> str:
    return new_note if not existing else f"{existing}\n{new_note}"


def _clean_blogger_html(html: str) -> str:
    """Blogger API 전송 전 HTML 후처리: imageanchor 래퍼 및 자동 캡션 제거."""
    # <a imageanchor="1">...</a> → 내부 내용만 유지
    html = re.sub(r'<a[^>]*imageanchor[^>]*>(.*?)</a>', r'\1', html, flags=re.DOTALL)
    # Blogger 자동 caption span 제거
    html = re.sub(r'<span[^>]*class="[^"]*caption[^"]*"[^>]*>.*?</span>', '', html, flags=re.DOTALL)
    return html


def _build_json_ld(
    title: str,
    date_iso: str,
    meta_description: str = "",
    labels: list[str] | None = None,
    faq_items: list[dict[str, str]] | None = None,
) -> str:
    """BlogPosting + FAQPage 복합 JSON-LD 구조화 데이터 <script> 태그 반환."""
    blog_posting: dict[str, object] = {
        "@type": "BlogPosting",
        "headline": title,
        "description": meta_description or title,
        "datePublished": date_iso,
        "dateModified": date_iso,
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
    }
    if labels:
        blog_posting["keywords"] = ", ".join(labels[:10])

    graph: list[dict[str, object]] = [blog_posting]

    # FAQPage 구조화 데이터 (Google FAQ Rich Snippet)
    if faq_items and isinstance(faq_items, list) and len(faq_items) >= 2:
        faq_entities = []
        for item in faq_items:
            q = item.get("question", "").strip()
            a = item.get("answer", "").strip()
            if q and a:
                faq_entities.append({
                    "@type": "Question",
                    "name": q,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": a,
                    },
                })
        if faq_entities:
            graph.append({
                "@type": "FAQPage",
                "mainEntity": faq_entities,
            })

    data = {
        "@context": "https://schema.org",
        "@graph": graph,
    }
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>\n'


def _build_optimal_hashtags(labels: list[str], title: str) -> list[str]:
    """라벨과 제목에서 최적의 해시태그 15~20개를 생성한다."""
    hashtags: list[str] = []
    seen: set[str] = set()

    # 1. 라벨 기반 해시태그
    for lb in labels:
        tag = f"#{lb.replace(' ', '')}"
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            hashtags.append(tag)

    # 2. 고정 인기 해시태그 풀 (AI/부업/생산성 관련)
    _popular = [
        "#AI활용", "#AI부업", "#부업추천", "#온라인부업", "#재택부업",
        "#생산성향상", "#업무자동화", "#AI추천", "#무료AI도구", "#직장인부업",
        "#N잡러", "#수익화", "#프리랜서", "#디지털노마드", "#AI트렌드",
        "#스마트워크", "#자동화도구", "#사이드프로젝트", "#투잡", "#AI리뷰",
    ]
    for tag in _popular:
        key = tag.lower()
        if key not in seen and len(hashtags) < 20:
            seen.add(key)
            hashtags.append(tag)

    # 3. 제목에서 도구명 추출하여 해시태그 추가
    import re as _re
    _tool_match = _re.search(r'[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*', title)
    if _tool_match:
        tool_tag = f"#{_tool_match.group().replace(' ', '')}"
        if tool_tag.lower() not in seen and len(hashtags) < 20:
            hashtags.insert(0, tool_tag)

    return normalize_hashtags(hashtags)
