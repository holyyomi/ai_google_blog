from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from blogspot_automation.models import ScoreBreakdown
from blogspot_automation.topic_discovery.parser import ParsedItem


WEIGHTS = {
    "freshness": 0.25,
    "study_value": 0.20,
    "practicality": 0.20,
    "monetization": 0.10,
    "searchability": 0.15,
    "differentiation": 0.10,
}

# 제목에 포함 시 점수 보너스 (심층 기술 뉴스 우선)
_PRIORITY_KEYWORDS = (
    "model", "release", "update", "api", "agent",
    "claude", "gpt", "gemini", "llama", "benchmark",
    "launch", "new", "vs", "compare",
)

# 제목에 포함 시 점수 패널티 (가벼운 부업/팁 콘텐츠 후순위)
_DEPRIORITY_KEYWORDS = (
    "부업", "수익", "side hustle", "make money",
    "tips", "tricks", "beginner",
)


def score_item(item: ParsedItem) -> ScoreBreakdown:
    freshness = _score_freshness(item.published_at)
    study_value = _keyword_score(item, ("research", "benchmark", "reasoning", "model", "paper", "safety"))
    practicality = _keyword_score(item, ("api", "tool", "workflow", "agent", "release", "integration"))
    monetization = _keyword_score(item, ("pricing", "enterprise", "workflow", "agent", "automation", "team"))
    searchability = _score_searchability(item.title)
    differentiation = _score_differentiation(item)
    total = (
        freshness * WEIGHTS["freshness"]
        + study_value * WEIGHTS["study_value"]
        + practicality * WEIGHTS["practicality"]
        + monetization * WEIGHTS["monetization"]
        + searchability * WEIGHTS["searchability"]
        + differentiation * WEIGHTS["differentiation"]
    )

    # 우선 키워드 보너스: 2개 이상 매칭 시 +0.2, 1개 매칭 시 +0.1
    title_lower = item.title.lower()
    priority_hits = sum(1 for kw in _PRIORITY_KEYWORDS if kw in title_lower)
    if priority_hits >= 2:
        total += 0.20
    elif priority_hits == 1:
        total += 0.10

    # 제외 키워드 패널티: 1개라도 매칭 시 -0.40
    if any(kw in title_lower for kw in _DEPRIORITY_KEYWORDS):
        total -= 0.40

    total = round(min(1.0, max(0.0, total)), 2)

    return ScoreBreakdown(
        freshness=round(freshness, 2),
        study_value=round(study_value, 2),
        practicality=round(practicality, 2),
        monetization=round(monetization, 2),
        searchability=round(searchability, 2),
        differentiation=round(differentiation, 2),
        total=total,
    )


def _score_freshness(published_at: str | None) -> float:
    if not published_at:
        return 0.45
    published = datetime.fromisoformat(published_at)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_days = max((datetime.now(timezone.utc) - published).total_seconds() / 86400.0, 0.0)
    return max(0.0, min(1.0, math.exp(-age_days / 7.0)))


def _keyword_score(item: ParsedItem, keywords: tuple[str, ...]) -> float:
    haystack = f"{item.title} {item.summary} {' '.join(item.tags)}".lower()
    hits = sum(1 for keyword in keywords if keyword in haystack)
    return min(1.0, 0.25 + hits * 0.18)


def _score_searchability(title: str) -> float:
    token_count = len(re.findall(r"[a-zA-Z0-9]+", title))
    has_specific_version = bool(re.search(r"\b(v?\d+(\.\d+)*)\b", title.lower()))
    base = 0.4 if 4 <= token_count <= 14 else 0.25
    if has_specific_version:
        base += 0.2
    if ":" in title or "-" in title:
        base += 0.1
    return min(1.0, base)


def _score_differentiation(item: ParsedItem) -> float:
    haystack = f"{item.title} {item.summary}".lower()
    if any(term in haystack for term in ("benchmark", "case study", "workflow", "comparison", "evaluation")):
        return 0.9
    if any(term in haystack for term in ("launch", "release", "update")):
        return 0.65
    return 0.5
