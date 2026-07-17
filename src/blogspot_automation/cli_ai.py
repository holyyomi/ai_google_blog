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
    """Compatibility entrypoint.

    The old AiTopicPipeline used Naver Blog RSS as its first source. That path is
    intentionally retired: this command now delegates to the fresh-news
    pipeline so scheduled AI posts are selected from current AI/news discovery
    sources, not from previously published Naver Blog posts.
    """
    # 로컬 실행에서 .env의 LLM 키 로드 (Actions는 workflow env 주입이라 no-op).
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception as _dotenv_exc:  # noqa: BLE001
        logger.debug("dotenv load skipped: %s", _dotenv_exc)

    os.environ.setdefault("NEWS_MODE", "news")
    os.environ.setdefault("AI_BLOG_MODE", "true")
    # 2026-07-17 영어 전환: holyyomiai 블로그는 영어권(미국·영국·캐나다·인도) 대상
    # 영어 AI 블로그다. ai_blog.yml 스케줄이 이 엔트리포인트를 쓰므로 여기 기본값이
    # 곧 운영값이다 (BLOG_LANGUAGE=ko를 명시하면 옛 한국어 동작으로 복귀).
    os.environ.setdefault("BLOG_LANGUAGE", "en")
    os.environ.setdefault("ALLOW_AI_NEWS_TOPICS", "true")
    os.environ.setdefault("ENABLE_NAVER_SEARCH", "false")
    os.environ.setdefault("ENABLE_NAVER_DATALAB", "false")
    os.environ.setdefault("ENABLE_COVER_IMAGE_AUTOGEN", "false")
    os.environ.setdefault("REQUIRE_NEWS_COVER_IMAGE", "false")

    force_topic = os.getenv("AI_FORCE_TOPIC", "").strip()
    if force_topic:
        logger.warning("AI_FORCE_TOPIC is ignored by cli_ai; use workflow_dispatch on cli_news for manual topic tests.")

    from blogspot_automation.cli_news import run_news_cycle

    logger.info("cli_ai delegated to NewsPipeline fresh AI/news discovery")
    result = run_news_cycle()

    print(json.dumps(result, ensure_ascii=False, indent=2))

    logger.info("=== Fresh AI NewsPipeline Summary ===")
    logger.info("  status             : %s", result.get("status"))
    logger.info("  selected_topic     : %s", result.get("selected_topic", ""))
    logger.info("  selected_title     : %s", result.get("selected_title", ""))
    logger.info("  article_candidate  : %s", result.get("article_candidate_generated"))
    logger.info("  geo_ready          : %s", result.get("geo_ready"))
    logger.info("  publish_mode       : %s", os.getenv("NEWS_PUBLISH_MODE", "dry_run"))
    logger.info("  auto_publish       : %s", os.getenv("AUTO_PUBLISH", "false"))
    logger.info("  publish_attempted  : %s", result.get("publish_attempted", False))
    logger.info("  publish_succeeded  : %s", result.get("publish_succeeded", False))
    logger.info("  blogger_url        : %s", result.get("blogger_url", "") or result.get("post_url", ""))
    if result.get("skip_reason"):
        logger.info("  skip_reason        : %s", result.get("skip_reason"))
    if result.get("error"):
        logger.error("  error              : %s", result.get("error"))


if __name__ == "__main__":
    main()
