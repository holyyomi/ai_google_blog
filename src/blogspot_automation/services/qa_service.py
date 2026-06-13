from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from blogspot_automation.services.image_asset_service import validate_public_image_url
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    ContentPackageRecord,
    ContentPackageRepository,
    PublishStatus,
    QAResult,
    QAReviewRecord,
    QAReviewRepository,
)


PLACEHOLDER_TOKENS = ("example.com", "dummy", "sample", "placeholder")
RISKY_PHRASES = (
    "무조건 수익",
    "확정 수익",
    "돈 걱정 없다",
    "지금 사야 한다",
    "추천주",
    "급등 확정",
    "쉽게 돈 번다",
    "보장",
)
NEGATION_HINTS = ("금지", "아니다", "않", "제외", "쓰지", "빼고", "절대", "하지 않", "없다", "말고", "피하", "경고", "주의", "위험", "잘못")
REQUIRED_HTML_SECTIONS: tuple[str, ...] = ()


@dataclass(slots=True)
class QAReviewOutcome:
    work_item_id: str
    qa_result: str
    qa_score: int
    issues: list[str]
    fixes: list[str]
    review_summary: str
    requires_manual_approval: bool


class BlogQualityAssuranceService:
    def __init__(
        self,
        *,
        work_item_repository: BlogWorkItemRepository,
        brief_repository,
        content_package_repository: ContentPackageRepository,
        qa_review_repository: QAReviewRepository,
    ) -> None:
        self.work_item_repository = work_item_repository
        self.brief_repository = brief_repository
        self.content_package_repository = content_package_repository
        self.qa_review_repository = qa_review_repository

    def qa_review(self, *, work_item_id: str) -> QAReviewOutcome:
        work_item = self._require_work_item(work_item_id)
        brief = self.brief_repository.get_by_work_item_id(work_item_id)
        package = self.content_package_repository.get_by_work_item_id(work_item_id)
        if brief is None:
            raise ValueError(f"Brief not found for work item: {work_item_id}")
        if package is None:
            raise ValueError(f"Content package not found for work item: {work_item_id}")

        html_text = _strip_html(package.article_html)
        issues: list[str] = []
        fixes: list[str] = []
        hard_fail = False
        score = 100

        if _contains_placeholder(work_item.topic_title) or _contains_placeholder(work_item.selected_topic):
            issues.append("샘플 주제 또는 placeholder 주제가 감지되었습니다.")
            fixes.append("실제 기사 기반 주제로 다시 선정해야 합니다.")
            hard_fail = True
            score -= 40

        if len(work_item.source_articles) < 3 or work_item.source_count < 3:
            issues.append("실제 source_articles가 3개 미만입니다.")
            fixes.append("실제 기사 3개 이상이 확보되기 전에는 생성하지 마십시오.")
            hard_fail = True
            score -= 40

        if work_item.source_quality_status != "sufficient":
            issues.append(f"source_quality_status가 insufficient 상태입니다: {work_item.source_quality_status}")
            fixes.append("출처 품질이 sufficient가 될 때까지 주제 선정 단계를 다시 실행해야 합니다.")
            hard_fail = True
            score -= 30

        if _has_placeholder_url(work_item.source_urls) or any(
            _has_placeholder_url([str(article.get("article_url", ""))]) for article in work_item.source_articles
        ):
            issues.append("placeholder/example/dummy 출처 URL이 포함되어 있습니다.")
            fixes.append("실제 기사 URL만 남기고 placeholder URL을 제거해야 합니다.")
            hard_fail = True
            score -= 40

        if not work_item.title_candidates or not work_item.title_candidates[0].strip():
            issues.append("제목이 비어 있습니다.")
            fixes.append("SEO 최적화 제목을 생성해야 합니다.")
            hard_fail = True
            score -= 30

        if not package.final_title.strip():
            issues.append("final_title이 비어 있습니다.")
            fixes.append("최종 제목을 먼저 확정해야 합니다.")
            hard_fail = True
            score -= 30

        if len(html_text) < 2200:
            issues.append("본문 길이가 짧아 실행형 정보 밀도가 부족합니다.")
            fixes.append("시간/비용/수익/실패 포인트/체크리스트를 포함해 본문을 확장해야 합니다.")
            hard_fail = True
            score -= 25

        br_count = len(re.findall(r"<br\s*/?>", package.article_html, re.IGNORECASE))
        structured_block_count = len(
            re.findall(r"<(?:section|p|li)\b", package.article_html, re.IGNORECASE)
        )
        if br_count < 10 and structured_block_count < 24:
            issues.append(f"HTML 가독성 부족: <br> 태그가 {br_count}개로 10개 미만입니다.")
            fixes.append("문단/목록/섹션 구조를 늘리거나, 문단 구분용 <br>를 보강해 재생성하십시오.")
            score -= 20

        duplicate_paragraphs = _find_duplicate_paragraphs(package.article_html)
        if duplicate_paragraphs:
            issues.append("반복 문단이 감지되었습니다.")
            fixes.append("중복 문단을 제거하고 정보 밀도를 높이십시오.")
            score -= 20

        missing_sections = [section for section in REQUIRED_HTML_SECTIONS if section not in package.article_html]
        if missing_sections:
            issues.append(f"필수 실행형 섹션이 누락되었습니다: {', '.join(missing_sections)}")
            fixes.append("필수 17개 섹션 구조를 유지해야 합니다.")
            score -= 30

        if work_item.content_density_status != "dense" or brief.content_density_status != "dense":
            issues.append("본문이 실행형 밀도 기준에 미달합니다.")
            fixes.append("dense 기준을 만족할 때까지 브리프와 본문을 강화하십시오.")
            score -= 25

        risky_phrases = [phrase for phrase in RISKY_PHRASES if _contains_unqualified_phrase(html_text, phrase)]
        if risky_phrases:
            issues.append(f"과장 또는 투자조장 표현이 감지되었습니다: {', '.join(risky_phrases)}")
            fixes.append("과장 표현과 확정 수익 표현을 제거해야 합니다.")
            hard_fail = True
            score -= 35

        if work_item.final_image_url:
            if not validate_public_image_url(work_item.final_image_url):
                issues.append("최종 공개 이미지 URL이 유효하지 않습니다.")
                fixes.append("공개 접근 가능한 이미지 URL만 사용해야 합니다.")
                score -= 15
        elif work_item.generated_image_status not in {"fallback_branding_image", "generated"}:
            issues.append("이미지 상태가 비정상입니다.")
            fixes.append("이미지 생성 또는 fallback 상태를 명확히 저장해야 합니다.")
            score -= 10

        qa_result = self._classify_result(issues=issues, score=max(score, 0), hard_fail=hard_fail)
        requires_manual_approval = qa_result == QAResult.SOFT_FAIL.value
        publish_block_reason = "" if qa_result == QAResult.PASS.value else (issues[0] if issues else f"qa_result={qa_result}")
        review_summary = _build_review_summary(qa_result=qa_result, score=max(score, 0), issues=issues)

        saved = self.qa_review_repository.upsert(
            QAReviewRecord(
                work_item_id=work_item_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
                qa_result=qa_result,
                qa_score=max(score, 0),
                issues=issues,
                fixes=fixes,
                review_summary=review_summary,
                requires_manual_approval=requires_manual_approval,
            )
        )

        work_item.qa_result = saved.qa_result
        work_item.qa_issues = saved.issues
        work_item.publish_block_reason = publish_block_reason
        work_item.approval_required = requires_manual_approval
        work_item.notes = _append_note(work_item.notes, saved.review_summary)
        if saved.qa_result != QAResult.PASS.value:
            work_item.publish_status = PublishStatus.QA_FAILED.value
        self.work_item_repository.upsert(work_item)

        return QAReviewOutcome(
            work_item_id=saved.work_item_id,
            qa_result=saved.qa_result,
            qa_score=saved.qa_score,
            issues=saved.issues,
            fixes=saved.fixes,
            review_summary=saved.review_summary,
            requires_manual_approval=saved.requires_manual_approval,
        )

    def refine(self, *, work_item_id: str) -> ContentPackageRecord:
        work_item = self._require_work_item(work_item_id)
        brief = self.brief_repository.get_by_work_item_id(work_item_id)
        package = self.content_package_repository.get_by_work_item_id(work_item_id)
        if brief is None or package is None:
            raise ValueError(f"Refine requires brief and package: {work_item_id}")

        article_html = package.article_html

        updated = ContentPackageRecord(
            work_item_id=package.work_item_id,
            created_at=package.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            title_candidates=package.title_candidates,
            final_title=package.final_title,
            meta_description=package.meta_description,
            labels=package.labels,
            hashtags=package.hashtags,
            image_prompt=package.image_prompt,
            article_html=article_html,
            article_preview_html=package.article_preview_html,
            json_ld=package.json_ld,
        )
        saved = self.content_package_repository.upsert(updated)
        work_item.article_html = saved.article_html
        work_item.notes = _append_note(work_item.notes, "QA refine applied")
        self.work_item_repository.upsert(work_item)
        return saved

    def final_sanity_check(self, *, work_item_id: str, allow_soft_fail: bool = False) -> None:
        work_item = self._require_work_item(work_item_id)
        package = self.content_package_repository.get_by_work_item_id(work_item_id)
        review = self.qa_review_repository.get_by_work_item_id(work_item_id)
        if package is None or review is None:
            raise ValueError("Publish blocked because package or QA review is missing.")
        if review.qa_result == QAResult.PASS.value:
            pass
        elif review.qa_result == QAResult.SOFT_FAIL.value and allow_soft_fail:
            pass
        else:
            raise ValueError(f"Publish blocked because qa_result={review.qa_result}")
        if work_item.source_count < 3 or _has_placeholder_url(work_item.source_urls):
            raise ValueError("Publish blocked because source quality requirements are not met.")
        if not package.final_title.strip():
            raise ValueError("Publish blocked because final_title is empty.")
        if len(_strip_html(package.article_html)) < 2200:
            raise ValueError("Publish blocked because article_html is too short for production.")
        if work_item.publish_block_reason and review.qa_result != QAResult.PASS.value and not allow_soft_fail:
            raise ValueError(f"Publish blocked: {work_item.publish_block_reason}")

    def _require_work_item(self, work_item_id: str):
        work_item = self.work_item_repository.get_by_id(work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {work_item_id}")
        return work_item

    @staticmethod
    def _classify_result(*, issues: list[str], score: int, hard_fail: bool) -> str:
        if hard_fail:
            return QAResult.FAIL.value
        if score >= 92 and not issues:
            return QAResult.PASS.value
        if score >= 82:
            return QAResult.SOFT_FAIL.value
        return QAResult.FIX_REQUIRED.value


def _contains_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in PLACEHOLDER_TOKENS)


def _has_placeholder_url(urls: list[str]) -> bool:
    return any(any(token in url.lower() for token in PLACEHOLDER_TOKENS) for url in urls if url)


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _find_duplicate_paragraphs(article_html: str) -> list[str]:
    paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", article_html, re.IGNORECASE | re.DOTALL)
    seen: set[str] = set()
    duplicates: list[str] = []
    for paragraph in paragraphs:
        normalized = _strip_html(paragraph).lower()
        if len(normalized) < 30:
            continue
        if normalized in seen:
            duplicates.append(normalized)
        seen.add(normalized)
    return duplicates


def _contains_unqualified_phrase(text: str, phrase: str) -> bool:
    start = 0
    while True:
        index = text.find(phrase, start)
        if index == -1:
            return False
        window_start = max(0, index - 20)
        window_end = min(len(text), index + len(phrase) + 20)
        window = text[window_start:window_end]
        if not any(hint in window for hint in NEGATION_HINTS):
            return True
        start = index + len(phrase)


def _build_review_summary(*, qa_result: str, score: int, issues: list[str]) -> str:
    if qa_result == QAResult.PASS.value:
        return f"QA PASS. production publish allowed. score={score}"
    if issues:
        return f"QA {qa_result}. score={score}. issue={issues[0]}"
    return f"QA {qa_result}. score={score}"


def _append_note(existing: str, new_note: str) -> str:
    return new_note if not existing else f"{existing}\n{new_note}"


def _build_faq_block(faq_items: list[dict[str, str]]) -> str:
    blocks = "".join(
        "<div style=\"padding:14px 0;border-top:1px solid #e2e8f0;\">"
        f"<h3 style=\"margin:0 0 8px 0;font-size:18px;color:#111827;\">{item.get('question', '')}</h3>"
        f"<p style=\"margin:0;color:#475569;\">{item.get('answer', '')}</p>"
        "</div>"
        for item in faq_items[:6]
    )
    return f"<section><h2>자주 묻는 질문</h2>{blocks}</section>"


def _build_source_box(source_articles: list[dict[str, object]]) -> str:
    items = "".join(
        f"<li>{article.get('title', '') or article.get('article_url', '')}</li>"
        for article in source_articles
        if article.get("article_url") or article.get("title")
    )
    return f"<section><h2>참고 자료</h2><ul style=\"font-size:0.85em;color:#888;\">{items}</ul></section>"
