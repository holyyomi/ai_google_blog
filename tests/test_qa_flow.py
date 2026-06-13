from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.content_generation.service import build_blog_package
from blogspot_automation.image_generation.service import generate_cover_image
from blogspot_automation.models import ScoreBreakdown, TopicCandidate, TopicCandidateStatus
from blogspot_automation.publishing.service import publish_topic
from blogspot_automation.qa.service import prepare_final_ready_package, qa_status, review_article_package
from blogspot_automation.storage import StateStore


class _FakeChatClient:
    def __init__(self) -> None:
        self._responses = [
            json.dumps(
                {
                    "angle": "핵심 변화와 적용 방법을 정리한다.",
                    "objective": "업데이트의 의미를 실무 중심으로 설명한다.",
                    "key_points": ["무엇", "왜", "어떻게"],
                    "recommended_readers": ["입문자", "실무자"],
                    "automation_opportunities": ["요약", "분류"],
                    "monetization_opportunities": ["서비스", "컨설팅"],
                    "search_intent": "실무 적용 방법",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "title_candidates": ["워크플로 업데이트 이해하기", "자동화 적용 관점에서 본 업데이트"],
                    "meta_description": "워크플로 업데이트의 핵심과 자동화 적용 관점을 설명합니다.",
                    "excerpt": "이 글은 워크플로 업데이트를 빠르게 이해하도록 돕습니다.",
                    "intro_paragraph": "이 토픽은 자동화 실무에 영향을 주는 업데이트입니다. 핵심은 기능 자체보다 적용 방식입니다. 따라서 독자는 실제 워크플로 연결 가능성을 먼저 봐야 합니다.",
                    "article_outline": ["무엇이 바뀌었는가", "실무 활용", "체크리스트"],
                    "key_takeaways": ["핵심 1", "핵심 2", "핵심 3"],
                    "article_sections": [
                        {
                            "heading": "무엇이 바뀌었는가",
                            "level": "h2",
                            "purpose": "핵심 변화 설명",
                            "paragraphs": ["문단 1", "문단 2"],
                            "bullets": ["항목 1"]
                        },
                        {
                            "heading": "실무 활용",
                            "level": "h2",
                            "purpose": "현장 연결성 설명",
                            "paragraphs": ["문단 3", "문단 4"],
                            "bullets": ["항목 2", "항목 3"]
                        }
                    ],
                    "practical_checklist": {
                        "heading": "실무 체크리스트",
                        "items": ["항목 A", "항목 B"]
                    },
                    "faq_items": [
                        {"question": "무엇인가요?", "answer": "테스트입니다."},
                        {"question": "왜 중요한가요?", "answer": "자동화 설계와 연결되기 때문입니다."}
                    ],
                    "labels": ["AI", "Automation"],
                    "hashtags": ["#AI", "#Automation"],
                    "internal_links": [
                        {
                            "anchor_text": "워크플로 설계 가이드",
                            "target_slug": "workflow-guide",
                            "reason": "관련 문서 연결"
                        }
                    ],
                    "external_citation_placeholders": [
                        {
                            "label": "공식 소스",
                            "source_url": "https://openai.com/index/workflow-update"
                        }
                    ],
                    "author_note": "공식 소스를 기준으로 정리했습니다.",
                    "conclusion": "실제 워크플로 연결 가능성을 먼저 봐야 합니다.",
                    "cta_text": "작은 실험부터 시작해 보세요.",
                    "image_prompt": "Editorial AI workflow cover image, minimal, no text",
                    "alt_text_candidates": ["자동화 워크플로를 표현한 기술 이미지"]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "final_title": "OpenAI Workflow Update를 이해하고 자동화 흐름에 적용하는 방법",
                    "reason": "주제와 실무 맥락이 모두 드러난다."
                },
                ensure_ascii=False,
            ),
        ]

    def create_chat_completion(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return self._responses.pop(0)


class _FailingImageClient:
    def generate_image(self, *, prompt: str, size: str = "1536x1024") -> dict[str, object]:
        del prompt, size
        raise RuntimeError("Image API unavailable")


class QAFlowTests(unittest.TestCase):
    def test_end_to_end_local_flow_to_publish_dry_run(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db", blogger_blog_id="blog-1")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate()])
            _seed_fact_pack(store, "topic-flow")

            build_blog_package(
                topic_id="topic-flow",
                store=store,
                settings=settings,
                client=_FakeChatClient(),
            )
            generate_cover_image(
                topic_id="topic-flow",
                store=store,
                settings=settings,
                client=_FailingImageClient(),
            )
            qa_review = review_article_package(topic_id="topic-flow", store=store)
            self.assertEqual(qa_review.qa_result, "PASS")

            qa_result = prepare_final_ready_package(
                topic_id="topic-flow",
                store=store,
                reviewer_notes="Manual review completed.",
            )
            publish_result = publish_topic(
                topic_id="topic-flow",
                store=store,
                settings=settings,
                dry_run=True,
            )

            self.assertEqual(qa_result.status, "final_ready")
            self.assertEqual(publish_result.status, "dry_run")
            self.assertEqual(qa_status(topic_id="topic-flow", store=store)["status"], "dry_run")
            self.assertTrue((root / "contents" / "topic-flow" / "final_ready_package.json").exists())
            self.assertTrue((root / "contents" / "topic-flow" / "publish" / "publish_request.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _seed_fact_pack(store: StateStore, topic_id: str) -> None:
    payload = {
        "topic_id": topic_id,
        "topic_data": {"topic_id": topic_id},
        "source_pack": {"source_urls": ["https://openai.com/index/workflow-update"]},
        "fact_pack": {
            "what_it_is": "A workflow update.",
            "why_it_matters": "It affects automation design.",
            "who_it_is_for": "Automation teams.",
            "key_points": ["Official source available", "Workflow relevance is high"],
            "constraints": ["Do not invent pricing"],
            "risks": ["Do not overclaim"],
            "examples": ["Support workflow"],
            "source_urls": ["https://openai.com/index/workflow-update"],
            "unsupported_claims_to_avoid": ["Unverified ROI"],
        },
    }
    store.save_fact_pack(topic_id, payload)


def _sample_topic_candidate() -> TopicCandidate:
    return TopicCandidate(
        run_id="discover-20260316T000000Z",
        topic_id="topic-flow",
        created_at="2026-03-16T00:00:00+00:00",
        ai_name="OpenAI",
        topic_name="Workflow Update",
        topic_type="developer_update",
        topic_angle="Explain usage and impact.",
        keyword_primary="OpenAI",
        keyword_secondary=["workflow", "automation"],
        topic_cluster="automation_workflows",
        topic_subcluster="agent_workflows",
        content_mode="news_explainer",
        main_keyword="workflow update",
        supporting_keywords=["workflow", "automation"],
        user_intent="how_to",
        audience_level="beginner_to_intermediate",
        geo_targeting_hint="Global first",
        age_targeting_hint="Answer engine friendly",
        search_angle="Explain the workflow update and how to apply it",
        monetization_angle="Automation consulting",
        automation_angle="Repeatable workflows",
        source_name="OpenAI Blog",
        source_type="rss",
        source_url="https://openai.com/index/workflow-update",
        source_published_at="2026-03-15T00:00:00+00:00",
        candidate_title="Workflow update",
        candidate_summary="Summary",
        trend_score=0.8,
        score_breakdown=ScoreBreakdown(0.9, 0.7, 0.8, 0.5, 0.7, 0.6, 0.8),
        duplicate_key="openai-workflow-update-123456",
        selected_reason="Selected.",
        status=TopicCandidateStatus.PLANNED,
    )


if __name__ == "__main__":
    unittest.main()
