from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import re
from uuid import uuid4

from blogspot_automation.models import TopicCandidate, TopicCandidateStatus
from blogspot_automation.storage import StateStore
from blogspot_automation.topic_discovery.fetcher import fetch_source
from blogspot_automation.topic_discovery.parser import ParsedItem, parse_source_payload
from blogspot_automation.topic_discovery.scoring import (
    score_item,
    _DEPRIORITY_KEYWORDS,
    _PRIORITY_KEYWORDS,
)
from blogspot_automation.topic_discovery.sources import get_source_registry
from blogspot_automation.topic_discovery.strategy import build_topic_strategy, cluster_priority_bonus


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveryResult:
    run_id: str
    fetched_sources: int
    parsed_items: int
    saved_topics: int
    duplicate_topics: int
    export_path: str


def discover_topics(store: StateStore) -> DiscoveryResult:
    run_id = datetime.now(timezone.utc).strftime("discover-%Y%m%dT%H%M%SZ")
    logger.info("starting topic discovery: %s", run_id)
    fetched_sources = 0
    parsed_items = 0
    selected: list[TopicCandidate] = []
    seen_duplicate_keys: set[str] = set()
    duplicate_topics = 0

    for source in get_source_registry():
        fetched = fetch_source(source)
        if fetched is None:
            logger.warning("topic source fetch failed: %s", source.name)
            continue
        fetched_sources += 1
        items = parse_source_payload(fetched)
        parsed_items += len(items)
        for item in items:
            title_lower = item.title.lower()
            if any(kw in title_lower for kw in _DEPRIORITY_KEYWORDS):
                logger.debug("topic hard-skipped (depriority keyword): %s", item.title)
                continue
            candidate = _normalize_item(run_id, item)
            if candidate.duplicate_key in seen_duplicate_keys or store.has_duplicate_key(candidate.duplicate_key):
                duplicate_topics += 1
                continue
            seen_duplicate_keys.add(candidate.duplicate_key)
            selected.append(candidate)

    selected.sort(key=lambda record: record.trend_score, reverse=True)
    saved_topics = store.save_topic_candidates(selected)
    if fetched_sources == 0:
        logger.warning("All topic sources failed. No fallback available.")
    export_path = str(store.export_planned_topics())
    logger.info(
        "topic discovery finished: run_id=%s fetched=%s parsed=%s saved=%s duplicates=%s",
        run_id,
        fetched_sources,
        parsed_items,
        saved_topics,
        duplicate_topics,
    )
    return DiscoveryResult(
        run_id=run_id,
        fetched_sources=fetched_sources,
        parsed_items=parsed_items,
        saved_topics=saved_topics,
        duplicate_topics=duplicate_topics,
        export_path=export_path,
    )


def _normalize_item(run_id: str, item: ParsedItem) -> TopicCandidate:
    score = score_item(item)
    topic_name = _topic_name_from_title(item.title, item.ai_name)
    keyword_primary = _select_keyword_primary(item, topic_name)
    keyword_secondary = _select_keyword_secondary(item, keyword_primary)
    strategy = build_topic_strategy(
        item=item,
        topic_name=topic_name,
        keyword_primary=keyword_primary,
        keyword_secondary=keyword_secondary,
    )
    topic_type = _classify_topic_type(item)
    topic_angle = _build_topic_angle(item, topic_type)
    duplicate_key = build_duplicate_key(item.ai_name, topic_name, item.item_url)
    selected_reason = _selected_reason(score, topic_type)
    topic_id = hashlib.sha1(f"{run_id}:{duplicate_key}".encode("utf-8")).hexdigest()[:16]
    trend_score = min(1.0, round(score.total + cluster_priority_bonus(strategy.topic_cluster), 2))
    return TopicCandidate(
        run_id=run_id,
        topic_id=topic_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        ai_name=item.ai_name,
        topic_name=topic_name,
        topic_type=topic_type,
        topic_angle=topic_angle,
        keyword_primary=keyword_primary,
        keyword_secondary=keyword_secondary,
        topic_cluster=strategy.topic_cluster,
        topic_subcluster=strategy.topic_subcluster,
        content_mode=strategy.content_mode,
        main_keyword=strategy.main_keyword,
        supporting_keywords=strategy.supporting_keywords,
        user_intent=strategy.user_intent,
        audience_level=strategy.audience_level,
        geo_targeting_hint=strategy.geo_targeting_hint,
        age_targeting_hint=strategy.age_targeting_hint,
        search_angle=strategy.search_angle,
        monetization_angle=strategy.monetization_angle,
        automation_angle=strategy.automation_angle,
        source_name=item.source_name,
        source_type=item.source_type,
        source_url=item.item_url,
        source_published_at=item.published_at,
        candidate_title=item.title,
        candidate_summary=item.summary or item.title,
        trend_score=trend_score,
        score_breakdown=score,
        duplicate_key=duplicate_key,
        selected_reason=f"{selected_reason} Cluster={strategy.topic_cluster}, intent={strategy.user_intent}.",
        status=TopicCandidateStatus.PLANNED,
    )


def build_duplicate_key(ai_name: str, topic_name: str, source_url: str) -> str:
    del source_url
    normalized_name = _slugify(f"{ai_name}-{topic_name}")
    digest = hashlib.sha1(normalized_name.encode("utf-8")).hexdigest()[:12]
    return f"{normalized_name}-{digest}"


def _topic_name_from_title(title: str, ai_name: str) -> str:
    cleaned = re.sub(re.escape(ai_name), "", title, flags=re.IGNORECASE).strip(" :-")
    return cleaned or title.strip()


def _select_keyword_primary(item: ParsedItem, topic_name: str) -> str:
    candidates = [item.ai_name, topic_name]
    for candidate in candidates:
        cleaned = candidate.strip()
        if cleaned:
            return cleaned
    return item.title


def _select_keyword_secondary(item: ParsedItem, keyword_primary: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\.]+", f"{item.title} {item.summary}")
    secondary: list[str] = []
    seen: set[str] = {keyword_primary.lower()}
    for token in tokens:
        lowered = token.lower()
        if lowered in seen or len(token) < 3:
            continue
        secondary.append(token)
        seen.add(lowered)
        if len(secondary) == 5:
            break
    return secondary


def _classify_topic_type(item: ParsedItem) -> str:
    haystack = f"{item.title} {item.summary}".lower()
    if any(term in haystack for term in ("api", "sdk", "developer", "integration")):
        return "developer_update"
    if any(term in haystack for term in ("pricing", "enterprise", "plan", "subscription")):
        return "business_update"
    if any(term in haystack for term in ("benchmark", "paper", "research", "reasoning", "evaluation")):
        return "research_update"
    return "product_update"


def _build_topic_angle(item: ParsedItem, topic_type: str) -> str:
    if topic_type == "developer_update":
        return "Explain what changed, who can use it, and how it affects AI workflows."
    if topic_type == "business_update":
        return "Explain the business impact, pricing logic, and user implications."
    if topic_type == "research_update":
        return "Explain the research significance, practical meaning, and limits."
    return "Explain the product update, the user value, and the practical impact."


def _selected_reason(score_breakdown, topic_type: str) -> str:
    return (
        f"Selected for {topic_type} relevance with strong freshness "
        f"and overall trend score {score_breakdown.total:.2f}."
    )


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return normalized.strip("-") or str(uuid4())
