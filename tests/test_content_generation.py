from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.content_generation.service import build_blog_package
from blogspot_automation.content_generation.section_templates import (
    apply_article_section_template,
    build_article_section_template,
)
from blogspot_automation.content_generation.validators import (
    build_brief_model,
    normalize_article_sections,
    normalize_brief_payload,
)
from blogspot_automation.models import ScoreBreakdown, TopicCandidate, TopicCandidateStatus
from blogspot_automation.storage import StateStore


class FakeChatClient:
    def __init__(self) -> None:
        self._responses = [
            json.dumps(
                {
                    "angle": "핵심 변화와 실무 적용 방법을 분명하게 설명한다.",
                    "objective": "사실 기반으로 변화의 의미와 활용법을 정리한다.",
                    "key_points": ["무엇이 바뀌었는가", "왜 중요한가", "어떻게 활용하는가"],
                    "recommended_readers": ["AI 입문자", "자동화 실무자"],
                    "automation_opportunities": ["요약 자동화", "에이전트 워크플로 설계"],
                    "monetization_opportunities": ["자동화 컨설팅", "실무 교육 상품"],
                    "search_intent": "업데이트의 실무 활용법을 찾는 독자",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "title_candidates": [
                        "OpenAI GPT-4.1 API 업데이트를 실무 관점에서 이해하는 방법",
                        "GPT-4.1 API 업데이트가 자동화 워크플로에 중요한 이유"
                    ],
                    "meta_description": "OpenAI GPT-4.1 API 업데이트의 핵심 변화, 활용법, 자동화 관점을 사실 기반으로 정리한 글입니다.",
                    "excerpt": "이 글은 GPT-4.1 API 업데이트가 무엇인지, 왜 중요한지, 실무에서 어떻게 연결할 수 있는지 빠르게 설명합니다.",
                    "intro_paragraph": "OpenAI GPT-4.1 API 업데이트는 개발자와 자동화 실무자가 더 안정적으로 AI 기능을 연결하도록 돕는 변화입니다. 이 업데이트는 API 사용 방식과 워크플로 설계 방식에 직접 영향을 줍니다. 따라서 기능 목록만 보는 것보다 실제 적용 흐름을 함께 이해하는 것이 중요합니다.",
                    "article_outline": [
                        "무엇이 바뀌었는가",
                        "왜 지금 중요한가",
                        "실무에서 어떻게 활용할 수 있는가",
                        "도입 전에 확인할 점"
                    ],
                    "key_takeaways": [
                        "이번 업데이트는 자동화 연결성과 운영 안정성 측면에서 의미가 크다.",
                        "초보자도 핵심 구조를 이해하면 실무 적용 가능성을 빠르게 판단할 수 있다.",
                        "과장된 기대보다 실제 워크플로 적합성을 먼저 점검해야 한다."
                    ],
                    "article_sections": [
                        {
                            "heading": "무엇이 바뀌었는가",
                            "level": "h2",
                            "purpose": "독자가 업데이트의 핵심을 바로 이해하게 한다.",
                            "paragraphs": [
                                "이번 업데이트는 개발자가 AI 기능을 더 안정적으로 연결하도록 돕는 변화에 가깝습니다.",
                                "이 변화는 단순한 성능 수치보다 실제 운영 구조와 연결 방식에서 더 큰 의미를 가질 수 있습니다."
                            ],
                            "bullets": [
                                "연결 안정성 개선 가능성",
                                "자동화 워크플로 설계 단순화 가능성"
                            ]
                        },
                        {
                            "heading": "왜 지금 중요한가",
                            "level": "h2",
                            "purpose": "시장 흐름과 실무 우선순위를 연결한다.",
                            "paragraphs": [
                                "많은 팀이 AI 기능을 실험 단계에서 운영 단계로 옮기고 있습니다.",
                                "이 시점에서는 새 기능 자체보다 운영 가능한 구조를 만드는 능력이 더 중요해집니다."
                            ],
                            "bullets": [
                                "운영 전환 가속",
                                "도입 기준의 현실화"
                            ]
                        },
                        {
                            "heading": "실무에서 어떻게 활용할 수 있는가",
                            "level": "h2",
                            "purpose": "독자가 자신의 업무에 연결할 수 있게 한다.",
                            "paragraphs": [
                                "예를 들어 고객 문의 분류, 내부 문서 요약, 리서치 초안 작성 같은 흐름에 연결할 수 있습니다.",
                                "이때 중요한 것은 기능을 많이 붙이는 것이 아니라 검토 지점과 실패 복구 지점을 함께 설계하는 것입니다."
                            ],
                            "bullets": [
                                "고객 지원 요약",
                                "문서 분류",
                                "초안 생성 후 사람 검토"
                            ]
                        }
                    ],
                    "practical_checklist": {
                        "heading": "도입 전에 확인할 체크리스트",
                        "items": [
                            "기존 워크플로에서 어떤 단계가 자동화 후보인지 정의한다.",
                            "출력 검토 기준을 문서화한다.",
                            "실패 시 수동 복구 경로를 준비한다."
                        ]
                    },
                    "faq_items": [
                        {
                            "question": "이 업데이트는 누구에게 가장 유용한가요?",
                            "answer": "API를 사용해 자동화 흐름을 설계하거나 운영하는 팀에게 가장 유용합니다."
                        }
                    ],
                    "labels": ["OpenAI", "GPT-4.1", "Automation"],
                    "hashtags": ["#OpenAI", "#GPT41", "#Automation"],
                    "internal_links": [
                        {
                            "anchor_text": "AI 자동화 워크플로 설계 가이드",
                            "target_slug": "ai-automation-workflow-guide",
                            "reason": "같은 클러스터의 실무형 보조 문서"
                        }
                    ],
                    "external_citation_placeholders": [
                        {
                            "label": "OpenAI 공식 발표",
                            "source_url": "https://openai.com/index/gpt-4-1-api-update"
                        }
                    ],
                    "author_note": "이 글은 공식 소스를 기준으로 실제 적용 관점에서 핵심을 압축했습니다.",
                    "conclusion": "핵심은 새 모델을 무조건 도입하는 것이 아니라, 현재 워크플로에 어떤 방식으로 안전하게 연결할지 판단하는 것입니다.",
                    "cta_text": "자신의 워크플로에서 한 단계만 선택해 시험 적용 시나리오를 먼저 작성해 보세요.",
                    "image_prompt": "Editorial cover image for an AI API workflow update, clean dashboard, modern minimal layout, no text",
                    "alt_text_candidates": [
                        "AI API 업데이트를 상징하는 미니멀 대시보드 이미지",
                        "자동화 워크플로를 표현한 깔끔한 기술 일러스트"
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "final_title": "OpenAI GPT-4.1 API 업데이트를 이해하고 자동화 워크플로에 적용하는 방법",
                    "reason": "주제, 활용 맥락, 검색 의도를 함께 드러낸다."
                },
                ensure_ascii=False,
            ),
        ]

    def create_chat_completion(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        if not self._responses:
            raise AssertionError("No more fake responses available.")
        return self._responses.pop(0)


class ContentGenerationTests(unittest.TestCase):
    def test_build_blog_package_writes_expected_files(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db")
            store = StateStore(settings)
            store.initialize()
            store.save_topic_candidates([_sample_topic_candidate()])
            _seed_fact_pack(store, "topic-001")

            result = build_blog_package(
                topic_id="topic-001",
                store=store,
                settings=settings,
                client=FakeChatClient(),
            )

            topic_dir = root / "contents" / "topic-001"
            self.assertEqual(result.topic_id, "topic-001")
            self.assertTrue((topic_dir / "brief.json").exists())
            self.assertTrue((topic_dir / "blog_package.json").exists())
            self.assertTrue((topic_dir / "article.html").exists())
            self.assertTrue((topic_dir / "article.md").exists())
            self.assertTrue((topic_dir / "metadata.json").exists())

            blog_package = json.loads((topic_dir / "blog_package.json").read_text(encoding="utf-8"))
            package = blog_package["blog_package"]
            self.assertEqual(package["final_title"], "OpenAI GPT-4.1 API 업데이트를 이해하고 자동화 워크플로에 적용하는 방법")
            self.assertIn("slug", package)
            self.assertIn("fact_pack", blog_package)
            self.assertIn("internal_links", package)
            self.assertIn("external_sources", package)
            self.assertIn("article_markdown", package)
            self.assertGreaterEqual(len(package["meta_description"]), 110)
            self.assertLessEqual(len(package["meta_description"]), 140)
            self.assertGreaterEqual(len(package["image_alt"]), 1)
            self.assertIn("@graph", package["json_ld"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_missing_brief_keys_fail_loudly(self) -> None:
        with self.assertRaises(KeyError):
            build_brief_model(
                run_id="brief-20260316T000000Z",
                topic_data=_sample_topic_candidate().to_dict(),
                fact_pack={"fact_pack": {}},
                payload={"angle": "missing most fields"},
            )

    def test_normalize_automation_opportunities_from_string(self) -> None:
        payload = normalize_brief_payload(
            {
                "angle": "angle",
                "objective": "objective",
                "key_points": ["a"],
                "recommended_readers": ["b"],
                "automation_opportunities": "single workflow",
                "monetization_opportunities": ["m1"],
                "search_intent": "intent",
            }
        )
        self.assertEqual(payload["automation_opportunities"], ["single workflow"])

    def test_normalize_automation_opportunities_from_null(self) -> None:
        payload = normalize_brief_payload(
            {
                "angle": "angle",
                "objective": "objective",
                "key_points": ["a"],
                "recommended_readers": ["b"],
                "automation_opportunities": None,
                "monetization_opportunities": None,
                "search_intent": "intent",
            }
        )
        self.assertEqual(payload["automation_opportunities"], [])
        self.assertEqual(payload["monetization_opportunities"], [])

    def test_normalize_automation_opportunities_from_list_of_dicts(self) -> None:
        payload = normalize_brief_payload(
            {
                "angle": "angle",
                "objective": "objective",
                "key_points": ["a"],
                "recommended_readers": ["b"],
                "automation_opportunities": [{"title": "workflow one"}, {"description": "workflow two"}],
                "monetization_opportunities": [{"label": "service offer"}],
                "search_intent": "intent",
            }
        )
        self.assertEqual(payload["automation_opportunities"], ["workflow one", "workflow two"])
        self.assertEqual(payload["monetization_opportunities"], ["service offer"])

    def test_normalize_automation_opportunities_from_proper_list(self) -> None:
        payload = normalize_brief_payload(
            {
                "angle": "angle",
                "objective": "objective",
                "key_points": ["a"],
                "recommended_readers": ["b"],
                "automation_opportunities": ["workflow one", "workflow two"],
                "monetization_opportunities": ["offer one"],
                "search_intent": "intent",
            }
        )
        self.assertEqual(payload["automation_opportunities"], ["workflow one", "workflow two"])

    def test_normalize_article_section_levels(self) -> None:
        sections = normalize_article_sections(
            [
                {"heading": "A", "level": "H2", "body": "body"},
                {"heading": "B", "level": "H3", "body": "body"},
                {"heading": "C", "level": "2", "body": "body"},
                {"heading": "D", "level": "3", "body": "body"},
                {"heading": "E", "level": 2, "body": "body"},
                {"heading": "F", "level": 3, "body": "body"},
                {"heading": "G", "level": "section", "body": "body"},
                {"heading": "H", "level": "subsection", "body": "body"},
                {"heading": "I", "level": "h4", "body": "body"},
                {"heading": "J", "level": None, "body": "body"},
            ]
        )
        self.assertEqual(
            [section["level"] for section in sections],
            ["h2", "h3", "h2", "h3", "h2", "h3", "h2", "h3", "h2", "h2"],
        )

    def test_normalize_article_sections_null_to_empty_list(self) -> None:
        self.assertEqual(normalize_article_sections(None), [])

    def test_article_section_template_forces_h2_h3_levels(self) -> None:
        topic_data = _sample_topic_candidate().to_dict()
        fact_pack = {
            "constraints": ["Do not invent pricing"],
            "risks": ["Do not overclaim"],
            "examples": ["Customer support workflow"],
        }
        template = build_article_section_template(topic_data=topic_data, fact_pack=fact_pack)
        merged = apply_article_section_template(
            template=template,
            generated_sections=[
                {"heading": "LLM freeform heading", "level": "h4", "paragraphs": ["A"]},
                {"heading": "Another heading", "level": "subsection", "paragraphs": ["B"]},
            ],
        )
        self.assertTrue(all(section["level"] in {"h2", "h3"} for section in merged))
        self.assertEqual(merged[0]["heading"], template[0]["heading"])
        self.assertEqual(merged[1]["heading"], template[1]["heading"])


def _seed_fact_pack(store: StateStore, topic_id: str) -> None:
    payload = {
        "topic_id": topic_id,
        "topic_data": {"topic_id": topic_id},
        "source_pack": {
            "source_urls": ["https://openai.com/index/gpt-4-1-api-update"]
        },
        "fact_pack": {
            "what_it_is": "A source-grounded API update.",
            "why_it_matters": "It changes workflow design decisions.",
            "who_it_is_for": "Developers and automation teams.",
            "key_points": ["Official source exists", "Workflow relevance is high"],
            "constraints": ["Do not invent pricing"],
            "risks": ["Do not overclaim"],
            "examples": ["Customer support workflow"],
            "source_urls": ["https://openai.com/index/gpt-4-1-api-update"],
            "unsupported_claims_to_avoid": ["Unverified ROI claims"],
        },
    }
    store.save_fact_pack(topic_id, payload)


def _sample_topic_candidate() -> TopicCandidate:
    return TopicCandidate(
        run_id="discover-20260316T000000Z",
        topic_id="topic-001",
        created_at="2026-03-16T00:00:00+00:00",
        ai_name="OpenAI",
        topic_name="GPT-4.1 API Update",
        topic_type="developer_update",
        topic_angle="Explain what changed and how teams can use it.",
        keyword_primary="OpenAI",
        keyword_secondary=["GPT-4.1", "API", "automation"],
        topic_cluster="automation_workflows",
        topic_subcluster="agent_workflows",
        content_mode="news_explainer",
        main_keyword="OpenAI GPT-4.1 API",
        supporting_keywords=["agents", "developer integration", "workflow automation"],
        user_intent="how_to",
        audience_level="intermediate",
        geo_targeting_hint="Global first",
        age_targeting_hint="Answer engine friendly",
        search_angle="Explain what changed and how to use the API update",
        monetization_angle="Automation consulting",
        automation_angle="Repeatable agent workflows",
        source_name="OpenAI Blog",
        source_type="rss",
        source_url="https://openai.com/index/gpt-4-1-api-update",
        source_published_at="2026-03-15T00:00:00+00:00",
        candidate_title="OpenAI releases GPT-4.1 API for agents",
        candidate_summary="New API release for agent workflows and developer integration.",
        trend_score=0.85,
        score_breakdown=ScoreBreakdown(
            freshness=0.9,
            study_value=0.7,
            practicality=0.8,
            monetization=0.6,
            searchability=0.7,
            differentiation=0.6,
            total=0.85,
        ),
        duplicate_key="openai-gpt-4-1-api-update-abcdef123456",
        selected_reason="Selected for strong practical value.",
        status=TopicCandidateStatus.PLANNED,
    )


if __name__ == "__main__":
    unittest.main()
