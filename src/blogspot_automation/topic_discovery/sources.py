from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    name: str
    source_type: str
    url: str
    ai_name: str
    tags: tuple[str, ...] = field(default_factory=tuple)


# 외부 RSS 소스 제거 — 네이버 블로그(holyyomi) 전용 파이프라인으로 전환
DEFAULT_SOURCES: tuple[SourceDefinition, ...] = ()


def get_source_registry() -> list[SourceDefinition]:
    config_path = Path("config/topic_sources.json")
    if not config_path.exists():
        return list(DEFAULT_SOURCES)

    try:
        raw_sources = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return list(DEFAULT_SOURCES)

    sources: list[SourceDefinition] = []
    for raw_source in raw_sources:
        try:
            sources.append(
                SourceDefinition(
                    name=raw_source["name"],
                    source_type=raw_source["source_type"],
                    url=raw_source["url"],
                    ai_name=raw_source["ai_name"],
                    tags=tuple(raw_source.get("tags", [])),
                )
            )
        except KeyError:
            continue
    return sources or list(DEFAULT_SOURCES)
