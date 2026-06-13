from __future__ import annotations

from pathlib import Path

from blogspot_automation.services.topic_selection_service import (
    DefaultTopicSelectionService,
    SelectedTopicResult,
    load_topic_discovery_runtime_config,
)
from blogspot_automation.storage import BlogWorkItemRepository, SQLiteBlogStore


def run_topic_selection_pipeline(*, root_dir: Path) -> SelectedTopicResult:
    repository = BlogWorkItemRepository(SQLiteBlogStore(root_dir))
    runtime_config = load_topic_discovery_runtime_config(root_dir)
    service = DefaultTopicSelectionService(
        repository=repository,
        providers=runtime_config.providers,
        min_source_articles=runtime_config.min_source_articles,
        min_unique_domains=runtime_config.min_unique_domains,
        pillar_strategy_map=runtime_config.pillar_strategy_map,
    )
    return service.discover_and_select_today_topic()
