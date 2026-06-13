# -*- coding: utf-8 -*-
"""네이버 블로그 → 블로그스팟 자동화 파이프라인.

실행: python -m blogspot_automation.cli_naver
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date as _date
from pathlib import Path

root_dir = Path(__file__).resolve().parents[2]
if str(root_dir / "src") not in sys.path:
    sys.path.insert(0, str(root_dir / "src"))

from blogspot_automation.app.runtime import build_service_runtime
from blogspot_automation.services.naver_blog_service import fetch_latest_unprocessed, mark_processed
from blogspot_automation.services.blog_package_service import (
    build_preview_html,
    cleanup_blogger_placeholders,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("cli_naver")

MIN_PUBLISH_SCORE = 5


def run_naver_cycle() -> None:
    enabled = os.getenv("ENABLE_NAVER_AI_PIPELINE", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        logger.info(
            "Naver AI rewrite pipeline is disabled. Set ENABLE_NAVER_AI_PIPELINE=true only when AI posting is intentionally re-enabled."
        )
        return

    logger.info("🚀 네이버 블로그 → 블로그스팟 파이프라인 시작")
    cwd = Path(".")
    services = build_service_runtime(root_dir=cwd)

    # ── 1. 네이버 미처리 글 확인 ────────────────────────────────────
    logger.info("📡 Step 1: 네이버 블로그 신규 글 확인...")
    post = fetch_latest_unprocessed()
    if post is None:
        logger.info("새 글 없음 — 종료")
        return
    logger.info("원고 확보: %s (%d자)", post.title, len(post.full_text))

    # ── 2. AI 재작성 (블로그스팟 SEO/AEO/GEO/SGE 최적화) ────────────
    logger.info("✍️  Step 2: 블로그스팟 최적화 버전 생성 중...")
    ai_svc = services.ai_content_service
    if ai_svc is None:
        logger.error("ai_content_service 초기화 실패")
        return
    wid = ai_svc.generate_from_naver_post(post)
    logger.info("콘텐츠 생성 완료: wid=%s", wid)

    # ── 3. 패키지 빌드 ──────────────────────────────────────────────
    logger.info("📦 Step 3: 패키지 빌드...")
    services.package_service.build_package(work_item_id=wid)

    # ── 4. 플레이스홀더 정리 ─────────────────────────────────────────
    logger.info("🧹 Step 4: 플레이스홀더 정리...")
    work_item = services.work_repo.get_by_id(wid)
    if work_item and work_item.article_html:
        html = cleanup_blogger_placeholders(work_item.article_html)

        work_item.article_html = html
        services.work_repo.upsert(work_item)

        pkg = services.package_repo.get_by_work_item_id(wid)
        if pkg:
            pkg.article_html = html
            pkg.article_preview_html = build_preview_html(html, pkg.final_title)
            services.package_repo.upsert(pkg)

    # ── 5. QA ───────────────────────────────────────────────────────
    logger.info("🔍 Step 5: QA 검토...")
    qa = services.qa_service.qa_review(work_item_id=wid)
    logger.info("QA 점수: %s / 결과: %s", qa.qa_score, qa.qa_result)

    # ── 6. 발행 ─────────────────────────────────────────────────────
    if qa.qa_score >= MIN_PUBLISH_SCORE:
        logger.info("🚀 Step 6: 블로그스팟 발행 (QA %s점)...", qa.qa_score)
        if qa.issues:
            logger.warning("QA 이슈: %s", qa.issues)
        services.publish_service.publish(
            work_item_id=wid, publish_mode="public", manual_soft_fail_approval=True
        )
        status = services.publish_service.get_publish_status(work_item_id=wid)
        status_val = status.get("status", "published") if isinstance(status, dict) else "published"
        logger.info("🎉 발행 완료! status=%s", status_val)

        # 네이버 글 처리 완료 기록
        mark_processed(post)

        # published_history.json 오늘 항목 마킹
        try:
            _history_path = root_dir / "data" / "published_history.json"
            _history: list[dict] = (
                json.loads(_history_path.read_text(encoding="utf-8"))
                if _history_path.exists() else []
            )
            for entry in reversed(_history):
                if entry.get("date") == _date.today().isoformat():
                    entry["published"] = True
                    break
            _history_path.write_text(
                json.dumps(_history, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("published_history.json 업데이트 실패: %s", exc)
    else:
        logger.warning(
            "⚠️  발행 차단: QA %s점 < 최소 %s점. Issues: %s",
            qa.qa_score, MIN_PUBLISH_SCORE, qa.issues,
        )


if __name__ == "__main__":
    try:
        run_naver_cycle()
    except Exception as exc:
        logger.error("❌ 치명적 오류: %s", exc, exc_info=True)
        sys.exit(1)
