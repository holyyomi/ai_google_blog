from __future__ import annotations

import json
import os
from pathlib import Path
import sys

root_dir = Path(__file__).resolve().parents[2]
if str(root_dir / "src") not in sys.path:
    sys.path.insert(0, str(root_dir / "src"))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stderr,
)
_logger = logging.getLogger(__name__)

# 로컬 실행에서 .env의 LLM/검색 키를 os.environ으로 로드 — 이게 없으면 로컬에서는
# provider 키가 안 보여 슬롯 LLM 보강이 조용히 정적 템플릿으로 폴백된다.
# GitHub Actions는 workflow env로 키를 직접 주입하므로 no-op. CLI 진입점에서만
# 로드한다 (라이브러리/테스트 프로세스에 키가 새어 들어가면 안 됨).
try:
    from dotenv import load_dotenv
    load_dotenv(root_dir / ".env")
except Exception as _dotenv_exc:  # noqa: BLE001 — dotenv 부재/실패는 비치명
    _logger.debug("dotenv load skipped: %s", _dotenv_exc)

from blogspot_automation.config.settings import Settings
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.contrarian_content_service import ContrarianContentService
from blogspot_automation.services.external_news_search_service import (
    ExternalNewsSearchConfig,
    ExternalNewsSearchService,
)
from blogspot_automation.services.llm_content_service import LlmContentService
from blogspot_automation.services.news_scoring_service import NewsScoringService
from blogspot_automation.services.news_publish_service import NewsPublishService
from blogspot_automation.services.news_topic_service import NewsTopicService
from blogspot_automation.services.run_artifact_service import RunArtifactService
from blogspot_automation.services.title_generation_service import TitleGenerationService
from blogspot_automation.services.topic_dedup_service import TopicDedupService


def run_news_cycle() -> dict[str, object]:
    settings = Settings.from_env()

    google_api_key = (settings.google_search_api_key or "").strip()
    google_search_cx = (settings.google_search_cx or "").strip()
    external_search_service = ExternalNewsSearchService(
        ExternalNewsSearchConfig(
            naver_client_id=(settings.naver_client_id or "").strip(),
            naver_client_secret=(settings.naver_client_secret or "").strip(),
            tavily_api_key=(settings.tavily_api_key or "").strip(),
            exa_api_key=(settings.exa_api_key or "").strip(),
            firecrawl_api_key=(settings.firecrawl_api_key or "").strip(),
            enable_naver_search=settings.enable_naver_search,
            enable_naver_datalab=settings.enable_naver_datalab,
            enable_tavily_search=settings.enable_tavily_search,
            enable_exa_search=settings.enable_exa_search,
            enable_firecrawl_search=settings.enable_firecrawl_search,
            naver_search_types=tuple(
                part.strip()
                for part in settings.news_naver_search_types.split(",")
                if part.strip()
            ),
            naver_max_requests=settings.news_naver_max_requests,
            naver_display=settings.news_naver_display,
            naver_datalab_max_requests=settings.news_naver_datalab_max_requests,
            tavily_max_requests=settings.news_tavily_max_requests,
            exa_max_requests=settings.news_exa_max_requests,
            firecrawl_max_requests=settings.news_firecrawl_max_requests,
        )
    )

    topic_service = NewsTopicService(
        api_key=google_api_key,
        search_cx=google_search_cx,
        candidate_limit=settings.topic_candidate_limit,
        enable_custom_search=settings.enable_google_custom_search,
        external_search_service=external_search_service,
        excluded_query_groups=[
            group.strip()
            for group in settings.news_excluded_query_groups.split(",")
            if group.strip()
        ],
    )
    scoring_service = NewsScoringService(min_topic_score=settings.min_topic_score)
    dedup_service = TopicDedupService(state_dir="state", dedup_days=settings.dedup_days)
    title_service = TitleGenerationService(title_candidate_count=settings.title_candidate_count)
    content_service = ContrarianContentService()

    # LLM content service: Gemini API first, OpenAI API fallback.
    llm_content_service = LlmContentService(
        google_search_api_key=google_api_key or "",
        google_search_cx=google_search_cx or "",
        enable_custom_search=settings.enable_google_custom_search,
    )

    artifact_service = RunArtifactService(runs_dir=settings.runs_dir)
    news_publish_mode = settings.news_publish_mode if settings.news_publish_mode in {"dry_run", "publish"} else "dry_run"
    publish_service = None
    if settings.auto_publish and not settings.dry_run and news_publish_mode == "publish":
        publish_service = NewsPublishService(settings=settings)

    pipeline = NewsPipeline(
        topic_service=topic_service,
        scoring_service=scoring_service,
        dedup_service=dedup_service,
        title_service=title_service,
        content_service=content_service,
        llm_content_service=llm_content_service,
        artifact_service=artifact_service,
        publish_service=publish_service,
        dry_run=settings.dry_run,
        news_publish_mode=news_publish_mode,
        auto_publish=settings.auto_publish,
    )
    return pipeline.run_with_retries()


def main() -> int:
    result = run_news_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 발행 로그 요약
    _logger.info("=== NewsPipeline Summary ===")
    _logger.info("  status                   : %s", result.get("status"))
    _logger.info("  selected_topic           : %s", result.get("selected_topic", ""))
    _logger.info("  fallback_used            : %s", bool(result.get("fallback_reason")))
    _logger.info("  fallback_type            : %s", result.get("fallback_reason", ""))
    _logger.info("  article_candidate_gen    : %s", result.get("article_candidate_generated"))
    _logger.info("  publish_ready            : %s", result.get("publish_ready"))
    _logger.info("  geo_ready                : %s", result.get("geo_ready"))
    _logger.info("  sge_ready                : %s", result.get("sge_ready"))
    _logger.info("  hold_reason              : %s", result.get("publish_hold_reason", ""))
    _logger.info("  publish_mode             : %s", os.getenv("NEWS_PUBLISH_MODE", "dry_run"))
    _logger.info("  auto_publish             : %s", os.getenv("AUTO_PUBLISH", "false"))
    _logger.info("  publish_attempted        : %s", result.get("publish_attempted", False))
    _logger.info("  publish_succeeded        : %s", result.get("publish_succeeded", False))
    _logger.info("  blogger_url              : %s", result.get("blogger_url", ""))

    if result.get("status") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
