"""Blogger 글 일회성 삭제 — 환경변수 POST_IDS(쉼표구분)의 글을 삭제한다.

BloggerClient.delete_post(공개 메서드)를 그대로 재사용한다(client.py 미수정).
실행:
  PYTHONPATH=src POST_IDS="123,456" python scripts/delete_blog_posts.py
"""
from __future__ import annotations

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
    raw = os.getenv("POST_IDS", "").strip()
    post_ids = [p.strip() for p in raw.split(",") if p.strip()]
    if not post_ids:
        logger.error("POST_IDS 환경변수가 비어 있습니다. 예: POST_IDS='123,456'")
        sys.exit(1)

    from blogspot_automation.config import Settings
    from blogspot_automation.publishing.client import BloggerClient

    client = BloggerClient(Settings.from_env())

    ok, fail = 0, 0
    for pid in post_ids:
        try:
            result = client.delete_post(pid)
            if result:
                logger.info("삭제 성공: post_id=%s", pid)
                ok += 1
            else:
                logger.warning("삭제 실패(응답 false): post_id=%s", pid)
                fail += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("삭제 예외: post_id=%s err=%s", pid, exc)
            fail += 1

    logger.info("=== 삭제 완료: 성공 %d / 실패 %d ===", ok, fail)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
