from __future__ import annotations

import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def main() -> None:
    enabled = os.getenv("ENABLE_AI_PIPELINE", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        logger.info(
            "AiTopicPipeline is disabled for news-only operation. Set ENABLE_AI_PIPELINE=true only when AI posting is intentionally re-enabled."
        )
        print(json.dumps({"status": "skipped", "reason": "ai_pipeline_disabled_news_only"}, ensure_ascii=False, indent=2))
        return

    from blogspot_automation.pipelines.ai_pipeline import AiTopicPipeline

    dry_run = os.getenv("DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}
    auto_publish = os.getenv("AUTO_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"}
    disable_image_generation = os.getenv("DISABLE_IMAGE_GENERATION", "true").strip().lower() in {"1", "true", "yes", "on"}
    disable_image_upload = os.getenv("DISABLE_IMAGE_UPLOAD", "true").strip().lower() in {"1", "true", "yes", "on"}

    logger.info(
        "AiTopicPipeline start | dry_run=%s auto_publish=%s disable_image=%s/%s",
        dry_run, auto_publish, disable_image_generation, disable_image_upload,
    )

    force_topic = os.getenv("AI_FORCE_TOPIC", "").strip()

    pipeline = AiTopicPipeline(
        dry_run=dry_run,
        auto_publish=auto_publish,
        disable_image_generation=disable_image_generation,
        disable_image_upload=disable_image_upload,
        _force_topic=force_topic,
    )
    result = pipeline.run_once()

    print(json.dumps(result, ensure_ascii=False, indent=2))

    logger.info("=== AiTopicPipeline Summary ===")
    logger.info("  status             : %s", result.get("status"))
    logger.info("  source_url         : %s", result.get("source_url", ""))
    logger.info("  source_title       : %s", result.get("source_title", ""))
    logger.info("  already_rewritten  : %s", result.get("already_rewritten", False))
    logger.info("  article_candidate  : %s", result.get("article_candidate_generated"))
    logger.info("  geo_ready          : %s", result.get("geo_ready"))
    logger.info("  publish_mode       : %s", "dry_run" if dry_run else "publish")
    logger.info("  auto_publish       : %s", auto_publish)
    logger.info("  publish_attempted  : %s", result.get("publish_attempted", False))
    logger.info("  publish_succeeded  : %s", result.get("publish_succeeded", False))
    logger.info("  blogger_url        : %s", result.get("blogger_url", ""))
    if result.get("skip_reason"):
        logger.info("  skip_reason        : %s", result.get("skip_reason"))
    if result.get("error"):
        logger.error("  error              : %s", result.get("error"))


if __name__ == "__main__":
    main()
