from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.services import BloggerPackageService
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    BriefRecord,
    BriefRecordRepository,
    ContentPackageRepository,
    ContentPillar,
    SQLiteBlogStore,
    create_sample_work_item,
)


class BlogPackageServiceTests(unittest.TestCase):
    def test_builds_execution_dense_html_package(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            store = SQLiteBlogStore(Path(temp_dir))
            work_repo = BlogWorkItemRepository(store)
            brief_repo = BriefRecordRepository(store)
            package_repo = ContentPackageRepository(store)

            work_item = create_sample_work_item(item_id="pkg-001", content_pillar=ContentPillar.AI_SIDE_HUSTLE)
            work_item.topic_title = "AI 자동화 흐름에서 찾은 AI 부업 실전 적용 포인트"
            work_item.primary_keyword = "AI 자동화"
            work_item.source_urls = [
                "https://news.hankyung.com/article/202603180001",
                "https://www.mk.co.kr/news/it/11223344",
                "https://www.etnews.com/202603180002",
            ]
            work_item.source_articles = [
                {
                    "title": "AI 자동화 툴이 반복 업무 비용을 낮춘다",
                    "summary": "반복 업무 자동화가 부업 운영 비용을 낮춘다는 실전 기사다.",
                    "article_url": "https://news.hankyung.com/article/202603180001",
                },
                {
                    "title": "챗GPT 템플릿 판매, 자동화 검수 체계가 수익 차이를 만든다",
                    "summary": "자동화와 사람 검수를 함께 설계해야 실제 수익화가 가능하다는 내용이다.",
                    "article_url": "https://www.mk.co.kr/news/it/11223344",
                },
                {
                    "title": "생성형 AI 워크플로, 소규모 운영자가 먼저 보는 체크포인트",
                    "summary": "검색 의도와 자동화 적용 범위를 함께 봐야 한다는 기사다.",
                    "article_url": "https://www.etnews.com/202603180002",
                },
            ]
            work_item.title_candidates = [
                "AI 자동화, 지금 안 보면 놓치기 쉬운 문제 3가지",
                "초보도 이해하는 AI 자동화 시작 기준",
                "AI 자동화 바로 실행하려면 오늘 무엇부터 해야 하나",
                "AI 자동화 직접 하기 vs 도구 활용, 어디서 차이가 나는가",
                "AI 자동화 흐름에서 찾은 AI 부업 실전 적용 포인트",
            ]
            work_item.title_candidate_types = ["문제형", "초보형", "실행형", "비교형", "뉴스해설형"]
            work_repo.upsert(work_item)

            brief_repo.upsert(
                BriefRecord(
                    work_item_id="pkg-001",
                    created_at="2026-03-17T00:00:00+00:00",
                    updated_at="2026-03-17T00:00:00+00:00",
                    brief_summary="AI 자동화 이슈를 실행 관점으로 다시 정리한 브리프다.",
                    final_angle="도구 소개가 아니라 실행 기준과 검수 흐름 중심으로 설명한다.",
                    target_reader="본업은 유지하면서 AI 자동화 수익 구조를 작게 검증하고 싶은 직장인",
                    reader_problem="툴은 많지만 실제로 무엇을 팔고 얼마의 시간이 드는지 감이 없다.",
                    search_intent="AI 자동화 부업이 실제로 가능한지 시간·비용·수익 기준을 알고 싶다.",
                    one_line_hook="멋진 자동화보다 오늘 밤 검증할 수 있는 작업 한 개를 고르는 사람이 더 빨리 남긴다.",
                    why_now="최근 기사들이 모두 자동화 적용과 검수 체계를 함께 강조하고 있어 지금 기준을 세우기 좋다.",
                    outline_sections=[
                        "Hero",
                        "한 줄 결론",
                        "이 글이 필요한 사람",
                        "핵심 요약 3~5개",
                        "기사 기반 핵심 사실 정리",
                        "지금 왜 중요한가",
                        "그래서 개인에게 무슨 의미인가",
                        "시작 방법 / 실행 단계",
                        "준비물 / 시간 / 비용 / 예상수익",
                        "추천 대상 / 비추천 대상",
                        "실패 포인트",
                        "실전 체크리스트",
                        "7일 실행 플랜 또는 첫 3단계 액션",
                        "주의사항",
                        "FAQ",
                        "CTA",
                        "출처 / 업데이트",
                    ],
                    key_takeaways=["핵심 1", "핵심 2", "핵심 3", "핵심 4"],
                    facts_from_sources=["기사 요약 1", "기사 요약 2", "기사 요약 3"],
                    hard_facts_from_sources=["사실 1", "사실 2", "사실 3", "사실 4"],
                    source_consensus=["공통점 1", "공통점 2"],
                    source_differences=["차이점 1"],
                    what_it_means_to_reader=["의미 1", "의미 2"],
                    cautions=["주의 1", "주의 2"],
                    practical_actions=["실행 1", "실행 2", "실행 3"],
                    estimated_time_to_start="첫 세팅 3~4시간, 이후 하루 40~90분",
                    estimated_cost_to_start="월 0원~7만원",
                    potential_income_range="월 10만~100만원",
                    difficulty_level="중상",
                    recommended_for=["추천 1", "추천 2"],
                    not_recommended_for=["비추천 1", "비추천 2"],
                    failure_points=["실패 1", "실패 2", "실패 3"],
                    monetization_block_idea="도구 비용과 검수 시간을 같이 비교한다.",
                    faq_candidates=["질문 1", "질문 2"],
                    faq_items=[
                        {"question": "진짜 초보도 가능한가?", "answer": "작게 시작하면 가능하다."},
                        {"question": "하루 몇 시간 필요한가?", "answer": "하루 40~90분 정도를 잡는 편이 낫다."},
                        {"question": "언제 수익이 나나?", "answer": "먼저 검증이 필요하다."},
                    ],
                    evidence_points=["증거 1", "증거 2"],
                    cta_direction="오늘은 자동화할 작업 한 개만 정하고, 다음 글에서 검수 기준까지 이어서 본다.",
                    cta_type="action_plan",
                    content_density_status="dense",
                )
            )

            service = BloggerPackageService(
                work_item_repository=work_repo,
                brief_repository=brief_repo,
                content_package_repository=package_repo,
            )
            result = service.build_package(work_item_id="pkg-001")

            self.assertEqual(len(result.title_candidates), 5)
            self.assertIn("한 줄 결론", result.article_html)
            self.assertIn("이 글이 필요한 사람", result.article_html)
            self.assertIn("기사 기반 핵심 사실 정리", result.article_html)
            self.assertIn("준비물 / 시간 / 비용 / 예상수익", result.article_html)
            self.assertIn("실패 포인트", result.article_html)
            self.assertIn("실전 체크리스트", result.article_html)
            self.assertIn("7일 실행 플랜 또는 첫 3단계 액션", result.article_html)
            self.assertIn("CTA", result.article_html)
            self.assertIn("출처 / 업데이트", result.article_html)
            self.assertIn("@graph", str(result.json_ld))
            saved = package_repo.get_by_work_item_id("pkg-001")
            self.assertIsNotNone(saved)
            self.assertTrue(saved.article_preview_html.startswith("<!doctype html>"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
