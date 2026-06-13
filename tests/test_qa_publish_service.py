from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config import Settings
from blogspot_automation.services import BlogQualityAssuranceService, BloggerPublishService
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    BriefRecord,
    BriefRecordRepository,
    ContentPackageRecord,
    ContentPackageRepository,
    ContentPillar,
    PublishRecordRepository,
    PublishStatus,
    QAReviewRepository,
    SQLiteBlogStore,
    create_sample_work_item,
)


class QAPublishServiceTests(unittest.TestCase):
    def test_qa_review_passes_publishable_article(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            services = _build_services(Path(temp_dir))
            _seed_publish_ready_content(services, work_item_id="qa-pass-001")

            result = services["qa"].qa_review(work_item_id="qa-pass-001")

            self.assertEqual(result.qa_result, "PASS")
            self.assertGreaterEqual(result.qa_score, 92)
            loaded = services["work_repo"].get_by_id("qa-pass-001")
            self.assertEqual(loaded.publish_block_reason, "")
            self.assertFalse(loaded.approval_required)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_fail_blocks_publish_for_placeholder_source(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            services = _build_services(Path(temp_dir))
            _seed_publish_ready_content(
                services,
                work_item_id="qa-fail-001",
                source_urls=["https://example.com/source-1", "https://news.hankyung.com/real"],
            )

            review = services["qa"].qa_review(work_item_id="qa-fail-001")
            self.assertEqual(review.qa_result, "FAIL")
            with self.assertRaisesRegex(ValueError, "PASS only publishing"):
                services["publish"].publish(work_item_id="qa-fail-001")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_soft_fail_requires_manual_approval_before_publish(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            services = _build_services(Path(temp_dir))
            _seed_publish_ready_content(
                services,
                work_item_id="qa-soft-001",
                image_status="generated",
                final_image_url="https://invalid.examplecdn.test/not-found.png",
            )

            review = services["qa"].qa_review(work_item_id="qa-soft-001")
            self.assertEqual(review.qa_result, "SOFT_FAIL")

            with self.assertRaisesRegex(ValueError, "SOFT_FAIL"):
                services["publish"].publish(work_item_id="qa-soft-001")

            outcome = services["publish"].publish(
                work_item_id="qa-soft-001",
                manual_soft_fail_approval=True,
            )
            self.assertEqual(outcome.publish_result, "published")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_publish_success_saves_sqlite_result(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            services = _build_services(Path(temp_dir), blogger_client=_FakeBloggerClient())
            _seed_publish_ready_content(services, work_item_id="pub-001")
            review = services["qa"].qa_review(work_item_id="pub-001")
            self.assertEqual(review.qa_result, "PASS")

            outcome = services["publish"].publish(work_item_id="pub-001", publish_mode="public")
            status = services["publish"].get_publish_status(work_item_id="pub-001")

            self.assertEqual(outcome.blog_post_id, "blogger-post-001")
            self.assertEqual(status["publish_status"], PublishStatus.PUBLISHED.value)
            self.assertEqual(len(services["publish_repo"].list_for_work_item("pub-001")), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class _FakeBloggerClient:
    def publish_post(
        self,
        *,
        title: str,
        article_html: str,
        labels: list[str],
        meta_description: str = "",
        permalink_slug: str = "",
        is_draft: bool = False,
    ) -> dict[str, object]:
        del title, article_html, labels, meta_description, permalink_slug, is_draft
        return {
            "id": "blogger-post-001",
            "url": "https://example.blogspot.com/2026/03/post.html",
            "status": "LIVE",
            "title": "발행 제목",
        }


def _build_services(temp_path: Path, blogger_client: _FakeBloggerClient | None = None) -> dict[str, object]:
    store = SQLiteBlogStore(temp_path)
    work_repo = BlogWorkItemRepository(store)
    brief_repo = BriefRecordRepository(store)
    package_repo = ContentPackageRepository(store)
    qa_repo = QAReviewRepository(store)
    publish_repo = PublishRecordRepository(store)
    qa_service = BlogQualityAssuranceService(
        work_item_repository=work_repo,
        brief_repository=brief_repo,
        content_package_repository=package_repo,
        qa_review_repository=qa_repo,
    )
    publish_service = BloggerPublishService(
        work_item_repository=work_repo,
        content_package_repository=package_repo,
        qa_review_repository=qa_repo,
        publish_record_repository=publish_repo,
        settings=Settings(data_dir=temp_path, sqlite_path="data/test.db"),
        blogger_client=blogger_client or _FakeBloggerClient(),
    )
    return {
        "work_repo": work_repo,
        "brief_repo": brief_repo,
        "package_repo": package_repo,
        "qa_repo": qa_repo,
        "publish_repo": publish_repo,
        "qa": qa_service,
        "publish": publish_service,
    }


def _seed_publish_ready_content(
    services: dict[str, object],
    *,
    work_item_id: str,
    source_urls: list[str] | None = None,
    image_status: str = "fallback_branding_image",
    final_image_url: str = "",
) -> None:
    work_repo: BlogWorkItemRepository = services["work_repo"]  # type: ignore[assignment]
    brief_repo: BriefRecordRepository = services["brief_repo"]  # type: ignore[assignment]
    package_repo: ContentPackageRepository = services["package_repo"]  # type: ignore[assignment]

    urls = source_urls or [
        "https://news.hankyung.com/article/202603180001",
        "https://www.mk.co.kr/news/it/11223344",
        "https://www.etnews.com/202603180002",
    ]
    work_item = create_sample_work_item(item_id=work_item_id, content_pillar=ContentPillar.AI_SIDE_HUSTLE)
    work_item.publish_status = PublishStatus.GENERATED.value
    work_item.final_title = "초보도 이해하는 AI 부업 시작 기준"
    work_item.meta_description = "시간, 비용, 수익 범위와 실패 포인트까지 포함한 실행형 가이드"
    work_item.source_urls = urls
    work_item.source_articles = [
        {"article_url": urls[0], "title": "기사 1", "summary": "요약 1"},
        {"article_url": urls[1], "title": "기사 2", "summary": "요약 2"},
        {"article_url": urls[2] if len(urls) > 2 else urls[-1], "title": "기사 3", "summary": "요약 3"},
    ]
    work_item.source_count = len(work_item.source_articles)
    work_item.source_quality_status = "sufficient"
    work_item.generated_image_status = image_status
    work_item.final_image_url = final_image_url
    work_item.content_density_status = "dense"
    work_item.title_candidates = ["a1", "a2", "a3", "a4", "a5"]
    work_item.article_html = _build_article_html()
    work_repo.upsert(work_item)

    brief_repo.upsert(
        BriefRecord(
            work_item_id=work_item_id,
            created_at="2026-03-17T00:00:00+00:00",
            updated_at="2026-03-17T00:00:00+00:00",
            brief_summary="실제 실행 기준을 담은 브리프입니다.",
            final_angle="도구 소개보다 실행 기준과 실패 포인트 중심 설명입니다.",
            target_reader="퇴근 후 1시간 안에서 검증하고 싶은 직장인",
            reader_problem="무엇부터 시작할지 모르고 시간 낭비가 두렵다.",
            search_intent="시간과 비용 대비 현실성을 알고 싶다.",
            one_line_hook="멋진 자동화보다 오늘 밤 검증할 한 단계가 중요하다.",
            why_now="여러 기사에서 같은 실행 조건을 다뤄 기준을 잡기 좋다.",
            outline_sections=["한 줄 결론", "기사 기반 핵심 사실 정리", "FAQ", "CTA"],
            key_takeaways=["요약 1", "요약 2", "요약 3"],
            facts_from_sources=["사실 1", "사실 2", "사실 3"],
            hard_facts_from_sources=["하드 사실 1", "하드 사실 2", "하드 사실 3", "하드 사실 4"],
            source_consensus=["공통 1", "공통 2"],
            source_differences=["차이 1"],
            what_it_means_to_reader=["의미 1", "의미 2"],
            cautions=["주의 1", "주의 2"],
            practical_actions=["실행 1", "실행 2", "실행 3"],
            estimated_time_to_start="첫 세팅 3시간, 이후 하루 40분",
            estimated_cost_to_start="월 0원~5만원",
            potential_income_range="월 10만~50만원",
            difficulty_level="중간",
            recommended_for=["추천 1"],
            not_recommended_for=["비추천 1"],
            failure_points=["실패 1", "실패 2", "실패 3"],
            monetization_block_idea="수익 구조와 비용 구조를 함께 본다.",
            faq_candidates=["질문 1", "질문 2"],
            faq_items=[
                {"question": "진짜 초보도 가능한가?", "answer": "가능하지만 첫 주는 자동화보다 검수와 기록 습관을 먼저 만드는 편이 안전합니다."},
                {"question": "하루 몇 시간 필요한가?", "answer": "하루 40분 정도를 잡고 실제로 가능한지 1주일만 먼저 측정하는 편이 현실적입니다."},
                {"question": "언제 돈을 버나?", "answer": "바로 수익을 기대하기보다 먼저 반응과 재작업 시간을 확인한 뒤 작게 시작해야 합니다."},
                {"question": "과장 아닌가?", "answer": "그래서 출처 없는 수치나 확정 수익 문구를 빼고 실제 기사와 조건만 남겼습니다."},
                {"question": "누가 하면 안 되나?", "answer": "즉시 고수익만 기대하거나 검수 없이 자동화 결과를 바로 내보낼 사람에게는 맞지 않습니다."},
            ],
            evidence_points=["증거 1", "증거 2"],
            cta_direction="오늘 할 1단계는 자동화할 작업 한 개를 정하는 것입니다.",
            cta_type="action_plan",
            content_density_status="dense",
        )
    )
    package_repo.upsert(
        ContentPackageRecord(
            work_item_id=work_item_id,
            created_at="2026-03-17T00:00:00+00:00",
            updated_at="2026-03-17T00:00:00+00:00",
            title_candidates=work_item.title_candidates,
            final_title=work_item.final_title,
            meta_description=work_item.meta_description,
            labels=["AI 부업", "자동화"],
            hashtags=["#AI부업", "#자동화"],
            image_prompt="editorial cover",
            article_html=work_item.article_html,
            article_preview_html="<!doctype html><html></html>",
            json_ld={"@graph": []},
        )
    )


def _build_article_html() -> str:
    body = " ".join(["실행 정보 문장"] * 300)
    return (
        "<article>"
        "<section><h2>한 줄 결론</h2><p>오늘 할 일부터 정하는 사람이 오래 갑니다.</p></section>"
        "<section><h2>기사 기반 핵심 사실 정리</h2><p>사실 1</p><p>사실 2</p></section>"
        "<section><h2>준비물 / 시간 / 비용 / 예상수익</h2><p>시간 3시간, 비용 월 0~5만원, 수익 월 10만~50만원</p></section>"
        "<section><h2>실패 포인트</h2><p>실패 1</p><p>실패 2</p><p>실패 3</p></section>"
        "<section><h2>실전 체크리스트</h2><p>체크 1</p><p>체크 2</p></section>"
        "<section><h2>FAQ</h2><h3>질문1</h3><p>답변1 충분히 깁니다.</p><h3>질문2</h3><p>답변2 충분히 깁니다.</p>"
        "<h3>질문3</h3><p>답변3 충분히 깁니다.</p><h3>질문4</h3><p>답변4 충분히 깁니다.</p>"
        "<h3>질문5</h3><p>답변5 충분히 깁니다.</p></section>"
        "<section><h2>CTA</h2><p>오늘은 자동화할 작업 한 개만 정하고 기록합니다.</p></section>"
        "<section><h2>출처 / 업데이트</h2><ul><li>https://news.hankyung.com/article/202603180001</li><li>https://www.mk.co.kr/news/it/11223344</li><li>https://www.etnews.com/202603180002</li></ul></section>"
        "<br><br><br><br><br><br><br><br><br><br>"
        f"<p>{body}</p>"
        "</article>"
    )


if __name__ == "__main__":
    unittest.main()
