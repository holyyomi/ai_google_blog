from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse


class PipelineStatus(StrEnum):
    QUEUED = "queued"
    DISCOVERED = "discovered"
    BRIEFED = "briefed"
    GENERATED = "generated"
    QA_PENDING = "qa_pending"
    FINAL_READY = "final_ready"
    PUBLISHED = "published"
    FAILED = "failed"


class TopicCandidateStatus(StrEnum):
    PLANNED = "planned"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    FACT_PACKED = "fact_packed"


def _validate_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {value}")
    return value


@dataclass(slots=True)
class TopicData:
    topic_id: str
    source_name: str
    title: str
    summary: str | None = None
    source_url: str | None = None
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    language: str = "en"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.source_url = _validate_url(self.source_url)


@dataclass(slots=True)
class Brief:
    run_id: str
    brief_id: str
    topic_id: str
    topic_data: dict[str, object]
    ai_name: str
    topic_name: str
    topic_type: str
    topic_angle: str
    angle: str
    audience: str = "Global AI-interested readers"
    content_language: str = "ko"
    objective: str = ""
    key_points: list[str] = field(default_factory=list)
    recommended_readers: list[str] = field(default_factory=list)
    automation_opportunities: list[str] = field(default_factory=list)
    monetization_opportunities: list[str] = field(default_factory=list)
    search_intent: str = ""
    selected_reason: str = ""
    writing_rules: list[str] = field(
        default_factory=lambda: [
            "Use clear and neutral Korean.",
            "Avoid slang, meme language, and culture-specific shorthand.",
            "Prefer explicit sentence structure for easy English translation.",
            "Keep sentence length short to medium.",
        ]
    )


@dataclass(slots=True)
class BlogPackage:
    run_id: str
    package_id: str
    topic_id: str
    topic_data: dict[str, object]
    fact_pack: dict[str, object]
    brief: dict[str, object]
    ai_name: str
    topic_name: str
    topic_type: str
    topic_angle: str
    keyword_primary: str
    keyword_secondary: list[str]
    source_name: str
    source_type: str
    source_url: str
    source_published_at: str | None
    title_candidates: list[str]
    final_title: str
    slug: str
    meta_description: str
    excerpt: str
    intro_paragraph: str
    article_outline: list[str]
    article_body: dict[str, object]
    labels: list[str]
    hashtags: list[str]
    faq_items: list[dict[str, str]]
    internal_links: list[dict[str, str]]
    external_sources: list[dict[str, str]]
    author_note: str
    update_date: str
    cta_text: str
    content_sections: list[dict[str, object]]
    cover_image_prompt: str
    image_prompt: str
    image_alt: list[str]
    article_html: str
    article_markdown: str
    json_ld_inputs: dict[str, object]
    json_ld: dict[str, object]
    image_assets: dict[str, object] = field(default_factory=dict)
    status: str = "generated"


@dataclass(slots=True)
class QAPackage:
    qa_id: str
    package_id: str
    checks: list[str] = field(default_factory=list)
    reviewer_notes: str | None = None
    approved: bool = False


@dataclass(slots=True)
class FinalReadyPackage:
    final_id: str
    topic_data: dict[str, object]
    brief: dict[str, object]
    blog_package: dict[str, object]
    qa: dict[str, object]
    approved_at: str | None = None
    publish_target: str = "blogger"
    final_ready_package: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreBreakdown:
    freshness: float
    study_value: float
    practicality: float
    monetization: float
    searchability: float
    differentiation: float
    total: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(slots=True)
class TopicCandidate:
    run_id: str
    topic_id: str
    created_at: str
    ai_name: str
    topic_name: str
    topic_type: str
    topic_angle: str
    keyword_primary: str
    keyword_secondary: list[str]
    topic_cluster: str
    topic_subcluster: str
    content_mode: str
    main_keyword: str
    supporting_keywords: list[str]
    user_intent: str
    audience_level: str
    geo_targeting_hint: str
    age_targeting_hint: str
    search_angle: str
    monetization_angle: str
    automation_angle: str
    source_name: str
    source_type: str
    source_url: str
    source_published_at: str | None
    candidate_title: str
    candidate_summary: str
    trend_score: float
    score_breakdown: ScoreBreakdown
    duplicate_key: str
    selected_reason: str
    status: TopicCandidateStatus = TopicCandidateStatus.PLANNED

    def __post_init__(self) -> None:
        _validate_url(self.source_url)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["score_breakdown"] = self.score_breakdown.to_dict()
        payload["status"] = self.status.value
        return payload


@dataclass(slots=True)
class SourcePack:
    topic_id: str
    source_name: str
    source_type: str
    source_url: str
    official_source_exists: bool
    source_urls: list[str]
    source_titles: list[str]
    source_excerpts: list[str]
    source_quality_notes: list[str]
    uncertainty_notes: list[str]


@dataclass(slots=True)
class FactPack:
    topic_id: str
    topic_data: dict[str, object]
    source_pack: dict[str, object]
    fact_pack: dict[str, object]


REQUIRED_BRIEF_KEYS = {
    "angle",
    "objective",
    "key_points",
    "recommended_readers",
    "automation_opportunities",
    "monetization_opportunities",
    "search_intent",
}

REQUIRED_BLOG_PACKAGE_KEYS = {
    "title_candidates",
    "meta_description",
    "excerpt",
    "intro_paragraph",
    "article_outline",
    "article_sections",
    "labels",
    "hashtags",
    "internal_links",
    "author_note",
    "cta_text",
    "faq_items",
    "external_citation_placeholders",
    "image_prompt",
    "alt_text_candidates",
    "key_takeaways",
    "practical_checklist",
    "conclusion",
}


def validate_required_keys(payload: dict[str, object], required_keys: set[str], payload_name: str) -> None:
    missing = sorted(required_keys.difference(payload.keys()))
    if missing:
        raise KeyError(f"Missing required keys in {payload_name}: {', '.join(missing)}")
