from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class ContentPillar(StrEnum):
    DAILY_SIDE_HUSTLE = "매일 새로운 부업 해부"
    AI_SIDE_HUSTLE = "AI 부업 / 온라인 수익화 실전"
    AI_TOOLS_NEWS = "신규 AI 도구 활용법 및 소식"
    KOREAN_STOCK_NEWS = "국내 주식 특징주 및 시황"
    KOREAN_STOCK_BEGINNER = "주식 초보를 위한 기초"
    SIDE_HUSTLE_TAX = "N잡러/프리랜서 세금 처리 가이드"


class PublishStatus(StrEnum):
    PLANNED = "planned"
    SOURCE_INSUFFICIENT = "source_insufficient"
    PLANNED_FAIL = "planned_fail"
    GENERATED = "generated"
    QA_FAILED = "qa_failed"
    PUBLISHED = "published"
    FAILED = "failed"


class QAResult(StrEnum):
    PASS = "PASS"
    SOFT_FAIL = "SOFT_FAIL"
    FAIL = "FAIL"
    FIX_REQUIRED = "FIX_REQUIRED"


DEFAULT_STATUS_TRANSITIONS: dict[PublishStatus, set[PublishStatus]] = {
    PublishStatus.PLANNED: {
        PublishStatus.GENERATED,
        PublishStatus.SOURCE_INSUFFICIENT,
        PublishStatus.PLANNED_FAIL,
    },
    PublishStatus.SOURCE_INSUFFICIENT: set(),
    PublishStatus.PLANNED_FAIL: set(),
    PublishStatus.GENERATED: {
        PublishStatus.QA_FAILED,
        PublishStatus.PUBLISHED,
        PublishStatus.FAILED,
    },
    PublishStatus.QA_FAILED: set(),
    PublishStatus.PUBLISHED: set(),
    PublishStatus.FAILED: set(),
}


@dataclass(slots=True)
class BlogWorkItem:
    id: str
    created_at: str
    updated_at: str
    content_pillar: str
    topic_title: str
    primary_keyword: str
    secondary_keywords: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    source_summary: str = ""
    selected_pillar: str = ""
    selected_topic: str = ""
    why_selected: str = ""
    source_articles: list[dict[str, object]] = field(default_factory=list)
    source_count: int = 0
    source_domains: list[str] = field(default_factory=list)
    keyword_set: dict[str, object] = field(default_factory=dict)
    title_candidates: list[str] = field(default_factory=list)
    title_candidate_types: list[str] = field(default_factory=list)
    topic_score: float = 0.0
    source_quality_status: str = ""
    discovery_debug: dict[str, object] = field(default_factory=dict)
    raw_candidate_count: int = 0
    parsed_candidate_count: int = 0
    filtered_candidate_count: int = 0
    reject_reason_summary: dict[str, int] = field(default_factory=dict)
    final_discovery_status: str = ""
    retry_count: int = 0
    retry_path: list[str] = field(default_factory=list)
    fallback_strategy_used: str = ""
    fallback_pillar_used: str = ""
    discovery_attempts: list[dict[str, object]] = field(default_factory=list)
    estimated_time_to_start: str = ""
    estimated_cost_to_start: str = ""
    potential_income_range: str = ""
    difficulty_level: str = ""
    recommended_for: list[str] = field(default_factory=list)
    not_recommended_for: list[str] = field(default_factory=list)
    failure_points: list[str] = field(default_factory=list)
    faq_items: list[dict[str, str]] = field(default_factory=list)
    cta_type: str = ""
    content_density_status: str = ""
    final_title: str = ""
    meta_description: str = ""
    labels: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    image_prompt: str = ""
    image_url: str = ""
    generated_image_status: str = ""
    image_error_message: str = ""
    final_image_url: str = ""
    article_html: str = ""
    json_ld: dict[str, object] = field(default_factory=dict)
    qa_result: str = ""
    qa_issues: list[str] = field(default_factory=list)
    publish_block_reason: str = ""
    approval_required: bool = False
    publish_status: str = PublishStatus.PLANNED.value
    blog_url: str = ""
    blog_post_id: str = ""
    notes: str = ""
    content_type: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class BriefRecord:
    work_item_id: str
    created_at: str
    updated_at: str
    brief_summary: str
    final_angle: str
    target_reader: str = ""
    reader_problem: str = ""
    search_intent: str = ""
    one_line_hook: str = ""
    why_now: str = ""
    outline_sections: list[str] = field(default_factory=list)
    key_takeaways: list[str] = field(default_factory=list)
    facts_from_sources: list[str] = field(default_factory=list)
    hard_facts_from_sources: list[str] = field(default_factory=list)
    source_consensus: list[str] = field(default_factory=list)
    source_differences: list[str] = field(default_factory=list)
    what_it_means_to_reader: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    practical_actions: list[str] = field(default_factory=list)
    estimated_time_to_start: str = ""
    estimated_cost_to_start: str = ""
    potential_income_range: str = ""
    difficulty_level: str = ""
    recommended_for: list[str] = field(default_factory=list)
    not_recommended_for: list[str] = field(default_factory=list)
    failure_points: list[str] = field(default_factory=list)
    monetization_block_idea: str = ""
    faq_candidates: list[str] = field(default_factory=list)
    faq_items: list[dict[str, str]] = field(default_factory=list)
    evidence_points: list[str] = field(default_factory=list)
    cta_direction: str = ""
    cta_type: str = ""
    content_density_status: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ContentPackageRecord:
    work_item_id: str
    created_at: str
    updated_at: str
    title_candidates: list[str] = field(default_factory=list)
    final_title: str = ""
    meta_description: str = ""
    labels: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    image_prompt: str = ""
    article_html: str = ""
    article_preview_html: str = ""
    json_ld: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class QAReviewRecord:
    work_item_id: str
    created_at: str
    updated_at: str
    qa_result: str
    qa_score: int
    issues: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    review_summary: str = ""
    requires_manual_approval: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PublishRecord:
    publish_id: str
    work_item_id: str
    created_at: str
    updated_at: str
    publish_mode: str
    target_status: str
    publish_result: str
    blog_url: str = ""
    blog_post_id: str = ""
    response_json: dict[str, object] = field(default_factory=dict)
    error_message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_sample_work_item(
    *,
    item_id: str = "fixture-topic-001",
    content_pillar: ContentPillar = ContentPillar.AI_SIDE_HUSTLE,
) -> BlogWorkItem:
    timestamp = now_iso()
    title = "AI 자동화 부업 구조 해설"
    return BlogWorkItem(
        id=item_id,
        created_at=timestamp,
        updated_at=timestamp,
        content_pillar=content_pillar.value,
        topic_title=title,
        primary_keyword="AI 자동화 부업",
        secondary_keywords=["자동화", "온라인 수익화", "실전 적용"],
        source_urls=[
            "https://news.hankyung.com/article/fixture-1",
            "https://www.mk.co.kr/news/fixture-2",
            "https://www.etnews.com/fixture-3",
        ],
        source_summary="실전형 AI 부업 구조를 실제 기사 흐름 기준으로 정리한 테스트용 레코드입니다.",
        selected_pillar=content_pillar.value,
        selected_topic=title,
        why_selected="테스트 픽스처입니다.",
        source_articles=[
            {
                "provider_name": "fixture",
                "source_url": "https://news.hankyung.com/rss",
                "title": "AI 자동화 부업 구조 해설",
                "summary": "테스트용 기사 요약입니다.",
                "article_url": "https://news.hankyung.com/article/fixture-1",
                "published_at": timestamp,
            },
            {
                "provider_name": "fixture",
                "source_url": "https://www.mk.co.kr/rss",
                "title": "AI 자동화 부업 적용 사례",
                "summary": "테스트용 기사 요약입니다.",
                "article_url": "https://www.mk.co.kr/news/fixture-2",
                "published_at": timestamp,
            },
            {
                "provider_name": "fixture",
                "source_url": "https://www.etnews.com/rss",
                "title": "AI 자동화 수익화 체크포인트",
                "summary": "테스트용 기사 요약입니다.",
                "article_url": "https://www.etnews.com/fixture-3",
                "published_at": timestamp,
            },
        ],
        source_count=3,
        source_domains=["news.hankyung.com", "www.mk.co.kr", "www.etnews.com"],
        keyword_set={
            "primary_keyword": "AI 자동화 부업",
            "secondary_keywords": ["자동화", "온라인 수익화", "실전 적용"],
        },
        title_candidates=[
            title,
            "AI 자동화 부업, 지금 늦기 전에 봐야 할 문제",
            "초보가 이해하는 AI 자동화 부업 시작법",
            "AI 자동화 부업 실행 전에 확인할 체크포인트",
            "AI 자동화 부업 이슈 해설과 실행 비교",
        ],
        title_candidate_types=["뉴스해설형", "문제형", "초보형", "실행형", "비교형"],
        topic_score=80.0,
        source_quality_status="sufficient",
        discovery_debug={
            "selected_pillar": content_pillar.value,
            "attempted_strategy_type": "fixture",
            "search_queries_used": [],
            "source_attempts": [
                {
                    "provider_type": "fixture",
                    "provider_name": "fixture",
                    "source_url": "https://news.hankyung.com/rss",
                    "fetch_status": "success",
                    "parse_status": "success",
                    "response_length": 3,
                    "parse_count": 3,
                    "filtered_out_count": 0,
                    "filtered_item_reasons": {},
                    "query_text": "",
                }
            ],
            "raw_candidate_count": 3,
            "parsed_candidate_count": 3,
            "filtered_candidate_count": 3,
            "reject_reason_summary": {},
            "final_failure_reason": "",
            "final_discovery_status": "selected",
            "unique_domain_count": 3,
        },
        raw_candidate_count=3,
        parsed_candidate_count=3,
        filtered_candidate_count=3,
        reject_reason_summary={},
        final_discovery_status="selected",
        retry_count=0,
        retry_path=[],
        fallback_strategy_used="",
        fallback_pillar_used="",
        discovery_attempts=[],
        estimated_time_to_start="하루 30~60분",
        estimated_cost_to_start="월 0~5만원",
        potential_income_range="월 5만~50만원",
        difficulty_level="중간",
        recommended_for=["퇴근 후 1시간 내 실험 가능한 직장인"],
        not_recommended_for=["즉시 고수익만 기대하는 사람"],
        failure_points=["검수 없이 자동화만 돌리는 경우"],
        faq_items=[{"question": "진짜 초보도 가능한가?", "answer": "작게 시작하면 가능하다."}],
        cta_type="action_plan",
        content_density_status="dense",
        generated_image_status="generated",
        image_error_message="",
        final_image_url="https://images.examplecdn.invalid/fixture-cover.png",
        publish_block_reason="",
        approval_required=False,
        publish_status=PublishStatus.PLANNED.value,
        notes="storage fixture record",
    )
