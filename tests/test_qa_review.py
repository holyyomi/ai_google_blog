from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.content_generation.service import refine_content
from blogspot_automation.models import ScoreBreakdown, TopicCandidate, TopicCandidateStatus
from blogspot_automation.qa.service import review_article_package
from blogspot_automation.storage import StateStore


class FakeRefineClient:
    def __init__(self) -> None:
        self._responses = [
            json.dumps(
                {
                    "title_candidates": ["개선 제목 1", "개선 제목 2"],
                    "meta_description": "개선된 메타 설명",
                    "excerpt": "이 글은 개선된 구조로 핵심을 빠르게 설명합니다.",
                    "intro_paragraph": "이 주제는 실제 자동화 워크플로에 영향을 주는 변화입니다. 핵심은 무엇이 바뀌었는지와 어떻게 적용할지입니다. 따라서 독자는 기능보다 적용 조건을 먼저 확인해야 합니다.",
                    "article_outline": ["정의", "왜 중요한가", "실무 체크"],
                    "key_takeaways": ["핵심 1", "핵심 2", "핵심 3"],
                    "article_sections": [
                        {
                            "heading": "정의",
                            "level": "h2",
                            "purpose": "주제를 짧게 정의한다.",
                            "paragraphs": ["개선된 문단 1", "개선된 문단 2"],
                            "bullets": ["정의 항목"]
                        }
                    ],
                    "practical_checklist": {
                        "heading": "실무 체크리스트",
                        "items": ["체크 1", "체크 2"]
                    },
                    "faq_items": [
                        {"question": "무엇인가요?", "answer": "개선된 답변입니다."},
                        {"question": "왜 중요한가요?", "answer": "실무 연결성이 높기 때문입니다."}
                    ],
                    "labels": ["AI", "Automation"],
                    "hashtags": ["#AI", "#Automation"],
                    "internal_links": [
                        {"anchor_text": "워크플로 가이드", "target_slug": "workflow-guide", "reason": "관련 문서"}
                    ],
                    "external_citation_placeholders": [
                        {"label": "공식 소스", "source_url": "https://example.com/source"}
                    ],
                    "author_note": "개선된 메모",
                    "conclusion": "이제 적용 조건을 기준으로 판단하면 됩니다.",
                    "cta_text": "작은 테스트부터 시작하세요.",
                    "image_prompt": "Editorial AI cover, clean, minimal, no text",
                    "alt_text_candidates": ["개선된 대체 텍스트"]
                },
                ensure_ascii=False,
            ),
            json.dumps({"final_title": "개선된 최종 제목", "reason": "명확성 향상"}, ensure_ascii=False),
        ]

    def create_chat_completion(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return self._responses.pop(0)


class QAReviewTests(unittest.TestCase):
    def test_qa_review_rejects_weak_content_with_fix_required(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate("topic-qa")])
            _seed_weak_article(store, "topic-qa")

            result = review_article_package(topic_id="topic-qa", store=store)

            self.assertEqual(result.qa_result, "FIX_REQUIRED")
            self.assertGreater(len(result.issues), 0)
            self.assertIsNotNone(result.revision_payload_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_refine_content_updates_blog_package_after_fix_required(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate("topic-refine")])
            _seed_weak_article(store, "topic-refine")
            review_article_package(topic_id="topic-refine", store=store)

            result = refine_content(
                topic_id="topic-refine",
                store=store,
                settings=settings,
                client=FakeRefineClient(),
            )

            payload = store.load_blog_package("topic-refine")
            self.assertEqual(result.topic_id, "topic-refine")
            self.assertEqual(payload["blog_package"]["final_title"], "개선된 최종 제목")
            self.assertIn("article_markdown", payload["blog_package"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _seed_weak_article(store: StateStore, topic_id: str) -> None:
    output_dir = store.topic_output_dir(topic_id)
    topic_data = {
        "topic_id": topic_id,
        "ai_name": "OpenAI",
        "topic_name": "Weak Topic",
        "topic_type": "developer_update",
        "topic_angle": "Explain usage.",
        "keyword_primary": "OpenAI",
        "keyword_secondary": ["workflow"],
        "topic_cluster": "automation_workflows",
        "topic_subcluster": "agent_workflows",
        "main_keyword": "workflow update",
        "geo_targeting_hint": "Global first",
        "age_targeting_hint": "Answer engine friendly",
        "monetization_angle": "Automation consulting",
        "automation_angle": "Repeatable workflows",
        "source_name": "OpenAI Blog",
        "source_type": "rss",
        "source_url": "https://example.com/source",
        "source_published_at": "2026-03-17T00:00:00+00:00",
        "selected_reason": "Selected",
    }
    fact_pack = {
        "topic_id": topic_id,
        "topic_data": topic_data,
        "source_pack": {"source_urls": ["https://example.com/source"]},
        "fact_pack": {
            "what_it_is": "Weak topic description",
            "why_it_matters": "Weak topic relevance",
            "who_it_is_for": "Beginners",
            "key_points": ["One point", "Two points"],
            "constraints": ["Do not invent pricing"],
            "risks": ["Do not overclaim"],
            "examples": ["One example"],
            "source_urls": ["https://example.com/source"],
            "unsupported_claims_to_avoid": ["Unverified pricing claims"],
        },
    }
    brief = {
        "run_id": "brief-1",
        "angle": "weak angle",
        "objective": "weak objective",
        "key_points": ["one"],
        "recommended_readers": ["reader"],
        "automation_opportunities": ["automation"],
        "monetization_opportunities": ["monetization"],
        "search_intent": "intent",
    }
    weak_blog_package = {
        "package_id": f"package-{topic_id}",
        "topic_id": topic_id,
        "topic_data": topic_data,
        "fact_pack": fact_pack,
        "brief": brief,
        "ai_name": "OpenAI",
        "topic_name": "Weak Topic",
        "topic_type": "developer_update",
        "topic_angle": "Explain usage.",
        "keyword_primary": "OpenAI",
        "keyword_secondary": ["workflow"],
        "source_name": "OpenAI Blog",
        "source_type": "rss",
        "source_url": "https://example.com/source",
        "source_published_at": "2026-03-17T00:00:00+00:00",
        "title_candidates": ["약한 제목"],
        "final_title": "Workflow Update 정리",
        "slug": "workflow-update-summary",
        "meta_description": "워크플로 업데이트를 간단히 정리한 글입니다.",
        "excerpt": "짧은 요약",
        "intro_paragraph": "이 글은 워크플로 업데이트를 간단히 정리합니다. 다만 적용 조건은 더 확인해야 합니다.",
        "article_outline": ["개요"],
        "article_body": {
            "key_takeaways": ["하나", "둘", "셋"],
            "article_sections": [
                {"heading": "요약", "level": "h2", "purpose": "설명", "paragraphs": ["이 업데이트는 워크플로 연결 방식에 영향을 줄 수 있습니다."], "bullets": []}
            ],
            "practical_checklist": {"heading": "체크", "items": ["항목 하나"]},
            "conclusion": "끝",
        },
        "labels": ["AI"],
        "hashtags": ["#AI"],
        "faq_items": [{"question": "무엇인가요?", "answer": "업데이트 정리입니다."}],
        "internal_links": [],
        "external_sources": [{"label": "공식 소스", "source_url": "https://example.com/source"}],
        "author_note": "메모",
        "update_date": "2026-03-17",
        "cta_text": "행동",
        "content_sections": [
            {"heading": "요약", "level": "h2", "purpose": "설명", "paragraphs": ["이 업데이트는 워크플로 연결 방식에 영향을 줄 수 있습니다."], "bullets": []}
        ],
        "cover_image_prompt": "prompt",
        "image_prompt": "prompt",
        "image_alt": ["워크플로 업데이트 이미지"],
        "article_html": "<article><p>혁신적인 혁신적인 혁신적인 업데이트입니다.</p></article>",
        "article_markdown": "혁신적인 혁신적인 혁신적인 업데이트입니다.",
        "json_ld_inputs": {},
        "json_ld": {},
        "image_assets": {},
        "status": "generated"
    }
    (output_dir / "brief.json").write_text(json.dumps({"topic_data": topic_data, "fact_pack": fact_pack, "brief": brief}, ensure_ascii=False), encoding="utf-8")
    (output_dir / "blog_package.json").write_text(json.dumps({"topic_data": topic_data, "fact_pack": fact_pack, "brief": brief, "blog_package": weak_blog_package}, ensure_ascii=False), encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps({"final_title": "약한 제목"}, ensure_ascii=False), encoding="utf-8")
    store.save_fact_pack(topic_id, fact_pack)


def _sample_topic_candidate(topic_id: str) -> TopicCandidate:
    return TopicCandidate(
        run_id="discover-20260317T000000Z",
        topic_id=topic_id,
        created_at="2026-03-17T00:00:00+00:00",
        ai_name="OpenAI",
        topic_name="Weak Topic",
        topic_type="developer_update",
        topic_angle="Explain usage.",
        keyword_primary="OpenAI",
        keyword_secondary=["workflow"],
        topic_cluster="automation_workflows",
        topic_subcluster="agent_workflows",
        content_mode="news_explainer",
        main_keyword="workflow update",
        supporting_keywords=["workflow"],
        user_intent="how_to",
        audience_level="beginner_to_intermediate",
        geo_targeting_hint="Global first",
        age_targeting_hint="Answer engine friendly",
        search_angle="Explain the workflow update",
        monetization_angle="Automation consulting",
        automation_angle="Repeatable workflows",
        source_name="OpenAI Blog",
        source_type="rss",
        source_url="https://example.com/source",
        source_published_at="2026-03-17T00:00:00+00:00",
        candidate_title="Weak topic title",
        candidate_summary="Weak summary",
        trend_score=0.7,
        score_breakdown=ScoreBreakdown(0.8, 0.6, 0.7, 0.4, 0.6, 0.5, 0.68),
        duplicate_key=f"{topic_id}-dup",
        selected_reason="Selected.",
        status=TopicCandidateStatus.PLANNED,
    )


if __name__ == "__main__":
    unittest.main()
