from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NewsCandidate:
    topic: str
    category: str
    summary: str
    source_hint: str | None = None
    published_at: str | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "category": self.category,
            "summary": self.summary,
            "source_hint": self.source_hint,
            "published_at": self.published_at,
            "url": self.url,
            "raw": dict(self.raw),
        }


@dataclass(slots=True)
class ScoredNewsCandidate:
    candidate: NewsCandidate
    freshness_score: int
    search_demand_score: int
    contrarian_gap_score: int
    mass_impact_score: int
    adsense_value_score: int
    hook_score: int
    risk_penalty: int
    total_score: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "freshness_score": self.freshness_score,
            "search_demand_score": self.search_demand_score,
            "contrarian_gap_score": self.contrarian_gap_score,
            "mass_impact_score": self.mass_impact_score,
            "adsense_value_score": self.adsense_value_score,
            "hook_score": self.hook_score,
            "risk_penalty": self.risk_penalty,
            "total_score": self.total_score,
            "reason": self.reason,
        }


@dataclass(slots=True)
class TitleCandidate:
    title: str
    hook_type: str
    ctr_score: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "hook_type": self.hook_type,
            "ctr_score": self.ctr_score,
            "reason": self.reason,
        }


@dataclass(slots=True)
class SelectedNewsPlan:
    selected_topic: ScoredNewsCandidate
    title_candidates: list[TitleCandidate]
    selected_title: TitleCandidate
    contrarian_angle: str
    mainstream_view: str
    reader_benefit: str
    labels: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_topic": self.selected_topic.to_dict(),
            "title_candidates": [candidate.to_dict() for candidate in self.title_candidates],
            "selected_title": self.selected_title.to_dict(),
            "contrarian_angle": self.contrarian_angle,
            "mainstream_view": self.mainstream_view,
            "reader_benefit": self.reader_benefit,
            "labels": list(self.labels),
        }
