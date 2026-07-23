from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape, unescape
import logging
import os
import json
from pathlib import Path
import random
import re
import traceback
from typing import Any, Protocol

from blogspot_automation.models.news_models import (
    NewsCandidate,
    ScoredNewsCandidate,
    SelectedNewsPlan,
    TitleCandidate,
)
from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.kst_clock import kst_today
from blogspot_automation.services.contrarian_content_service import ContrarianContentService
from blogspot_automation.services.evergreen_topic_service import EvergreenTopicService
from blogspot_automation.services.answer_engine_policy import ensure_answer_engine_optimized_html
from blogspot_automation.services.cover_image_policy import cover_image_url_from_env, ensure_cover_image_html
from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService
from blogspot_automation.services.issue_content_profile_service import IssueContentProfileService
from blogspot_automation.services.title_candidate_service import TitleCandidateService
from blogspot_automation.services.news_focus_policy import evaluate_news_focus
from blogspot_automation.services.news_image_prompt_service import NewsImagePromptService
from blogspot_automation.services.news_label_service import NewsLabelService, en_content_family
from blogspot_automation.services.news_quality_gate import NewsQualityGate
from blogspot_automation.services.news_scoring_service import NewsScoringService
from blogspot_automation.services.news_topic_service import NewsTopicService
from blogspot_automation.services.post_publish_audit_service import fetch_and_audit_post
from blogspot_automation.services.publish_history_service import PublishHistoryService
from blogspot_automation.services.reader_first_layout_service import reorder_for_reader_first
from blogspot_automation.services.run_artifact_service import RunArtifactService
from blogspot_automation.services.seo_policy import (
    append_hashtags_block,
    build_english_permalink_slug,
    build_internal_links_from_history,
    normalize_hashtags,
    normalize_labels,
    normalize_search_description,
    prepare_blogspot_html,
)
from blogspot_automation.services.title_generation_service import TitleGenerationService
from blogspot_automation.services.topic_dedup_service import TopicDedupService
from blogspot_automation.utils.html_meta import extract_meta_description

logger = logging.getLogger(__name__)

_HISTORY_RECORDABLE_STATUSES: frozenset[str] = frozenset({
    "published",
    "trending_published",
    "blocked_by_quality_gate",
    "blocked_fallback_candidate",
    "held_for_review",
    "held_no_real_news_publish_candidate",
    "skipped",
    "skipped_after_retry_limit",
    "skipped_duplicate",
    "blocked_by_post_publish_audit",
    "trending_held_for_review",
    "trending_publish_failed",
    "failed",
    "draft_saved_for_review",
})


class NewsPublisher(Protocol):
    def publish(
        self,
        *,
        title: str,
        article_html: str,
        labels: list[str],
        meta_description: str = "",
        selected_topic: str = "",
        total_score: int | None = None,
        click_potential_score: int | None = None,
        topic_group: str = "",
        image_alt_text: str = "",
        is_draft: bool = False,
    ) -> Any:
        ...


class NewsPipeline:
    def __init__(
        self,
        *,
        topic_service: NewsTopicService | None = None,
        scoring_service: NewsScoringService | None = None,
        dedup_service: TopicDedupService | None = None,
        title_service: TitleGenerationService | None = None,
        content_service: ContrarianContentService | None = None,
        llm_content_service: Any | None = None,
        evergreen_topic_service: EvergreenTopicService | None = None,
        image_prompt_service: NewsImagePromptService | None = None,
        label_service: NewsLabelService | None = None,
        artifact_service: RunArtifactService | None = None,
        publish_history_service: PublishHistoryService | None = None,
        publish_service: NewsPublisher | None = None,
        dry_run: bool = True,
        news_publish_mode: str = "dry_run",
        auto_publish: bool | None = None,
    ) -> None:
        self.topic_service = topic_service or NewsTopicService()
        self.scoring_service = scoring_service or NewsScoringService()
        self.dedup_service = dedup_service or TopicDedupService()
        self.title_service = title_service or TitleGenerationService()
        self.content_service = content_service or ContrarianContentService()
        self.llm_content_service = llm_content_service  # LLM 기반 생성 (우선)
        self.evergreen_topic_service = evergreen_topic_service or EvergreenTopicService()
        self.image_prompt_service = image_prompt_service or NewsImagePromptService()
        self.label_service = label_service or NewsLabelService()
        self.artifact_service = artifact_service or RunArtifactService()
        self.publish_history_service = publish_history_service or PublishHistoryService()
        self.quality_gate = NewsQualityGate()
        self.golden_preview_service = GoldenArticlePreviewService()
        self.issue_profile_service = IssueContentProfileService()
        self.title_candidate_service = TitleCandidateService()
        self.publish_service = publish_service
        self.dry_run = dry_run
        self.news_publish_mode = (news_publish_mode or "dry_run").strip().lower()
        self.auto_publish = (
            os.getenv("AUTO_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"}
            if auto_publish is None
            else bool(auto_publish)
        )
        # 수동 publish 리허설을 라이브 대신 Blogger 초안으로 보낸다.
        # 배경: ai_blog.yml의 workflow_dispatch publish 모드는 스케줄과 똑같이
        # 라이브에 발행한다. PR 개발 중 이 "리허설"들이 실제 글을 라이브에 쌓아
        # 중복(예: 네이버 AI 3연속)을 만들었다. NEWS_PUBLISH_AS_DRAFT=true면
        # 최종 발행 계약까지 동일하게 검증하되 글은 초안으로만 남아 라이브 오염 0.
        # 스케줄 발행은 이 값을 세팅하지 않으므로 항상 라이브.
        self.publish_as_draft = (
            os.getenv("NEWS_PUBLISH_AS_DRAFT", "").strip().lower() in {"1", "true", "yes", "on"}
        )
        seed = os.getenv("NEWS_TOPIC_SELECTION_SEED", "").strip()
        self._selection_random_seed = seed or f"{datetime.now(timezone.utc).isoformat()}:{os.getpid()}:{id(self)}"
        self._retry_excluded_topics: list[str] = []
        self._current_retry_attempt = 0

    def run_with_retries(self, *, max_attempts: int | None = None) -> dict[str, Any]:
        attempts_limit = self._publish_attempt_limit(max_attempts)
        if self.dry_run or self.news_publish_mode != "publish" or attempts_limit <= 1:
            return self.run_once()

        original_excluded = list(self._retry_excluded_topics)
        retry_attempts: list[dict[str, Any]] = []
        last_result: dict[str, Any] = {}
        pool_exhausted = False
        consecutive_no_candidate = 0
        try:
            self._retry_excluded_topics = list(dict.fromkeys(original_excluded))
            for attempt in range(1, attempts_limit + 1):
                self._current_retry_attempt = attempt
                result = self.run_once()
                result["retry_attempt"] = attempt
                result["max_publish_attempts"] = attempts_limit
                last_result = result
                retry_attempts.append(self._retry_attempt_summary(result, attempt))

                if self._publish_result_succeeded(result):
                    result["retry_attempts"] = retry_attempts
                    return result

                if not self._should_retry_publish_result(result):
                    result["retry_attempts"] = retry_attempts
                    return result

                # 후보 풀 소진 감지 (2026-07-10 실측): 제외 목록 누적 후 후보가 0이
                # 되면 이후 시도는 전부 같은 빈 결과다 — 남은 시도를 공회전으로
                # 소모하지 않는다(12회 한도에서 9회 낭비 실측). 수집 소스가 시도마다
                # 미세하게 달라질 수 있어 1회는 봐주고, 연속 2회 비면 중단.
                if str(result.get("status") or "") == "skipped" and not str(
                    result.get("selected_topic") or ""
                ).strip():
                    consecutive_no_candidate += 1
                    if consecutive_no_candidate >= 2:
                        pool_exhausted = True
                        logger.info(
                            "NewsPipeline: candidate pool exhausted after attempt %d/%d — stopping retries early",
                            attempt,
                            attempts_limit,
                        )
                        break
                else:
                    consecutive_no_candidate = 0

                retry_exclusions = self._retry_exclusion_keys_from_result(result)
                for key in retry_exclusions:
                    if key not in self._retry_excluded_topics:
                        self._retry_excluded_topics.append(key)
                topic = str(result.get("selected_topic") or "").strip()
                if attempt < attempts_limit:
                    logger.info(
                        "NewsPipeline: retrying with another candidate after attempt %d/%d status=%s topic=%s excluded_keys=%d",
                        attempt,
                        attempts_limit,
                        result.get("status"),
                        topic[:80],
                        len(retry_exclusions),
                    )

            final_result = {
                "status": "skipped_after_retry_limit",
                "reason": (
                    "candidate_pool_exhausted" if pool_exhausted else "max_publish_attempts_exhausted"
                ),
                "retry_attempts": retry_attempts,
                "max_publish_attempts": attempts_limit,
                "publish_attempted": any(item.get("publish_attempted") for item in retry_attempts),
                "publish_succeeded": False,
                "dry_run": self.dry_run,
                "news_publish_mode": self.news_publish_mode,
                "selected_topic": last_result.get("selected_topic", ""),
                "selected_title": last_result.get("selected_title", ""),
                "topic_group": last_result.get("topic_group", ""),
                "content_angle": last_result.get("content_angle", {}),
                "publish_quality_gate": last_result.get("publish_quality_gate", {}),
                "blocking_issues": last_result.get("blocking_issues")
                or (last_result.get("publish_quality_gate") or {}).get("blocking_issues", []),
                "last_status": last_result.get("status", ""),
                "last_artifact_dir": last_result.get("artifact_dir", ""),
            }
            artifact_dir = self.artifact_service.save_status_result(
                status_payload=final_result,
                run_meta={
                    "pipeline": "news_pipeline",
                    "mode": self.news_publish_mode,
                    "dry_run": self.dry_run,
                    "status": "skipped_after_retry_limit",
                    "reason": str(final_result.get("reason") or "max_publish_attempts_exhausted"),
                    "max_publish_attempts": attempts_limit,
                    "retry_attempts": retry_attempts,
                },
            )
            final_result["artifact_dir"] = str(artifact_dir)
            final_result["history_recorded"] = self._try_record_history(
                status="skipped_after_retry_limit",
                result=final_result,
            )
            return final_result
        finally:
            self._retry_excluded_topics = original_excluded
            self._current_retry_attempt = 0

    @staticmethod
    def _publish_attempt_limit(max_attempts: int | None = None) -> int:
        if max_attempts is not None:
            return max(1, int(max_attempts))
        raw = os.getenv("NEWS_MAX_PUBLISH_ATTEMPTS", "1").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning("Invalid NEWS_MAX_PUBLISH_ATTEMPTS=%r, using 1", raw)
            return 1

    @staticmethod
    def _publish_result_succeeded(result: dict[str, Any]) -> bool:
        status = str(result.get("status") or "")
        return bool(result.get("publish_succeeded")) or status in {"published", "trending_published"}

    def _should_retry_publish_result(self, result: dict[str, Any]) -> bool:
        if self.dry_run or self.news_publish_mode != "publish":
            return False
        status = str(result.get("status") or "")
        retryable_statuses = {
            "blocked_by_quality_gate",
            "blocked_fallback_candidate",
            "held_for_review",
            "skipped_duplicate",
            "blocked_by_post_publish_audit",
            "trending_held_for_review",
            "trending_publish_failed",
        }
        if status in retryable_statuses:
            return True
        if status == "skipped" and str(result.get("reason") or "") in {
            "no_golden_publish_candidate",
            "no_publishable_candidate",
        }:
            return True
        quality_gate = result.get("publish_quality_gate") or {}
        if isinstance(quality_gate, dict) and quality_gate and not bool(quality_gate.get("passed")):
            return True
        return False

    @staticmethod
    def _retry_attempt_summary(result: dict[str, Any], attempt: int) -> dict[str, Any]:
        quality_gate = result.get("publish_quality_gate") or {}
        blocking_issues = result.get("blocking_issues")
        if not blocking_issues and isinstance(quality_gate, dict):
            blocking_issues = quality_gate.get("blocking_issues", [])
        return {
            "attempt": attempt,
            "status": result.get("status", ""),
            "selected_topic": result.get("selected_topic", ""),
            "selected_title": result.get("selected_title", ""),
            "blocking_issues": blocking_issues or [],
            "publish_hold_reason": result.get("publish_hold_reason", ""),
            "publish_attempted": bool(result.get("publish_attempted", False)),
            "publish_succeeded": bool(result.get("publish_succeeded", False)),
            "artifact_dir": result.get("artifact_dir", ""),
        }

    def _retry_excluded_topic_set(self) -> set[str]:
        return {
            self.dedup_service.normalize_text(str(topic).strip())
            for topic in getattr(self, "_retry_excluded_topics", [])
            if str(topic).strip() and self.dedup_service.normalize_text(str(topic).strip())
        }

    def _is_retry_excluded_candidate(self, candidate: ScoredNewsCandidate) -> bool:
        excluded = self._retry_excluded_topic_set()
        if not excluded:
            return False
        candidate_keys = self._retry_exclusion_keys_from_candidate(candidate)
        for candidate_key in candidate_keys:
            if candidate_key in excluded:
                return True
            if any(self._retry_exclusion_keys_match(candidate_key, blocked_key) for blocked_key in excluded):
                return True
        return False

    def _exclude_retry_candidates(
        self,
        candidates: list[ScoredNewsCandidate],
    ) -> list[ScoredNewsCandidate]:
        excluded = self._retry_excluded_topic_set()
        if not excluded:
            return candidates
        filtered = [
            candidate
            for candidate in candidates
            if not self._is_retry_excluded_candidate(candidate)
        ]
        skipped = len(candidates) - len(filtered)
        if skipped:
            logger.info("NewsPipeline: excluded %d failed retry candidate(s)", skipped)
        return filtered

    def _retry_exclusion_keys_from_result(self, result: dict[str, Any]) -> list[str]:
        values: list[Any] = [
            result.get("selected_topic"),
            result.get("selected_title"),
            result.get("search_demand_topic"),
            result.get("original_topic"),
            result.get("source_title"),
        ]
        search_angle = result.get("search_angle")
        if isinstance(search_angle, dict):
            values.extend(
                [
                    search_angle.get("search_demand_topic"),
                    search_angle.get("original_topic"),
                    search_angle.get("transformed_topic"),
                    search_angle.get("source_title"),
                ]
            )
        content_angle = result.get("content_angle")
        if isinstance(content_angle, dict):
            values.extend(
                [
                    content_angle.get("search_demand_topic"),
                    content_angle.get("original_topic"),
                    content_angle.get("transformed_topic"),
                    content_angle.get("source_title"),
                ]
            )
        # 주의: 과거에는 top_scored_candidates 전체를 배제 목록에 넣었는데,
        # 한 후보의 게이트 실패가 "그 실행의 상위 후보 전부"를 퍼지 매칭으로
        # 태워버려 재시도 2회 만에 풀이 고갈됐다(2026-07-19~20 발행 0건 사슬).
        # 재시도 배제는 실제로 시도해 실패한 주제(선택된 주제와 그 변형 각도)로만
        # 한정한다 — 실제 중복은 어차피 dedup/품질 게이트가 다시 걸러낸다.
        return self._normalize_retry_exclusion_values(values)

    def _retry_exclusion_keys_from_candidate(self, candidate: ScoredNewsCandidate) -> list[str]:
        raw = candidate.candidate.raw if isinstance(candidate.candidate.raw, dict) else {}
        values: list[Any] = [
            candidate.candidate.topic,
            raw.get("search_demand_topic"),
            raw.get("original_topic"),
            raw.get("transformed_topic"),
            raw.get("source_title"),
            raw.get("title"),
        ]
        search_angle = raw.get("search_angle")
        if isinstance(search_angle, dict):
            values.extend(
                [
                    search_angle.get("search_demand_topic"),
                    search_angle.get("original_topic"),
                    search_angle.get("transformed_topic"),
                    search_angle.get("source_title"),
                ]
            )
        content_angle = raw.get("content_angle")
        if isinstance(content_angle, dict):
            values.extend(
                [
                    content_angle.get("search_demand_topic"),
                    content_angle.get("original_topic"),
                    content_angle.get("transformed_topic"),
                    content_angle.get("source_title"),
                ]
            )
        return self._normalize_retry_exclusion_values(values)

    def _normalize_retry_exclusion_values(self, values: list[Any]) -> list[str]:
        keys: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            normalized = self.dedup_service.normalize_text(text)
            if normalized and len(normalized) >= 4:
                keys.append(normalized)
        return list(dict.fromkeys(keys))

    def _retry_exclusion_keys_match(self, candidate_key: str, blocked_key: str) -> bool:
        if candidate_key == blocked_key:
            return True
        shorter, longer = sorted((candidate_key, blocked_key), key=len)
        if len(shorter) >= 8 and shorter in longer:
            return True
        candidate_keywords = self.dedup_service.extract_keywords(candidate_key)
        blocked_keywords = self.dedup_service.extract_keywords(blocked_key)
        if not candidate_keywords or not blocked_keywords:
            return False
        overlap = candidate_keywords & blocked_keywords
        required_overlap = 3 if min(len(candidate_keywords), len(blocked_keywords)) >= 3 else 2
        return len(overlap) >= required_overlap

    def run_once(self) -> dict[str, Any]:
        try:
            # 깨끗한 트렌딩 선형 경로 우선 시도 (실패/없음 시 기존 파이프라인 폴백).
            _clean = self._run_clean_trending_publish()
            if _clean is not None:
                return _clean

            candidates = self.topic_service.collect_candidates()
            ai_blog_mode = str(os.getenv("AI_BLOG_MODE", "false")).strip().lower() in {"1", "true", "yes", "on"}

            # Trending News — 네이버 인기 기사 페이지에서 실제 클릭 데이터 수집.
            # IssueDiscoveryService(Google News broad scan + 추정 buzz)와 보완.
            # 사용자 선호 반영: 대기업 corporate(노조/공시/총수) 후순위.
            if ai_blog_mode:
                logger.info("AI_BLOG_MODE: broad trending/discovery 후보 주입 건너뜀")
                # 커뮤니티 언급량 기반 이슈 AI 후보 주입 (2026-07-20, 운영자 요청):
                # "사람들이 가장 많이 언급하는 AI"를 Reddit hot + HN Algolia에서
                # 직접 수집한다. 뉴스 RSS 헤드라인(보도자료형)과 달리 실제 토론량
                # (score/댓글수)이 실린 후보라 검색 수요의 선행 지표가 된다.
                try:
                    from blogspot_automation.services.community_topic_service import (
                        collect_community_topics,
                    )
                    _community_topics = collect_community_topics(max_items=20)
                    _community_candidates = []
                    for _ct in _community_topics:
                        _ct_title = (_ct.title or "").strip()
                        if not _ct_title:
                            continue
                        _ct_source_type = (
                            "community_reddit"
                            if _ct.source.startswith("reddit")
                            else "community_hackernews"
                        )
                        _ct_published = datetime.fromtimestamp(
                            _ct.created_utc, tz=timezone.utc
                        ).isoformat(timespec="seconds")
                        from blogspot_automation.utils.text_clip import (
                            clip_at_word_boundary as _clip_wb,
                        )
                        _community_candidates.append(
                            NewsCandidate(
                                topic=_clip_wb(_ct_title, 90),
                                category="today_issue",
                                summary=_ct_title,
                                source_hint=_ct.source,
                                published_at=_ct_published,
                                url=_ct.url or None,
                                raw={
                                    "source_type": _ct_source_type,
                                    "query": "community_mentions",
                                    "query_group": "community_mentions",
                                    "parsed_pub_date": _ct_published,
                                    "is_stale": False,
                                    "source": _ct.source,
                                    "original_title": _ct_title,
                                    "cleaned_title": _ct_title,
                                    "community_mention_score": int(_ct.mention_score),
                                    "community_comments": int(_ct.comments),
                                },
                            )
                        )
                    if _community_candidates:
                        logger.info(
                            "community_topics: %d개 커뮤니티 언급 후보 주입 (reddit/hn)",
                            len(_community_candidates),
                        )
                        candidates = _community_candidates + candidates
                except Exception as _comm_exc:  # noqa: BLE001
                    logger.warning("community_topic_service failed: %s", _comm_exc)

                # 실검색 AI 트렌드 후보 (2026-07-23): 고정 에버그린 뱅크가 엔티티
                # 쿨다운/dedup에 막혀 소진되는 날에도 "후보 없음 → 스킵" 대신
                # 오늘 실제 검색 수요가 있는 AI 주제로 후보를 만든다. 기존 품질/
                # 사실안전 게이트는 그대로 적용 — 여기서 통과 못 해도 그냥 탈락.
                try:
                    from blogspot_automation.services.live_ai_demand_topic_service import (
                        collect_live_ai_demand_candidates,
                    )
                    _live_demand_candidates = collect_live_ai_demand_candidates(max_candidates=3)
                    if _live_demand_candidates:
                        logger.info(
                            "live_ai_demand: %d개 실검색 AI 트렌드 후보 주입",
                            len(_live_demand_candidates),
                        )
                        candidates = _live_demand_candidates + candidates
                except Exception as _live_exc:  # noqa: BLE001
                    logger.warning("live_ai_demand_topic_service failed: %s", _live_exc)
            else:
                try:
                    from blogspot_automation.services.trending_news_service import TrendingNewsService
                    _trend = TrendingNewsService()
                    _trending_candidates = _trend.collect_trending_candidates(
                        max_candidates=10, min_cluster_size=2,
                    )
                    if _trending_candidates:
                        logger.info(
                            "trending_news: %d개 실제 클릭 트렌딩 후보 추가 (corporate 후순위)",
                            len(_trending_candidates),
                        )
                        # 가장 우선 — issue_discovery보다도 앞에 prepend
                        candidates = _trending_candidates + candidates
                except Exception as _tn_exc:  # noqa: BLE001
                    logger.warning("trending_news_service failed: %s", _tn_exc)

                # Google Trends(KR) 트렌딩 키워드 → 토픽 시드. 매일 반복되는 좁은
                # 에버그린 풀을 신선한 트렌딩 토픽으로 보완 (소싱 폭 확대).
                # 정치/대기업/사건사고는 GoogleTrendsTopicService가 focus 필터로 사전 제외.
                try:
                    from blogspot_automation.services.google_trends_topic_service import GoogleTrendsTopicService
                    _gt_candidates = GoogleTrendsTopicService().collect_trending_candidates(max_candidates=12)
                    if _gt_candidates:
                        logger.info(
                            "google_trends_topic: %d개 트렌딩 토픽 시드 추가 (focus 통과)",
                            len(_gt_candidates),
                        )
                        candidates = _gt_candidates + candidates
                except Exception as _gt_exc:  # noqa: BLE001
                    logger.warning("google_trends_topic_service failed: %s", _gt_exc)

                # Real Issue Discovery Engine — broad scan + entity + cluster
                # 고정 query group이 아니라 실제 오늘 여러 매체에서 반복 등장하는 이슈 발견
                discovered_count = 0
                try:
                    from blogspot_automation.services.issue_discovery_service import IssueDiscoveryService
                    _disc = IssueDiscoveryService()
                    _discovered_issues = _disc.discover_today_issues()
                    discovered_count = len(_discovered_issues)
                    _discovered_candidates = _disc.to_news_candidates(_discovered_issues)
                    if _discovered_candidates:
                        logger.info(
                            "issue_discovery: %d issues found, %d converted to candidates (buzz/specificity/safe gate)",
                            discovered_count, len(_discovered_candidates),
                        )
                        # 발견된 후보를 기존 후보 앞에 prepend (높은 우선순위)
                        candidates = _discovered_candidates + candidates
                    else:
                        logger.info(
                            "issue_discovery: %d issues found, 0 passed strict gate", discovered_count,
                        )
                except Exception as _disc_exc:  # noqa: BLE001
                    logger.warning("issue_discovery_service failed: %s", _disc_exc)
            scored = self.scoring_service.score_candidates(candidates)
            topic_group_history = self._load_topic_group_history()
            recent_context = self._load_recent_context()
            recent_evergreen_axes = recent_context["recent_evergreen_axes"]
            recent_topic_groups_hist = recent_context["recent_topic_groups"]
            recent_content_types_hist = recent_context["recent_content_types"]
            preferred_axis = EvergreenTopicService.preferred_axis_by_weekday()
            recommended_next_axis = self._recommended_next_axis(recent_evergreen_axes)
            scored = self._apply_topic_group_cooldowns(scored, topic_group_history, recent_evergreen_axes)

            # Trending 후보 강제 score boost — cooldown 이후 적용.
            # NewsScoringService는 trending raw 메타데이터(today_buzz, click_potential)를
            # 모르므로 publishable 임계값 통과를 위해 명시 boost. corporate는 이미
            # TrendingNewsService에서 후순위라 일반 trending만 boost된다.
            if not ai_blog_mode:
                scored = self._apply_trending_score_boost(scored)
            else:
                # AI_BLOG_MODE: 신선한 실뉴스 AI 이슈 후보 부스트 — evergreen보다 항상 우선
                scored = self._apply_ai_issue_score_boost(scored)
            # Search Console 성과 루프 — 실제 검색 성과(클릭/노출) 쿼리와 겹치는
            # 후보에 가산점 (data/search_performance.json 없으면 no-op)
            scored = self._apply_search_performance_boost(scored)
            # boost 적용된 후 다시 정렬 (scored는 _apply_topic_group_cooldowns가 정렬 반환)
            scored = sorted(scored, key=lambda c: c.total_score, reverse=True)

            publishable = self.scoring_service.get_publishable_candidates(scored)
            news_candidate_count = len(candidates)
            news_publishable_count = len(publishable)
            real_news_publishable = [
                item for item in publishable if self._is_news_auto_publish_candidate(item)
            ]
            news_publishable_real_count = len(real_news_publishable)
            fallback_reason = ""
            force_viral_test = self._force_viral_issue_test()
            force_evergreen = self._force_evergreen_fallback()

            if force_viral_test:
                viral_candidates = self._extract_viral_test_candidates(scored)
                if viral_candidates:
                    # golden 매칭 후보에는 더 높은 점수 부여 → _select_diverse_candidate에서 우선 선택
                    ps = self.golden_preview_service._ps
                    for item in viral_candidates:
                        _conf = int(ps.match_pattern(topic=item.candidate.topic or "")["confidence"])
                        boosted = 92 if _conf >= 80 else 80
                        item.total_score = max(item.total_score, boosted)
                        item.candidate.raw["force_viral_score_boosted"] = True
                        item.candidate.raw["golden_pre_confidence"] = _conf
                        item.candidate.raw["click_potential_score"] = max(
                            int(item.candidate.raw.get("click_potential_score") or 0), 9
                        )
                    viral_candidates = self._sort_by_golden_confidence(viral_candidates)
                    publishable = viral_candidates
                    fallback_reason = "force_viral_issue_test"
                    logger.info("FORCE_VIRAL_ISSUE_TEST: %d viral candidate(s) promoted", len(viral_candidates))

            primary_query_count = news_candidate_count
            secondary_query_count = 0
            score_relaxed_used = False
            score_65_74_candidate_count = 0

            if (
                fallback_reason != "force_viral_issue_test"
                and not force_evergreen
                and news_publishable_real_count == 0
            ):
                # secondary query 재시도: viral/platform/consumer 집중 쿼리
                try:
                    secondary_candidates = self.topic_service.collect_secondary_candidates()
                    secondary_query_count = len(secondary_candidates)
                    if secondary_candidates:
                        secondary_scored = self.scoring_service.score_candidates(secondary_candidates)
                        secondary_scored = self._apply_topic_group_cooldowns(
                            secondary_scored, topic_group_history, recent_evergreen_axes
                        )
                        secondary_publishable = self.scoring_service.get_publishable_candidates(secondary_scored)
                        secondary_real = [
                            item for item in secondary_publishable
                            if self._is_news_auto_publish_candidate(item)
                        ]
                        if secondary_real:
                            logger.info(
                                "secondary query 재시도 성공: %d real news candidate(s)",
                                len(secondary_real),
                            )
                            # primary 결과와 합산 (중복 제거는 dedup_service에서 처리)
                            scored = secondary_scored + scored
                            publishable = secondary_real + publishable
                            real_news_publishable = secondary_real
                            news_publishable_real_count = len(real_news_publishable)
                        else:
                            # secondary scored도 메인 scored에 합산 (relaxed 후보 탐색용)
                            scored = secondary_scored + scored
                            logger.info(
                                "secondary query 재시도 후도 real news 없음 (secondary=%d candidates)",
                                secondary_query_count,
                            )
                except Exception as _sec_exc:  # noqa: BLE001
                    logger.warning("secondary query 재시도 실패: %s", _sec_exc)

            # ── relaxed retry: score 65~74 후보 생성 진입 허용 ─────────────
            # 후보 생성 기준(65)과 자동 발행 기준(publish_ready/geo_ready/sge_ready)을 분리.
            # score 65~74 후보는 article_candidate.html은 만들지만, 실제 자동 발행은
            # _evaluate_auto_publish_gate에서 publish_ready/geo_ready/sge_ready로 차단됨.
            if (
                fallback_reason != "force_viral_issue_test"
                and not force_evergreen
                and news_publishable_real_count == 0
            ):
                relaxed_eligible = self.scoring_service.get_candidate_generation_eligible(scored)
                relaxed_real_news = [
                    item for item in relaxed_eligible
                    if self._is_news_auto_publish_candidate(item)
                    and not self._is_stale_candidate(item)
                    and int(item.candidate.raw.get("risk_penalty", 0) or 0) == 0
                ]
                # score 65~74 후보 수 (auto-publish threshold 미만)
                score_65_74_candidate_count = sum(
                    1 for item in relaxed_real_news
                    if item.total_score < self.scoring_service.min_topic_score
                )
                if relaxed_real_news:
                    for _item in relaxed_real_news:
                        _raw = _item.candidate.raw if isinstance(_item.candidate.raw, dict) else {}
                        _raw["score_relaxed_for_candidate_generation"] = bool(
                            _item.total_score < self.scoring_service.min_topic_score
                        )
                        _raw["candidate_generation_threshold"] = (
                            self.scoring_service.candidate_generation_min_score
                        )
                    score_relaxed_used = score_65_74_candidate_count > 0
                    publishable = relaxed_real_news + publishable
                    real_news_publishable = relaxed_real_news
                    news_publishable_real_count = len(real_news_publishable)
                    logger.info(
                        "relaxed retry: %d real news candidate(s), score 65-74=%d, "
                        "candidate_generation only (auto-publish requires publish_ready/geo_ready/sge_ready)",
                        len(relaxed_real_news),
                        score_65_74_candidate_count,
                    )

            if fallback_reason != "force_viral_issue_test":
                if force_evergreen or news_publishable_real_count == 0:
                    fallback_reason = (
                        "forced_evergreen_fallback"
                        if force_evergreen
                        else "no_publishable_news_candidate_used_evergreen"
                    )
                    (
                        candidates,
                        scored,
                        publishable,
                    ) = self._collect_evergreen_publish_fallback_candidates(
                        topic_group_history=topic_group_history,
                        recent_evergreen_axes=recent_evergreen_axes,
                    )
                    if not publishable:
                        hold_result = self._save_no_real_news_hold_report(
                            candidates=candidates,
                            scored=scored,
                            publishable=publishable,
                            fallback_reason=(
                                "forced_evergreen_fallback_blocked"
                                if force_evergreen
                                else "no_real_news_publish_candidate"
                            ),
                            news_candidate_count=news_candidate_count,
                            news_publishable_count=news_publishable_count,
                            news_publishable_real_count=news_publishable_real_count,
                            recent_evergreen_axes=recent_evergreen_axes,
                            preferred_axis=preferred_axis,
                            recommended_next_axis=recommended_next_axis,
                            recent_topic_groups_hist=recent_topic_groups_hist,
                            recent_content_types_hist=recent_content_types_hist,
                            primary_query_count=primary_query_count,
                            secondary_query_count=secondary_query_count,
                            score_65_74_candidate_count=score_65_74_candidate_count,
                        )
                        history_recorded = self._try_record_history(
                            status="held_no_real_news_publish_candidate",
                            result={"dry_run": self.dry_run, **hold_result},
                        )
                        return {
                            "history_recorded": history_recorded,
                            **hold_result,
                        }
                else:
                    publishable = real_news_publishable
                    # 점수 우선 경쟁(2026-07-20): 뉴스 후보가 있어도 전부 수요 신호
                    # (트렌드/커뮤니티) 0이면, 에버그린 후보를 풀에 "합류"시켜
                    # total_score·다양성 기준으로 같이 경쟁시킨다. 과거에는 뉴스가
                    # 1건이라도 있으면 에버그린을 수집조차 안 해(소스 우선), 수요
                    # 없는 니치 뉴스가 항상 고수요 에버그린을 이겼다. 뉴스가 수요
                    # 신호를 갖고 있으면 기존 동작 그대로다(회귀 0).
                    if ai_blog_mode and not any(
                        int(
                            (it.candidate.raw or {}).get("demand_signal_boost") or 0
                        ) > 0
                        for it in real_news_publishable
                    ):
                        try:
                            (
                                _sf_candidates,
                                _sf_scored,
                                _sf_publishable,
                            ) = self._collect_evergreen_publish_fallback_candidates(
                                topic_group_history=topic_group_history,
                                recent_evergreen_axes=recent_evergreen_axes,
                            )
                            if _sf_publishable:
                                logger.info(
                                    "score-first: 뉴스 후보 수요 신호 0 → 에버그린 %d개 풀 합류 (점수 경쟁)",
                                    len(_sf_publishable),
                                )
                                publishable = publishable + _sf_publishable
                                scored = scored + _sf_scored
                        except Exception as _sf_exc:  # noqa: BLE001
                            logger.warning("score-first evergreen merge 실패(무시): %s", _sf_exc)
            dedup_history_records = self._dedup_history_records()
            manual_dedup_bypass = self._manual_dedup_bypass_enabled()
            if manual_dedup_bypass:
                after_dedup = list(publishable)
                logger.warning(
                    "NewsPipeline: manual dedup bypass enabled for workflow_dispatch publish run; "
                    "recent-topic dedup skipped for this run only"
                )
            else:
                after_dedup = self.dedup_service.exclude_recent_duplicates(
                    publishable,
                    history_records=dedup_history_records,
                )
            dedup_removed_count = len(publishable) - len(after_dedup)
            deduped = self._exclude_retry_candidates(after_dedup)
            retry_excluded_count = len(after_dedup) - len(deduped)
            golden_filtered_count = 0
            if deduped:
                self._annotate_golden_selection_confidence(deduped)
                golden_deduped = [
                    item for item in deduped
                    if self._candidate_golden_selection_penalty(item) == 0
                ]
                golden_filtered_count = len(deduped) - len(golden_deduped)
                deduped = golden_deduped
            top_scored_candidates = self._top_scored_candidates(scored)

            if not deduped and fallback_reason not in {
                "force_viral_issue_test",
                "forced_evergreen_fallback",
                "no_publishable_news_candidate_used_evergreen",
                "no_golden_publish_candidate_used_evergreen",
                "no_publishable_candidate_used_evergreen",
            }:
                blocked_reason = (
                    "no_golden_publish_candidate"
                    if golden_filtered_count
                    else "no_publishable_candidate"
                )
                (
                    evergreen_candidates,
                    evergreen_scored,
                    evergreen_publishable,
                ) = self._collect_evergreen_publish_fallback_candidates(
                    topic_group_history=topic_group_history,
                    recent_evergreen_axes=recent_evergreen_axes,
                )
                if manual_dedup_bypass:
                    evergreen_after_dedup = list(evergreen_publishable)
                else:
                    evergreen_after_dedup = self.dedup_service.exclude_recent_duplicates(
                        evergreen_publishable,
                        history_records=dedup_history_records,
                    )
                evergreen_deduped = self._exclude_retry_candidates(evergreen_after_dedup)
                if evergreen_deduped:
                    logger.info(
                        "NewsPipeline: %s recovered with evergreen fallback candidate(s)=%d",
                        blocked_reason,
                        len(evergreen_deduped),
                    )
                    fallback_reason = f"{blocked_reason}_used_evergreen"
                    candidates = evergreen_candidates
                    scored = evergreen_scored
                    publishable = evergreen_publishable
                    dedup_removed_count = len(evergreen_publishable) - len(evergreen_after_dedup)
                    retry_excluded_count = len(evergreen_after_dedup) - len(evergreen_deduped)
                    golden_filtered_count = 0
                    deduped = evergreen_deduped
                    top_scored_candidates = self._top_scored_candidates(scored)

            if not deduped:
                result = {
                    "status": "skipped",
                    "reason": (
                        "no_golden_publish_candidate"
                        if golden_filtered_count
                        else "no_publishable_candidate"
                    ),
                    "candidate_count": len(candidates),
                    "publishable_count": len(publishable),
                    "deduped_count": len(deduped),
                    "dedup_removed_count": dedup_removed_count,
                    "retry_excluded_count": retry_excluded_count,
                    "golden_filtered_count": golden_filtered_count,
                    "news_candidate_count": news_candidate_count,
                    "news_publishable_count": news_publishable_count,
                    "news_publishable_real_count": news_publishable_real_count,
                    "fallback_reason": fallback_reason,
                    "min_topic_score": self.scoring_service.min_topic_score,
                    "top_scored_candidates": top_scored_candidates,
                }
                artifact_dir = self.artifact_service.save_status_result(
                    status_payload=result,
                    run_meta={
                        "pipeline": "news_pipeline",
                        "mode": self.news_publish_mode,
                        "dry_run": self.dry_run,
                        "status": result["status"],
                        "reason": result["reason"],
                        "candidate_count": len(candidates),
                        "scored_count": len(scored),
                        "publishable_count": len(publishable),
                        "deduped_count": len(deduped),
                        "dedup_removed_count": dedup_removed_count,
                        "retry_excluded_count": retry_excluded_count,
                        "golden_filtered_count": golden_filtered_count,
                        "news_candidate_count": news_candidate_count,
                        "news_publishable_count": news_publishable_count,
                        "news_publishable_real_count": news_publishable_real_count,
                        "fallback_reason": fallback_reason,
                        "recent_evergreen_axes": recent_evergreen_axes[:5],
                        "preferred_axis_by_weekday": preferred_axis,
                        "recommended_next_axis": recommended_next_axis,
                        "history_recent_evergreen_axes": recent_evergreen_axes[:7],
                        "history_recent_topic_groups": recent_topic_groups_hist[:7],
                        "history_recent_content_types": recent_content_types_hist[:7],
                        "history_path": str(self.publish_history_service.history_path),
                    },
                )
                history_recorded = self._try_record_history(
                    status="skipped",
                    result={"fallback_reason": fallback_reason, "dry_run": self.dry_run},
                )
                return {
                    "artifact_dir": str(artifact_dir),
                    "history_recorded": history_recorded,
                    **result,
                }

            # ── Trending 우선 분기 — 자동발행 허용 타입과 포커스 게이트를 통과한 trending만 우선 ─
            _best_regular_score = max(
                (c.total_score for c in deduped if not self._is_trending_candidate(c)),
                default=0,
            )
            _trending_anywhere = [] if ai_blog_mode else [
                c for c in scored
                if self._is_trending_candidate(c)
                and not self._is_retry_excluded_candidate(c)
                and self._is_news_auto_publish_candidate(c)
                and not self._trending_priority_quality_issues(c)
                and c.total_score >= _best_regular_score
            ]
            if _trending_anywhere:
                selected = max(_trending_anywhere, key=lambda c: c.total_score)
                logger.info(
                    "Trending 우선 선택 (scored 단계): %s (score=%d, scored 안 trending %d개)",
                    (selected.candidate.topic or "")[:60],
                    selected.total_score, len(_trending_anywhere),
                )
                _trending_result = self._handle_trending_candidate(selected)
                if _trending_result is not None:
                    return _trending_result
                logger.warning("Trending 분기 실패 → 일반 _select_diverse_candidate 흐름으로 fallback")

            selected = self._select_diverse_candidate(deduped, topic_group_history)

            # ── stale 후보 감지 → fresh 대체 탐색 ──────────────────────────
            _replacement_meta: dict[str, Any] = {}
            if self._is_stale_candidate(selected):
                self._annotate_golden_selection_confidence(scored)
                _fresh_cand, _fresh_reason = self._find_fresh_replacement_candidate(
                    scored=scored,
                    original=selected,
                    history_records=dedup_history_records,
                    dedup_service=self.dedup_service,
                )
                _orig_raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
                if _fresh_cand:
                    _replacement_meta = {
                        "stale_candidate_replaced": True,
                        "original_stale_topic": selected.candidate.topic or "",
                        "original_stale_source_url": str(_orig_raw.get("source_url") or ""),
                        "original_stale_published_at": str(_orig_raw.get("published_at") or ""),
                        "original_stale_reason": (
                            "stale_penalty_applied"
                            if _orig_raw.get("stale_penalty_applied")
                            else "is_stale"
                        ),
                        "fresh_replacement_topic": _fresh_cand.candidate.topic or "",
                        "fresh_replacement_reason": _fresh_reason,
                        "fresh_replacement_source_url": str(
                            (_fresh_cand.candidate.raw or {}).get("source_url") or ""
                        ),
                        "fresh_replacement_published_at": str(
                            (_fresh_cand.candidate.raw or {}).get("published_at") or ""
                        ),
                        "fresh_replacement_selected": True,
                    }
                    logger.info(
                        "stale_replacement: '%s' → '%s' (%s)",
                        _replacement_meta["original_stale_topic"][:40],
                        _replacement_meta["fresh_replacement_topic"][:40],
                        _fresh_reason,
                    )
                    selected = _fresh_cand
                else:
                    # fresh replacement 없음 → fallback 탐색
                    _fallback_cand, _fallback_reason, _fallback_type = (
                        self._find_fallback_when_no_fresh_replacement(
                            scored=scored, original=selected
                        )
                    )
                    if _fallback_cand:
                        _fb_raw = _fallback_cand.candidate.raw if isinstance(
                            _fallback_cand.candidate.raw, dict
                        ) else {}
                        _replacement_meta = {
                            "stale_candidate_replaced": True,
                            "no_fresh_replacement_fallback_used": True,
                            "fallback_type": _fallback_type,
                            "fallback_reason": _fallback_reason,
                            "fallback_topic": _fallback_cand.candidate.topic or "",
                            "fallback_content_type": str(
                                (_fb_raw.get("content_angle") or {}).get("content_type") or ""
                            ),
                            "fallback_topic_group": str(_fb_raw.get("topic_group") or ""),
                            "fallback_human_review_required": True,
                            "original_stale_topic": selected.candidate.topic or "",
                            "original_stale_source_url": str(_orig_raw.get("source_url") or ""),
                            "original_stale_published_at": str(_orig_raw.get("published_at") or ""),
                            "original_stale_reason": (
                                "stale_penalty_applied"
                                if _orig_raw.get("stale_penalty_applied")
                                else "is_stale"
                            ),
                            "fresh_replacement_attempted": True,
                            "fresh_replacement_found": False,
                            "fallback_attempted": True,
                            "fallback_found": True,
                        }
                        logger.info(
                            "fallback selected: '%s' type=%s (%s)",
                            _fallback_cand.candidate.topic[:40],
                            _fallback_type,
                            _fallback_reason,
                        )
                        selected = _fallback_cand
                    else:
                        # fallback도 없음 → hold report 저장 후 조기 반환
                        _hold_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        _hold_path = (
                            Path(getattr(self.artifact_service, "runs_dir", "runs"))
                            / f"news_{_hold_ts}"
                        )
                        _hold_path.mkdir(parents=True, exist_ok=True)
                        _hold_report: dict[str, Any] = {
                            "article_candidate_generated": False,
                            "publish_attempted": False,
                            "hold_reason": "no_fresh_or_fallback_candidate",
                            "original_stale_topic": selected.candidate.topic or "",
                            "original_stale_published_at": str(_orig_raw.get("published_at") or ""),
                            "original_stale_source_url": str(_orig_raw.get("source_url") or ""),
                            "fresh_replacement_attempted": True,
                            "fresh_replacement_found": False,
                            "fallback_attempted": True,
                            "fallback_found": False,
                            "stale_source_warning": True,
                            "fresh_source_replacement_required": True,
                            "next_action": "wait_for_fresh_news_or_manual_publish_review",
                        }
                        RunArtifactService._write_json(
                            _hold_path / "candidate_hold_report.json", _hold_report
                        )
                        logger.warning(
                            "no fresh or fallback candidate → hold report: %s",
                            selected.candidate.topic[:40],
                        )
                        self._try_record_history(
                            status="held_no_fresh_or_fallback_candidate",
                            result={"dry_run": self.dry_run, **_hold_report},
                        )
                        return {
                            "status": "held_no_fresh_or_fallback_candidate",
                            "artifact_dir": str(_hold_path),
                            **_hold_report,
                        }
            # ─────────────────────────────────────────────────────────────────

            self._apply_issue_content_profile(selected)
            titles = self.title_service.generate_titles(selected)
            best_title = self.title_service.select_best_title(titles)
            content_angle_summary = self._content_angle_summary(selected)
            final_labels = self.label_service.build(
                selected_topic=selected.candidate.topic,
                selected_title=best_title.title,
                topic_group=str(selected.candidate.raw.get("topic_group") or "general_life"),
                content_type=str(content_angle_summary.get("content_type") or "general_life"),
                content_angle=content_angle_summary,
                existing_labels=[selected.candidate.category, best_title.hook_type],
            )
            final_labels = normalize_labels(final_labels)
            final_hashtags = self.label_service.build_hashtags(
                selected_topic=selected.candidate.topic,
                selected_title=best_title.title,
                topic_group=str(selected.candidate.raw.get("topic_group") or "general_life"),
                content_type=str(content_angle_summary.get("content_type") or "general_life"),
                labels=final_labels,
            )
            final_hashtags = normalize_hashtags(final_hashtags)
            selected.candidate.raw["hashtags"] = final_hashtags
            selected.candidate.raw["hashtag_count"] = len(final_hashtags)
            reader_interest_brief = (
                selected.candidate.raw.get("reader_interest_brief")
                if isinstance(selected.candidate.raw.get("reader_interest_brief"), dict)
                else {}
            )

            plan = SelectedNewsPlan(
                selected_topic=selected,
                title_candidates=titles,
                selected_title=best_title,
                contrarian_angle=str(
                    reader_interest_brief.get("click_hook")
                    or selected.candidate.raw.get("click_reason")
                    or selected.reason
                ),
                mainstream_view=str(
                    "겉으로 보이는 반응보다 검색자가 실제로 궁금해한 질문을 먼저 풀어야 한다."
                ),
                reader_benefit=str(
                    reader_interest_brief.get("reader_payoff")
                    or selected.candidate.raw.get("reader_benefit")
                    or "독자가 지금 확인할 기준을 얻는다."
                ),
                labels=final_labels,
            )

            # LLM 기반 고품질 생성 우선 시도, 실패 시 기존 서비스 폴백
            html = None
            _llm_used = False
            _llm_generation_failed = False
            _llm_source_citations: list[dict[str, str]] = []
            if self.llm_content_service:
                try:
                    _raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
                    _ct = str((_raw.get("content_angle") or {}).get("content_type") or "")
                    _rqs = list(_raw.get("reader_search_questions") or [])
                    html = self.llm_content_service.generate_html(
                        title=best_title.title,
                        topic=selected.candidate.topic or "",
                        category=str(selected.candidate.category or "AI활용"),
                        content_type=_ct,
                        labels=final_labels,
                        hashtags=list(final_hashtags or []),
                        reader_questions=_rqs,
                        raw=_raw,
                    )
                    if html:
                        _llm_used = True
                        # generate_html이 내부적으로 수집한 실제 인용 URL(Naver/Exa) —
                        # SOURCE_TRUST_BLOCK에 실제 <a href> 근거로 전달한다.
                        _llm_source_citations = list(
                            getattr(self.llm_content_service, "last_source_citations", None) or []
                        )
                        logger.info("NewsPipeline: LLM 콘텐츠 생성 성공 (%d자)", len(html))
                    else:
                        _llm_generation_failed = True
                        logger.warning("NewsPipeline: LLM 반환 None — ContrarianContentService 폴백")
                except Exception as _llm_exc:
                    _llm_generation_failed = True
                    logger.warning("NewsPipeline: LLM 생성 실패 (%s) — 폴백", _llm_exc)
            if _llm_generation_failed and is_english_mode():
                # EN 모드에서 LLM 실패는 곧 발행 불가(템플릿 폴백은 한국어라 차단됨).
                # 표면 증상(near-duplicate 차단 등)에 묻히지 않게 여기서 크게 실패를 남긴다.
                logger.error(
                    "NewsPipeline: LLM 생성 전멸 — EN 모드에서는 이 실행의 발행이 사실상 불가능 "
                    "(topic=%s). provider 로그(429/timeout)를 확인하라.",
                    (selected.candidate.topic or "")[:60],
                )

            if not html:
                html = self.content_service.generate_html(plan)
                logger.info("NewsPipeline: ContrarianContentService 사용 (%d자)", len(html))

            # 모든 HTML 생성 경로에 대한 최종 entity artifact 정제
            from blogspot_automation.services.llm_content_service import _clean_entity_artifacts as _clean_ent
            html = _clean_ent(html)
            history_internal_links = self._history_internal_link_targets(
                selected=selected,
                content_type=str(content_angle_summary.get("content_type") or "general_life"),
            )
            html = prepare_blogspot_html(html, links=history_internal_links, strip_document=True)
            html = ensure_answer_engine_optimized_html(
                html,
                title=best_title.title,
                topic=selected.candidate.topic or "",
                content_type=str(content_angle_summary.get("content_type") or ""),
                topic_group=str(selected.candidate.raw.get("topic_group") or ""),
                reader_questions=list(selected.candidate.raw.get("reader_search_questions") or []),
                source_citations=_llm_source_citations,
            )
            meta_description = normalize_search_description(
                title=best_title.title,
                description=extract_meta_description(html),
                html=html,
                topic=selected.candidate.topic,
            )
            click_potential_score = self._click_potential_score(selected)
            image_plan = self.image_prompt_service.build(
                selected=selected,
                selected_title=best_title.title,
            )
            cover_image_url = self._resolve_cover_image_url(
                selected=selected,
                selected_title=best_title.title,
                content_type=str(content_angle_summary.get("content_type") or ""),
                topic_group=str(selected.candidate.raw.get("topic_group") or ""),
                image_plan=image_plan,
            )
            if cover_image_url:
                image_plan["cover_image_url"] = cover_image_url
            html = ensure_cover_image_html(
                html,
                image_url=cover_image_url,
                alt_text=image_plan.get("image_alt_text", ""),
                title=best_title.title,
            )
            # 독자 우선 레이아웃: GEO/SEO 블록을 본문 뒤로 재배치 (블록 존재는 유지).
            # 해시태그 부착은 반드시 재배치 "이후" — 순서가 반대면 이동된 GEO 블록이
            # 해시태그 뒤로 가서 해시태그가 글 중간에 끼는 결함이 생긴다 (라이브 실측).
            html = reorder_for_reader_first(html)
            html = append_hashtags_block(html, hashtags=final_hashtags, labels=plan.labels)
            internal_link_suggestions = self._internal_link_suggestions(
                selected=selected,
                content_type=str(content_angle_summary.get("content_type") or "general_life"),
            )
            source_flags = self._candidate_source_flags(selected)
            selected_axis = str(selected.candidate.raw.get("evergreen_axis") or "")
            axis_consecutive_count = 0
            for _ax in recent_evergreen_axes:
                if _ax == selected_axis:
                    axis_consecutive_count += 1
                else:
                    break
            selected.candidate.raw["axis_consecutive_count"] = axis_consecutive_count
            selected.candidate.raw["tax_refund_consecutive_count"] = sum(
                1 for _ax in recent_evergreen_axes[:2] if _ax == "tax_refund_support"
            )
            publish_mode_active = (not self.dry_run) or self.news_publish_mode == "publish"
            # _llm_source_citations는 실제 Naver/Exa API 응답에서 나온 URL이라
            # SOURCE_TRUST_BLOCK에 <a href>로 남아있다 — 게이트의 외부 앵커 차단이
            # 이 URL까지 잡지 않도록 같은 예외를 넘긴다(strip_external_anchor_links와 동일 계약).
            _llm_citation_urls = tuple(
                str(c.get("url", "")).strip()
                for c in _llm_source_citations
                if isinstance(c, dict) and str(c.get("url", "")).strip()
            )
            # 최종 발행 html이 어느 소스(LLM 서술 vs article_candidate)로 확정되든
            # 그 html의 실제 SOURCE_TRUST_BLOCK 인용 URL과 짝을 맞춰 끝까지 들고 간다
            # (publish_args 빌드·NewsPublishService.publish까지) — 짝이 안 맞으면
            # strip_external_anchor_links가 검증된 링크를 href만 벗겨낸다(실측 사고).
            _final_citation_urls = _llm_citation_urls
            publish_quality_gate = self.quality_gate.evaluate(
                selected=selected,
                selected_title=best_title.title,
                html=html,
                image_prompt=image_plan.get("image_prompt", ""),
                image_alt_text=image_plan.get("image_alt_text", ""),
                labels=plan.labels,
                hashtags=final_hashtags,
                dry_run=self.dry_run,
                news_publish_mode=self.news_publish_mode,
                extra_allowed_urls=_llm_citation_urls,
            )
            # 콘텐츠 품질: LLM 서술형 본문이 자체 품질 게이트를 통과했는지 여기서 캡처한다.
            # 통과했다면 아래 golden_preview promotion에서 발행 가부·플래그는 그대로 두되
            # 실제 발행 본문(html)만 한 편으로 읽히는 LLM 서술형을 유지한다(가독성 우선).
            # 통과 못 했으면 기존처럼 템플릿을 발행해 발행 자체가 막히지 않게 폴백한다.
            _llm_body_gate_passed = bool(_llm_used) and bool(publish_quality_gate.get("passed"))
            if bool(_llm_used) and not _llm_body_gate_passed:
                logger.info(
                    "news pipeline: LLM 서술형 본문 자체 게이트 미통과 → 템플릿 폴백 (blocking=%s)",
                    publish_quality_gate.get("blocking_issues"),
                )
            duplicate_issue = self._recent_duplicate_issue(
                selected_topic=selected.candidate.topic,
                selected_title=best_title.title,
            )

            _artifact_result = self._save_artifact(
                html=html,
                selected=selected,
                titles=[item.to_dict() for item in titles],
                publish_quality_gate=publish_quality_gate,
                image_plan=image_plan,
                run_meta={
                    "pipeline": "news_pipeline",
                    "mode": self.news_publish_mode,
                    "dry_run": self.dry_run,
                    "candidate_count": len(candidates),
                    "scored_count": len(scored),
                    "publishable_count": len(publishable),
                    "deduped_count": len(deduped),
                    "news_candidate_count": news_candidate_count,
                    "news_publishable_count": news_publishable_count,
                    "news_publishable_real_count": news_publishable_real_count,
                    "fallback_reason": fallback_reason,
                    "duplicate_issue": duplicate_issue,
                    "manual_dedup_bypass": manual_dedup_bypass,
                    "selected_topic_group": selected.candidate.raw.get("topic_group"),
                    "selected_content_angle": self._content_angle_summary(selected),
                    "selected_issue_content_profile": selected.candidate.raw.get("issue_content_profile"),
                    "evergreen_axis": selected.candidate.raw.get("evergreen_axis", ""),
                    "evergreen_reason": selected.candidate.raw.get("evergreen_reason", ""),
                    "recent_evergreen_axes": recent_evergreen_axes[:5],
                    "preferred_axis_by_weekday": preferred_axis,
                    "selected_axis_reason": self._axis_selection_reason(
                        selected_axis, recent_evergreen_axes, preferred_axis
                    ),
                    "recommended_next_axis": recommended_next_axis,
                    "evergreen_candidate_available": True,
                    "axis_consecutive_count": axis_consecutive_count,
                    "history_recent_evergreen_axes": recent_evergreen_axes[:7],
                    "history_recent_topic_groups": recent_topic_groups_hist[:7],
                    "history_recent_content_types": recent_content_types_hist[:7],
                    "history_path": str(self.publish_history_service.history_path),
                    "history_recorded": True,
                    "target_reader": selected.candidate.raw.get("target_reader", ""),
                    "internal_link_suggestions": internal_link_suggestions,
                    "search_angle": selected.candidate.raw.get("search_angle"),
                    "search_demand_topic": selected.candidate.raw.get("search_demand_topic"),
                    "reader_search_questions": selected.candidate.raw.get("reader_search_questions"),
                    "click_reason": selected.candidate.raw.get("click_reason"),
                    "reader_benefit": selected.candidate.raw.get("reader_benefit"),
                    "reader_interest_score": selected.candidate.raw.get("reader_interest_score"),
                    "reader_interest_strategy": selected.candidate.raw.get("reader_interest_strategy"),
                    "reader_interest_publish_intent": selected.candidate.raw.get("reader_interest_publish_intent"),
                    "reader_interest_brief": selected.candidate.raw.get("reader_interest_brief"),
                    "save_value_score": selected.candidate.raw.get("save_value_score"),
                    "curiosity_score": selected.candidate.raw.get("curiosity_score"),
                    "urgency_reason": selected.candidate.raw.get("urgency_reason"),
                    "content_promise": selected.candidate.raw.get("content_promise"),
                    "angle_type": selected.candidate.raw.get("angle_type"),
                    "commercial_support_signal": selected.candidate.raw.get("commercial_support_signal", False),
                    "generic_support_keyword": selected.candidate.raw.get("generic_support_keyword", ""),
                    "public_benefit_keyword": selected.candidate.raw.get("public_benefit_keyword", ""),
                    "public_benefit_confidence": selected.candidate.raw.get("public_benefit_confidence", "none"),
                    "stale_penalty_applied": selected.candidate.raw.get("stale_penalty_applied", False),
                    "public_benefit_promotion_blocked": selected.candidate.raw.get("public_benefit_promotion_blocked", False),
                    "selected_cooldown_penalty": selected.candidate.raw.get("cooldown_penalty", 0),
                    "score_relaxed_for_candidate_generation": bool(
                        selected.candidate.raw.get("score_relaxed_for_candidate_generation")
                    ),
                    "candidate_generation_threshold": int(
                        selected.candidate.raw.get("candidate_generation_threshold")
                        or self.scoring_service.candidate_generation_min_score
                    ),
                    "auto_publish_min_score": self.scoring_service.min_topic_score,
                    "selected_total_score": int(selected.total_score),
                    "selected_raw_total_score": int(
                        (selected.candidate.raw.get("strategy_score_breakdown") or {}).get("raw_total_score")
                        or selected.candidate.raw.get("raw_total_score")
                        or selected.total_score
                    ),
                    "cooldown_source": getattr(self, "_last_cooldown_source", "publish_history"),
                    "publish_score_basis": "total_score>=75 (cooldown-adjusted) or raw_total_score>=65 (candidate_generation)",
                    **source_flags,
                    "labels": plan.labels,
                    "label_count": len(plan.labels),
                    "hashtags": final_hashtags,
                    "hashtag_count": len(final_hashtags),
                    # 영어 전환 성과 루프(2026-07-18): content_family별 RPM/CTR 분석용.
                    # ko 모드에서는 빈 값 — 스키마 additive라 기존 소비자 영향 없음.
                    "content_family": (
                        en_content_family(selected.candidate.topic or "", best_title.title)
                        if is_english_mode()
                        else ""
                    ),
                    "official_source_count": len(_llm_source_citations),
                    "last_checked_date": kst_today("%Y-%m-%d") if is_english_mode() else "",
                    "faq_count": publish_quality_gate.get("faq_count"),
                    "faqpage_json_ld_present": publish_quality_gate.get("faqpage_json_ld_present"),
                    "article_focus_score": publish_quality_gate.get("article_focus_score"),
                    "reader_value_score": publish_quality_gate.get("reader_value_score"),
                    "related_ai_blog_url": os.getenv("RELATED_AI_BLOG_URL", "https://holyyomiai.blogspot.com/"),
                    "related_ai_blog_box_present": publish_quality_gate.get("related_ai_blog_box_present", False),
                    **image_plan,
                    **_replacement_meta,
                },
                replacement_meta=_replacement_meta,
            )
            artifact_dir = _artifact_result["run_path"]
            _gpr = _artifact_result.get("golden_preview_result") or {}
            _es = _artifact_result.get("editorial_scores") or {}
            _grade = _artifact_result.get("content_candidate_grade", "D")
            _gpm = _gpr.get("pattern_match") or {}
            _candidate_meta = _artifact_result.get("article_candidate_meta") or {}
            _article_candidate_generated = bool(
                _artifact_result.get("_article_candidate_generated")
                or _candidate_meta.get("article_candidate_generated")
            )
            _publish_ready = bool(_candidate_meta.get("publish_ready"))
            _geo_ready = bool(_candidate_meta.get("geo_ready"))
            _sge_ready = bool(_candidate_meta.get("sge_ready"))
            _sge_score = int(_candidate_meta.get("sge_score") or 0)
            _candidate_title = str(_candidate_meta.get("candidate_h1") or "").strip()
            if _candidate_title and _candidate_title != best_title.title:
                _pre_override_title = best_title
                _pre_override_gate = publish_quality_gate
                _pre_override_llm_ok = _llm_body_gate_passed
                best_title = TitleCandidate(
                    title=_candidate_title,
                    hook_type=best_title.hook_type,
                    ctr_score=max(int(best_title.ctr_score or 0), int(_candidate_meta.get("selected_title_ctr_score") or 0)),
                    reason="title_candidate_service article candidate title",
                )
                plan.selected_title = best_title
                selected.candidate.raw["selected_title"] = _candidate_title
                # 영어 모드(2026-07-17): 서술 본문 게이트는 위에서 '확정 전' 빌더
                # 제목으로 평가됐다. 슬롯 LLM 제목은 본문과 다른 생성물이라 단어가
                # 어긋날 수 있으므로(title_body_entity_mismatch 실측) 최종 제목으로
                # 재평가하고, 재평가가 실패하면 본문과 정합이 확인된 원래 제목을
                # 유지한다 — 제목 채택은 게이트 통과를 전제로 한 조건부다.
                if self._ai_blog_mode_enabled() and is_english_mode() and bool(_llm_used):
                    _regate = self.quality_gate.evaluate(
                        selected=selected,
                        selected_title=best_title.title,
                        html=html,
                        image_prompt=image_plan.get("image_prompt", ""),
                        image_alt_text=image_plan.get("image_alt_text", ""),
                        labels=plan.labels,
                        hashtags=final_hashtags,
                        dry_run=self.dry_run,
                        news_publish_mode=self.news_publish_mode,
                        extra_allowed_urls=_llm_citation_urls,
                    )
                    if bool(_regate.get("passed")) or not _pre_override_llm_ok:
                        publish_quality_gate = _regate
                        _llm_body_gate_passed = bool(_regate.get("passed"))
                    else:
                        logger.info(
                            "news pipeline: EN mode — 슬롯 제목 재평가 실패(%s) → 본문 정합 제목 유지: %s",
                            _regate.get("blocking_issues"),
                            _pre_override_title.title[:60],
                        )
                        best_title = _pre_override_title
                        plan.selected_title = best_title
                        selected.candidate.raw["selected_title"] = best_title.title
                        publish_quality_gate = _pre_override_gate
                        _llm_body_gate_passed = _pre_override_llm_ok

            # article_candidate.html이 모든 GEO/SGE/품질 구조를 충족하면 그것을 publish content로 사용한다.
            # 이렇게 하면 LLM/ContrarianContentService가 GEO/SGE 구조를 빠뜨려도 publish_quality_gate를 통과한다.
            _candidate_html = str(_gpr.get("_article_candidate_html") or "")
            if (
                _article_candidate_generated
                and _candidate_html
                and len(_candidate_html) > 1000
                and _geo_ready
                and _sge_ready
                and _grade in ("A", "B")
            ):
                # render_article_candidate_html이 이미 SOURCE_TRUST_BLOCK에 실제
                # 인용 URL을 넣고 prepare_blogspot_html의 외부 링크 제거를 한 번
                # 통과시켰다 — 이 두 번째 prepare_blogspot_html 호출에서 같은
                # extra_allowed_urls를 넘기지 않으면 그 URL이 다시 벗겨진다.
                _candidate_slots = (
                    _gpr.get("slot_result") if isinstance(_gpr.get("slot_result"), dict) else {}
                ) or {}
                _candidate_citation_urls = tuple(
                    str(c.get("url", "")).strip()
                    for c in (_candidate_slots.get("slots") or {}).get("_llm_source_citations") or []
                    if isinstance(c, dict) and str(c.get("url", "")).strip()
                )
                _candidate_publish_html = prepare_blogspot_html(
                    _candidate_html,
                    links=history_internal_links,
                    strip_document=True,
                    extra_allowed_urls=_candidate_citation_urls,
                )
                _candidate_publish_html = ensure_answer_engine_optimized_html(
                    _candidate_publish_html,
                    title=best_title.title,
                    topic=selected.candidate.topic or "",
                    content_type=str(content_angle_summary.get("content_type") or ""),
                    topic_group=str(selected.candidate.raw.get("topic_group") or ""),
                    reader_questions=list(selected.candidate.raw.get("reader_search_questions") or []),
                )
                _candidate_publish_html = ensure_cover_image_html(
                    _candidate_publish_html,
                    image_url=cover_image_url,
                    alt_text=image_plan.get("image_alt_text", ""),
                    title=best_title.title,
                )
                # 독자 우선 레이아웃 재배치 후 해시태그 부착 (순서 중요 — 반대면
                # 해시태그가 글 중간에 낌, 라이브 실측 결함)
                _candidate_publish_html = reorder_for_reader_first(_candidate_publish_html)
                _candidate_publish_html = append_hashtags_block(
                    _candidate_publish_html,
                    hashtags=final_hashtags,
                    labels=plan.labels,
                )
                _candidate_publish_gate = self.quality_gate.evaluate(
                    selected=selected,
                    selected_title=best_title.title,
                    html=_candidate_publish_html,
                    image_prompt=image_plan.get("image_prompt", ""),
                    image_alt_text=image_plan.get("image_alt_text", ""),
                    labels=plan.labels,
                    hashtags=final_hashtags,
                    dry_run=self.dry_run,
                    news_publish_mode=self.news_publish_mode,
                    extra_allowed_urls=_candidate_citation_urls,
                )
                # 영어 모드 강화 게이트(2026-07-17): 템플릿 candidate는 구조·헤딩이
                # 한국어라 영어 블로그에 그대로 나가면 안 된다. LLM 영어 서술 본문이
                # 자체 게이트를 통과했을 때만 발행을 허용하고, 아니면 이 후보를
                # 차단해 재시도 루프가 다음 후보로 넘어가게 한다 (추가 차단 = 강화).
                if is_english_mode() and not _llm_body_gate_passed:
                    logger.info(
                        "news pipeline: EN mode — LLM 영어 본문 게이트 미통과, 한국어 템플릿 폴백 발행 차단"
                    )
                    _candidate_publish_gate = dict(_candidate_publish_gate)
                    _candidate_publish_gate["passed"] = False
                    _cpg_issues = list(_candidate_publish_gate.get("blocking_issues") or [])
                    _cpg_issues.append("en_mode_template_fallback_blocked")
                    _candidate_publish_gate["blocking_issues"] = _cpg_issues
                # 영어 모드 발행 판정(2026-07-17 드라이런 #4·#5 실측 교훈): candidate는
                # 한국어 템플릿+영어 주제의 혼합물로 EN에서는 절대 발행되지 않는 게이트
                # 판정용 아티팩트인데, 그 혼합물에서만 나는 구조적 이슈(한국어 박스에
                # 영어 헤드라인 반복 삽입 등)가 발행을 막는 두더지잡기가 된다.
                # EN에서는 "실제 발행본"인 LLM 영어 서술 본문이 같은 풀 게이트
                # (quality_gate.evaluate)를 통과했으면 그 결과를 발행 판정으로 쓴다 —
                # 발행되는 본문 기준으로는 동일 강도의 게이트가 그대로 전부 적용된다.
                # (candidate의 구조 플래그 geo/sge/grade 요건은 바깥 if가 이미 강제.)
                _en_narrative_publish = (
                    is_english_mode()
                    and _llm_body_gate_passed
                    and not bool(_candidate_publish_gate.get("passed"))
                )
                if _en_narrative_publish:
                    logger.info(
                        "news pipeline: EN mode — 후보 게이트 대신 발행본(영어 서술) 게이트로 판정 "
                        "(candidate-only blocking=%s)",
                        _candidate_publish_gate.get("blocking_issues"),
                    )
                if bool(_candidate_publish_gate.get("passed")) or _en_narrative_publish:
                    # 템플릿 candidate가 게이트를 통과했다 — 발행 가부 판정·플래그는 이 기준을
                    # 그대로 쓴다(발행 회귀 0). 단 LLM 서술형 본문도 자체 게이트를 통과했다면
                    # 실제 발행 본문은 한 편으로 읽히는 LLM 서술형(html)을 유지하고, 통과 못
                    # 했을 때만 템플릿 candidate로 발행한다.
                    _final_html_source = "llm_narrative" if _llm_body_gate_passed else "article_candidate"
                    logger.info(
                        "news pipeline: candidate gate passed — publishing %s (grade=%s, llm_ok=%s)",
                        _final_html_source, _grade, _llm_body_gate_passed,
                    )
                    if not _llm_body_gate_passed:
                        html = _candidate_publish_html
                        _final_citation_urls = _candidate_citation_urls
                    meta_description = normalize_search_description(
                        title=best_title.title,
                        description=extract_meta_description(html) or meta_description,
                        html=html,
                        topic=selected.candidate.topic,
                    )
                    if not _en_narrative_publish:
                        publish_quality_gate = _candidate_publish_gate
                        if _llm_body_gate_passed:
                            # 게이트 판정은 candidate 기준을 쓰더라도, 원장에 남는
                            # content_fingerprint는 "실제 발행되는 html"(LLM 서술형)
                            # 기준이어야 한다. candidate(템플릿) 지문이 published
                            # 레코드에 남으면 이후 모든 템플릿 렌더가 그 레코드와
                            # 0.85+로 충돌하는 원장 오염이 생긴다(2026-07-18 실측:
                            # "Best AI Tools for Real Estate Agents" → 7/19~20
                            # 에버그린 전멸 사슬).
                            try:
                                from blogspot_automation.services.content_similarity_service import (
                                    sentence_fingerprints as _sentence_fps,
                                )
                                publish_quality_gate = dict(publish_quality_gate)
                                publish_quality_gate["content_fingerprint"] = _sentence_fps(html)
                            except Exception as _fp_exc:  # noqa: BLE001
                                logger.warning("fingerprint recompute failed: %s", _fp_exc)
                    # _en_narrative_publish면 publish_quality_gate는 이미 발행본(영어
                    # 서술) 평가 결과(passed=True)다 — 그대로 유지한다.
                    _publish_ready = True
                    self.artifact_service.update_publish_artifacts(
                        artifact_dir,
                        html=html,
                        publish_quality_gate=publish_quality_gate,
                        run_meta_updates={
                            "final_publish_html_source": _final_html_source,
                            "promoted_article_candidate_as_publish_content": not _llm_body_gate_passed,
                            "llm_narrative_published": _llm_body_gate_passed,
                            "en_candidate_gate_bypassed_for_narrative": _en_narrative_publish,
                            "en_candidate_gate_blocking_issues": (
                                list(_candidate_publish_gate.get("blocking_issues") or [])
                                if _en_narrative_publish
                                else []
                            ),
                            "promoted_article_candidate_grade": _grade,
                            "promoted_article_candidate_length": len(_candidate_html),
                            "selected_title": best_title.title,
                            "article_candidate_generated": _article_candidate_generated,
                            "article_candidate_source": _candidate_meta.get("article_candidate_source", ""),
                            "human_review_required": bool(_candidate_meta.get("human_review_required", False)),
                            "publish_allowed_in_phase2": bool(_candidate_meta.get("publish_allowed_in_phase2", False)),
                            "publish_ready": True,
                            "geo_ready": _geo_ready,
                            "sge_ready": _sge_ready,
                            "near_match": bool(_candidate_meta.get("near_match") or _gpr.get("near_match")),
                            "faq_count": publish_quality_gate.get("faq_count"),
                            "faqpage_json_ld_present": publish_quality_gate.get("faqpage_json_ld_present"),
                            "article_focus_score": publish_quality_gate.get("article_focus_score"),
                            "reader_value_score": publish_quality_gate.get("reader_value_score"),
                            "related_ai_blog_box_present": publish_quality_gate.get("related_ai_blog_box_present", False),
                        },
                        scoring_updates={
                            "final_publish_html_source": _final_html_source,
                            "selected_title": best_title.title,
                            "faq_count": publish_quality_gate.get("faq_count"),
                            "faqpage_json_ld_present": publish_quality_gate.get("faqpage_json_ld_present"),
                            "article_focus_score": publish_quality_gate.get("article_focus_score"),
                            "reader_value_score": publish_quality_gate.get("reader_value_score"),
                        },
                    )
                    logger.info(
                        "news pipeline: re-evaluated publish_quality_gate after promotion: passed=%s blocking=%s",
                        publish_quality_gate.get("passed"),
                        publish_quality_gate.get("blocking_issues"),
                    )
                else:
                    selected.candidate.raw["article_candidate_promotion_blocking_issues"] = list(
                        _candidate_publish_gate.get("blocking_issues") or []
                    )
                    _current_blocking = list(publish_quality_gate.get("blocking_issues") or [])
                    _candidate_blocking = list(_candidate_publish_gate.get("blocking_issues") or [])
                    _candidate_final_audit = _candidate_publish_gate.get("final_html_audit") or {}
                    if (
                        _candidate_blocking
                        and len(_candidate_blocking) < len(_current_blocking)
                        and bool(_candidate_final_audit.get("passed", True))
                    ):
                        html = _candidate_publish_html
                        _final_citation_urls = _candidate_citation_urls
                        publish_quality_gate = _candidate_publish_gate
                        self.artifact_service.update_publish_artifacts(
                            artifact_dir,
                            html=html,
                            publish_quality_gate=publish_quality_gate,
                            run_meta_updates={
                                "final_publish_html_source": "article_candidate_quality_review",
                                "article_candidate_selected_for_quality_review": True,
                                "article_candidate_quality_review_blocking": _candidate_blocking,
                                "selected_title": best_title.title,
                                "article_candidate_generated": _article_candidate_generated,
                                "article_candidate_source": _candidate_meta.get("article_candidate_source", ""),
                                "human_review_required": bool(_candidate_meta.get("human_review_required", False)),
                                "publish_allowed_in_phase2": bool(_candidate_meta.get("publish_allowed_in_phase2", False)),
                                "publish_ready": bool(_candidate_meta.get("publish_ready")),
                                "geo_ready": _geo_ready,
                                "sge_ready": _sge_ready,
                                "near_match": bool(_candidate_meta.get("near_match") or _gpr.get("near_match")),
                                "faq_count": publish_quality_gate.get("faq_count"),
                                "faqpage_json_ld_present": publish_quality_gate.get("faqpage_json_ld_present"),
                                "article_focus_score": publish_quality_gate.get("article_focus_score"),
                                "reader_value_score": publish_quality_gate.get("reader_value_score"),
                            },
                            scoring_updates={
                                "final_publish_html_source": "article_candidate_quality_review",
                                "selected_title": best_title.title,
                                "faq_count": publish_quality_gate.get("faq_count"),
                                "faqpage_json_ld_present": publish_quality_gate.get("faqpage_json_ld_present"),
                                "article_focus_score": publish_quality_gate.get("article_focus_score"),
                                "reader_value_score": publish_quality_gate.get("reader_value_score"),
                            },
                        )
                        logger.info(
                            "news pipeline: using article_candidate for quality review only: blocking=%s",
                            _candidate_blocking,
                        )
                    logger.info(
                        "news pipeline: article_candidate promotion blocked by quality gate: %s",
                        _candidate_publish_gate.get("blocking_issues"),
                    )

            _title_repair = self._try_repair_publish_title(
                selected=selected,
                best_title=best_title,
                html=html,
                publish_quality_gate=publish_quality_gate,
                image_plan=image_plan,
                labels=plan.labels,
                hashtags=final_hashtags,
                content_angle_summary=content_angle_summary,
                artifact_dir=artifact_dir,
                # html이 candidate로 승격됐을 수 있으므로 그 html에 맞는 인용 URL
                # 집합을 써야 한다(고정된 _llm_citation_urls면 candidate 인용 URL이
                # 화이트리스트에서 빠져 게이트 재평가가 잘못된 기준으로 돈다).
                extra_allowed_urls=_final_citation_urls,
            )
            if _title_repair:
                html = str(_title_repair["html"])
                best_title = _title_repair["best_title"]
                plan.selected_title = best_title
                selected.candidate.raw["selected_title"] = best_title.title
                publish_quality_gate = _title_repair["publish_quality_gate"]
                duplicate_issue = self._recent_duplicate_issue(
                    selected_topic=selected.candidate.topic,
                    selected_title=best_title.title,
                )

            base_result = {
                "artifact_dir": str(artifact_dir),
                "dry_run": self.dry_run,
                "news_publish_mode": self.news_publish_mode,
                "llm_generation_failed": _llm_generation_failed,
                "retry_attempt": self._current_retry_attempt,
                "selected_topic": selected.candidate.topic,
                "selected_title": best_title.title,
                "topic_group": selected.candidate.raw.get("topic_group"),
                "content_angle": self._content_angle_summary(selected),
                "issue_content_profile": selected.candidate.raw.get("issue_content_profile"),
                "search_angle": selected.candidate.raw.get("search_angle"),
                "search_demand_topic": selected.candidate.raw.get("search_demand_topic"),
                "reader_search_questions": selected.candidate.raw.get("reader_search_questions"),
                "click_reason": selected.candidate.raw.get("click_reason"),
                "reader_benefit": selected.candidate.raw.get("reader_benefit"),
                "reader_interest_score": selected.candidate.raw.get("reader_interest_score"),
                "reader_interest_strategy": selected.candidate.raw.get("reader_interest_strategy"),
                "reader_interest_publish_intent": selected.candidate.raw.get("reader_interest_publish_intent"),
                "reader_interest_brief": selected.candidate.raw.get("reader_interest_brief"),
                "save_value_score": selected.candidate.raw.get("save_value_score"),
                "curiosity_score": selected.candidate.raw.get("curiosity_score"),
                "urgency_reason": selected.candidate.raw.get("urgency_reason"),
                "content_promise": selected.candidate.raw.get("content_promise"),
                "angle_type": selected.candidate.raw.get("angle_type"),
                "commercial_support_signal": selected.candidate.raw.get("commercial_support_signal", False),
                "generic_support_keyword": selected.candidate.raw.get("generic_support_keyword", ""),
                "public_benefit_keyword": selected.candidate.raw.get("public_benefit_keyword", ""),
                "public_benefit_confidence": selected.candidate.raw.get("public_benefit_confidence", "none"),
                "stale_penalty_applied": selected.candidate.raw.get("stale_penalty_applied", False),
                "public_benefit_promotion_blocked": selected.candidate.raw.get("public_benefit_promotion_blocked", False),
                "trending_engine": bool(selected.candidate.raw.get("trending_engine")),
                "discovery_engine": bool(selected.candidate.raw.get("discovery_engine")),
                "today_buzz_score": selected.candidate.raw.get("today_buzz_score"),
                "source_count": selected.candidate.raw.get("source_count"),
                "safe_commentary_score": selected.candidate.raw.get("safe_commentary_score"),
                "total_score": selected.total_score,
                "raw_total_score": selected.candidate.raw.get("raw_total_score"),
                "strategy_score_breakdown": selected.candidate.raw.get("strategy_score_breakdown"),
                "cooldown_penalty": selected.candidate.raw.get("cooldown_penalty", 0),
                "evergreen_axis": selected.candidate.raw.get("evergreen_axis", ""),
                "evergreen_reason": selected.candidate.raw.get("evergreen_reason", ""),
                "recent_evergreen_axes": recent_evergreen_axes[:5],
                "preferred_axis_by_weekday": preferred_axis,
                "recommended_next_axis": recommended_next_axis,
                "axis_consecutive_count": axis_consecutive_count,
                "history_recent_evergreen_axes": recent_evergreen_axes[:7],
                "history_recent_topic_groups": recent_topic_groups_hist[:7],
                "history_recent_content_types": recent_content_types_hist[:7],
                "fallback_reason": fallback_reason,
                "manual_dedup_bypass": manual_dedup_bypass,
                "target_reader": selected.candidate.raw.get("target_reader", ""),
                "click_potential_score": click_potential_score,
                **source_flags,
                "labels": plan.labels,
                "label_count": len(plan.labels),
                "hashtags": final_hashtags,
                "hashtag_count": len(final_hashtags),
                "internal_link_suggestions": internal_link_suggestions,
                "internal_link_targets": [
                    {"anchor_text": text, "url": url}
                    for text, url in history_internal_links
                ],
                **image_plan,
                "candidate_count": len(candidates),
                "publishable_count": len(publishable),
                "news_candidate_count": news_candidate_count,
                "news_publishable_count": news_publishable_count,
                "news_publishable_real_count": news_publishable_real_count,
                "min_topic_score": self.scoring_service.min_topic_score,
                "top_scored_candidates": top_scored_candidates,
                "publish_quality_gate": publish_quality_gate,
                # Golden Preview
                "golden_preview_ready_for_review": _gpr.get("ready_for_review", False),
                "golden_pattern_id": _gpm.get("pattern_id") or "",
                "golden_pattern_confidence": int(_gpm.get("confidence", 0)),
                "golden_slot_fill_rate": float(_gpr.get("slot_fill_rate", 0.0)),
                "golden_blocking_issues": _gpr.get("blocking_issues", []),
                "golden_warnings": _gpr.get("warnings", []),
                # Editorial Scoring
                "content_candidate_grade": _grade,
                "traffic_potential_score": _es.get("traffic_potential_score", 0),
                "usefulness_score": _es.get("usefulness_score", 0),
                "evergreen_asset_score": _es.get("evergreen_asset_score", 0),
                "viral_safety_score": _es.get("viral_safety_score", 0),
                "final_editorial_score": _es.get("final_editorial_score", 0),
                # Topic Engine v2
                "topic_candidate_bucket": (selected.candidate.raw or {}).get("topic_candidate_bucket", "general"),
                "topic_engine_score": (selected.candidate.raw or {}).get("topic_engine_score", 0),
                "topic_candidate_grade": (selected.candidate.raw or {}).get("topic_candidate_grade", "D"),
                "topic_traffic_potential_score": (selected.candidate.raw or {}).get("topic_traffic_potential_score", 0),
                "topic_search_intent_score": (selected.candidate.raw or {}).get("topic_search_intent_score", 0),
                "topic_usefulness_score": (selected.candidate.raw or {}).get("topic_usefulness_score", 0),
                "topic_safety_score": (selected.candidate.raw or {}).get("topic_safety_score", 0),
                "topic_monetization_score": (selected.candidate.raw or {}).get("topic_monetization_score", 0),
                "golden_matched": (selected.candidate.raw or {}).get("golden_matched", False),
                "why_topic_selected": _artifact_result.get("_why_topic_selected", ""),
                "why_topic_held": _artifact_result.get("_why_topic_held", ""),
                "human_review_required": bool(
                    _candidate_meta.get(
                        "human_review_required",
                        _artifact_result.get("_human_review_required", True),
                    )
                ),
                "article_candidate_generated": _article_candidate_generated,
                "article_candidate_path": "article_candidate.html" if _article_candidate_generated else "",
                "article_candidate_source": _candidate_meta.get("article_candidate_source", ""),
                "publish_allowed_in_phase2": bool(_candidate_meta.get("publish_allowed_in_phase2", False)),
                "publish_ready": _publish_ready,
                "near_match": bool(_candidate_meta.get("near_match") or _gpr.get("near_match")),
                "geo_ready": _geo_ready,
                "sge_ready": _sge_ready,
                "sge_score": _sge_score,
                "publish_attempted": False,
                "publish_succeeded": False,
            }

            if source_flags["fallback_candidate"] and publish_mode_active:
                history_recorded = self._try_record_history(status="blocked_fallback_candidate", result=base_result)
                return {
                    "status": "blocked_fallback_candidate",
                    "blocking_issues": publish_quality_gate["blocking_issues"],
                    "history_recorded": history_recorded,
                    **base_result,
                }

            if duplicate_issue:
                history_recorded = self._try_record_history(status="skipped_duplicate", result=base_result)
                return {
                    "status": "skipped_duplicate",
                    "duplicate_issue": duplicate_issue,
                    "history_recorded": history_recorded,
                    **base_result,
                }

            if not publish_quality_gate["passed"]:
                # stale_policy 차단 시 evergreen golden 재탐색 힌트 저장
                _stale_blocked = any(
                    "stale_policy" in issue
                    for issue in publish_quality_gate.get("blocking_issues", [])
                )
                if _stale_blocked:
                    try:
                        _eg_raw = self.evergreen_topic_service.collect_candidates()
                        _eg_scored = self.scoring_service.score_candidates(_eg_raw)
                        _eg_golden = self._prefer_golden_matched_candidates(_eg_scored)
                        if _eg_golden:
                            base_result["stale_evergreen_hint"] = _eg_golden[0].candidate.topic
                            base_result["stale_evergreen_pattern"] = str(
                                self.golden_preview_service._ps.match_pattern(
                                    topic=_eg_golden[0].candidate.topic or ""
                                ).get("pattern_id") or ""
                            )
                            logger.info(
                                "stale_policy blocked: evergreen hint → %s",
                                _eg_golden[0].candidate.topic[:40],
                            )
                        # 대기 중인 fresh 대안 후보도 기록
                        _fresh_alts = [
                            c for c in deduped
                            if c.candidate.topic != selected.candidate.topic
                        ]
                        if _fresh_alts:
                            base_result["stale_alt_candidate"] = _fresh_alts[0].candidate.topic
                    except Exception as _se:
                        logger.warning("stale fallback search failed: %s", _se)
                history_recorded = self._try_record_history(status="blocked_by_quality_gate", result=base_result)
                return {
                    "status": "blocked_by_quality_gate",
                    "blocking_issues": publish_quality_gate["blocking_issues"],
                    "stale_blocked": _stale_blocked if _stale_blocked else False,
                    "history_recorded": history_recorded,
                    **base_result,
                }

            # EN 모드 최종 방어선(2026-07-20, 추가 차단 = 강화): 발행 직전 본문에
            # 한국어가 실질적으로 남아 있으면 무조건 차단한다. 2026-07-18 실측 사고 —
            # en_mode_template_fallback_blocked는 candidate 승격 경로만 막았고, LLM
            # 실패로 폴백된 한국어 템플릿 본문(ContrarianContentService)은 한국어
            # 기준 게이트를 passed=True로 통과해 그대로 라이브 발행됐다("Best AI
            # Tools for Real Estate Agents" 한국어 껍데기). 게이트가 어떤 경로로
            # 판정됐든, "실제 발행되는 html"이 영어가 아니면 여기서 끝낸다.
            if is_english_mode():
                _visible_for_lang = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.DOTALL)
                _visible_for_lang = re.sub(r"<[^>]+>", " ", _visible_for_lang)
                _hangul_chars = sum(1 for _ch in _visible_for_lang if "가" <= _ch <= "힣")
                if _hangul_chars > 40:
                    logger.error(
                        "NewsPipeline: EN 모드 최종 본문에 한국어 %d자 잔존 — 발행 차단 "
                        "(llm_generation_failed=%s)",
                        _hangul_chars, _llm_generation_failed,
                    )
                    publish_quality_gate = dict(publish_quality_gate)
                    publish_quality_gate["passed"] = False
                    _kb_issues = list(publish_quality_gate.get("blocking_issues") or [])
                    _kb_issues.append("en_mode_korean_body_publish_blocked")
                    publish_quality_gate["blocking_issues"] = _kb_issues
                    base_result["publish_quality_gate"] = publish_quality_gate
                    history_recorded = self._try_record_history(
                        status="blocked_by_quality_gate", result=base_result
                    )
                    return {
                        "status": "blocked_by_quality_gate",
                        "blocking_issues": publish_quality_gate["blocking_issues"],
                        "history_recorded": history_recorded,
                        **base_result,
                    }

            auto_publish_gate = self._evaluate_auto_publish_gate(
                base_result=base_result,
                publish_quality_gate=publish_quality_gate,
            )
            base_result["auto_publish_gate"] = auto_publish_gate
            if publish_mode_active and not auto_publish_gate["allowed"]:
                hold_reason = ";".join(auto_publish_gate["blocking_reasons"])
                base_result["publish_hold_reason"] = hold_reason
                history_recorded = self._try_record_history(status="held_for_review", result=base_result)
                return {
                    "status": "held_for_review",
                    "publish_hold_reason": hold_reason,
                    "history_recorded": history_recorded,
                    **base_result,
                }

            if self.dry_run or self.news_publish_mode != "publish":
                history_recorded = self._try_record_history(status="dry_run_saved", result=base_result)
                return {
                    "status": "dry_run_saved",
                    "history_recorded": history_recorded,
                    **base_result,
                }

            if self._is_publish_hold_phase2():
                hold_reason = (
                    "PUBLISH_HOLD_PHASE2=true — Phase 2 게이팅: 골든 패턴 검증 완료 후 사람이 검토해야 발행 가능"
                )
                base_result["publish_hold_reason"] = hold_reason
                history_recorded = self._try_record_history(status="held_for_review", result=base_result)
                return {
                    "status": "held_for_review",
                    "publish_hold_reason": hold_reason,
                    "history_recorded": history_recorded,
                    **base_result,
                }

            if self.publish_service is None:
                raise RuntimeError("NEWS_PUBLISH_MODE=publish requires a configured NewsPublishService.")

            flow = self._execute_publish_flow(
                topic=selected.candidate.topic,
                publish_args={
                    "title": best_title.title,
                    # extra_allowed_urls 없이 호출하면 실제 리서치로 검증된
                    # SOURCE_TRUST_BLOCK 인용 링크의 href가 여기서 벗겨진다(2026-07-18
                    # 실측 사고 — 잘린 앵커 텍스트만 라이브에 남고 <a href>가 사라짐).
                    "article_html": prepare_blogspot_html(
                        html,
                        links=history_internal_links,
                        strip_document=True,
                        extra_allowed_urls=_final_citation_urls,
                    ),
                    "labels": normalize_labels(plan.labels),
                    "meta_description": meta_description,
                    "selected_topic": selected.candidate.topic,
                    "total_score": selected.total_score,
                    "click_potential_score": click_potential_score,
                    "topic_group": str(selected.candidate.raw.get("topic_group") or ""),
                    "content_type": str(content_angle_summary.get("content_type") or ""),
                    "hashtags": final_hashtags,
                    "image_alt_text": image_plan.get("image_alt_text", ""),
                    # NewsPublishService.publish() 내부의 두 번째 anchor-strip 단계에도
                    # 같은 화이트리스트를 넘겨야 최종 발행 HTML에서 링크가 살아남는다.
                    "extra_allowed_urls": _final_citation_urls,
                    # 2026-07-18 실측: 이 키가 없어 메인 발행 경로의 라이브 글에
                    # 내부링크 블록(Related guides)이 한 번도 붙지 않았다 —
                    # prepare_blogspot_html(links=...)는 include_internal_links
                    # 기본값 False라 링크를 계산만 하고 버리고, publish() 쪽
                    # append는 internal_links 인자가 있어야만 동작한다.
                    # (EN 모드에선 한글 제목 링크가 걸러지고 라벨 페이지 폴백이
                    # 들어간다 — seo_policy.append_internal_links_block.)
                    "internal_links": history_internal_links,
                },
            )
            if flow["kind"] == "draft":
                base_result.update(flow["draft_result"])
                history_recorded = self._try_record_history(status="draft_saved_for_review", result=base_result)
                return {**base_result, "history_recorded": history_recorded}
            _pub_url = flow["post_url"]
            post_publish_audit = flow["post_publish_audit"]
            if flow["kind"] == "audit_blocked":
                base_result.update({
                    "published_url": _pub_url,
                    "post_url": _pub_url,
                    "post_id": flow["post_id"],
                    "post_publish_audit": post_publish_audit,
                    "post_publish_audit_cleanup_deleted": flow["cleanup_deleted"],
                    "publish_attempted": True,
                    "publish_succeeded": False,
                    "blogger_url": _pub_url,
                })
                history_recorded = self._try_record_history(
                    status="blocked_by_post_publish_audit",
                    result=base_result,
                )
                return {
                    **base_result,
                    "status": "blocked_by_post_publish_audit",
                    "blocking_issues": flow["fatal_issues"],
                    "history_recorded": history_recorded,
                }
            base_result.update({
                "published_url": _pub_url,
                "post_url": _pub_url,
                "post_id": flow["post_id"],
                "post_publish_audit": post_publish_audit,
                "publish_attempted": True,
                "publish_succeeded": True,
                "blogger_url": _pub_url,
            })
            history_recorded = self._try_record_history(status="published", result=base_result)
            return {
                **base_result,
                "status": "published",
                "published_url": _pub_url,
                "post_url": _pub_url,
                "post_id": flow["post_id"],
                "publish_attempted": True,
                "publish_succeeded": True,
                "post_publish_audit": post_publish_audit,
                "blogger_url": _pub_url,
                "history_recorded": history_recorded,
            }
        except Exception as exc:  # noqa: BLE001
            trace = traceback.format_exc()
            logger.error("NewsPipeline failed: %s\n%s", exc, trace)
            result = {
                "status": "failed",
                "error": str(exc),
                "traceback": trace,
            }
            try:
                self._try_record_history(status="failed", result={"dry_run": self.dry_run, "status": "failed"})
                artifact_dir = self.artifact_service.save_status_result(
                    status_payload=result,
                    run_meta={
                        "pipeline": "news_pipeline",
                        "mode": self.news_publish_mode,
                        "dry_run": self.dry_run,
                        "status": result["status"],
                        "error": result["error"],
                    },
                )
                result["artifact_dir"] = str(artifact_dir)
            except Exception as artifact_exc:  # noqa: BLE001
                result["artifact_error"] = str(artifact_exc)
            return result

    def _save_no_real_news_hold_report(
        self,
        *,
        candidates: list[Any],
        scored: list[ScoredNewsCandidate],
        publishable: list[ScoredNewsCandidate],
        fallback_reason: str,
        news_candidate_count: int,
        news_publishable_count: int,
        news_publishable_real_count: int,
        recent_evergreen_axes: list[str],
        preferred_axis: str,
        recommended_next_axis: str,
        recent_topic_groups_hist: list[str],
        recent_content_types_hist: list[str],
        primary_query_count: int = 0,
        secondary_query_count: int = 0,
        score_65_74_candidate_count: int = 0,
    ) -> dict[str, Any]:
        run_path = (
            Path(getattr(self.artifact_service, "runs_dir", "runs"))
            / f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        run_path.mkdir(parents=True, exist_ok=True)
        top_scored_candidates = self._top_scored_candidates(scored)

        # 허용 content_type 후보 수 계산
        allowed_ct_candidates = [
            item for item in scored
            if self._news_publish_content_type(
                item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            ) in self.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES
        ]

        # score 65~74 + allowed_ct + non-fallback + non-stale + risk=0
        gen_min = getattr(self.scoring_service, "candidate_generation_min_score", 65)
        pub_min = self.scoring_service.min_topic_score
        top_score_too_low_candidates: list[dict[str, Any]] = []
        score_too_low_pool = sorted(
            (item for item in allowed_ct_candidates if gen_min <= item.total_score < pub_min),
            key=lambda x: x.total_score,
            reverse=True,
        )[:5]
        for _it in score_too_low_pool:
            _raw = _it.candidate.raw if isinstance(_it.candidate.raw, dict) else {}
            _src = str(_raw.get("source_type") or _raw.get("source") or "").lower()
            top_score_too_low_candidates.append({
                "topic": _it.candidate.topic[:80] if _it.candidate.topic else "",
                "content_type": self._news_publish_content_type(_raw),
                "score": int(_it.total_score),
                "source_type": _src,
                "reason": (
                    "eligible_for_candidate_generation_after_relax"
                    if _src not in {"fallback", "evergreen_fallback", "viral_fallback"}
                    else "fallback_blocked"
                ),
            })

        # 거부 이유 집계 (상위 5개)
        rejected_reasons: dict[str, int] = {}
        for item in scored:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            source_type = str(raw.get("source_type") or raw.get("source") or "").lower()
            content_type = self._news_publish_content_type(raw)
            if source_type in {"fallback", "evergreen_fallback", "viral_fallback"}:
                rejected_reasons[f"source_type:{source_type}"] = rejected_reasons.get(f"source_type:{source_type}", 0) + 1
            elif content_type in self.NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES:
                rejected_reasons[f"excluded_ct:{content_type}"] = rejected_reasons.get(f"excluded_ct:{content_type}", 0) + 1
            elif content_type not in self.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES:
                rejected_reasons[f"not_allowed_ct:{content_type or 'missing'}"] = rejected_reasons.get(f"not_allowed_ct:{content_type or 'missing'}", 0) + 1
            elif item.total_score < self.scoring_service.min_topic_score:
                rejected_reasons["score_too_low"] = rejected_reasons.get("score_too_low", 0) + 1
        top_rejected = sorted(rejected_reasons.items(), key=lambda x: x[1], reverse=True)[:5]

        report: dict[str, Any] = {
            "article_candidate_generated": False,
            "publish_attempted": False,
            "publish_succeeded": False,
            "publish_ready": False,
            "geo_ready": False,
            "sge_ready": False,
            "hold_reason": "no_real_news_publish_candidate",
            "fallback_reason": fallback_reason,
            "candidate_count": len(candidates),
            "scored_count": len(scored),
            "publishable_count": len(publishable),
            "news_candidate_count": news_candidate_count,
            "news_publishable_count": news_publishable_count,
            "news_publishable_real_count": news_publishable_real_count,
            "real_news_candidate_count": sum(
                1 for item in scored
                if str(
                    (item.candidate.raw or {}).get("source_type") or
                    (item.candidate.raw or {}).get("source") or ""
                ).lower() not in {"fallback", "evergreen_fallback", "viral_fallback"}
            ),
            "primary_query_count": primary_query_count,
            "secondary_query_count": secondary_query_count,
            "allowed_content_type_candidate_count": len(allowed_ct_candidates),
            "score_65_74_candidate_count": score_65_74_candidate_count,
            "candidate_generation_threshold": gen_min,
            "auto_publish_threshold_note": (
                "publish still requires publish_ready, geo_ready, sge_ready "
                "and allowed content_type; score relaxation only affects "
                "candidate generation entry"
            ),
            "top_rejected_reasons": [{"reason": r, "count": c} for r, c in top_rejected],
            "top_score_too_low_candidates": top_score_too_low_candidates,
            "allowed_content_types": sorted(self.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES),
            "excluded_content_types": sorted(self.NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES),
            "top_scored_candidates": top_scored_candidates,
            "next_action": "expand_news_queries_or_lower_threshold_with_review",
        }
        run_meta = {
            "pipeline": "news_pipeline",
            "mode": self.news_publish_mode,
            "dry_run": self.dry_run,
            "status": "held_no_real_news_publish_candidate",
            "hold_reason": "no_real_news_publish_candidate",
            "fallback_reason": fallback_reason,
            "candidate_count": len(candidates),
            "scored_count": len(scored),
            "publishable_count": len(publishable),
            "news_candidate_count": news_candidate_count,
            "news_publishable_count": news_publishable_count,
            "news_publishable_real_count": news_publishable_real_count,
            "recent_evergreen_axes": recent_evergreen_axes[:5],
            "preferred_axis_by_weekday": preferred_axis,
            "recommended_next_axis": recommended_next_axis,
            "history_recent_evergreen_axes": recent_evergreen_axes[:7],
            "history_recent_topic_groups": recent_topic_groups_hist[:7],
            "history_recent_content_types": recent_content_types_hist[:7],
            "history_path": str(self.publish_history_service.history_path),
            "article_candidate_generated": False,
            "publish_attempted": False,
            "publish_ready": False,
            "geo_ready": False,
            "sge_ready": False,
        }
        RunArtifactService._write_json(run_path / "candidate_hold_report.json", report)
        RunArtifactService._write_json(run_path / "run_meta.json", run_meta)
        logger.info("no real news publish candidate, hold report saved: %s", run_path)
        return {
            "status": "held_no_real_news_publish_candidate",
            "artifact_dir": str(run_path),
            **report,
        }

    def _evaluate_auto_publish_gate(
        self,
        *,
        base_result: dict[str, Any],
        publish_quality_gate: dict[str, Any],
    ) -> dict[str, Any]:
        blocking_reasons: list[str] = []
        source_type = str(base_result.get("source_type") or "").strip().lower()
        base_raw = {
            "topic_group": base_result.get("topic_group"),
            "content_angle": base_result.get("content_angle") or {},
        }
        content_type = self._news_publish_content_type(base_raw)
        evergreen_axis = str(base_result.get("evergreen_axis") or "").strip()
        ai_blog_content_allowed = self._ai_blog_mode_enabled() and content_type == "ai_work_tip"

        if not self.auto_publish:
            blocking_reasons.append("auto_publish_false")
        if not bool(publish_quality_gate.get("passed")):
            blocking_reasons.append("publish_quality_gate_failed")
        evergreen_daily_fallback = self._is_daily_evergreen_publish_fallback(base_result)
        # Evergreen fallback 자동발행 기본 금지 (2026-07-02 사용자 지시):
        # "직장인 ChatGPT 활용법" 류 범용 evergreen 글이 이슈 글 자리를 차지하는
        # 문제를 차단한다. ALLOW_EVERGREEN_AUTO_PUBLISH=true 또는
        # FORCE_EVERGREEN_FALLBACK=true(명시적 수동 강제)일 때만 예외 허용.
        evergreen_auto_publish_allowed = (
            evergreen_daily_fallback and self._evergreen_auto_publish_allowed()
        )
        if source_type in {"fallback", "viral_fallback"} or (
            source_type == "evergreen_fallback" and not evergreen_auto_publish_allowed
        ):
            blocking_reasons.append(
                "evergreen_auto_publish_disabled"
                if source_type == "evergreen_fallback" and evergreen_daily_fallback
                else f"source_type_not_auto_publishable:{source_type}"
            )
        if content_type not in self.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES and not ai_blog_content_allowed:
            blocking_reasons.append(f"content_type_not_auto_publishable:{content_type or 'missing'}")
        if content_type in self.NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES and not ai_blog_content_allowed:
            blocking_reasons.append(f"content_type_excluded_from_news:{content_type}")
        if evergreen_axis in self.NEWS_AUTO_PUBLISH_EXCLUDED_EVERGREEN_AXES:
            blocking_reasons.append(f"evergreen_axis_excluded_from_news:{evergreen_axis}")
        if bool(base_result.get("fallback_candidate")):
            blocking_reasons.append("fallback_candidate_not_auto_publishable")
        top_issue_direct_publish = self._is_top_issue_direct_publish_candidate(
            base_result=base_result,
            publish_quality_gate=publish_quality_gate,
        )
        if not bool(base_result.get("article_candidate_generated")) and not top_issue_direct_publish:
            blocking_reasons.append("article_candidate_not_generated")
        if not bool(base_result.get("publish_ready")) and not top_issue_direct_publish:
            blocking_reasons.append("publish_ready_false")
        if bool(base_result.get("human_review_required")):
            blocking_reasons.append("human_review_required")
        if bool(base_result.get("near_match")):
            blocking_reasons.append("near_match_requires_review")
        if not bool(base_result.get("geo_ready")) and not top_issue_direct_publish:
            blocking_reasons.append("geo_ready_false")
        if not bool(base_result.get("sge_ready")) and not top_issue_direct_publish:
            blocking_reasons.append("sge_ready_false")

        return {
            "allowed": not blocking_reasons,
            "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
            "auto_publish": self.auto_publish,
            "publish_ready": bool(base_result.get("publish_ready")),
            "geo_ready": bool(base_result.get("geo_ready")),
            "sge_ready": bool(base_result.get("sge_ready")),
            "article_candidate_generated": bool(base_result.get("article_candidate_generated")),
            "top_issue_direct_publish": top_issue_direct_publish,
            "evergreen_daily_fallback": evergreen_daily_fallback,
            "evergreen_auto_publish_allowed": evergreen_auto_publish_allowed,
            "source_type": source_type,
            "content_type": content_type,
            "allowed_content_types": sorted(
                self.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES
                | (frozenset({"ai_work_tip"}) if ai_blog_content_allowed else frozenset())
            ),
        }

    @staticmethod
    def _evergreen_auto_publish_allowed() -> bool:
        """Evergreen fallback 자동발행 허용 여부 — 기본 False.

        ALLOW_EVERGREEN_AUTO_PUBLISH=true: 운영자가 명시적으로 evergreen 자동발행 재허용.
        FORCE_EVERGREEN_FALLBACK=true: 수동 evergreen 강제 실행(테스트/수동 발행)도 허용으로 간주.
        """
        explicit_allow = os.getenv("ALLOW_EVERGREEN_AUTO_PUBLISH", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }
        forced = os.getenv("FORCE_EVERGREEN_FALLBACK", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        return explicit_allow or forced

    @staticmethod
    def _is_daily_evergreen_publish_fallback(base_result: dict[str, Any]) -> bool:
        source_type = str(base_result.get("source_type") or "").strip().lower()
        if source_type != "evergreen_fallback":
            return False
        fallback_reason = str(base_result.get("fallback_reason") or "").strip()
        return fallback_reason in {
            "forced_evergreen_fallback",
            "no_publishable_news_candidate_used_evergreen",
            "no_golden_publish_candidate_used_evergreen",
            "no_publishable_candidate_used_evergreen",
        }

    NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
        "today_issue_explainer",
        "viral_issue_decode",
        "money_checklist",
        "platform_change",
        "consumer_warning",
        "policy_deadline",
        "policy_benefit",
    })
    NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES: frozenset[str] = frozenset({
        "general_life",
        "ai_work_tip",
        "blogspot_growth",
        "evergreen_fallback",
    })
    NEWS_AUTO_PUBLISH_EXCLUDED_EVERGREEN_AXES: frozenset[str] = frozenset({
        "blogspot_growth",
    })

    @staticmethod
    def _ai_blog_mode_enabled() -> bool:
        return str(os.getenv("AI_BLOG_MODE", "false")).strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def _is_top_issue_direct_publish_candidate(
        cls,
        *,
        base_result: dict[str, Any],
        publish_quality_gate: dict[str, Any],
    ) -> bool:
        base_raw = {
            "topic_group": base_result.get("topic_group"),
            "content_angle": base_result.get("content_angle") or {},
        }
        content_type = cls._news_publish_content_type(base_raw)
        if content_type != "today_issue_explainer":
            return False
        if not bool(publish_quality_gate.get("passed")):
            return False
        if bool(base_result.get("fallback_candidate")):
            return False
        source_type = str(base_result.get("source_type") or "").strip().lower()
        if source_type in {"fallback", "evergreen_fallback", "viral_fallback"}:
            return False
        has_real_today_signal = bool(base_result.get("trending_engine")) or bool(base_result.get("discovery_engine"))
        try:
            buzz = int(base_result.get("today_buzz_score") or 0)
        except (TypeError, ValueError):
            buzz = 0
        try:
            source_count = int(base_result.get("source_count") or 0)
        except (TypeError, ValueError):
            source_count = 0
        if buzz >= 8 or source_count >= 3:
            has_real_today_signal = True
        if not has_real_today_signal:
            return False
        for score_key, threshold in (("article_focus_score", 65), ("reader_value_score", 75)):
            value = publish_quality_gate.get(score_key)
            if value is None:
                continue
            try:
                if int(value) < threshold:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def _try_repair_publish_title(
        self,
        *,
        selected: ScoredNewsCandidate,
        best_title: TitleCandidate,
        html: str,
        publish_quality_gate: dict[str, Any],
        image_plan: dict[str, Any],
        labels: list[str],
        hashtags: list[str],
        content_angle_summary: dict[str, Any],
        artifact_dir: Path,
        extra_allowed_urls: frozenset[str] | tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        blocking = [str(issue) for issue in publish_quality_gate.get("blocking_issues", [])]
        if bool(publish_quality_gate.get("passed")) or not self._quality_title_repairable(blocking):
            return None
        repaired_title = self._source_preserving_repair_title(selected, current_title=best_title.title)
        if not repaired_title or repaired_title == best_title.title:
            return None

        repaired_html = self._replace_html_h1(html, repaired_title)
        repaired_html = ensure_answer_engine_optimized_html(
            repaired_html,
            title=repaired_title,
            topic=selected.candidate.topic or "",
            content_type=str(content_angle_summary.get("content_type") or ""),
            topic_group=str(selected.candidate.raw.get("topic_group") or ""),
            reader_questions=list(selected.candidate.raw.get("reader_search_questions") or []),
        )
        meta_description = normalize_search_description(
            title=repaired_title,
            description=extract_meta_description(repaired_html),
            html=repaired_html,
            topic=selected.candidate.topic,
        )
        repaired_html = ensure_cover_image_html(
            repaired_html,
            image_url=cover_image_url_from_env(
                content_type=str(content_angle_summary.get("content_type") or ""),
                topic_group=str(selected.candidate.raw.get("topic_group") or ""),
            ),
            alt_text=image_plan.get("image_alt_text", ""),
            title=repaired_title,
        )
        repaired_html = append_hashtags_block(repaired_html, hashtags=hashtags, labels=labels)
        repaired_gate = self.quality_gate.evaluate(
            selected=selected,
            selected_title=repaired_title,
            html=repaired_html,
            image_prompt=image_plan.get("image_prompt", ""),
            image_alt_text=image_plan.get("image_alt_text", ""),
            labels=labels,
            hashtags=hashtags,
            dry_run=self.dry_run,
            news_publish_mode=self.news_publish_mode,
            extra_allowed_urls=extra_allowed_urls,
        )
        if not self._quality_title_repair_improved(
            before=publish_quality_gate,
            after=repaired_gate,
        ):
            logger.info(
                "news pipeline: title repair skipped, no gate improvement (%s -> %s)",
                blocking,
                repaired_gate.get("blocking_issues"),
            )
            return None

        repaired_best = TitleCandidate(
            title=repaired_title,
            hook_type=best_title.hook_type,
            ctr_score=int(best_title.ctr_score or 0),
            reason="source-preserving quality gate repair",
        )
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        raw["quality_title_repaired"] = True
        raw["quality_title_repair_from"] = best_title.title
        raw["quality_title_repair_to"] = repaired_title
        self.artifact_service.update_publish_artifacts(
            artifact_dir,
            html=repaired_html,
            publish_quality_gate=repaired_gate,
            run_meta_updates={
                "quality_title_repaired": True,
                "quality_title_repair_from": best_title.title,
                "quality_title_repair_to": repaired_title,
                "selected_title": repaired_title,
                "faq_count": repaired_gate.get("faq_count"),
                "faqpage_json_ld_present": repaired_gate.get("faqpage_json_ld_present"),
                "article_focus_score": repaired_gate.get("article_focus_score"),
                "reader_value_score": repaired_gate.get("reader_value_score"),
                "related_ai_blog_box_present": repaired_gate.get("related_ai_blog_box_present", False),
            },
            scoring_updates={
                "quality_title_repaired": True,
                "quality_title_repair_from": best_title.title,
                "selected_title": repaired_title,
                "faq_count": repaired_gate.get("faq_count"),
                "faqpage_json_ld_present": repaired_gate.get("faqpage_json_ld_present"),
                "article_focus_score": repaired_gate.get("article_focus_score"),
                "reader_value_score": repaired_gate.get("reader_value_score"),
            },
        )
        logger.info(
            "news pipeline: repaired title for publish gate (%r -> %r) passed=%s blocking=%s",
            best_title.title,
            repaired_title,
            repaired_gate.get("passed"),
            repaired_gate.get("blocking_issues"),
        )
        return {
            "html": repaired_html,
            "best_title": repaired_best,
            "publish_quality_gate": repaired_gate,
        }

    @classmethod
    def _quality_title_repairable(cls, blocking_issues: list[str]) -> bool:
        if not blocking_issues:
            return False
        return all(cls._quality_title_repairable_issue(issue) for issue in blocking_issues)

    @staticmethod
    def _quality_title_repairable_issue(issue: str) -> bool:
        return (
            issue == "title_has_no_specific_entity"
            or issue == "generic_title_without_subject"
            or issue == "selected_title_has_truncated_word"
            or issue.startswith("title_body_entity_mismatch:")
            or issue.startswith("selected_title_uses_repeated_")
        )

    @classmethod
    def _quality_title_repair_improved(
        cls,
        *,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        if bool(after.get("passed")):
            return True
        before_blocking = [str(issue) for issue in before.get("blocking_issues", [])]
        after_blocking = [str(issue) for issue in after.get("blocking_issues", [])]
        before_repairable = sum(1 for issue in before_blocking if cls._quality_title_repairable_issue(issue))
        after_repairable = sum(1 for issue in after_blocking if cls._quality_title_repairable_issue(issue))
        after_non_repairable = [
            issue for issue in after_blocking if not cls._quality_title_repairable_issue(issue)
        ]
        return not after_non_repairable and after_repairable < before_repairable

    @classmethod
    def _source_preserving_repair_title(
        cls,
        selected: ScoredNewsCandidate,
        *,
        current_title: str,
    ) -> str:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_values: list[Any] = [
            raw.get("original_title"),
            raw.get("cleaned_title"),
            raw.get("source_title"),
            raw.get("original_topic"),
        ]
        source_values.extend(raw.get("source_titles") if isinstance(raw.get("source_titles"), list) else [])
        naver_item = raw.get("naver_item")
        if isinstance(naver_item, dict):
            source_values.extend([naver_item.get("title"), naver_item.get("description")])
        source_values.extend([
            raw.get("search_demand_topic"),
            selected.candidate.topic,
            current_title,
        ])
        for value in source_values:
            core = cls._clean_source_title_core(value)
            if not core:
                continue
            repaired = cls._compose_repair_title(
                core,
                content_type=cls._news_publish_content_type(raw),
                topic_group=str(raw.get("topic_group") or ""),
            )
            if repaired and repaired != current_title:
                return repaired
        return ""

    @staticmethod
    def _clean_source_title_core(value: Any, *, max_chars: int = 38) -> str:
        text = unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\[[^\]]{1,12}\]", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" ,.-:;!?\"'")
        if not text:
            return ""
        text = re.split(r"\s+[|｜]\s+|\s+-\s+", text)[0].strip(" ,.-:;!?\"'")
        text = re.sub(r"\s*(연합뉴스|뉴시스|뉴스1|이데일리|매일경제|한국경제)$", "", text).strip()
        if len(text) <= max_chars:
            return text
        words = text.split()
        if len(words) <= 1:
            return text[:max_chars].rstrip(" ,.-")
        core = ""
        for word in words:
            candidate = f"{core} {word}".strip()
            if len(candidate) > max_chars:
                break
            core = candidate
        return core or text[:max_chars].rstrip(" ,.-")

    @staticmethod
    def _compose_repair_title(core: str, *, content_type: str, topic_group: str) -> str:
        suffix = "지금 확인할 3가지"
        if content_type in {"policy_deadline", "policy_benefit", "tax_refund"} or topic_group == "policy_benefit":
            suffix = "신청 전 볼 3가지"
        elif content_type in {"money_checklist", "consumer_warning"}:
            suffix = "결제 전 볼 3가지"
        elif content_type in {"viral_issue_decode", "today_issue_explainer"}:
            suffix = "지금 갈린 이유"
        if suffix in core:
            return core
        if len(core) + len(suffix) + 2 <= 52:
            return f"{core}, {suffix}"
        return core

    @staticmethod
    def _replace_html_h1(html: str, title: str) -> str:
        escaped_title = escape(title)
        if re.search(r"<h1\b[^>]*>.*?</h1>", html, flags=re.IGNORECASE | re.DOTALL):
            return re.sub(
                r"(<h1\b[^>]*>).*?(</h1>)",
                lambda match: f"{match.group(1)}{escaped_title}{match.group(2)}",
                html,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
        return html.replace("<body>", f"<body>\n<h1>{escaped_title}</h1>", 1)

    @staticmethod
    def _candidate_source_flags(selected: ScoredNewsCandidate) -> dict[str, Any]:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_type = str(raw.get("source_type") or raw.get("source") or "")
        is_test_candidate = bool(raw.get("is_test_candidate"))
        publish_allowed = raw.get("publish_allowed", True)
        fallback_candidate = (
            source_type.lower() == "fallback"
            or is_test_candidate
            or publish_allowed is False
        )
        return {
            "source_type": source_type,
            "is_test_candidate": is_test_candidate,
            "fallback_candidate": fallback_candidate,
            "publish_allowed": publish_allowed,
        }

    @classmethod
    def _apply_trending_score_boost(
        cls,
        scored: list[ScoredNewsCandidate],
    ) -> list[ScoredNewsCandidate]:
        for item in scored:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            if not raw.get("trending_engine"):
                continue
            if not cls._is_news_auto_publish_candidate(item):
                raw["trending_score_boost_applied"] = False
                raw["trending_score_boost_skipped"] = "not_auto_publish_candidate"
                continue
            quality_issues = cls._trending_priority_quality_issues(item)
            if quality_issues:
                raw["trending_score_boost_applied"] = False
                raw["trending_score_boost_skipped"] = "trending_priority_quality_gate:" + ",".join(quality_issues)
                continue
            original = item.total_score
            item.total_score = max(item.total_score, 95)
            raw["trending_score_boost_applied"] = True
            raw["trending_score_boost_from"] = original
        return scored

    # 실제 AI 뉴스 소스로 인정하는 source_type — fallback/evergreen 계열 제외
    _AI_ISSUE_REAL_NEWS_SOURCES: frozenset[str] = frozenset({
        "google_news_rss",
        "google_custom_search",
        "tavily_search",
        "exa_search",
        "firecrawl_search",
        "naver_news_search",
        "daum_news_search",
        # 커뮤니티 언급량 소스(2026-07-20) — 실제 토론량이 실린 이슈 후보
        "community_reddit",
        "community_hackernews",
    })
    # AI 이슈 부스트 자격 판단용 엔티티 토큰 (도구/모델/기업명)
    _AI_ISSUE_ENTITY_TOKENS: tuple[str, ...] = (
        "chatgpt", "챗gpt", "챗지피티", "gpt", "openai", "오픈ai", "오픈에이아이",
        "claude", "클로드", "anthropic", "앤스로픽",
        "gemini", "제미나이", "제미니", "구글 ai", "딥마인드",
        "copilot", "코파일럿", "perplexity", "퍼플렉시티",
        "midjourney", "미드저니", "sora", "소라",
        "네이버 ai", "하이퍼클로바", "카카오 ai", "갤럭시 ai", "삼성 ai",
        "엔비디아", "nvidia", "라마", "llama", "grok", "그록",
    )

    @classmethod
    def _apply_ai_issue_score_boost(
        cls,
        scored: list[ScoredNewsCandidate],
    ) -> list[ScoredNewsCandidate]:
        """AI_BLOG_MODE 전용 — 신선한 실뉴스 AI 이슈 후보를 발행 임계값 위로 끌어올린다.

        ai_work 후보는 MONEY/URGENCY 키워드 기반 click_potential 점수가 구조적으로
        낮아 매일 evergreen fallback으로 밀리는 문제가 있었다. 실제 뉴스 소스 +
        신선(pubDate stale 아님) + 구체 엔티티(도구/모델명) 3조건을 모두 갖춘
        후보만 부스트한다. 하류 품질 게이트(본문/제목/포커스)는 그대로 적용된다.
        """
        for item in scored:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
            if source_type not in cls._AI_ISSUE_REAL_NEWS_SOURCES:
                continue
            if str(raw.get("topic_group") or "") != "ai_work":
                continue
            if bool(raw.get("is_stale")) or bool(raw.get("stale_penalty_applied")):
                continue
            haystack = " ".join(
                str(part or "")
                for part in (
                    item.candidate.topic,
                    item.candidate.summary,
                    raw.get("original_title"),
                    raw.get("cleaned_title"),
                )
            ).lower()
            if not any(token in haystack for token in cls._AI_ISSUE_ENTITY_TOKENS):
                continue
            if int(raw.get("risk_penalty", 0) or 0) > 0:
                continue
            original_score = item.total_score
            original_click = int(raw.get("click_potential_score") or 0)
            raw["ai_issue_engine"] = True
            raw["ai_issue_score_boosted"] = True
            raw["ai_issue_boost_from_score"] = original_score
            raw["ai_issue_boost_from_click"] = original_click
            raw["click_potential_score"] = max(original_click, 8)
            # 수요 조건부 부스트(2026-07-20): 과거의 무조건 82점 평탄화는 "AI 엔티티
            # 단어만 있으면 니치 보도자료도 자동 발행 자격"이라는 뜻이었고, 그 결과
            # 점수 49(D등급) 뉴스가 74~77점 에버그린을 항상 이겼다(운영자 불만의
            # 근본 원인). 이제 실제 수요 신호(Google Trends US 검색량 + 커뮤니티
            # 언급량)가 있는 후보만 82+수요만큼 올라가고, 신호가 없는 후보는
            # 발행 하한(76)까지만 올려 수요 있는 후보·에버그린과 점수로 경쟁한다.
            demand_boost = 0
            demand_keywords: list[str] = []
            _topic_text = " ".join(
                str(part or "")
                for part in (item.candidate.topic, raw.get("original_title"))
            )
            try:
                from blogspot_automation.services.google_trends_signal import GoogleTrendsSignal
                _tb, _tk = GoogleTrendsSignal.score_topic_boost(_topic_text, max_boost=20)
                demand_boost += _tb
                demand_keywords.extend(_tk)
            except Exception as _tr_exc:  # noqa: BLE001
                logger.warning("trends demand signal 실패(무시): %s", _tr_exc)
            try:
                from blogspot_automation.services.community_topic_service import (
                    score_topic_boost as _community_boost,
                )
                _cb, _ck = _community_boost(_topic_text, max_boost=15)
                demand_boost += _cb
                demand_keywords.extend(_ck)
            except Exception as _cm_exc:  # noqa: BLE001
                logger.warning("community demand signal 실패(무시): %s", _cm_exc)
            # 커뮤니티에서 직접 수집된 후보는 언급량 자체가 수요 신호다.
            _own_mentions = int(raw.get("community_mention_score") or 0)
            if _own_mentions >= 200:
                demand_boost += 8 if _own_mentions < 500 else 12
                demand_keywords.append(f"community_mentions:{_own_mentions}")
            # Google Autocomplete 상시 검색 수요(2026-07-22): Trends RSS는 "오늘
            # 급상승"만 잡는다 — 자동완성 제안 수는 그 주제가 평소에 얼마나
            # 검색되는지의 프록시라, 이슈성 없는 날에도 수요 있는 후보를 가려낸다.
            try:
                from blogspot_automation.services.search_autocomplete_signal import (
                    score_topic_boost as _autocomplete_boost,
                )
                _ab, _ak = _autocomplete_boost(_topic_text, max_boost=10)
                demand_boost += _ab
                demand_keywords.extend(_ak)
            except Exception as _ac_exc:  # noqa: BLE001
                logger.warning("autocomplete demand signal 실패(무시): %s", _ac_exc)
            raw["demand_signal_boost"] = demand_boost
            raw["demand_signal_keywords"] = list(dict.fromkeys(demand_keywords))
            if demand_boost > 0:
                item.total_score = min(max(item.total_score, 82) + min(demand_boost, 18), 100)
            else:
                item.total_score = max(item.total_score, 76)
        return scored

    @staticmethod
    def _apply_search_performance_boost(
        scored: list[ScoredNewsCandidate],
    ) -> list[ScoredNewsCandidate]:
        """Search Console 성과 루프 — 실검색 쿼리와 겹치는 후보 가산점.

        data/search_performance.json(scripts/fetch_search_performance.py가 갱신)이
        없으면 no-op. 부스트는 additive(최대 8점)이고 하류 품질 게이트는 그대로다.
        """
        try:
            from blogspot_automation.services.search_console_service import (
                load_search_performance,
                topic_boost_for,
            )
            performance = load_search_performance()
            if not performance:
                return scored
            for item in scored:
                result = topic_boost_for(item.candidate.topic or "", performance)
                boost = int(result.get("boost") or 0)
                if boost <= 0:
                    continue
                raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
                raw["search_performance_boost"] = boost
                raw["search_performance_matched_queries"] = list(result.get("matched_queries") or [])
                item.total_score = item.total_score + boost
            return scored
        except Exception as exc:  # noqa: BLE001 — 성과 루프 실패는 비치명
            logger.warning("search performance boost 실패(무시): %s", exc)
            return scored

    @staticmethod
    def _is_trending_candidate(item: ScoredNewsCandidate) -> bool:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        return bool(raw.get("trending_engine")) or str(raw.get("source_type") or "") == "naver_trending"

    @staticmethod
    def _trending_priority_quality_issues(item: ScoredNewsCandidate) -> list[str]:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        topic = item.candidate.topic or ""
        original_topic = str(raw.get("original_topic") or "")
        combined = f"{topic} {original_topic} {item.candidate.summary or ''}"
        issues: list[str] = []

        if any(term in combined for term in ("로또", "당첨번호", "1등", "대박")):
            issues.append("lottery_headline")

        if original_topic:
            preservation = NewsQualityGate._compute_original_issue_preservation(item, title=topic)
            raw["trending_original_issue_preservation_score"] = preservation
            if preservation < 6:
                issues.append(f"original_issue_preservation_below_6:{preservation}")

        return list(dict.fromkeys(issues))

    @classmethod
    def _is_news_auto_publish_candidate(cls, selected: ScoredNewsCandidate) -> bool:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        content_type = cls._news_publish_content_type(raw)
        evergreen_axis = str(raw.get("evergreen_axis") or "").strip()
        fallback_type = str(raw.get("fallback_type") or "").strip().lower()
        if source_type in {"fallback", "evergreen_fallback", "viral_fallback"}:
            return False
        if fallback_type == "evergreen":
            return False
        if raw.get("is_test_candidate") or raw.get("publish_allowed") is False:
            return False
        if str(raw.get("angle_type") or "").strip() == "market_finance":
            raw["auto_publish_block_reason"] = "market_finance_not_auto_publishable"
            return False
        focus = evaluate_news_focus(
            topic=selected.candidate.topic or "",
            summary=selected.candidate.summary or "",
            raw=raw,
        )
        if not focus.allowed:
            return False
        ai_blog_mode = cls._ai_blog_mode_enabled()
        ai_blog_content_allowed = ai_blog_mode and content_type == "ai_work_tip"
        if content_type in cls.NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES and not ai_blog_content_allowed:
            return False
        if content_type not in cls.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES and not ai_blog_content_allowed:
            return False
        if evergreen_axis in cls.NEWS_AUTO_PUBLISH_EXCLUDED_EVERGREEN_AXES:
            return False
        if cls._is_low_today_static_web_policy_candidate(selected):
            raw["auto_publish_block_reason"] = "low_today_relevance_static_web_candidate"
            return False
        # click_potential gate — 조회수 가능성 낮은 주제 자동발행 차단.
        # discovery_engine 후보도 최종 quality_gate의 top-issue 완화 기준(>=6)
        # 아래면 선택 단계에서 먼저 제외한다.
        click_score = int(raw.get("click_potential_score") or 0)
        if click_score < 7 and (not raw.get("discovery_engine") or click_score < 6):
            return False
        return True

    @classmethod
    def _is_low_today_static_web_policy_candidate(cls, selected: ScoredNewsCandidate) -> bool:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        static_web_sources = {"naver_webkr_search", "naver_web_search", "webkr"}
        if source_type not in static_web_sources:
            return False
        if raw.get("discovery_engine") or raw.get("trending_engine"):
            return False
        content_type = cls._news_publish_content_type(raw)
        topic_group = str(raw.get("topic_group") or "").strip()
        is_policy = topic_group == "policy_benefit" or content_type in {
            "policy_deadline",
            "policy_benefit",
            "tax_refund",
        }
        is_sensitive_practical = topic_group in {
            "refund_consumer",
            "platform_consumer",
            "privacy_security",
            "delivery_money",
        } or content_type in {
            "consumer_warning",
            "money_checklist",
        }
        if not (is_policy or is_sensitive_practical):
            return False
        return cls._selection_today_relevance_score(selected) < 7

    @staticmethod
    def _selection_today_relevance_score(item: ScoredNewsCandidate) -> int:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        cached = raw.get("today_relevance_score")
        if cached is None:
            cached = raw.get("selection_today_relevance_score")
        if cached is not None:
            try:
                score = int(cached)
                raw["selection_today_relevance_score"] = score
                return score
            except (TypeError, ValueError):
                pass
        score = NewsQualityGate._compute_today_relevance(item)
        raw["selection_today_relevance_score"] = score
        return score

    @staticmethod
    def _is_news_focus_candidate(selected: ScoredNewsCandidate) -> bool:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        focus = evaluate_news_focus(
            topic=selected.candidate.topic or "",
            summary=selected.candidate.summary or "",
            raw=raw,
        )
        return focus.allowed

    @staticmethod
    def _news_publish_content_type(raw: dict[str, Any]) -> str:
        content_angle = raw.get("content_angle") if isinstance(raw.get("content_angle"), dict) else {}
        content_type = str(content_angle.get("content_type") or raw.get("content_type") or "").strip()
        topic_group = str(raw.get("topic_group") or "").strip()
        if content_type == "tax_refund" and topic_group == "policy_benefit":
            return "policy_benefit"
        return content_type

    @staticmethod
    def _force_evergreen_fallback() -> bool:
        value = os.getenv("FORCE_EVERGREEN_FALLBACK", "")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _force_viral_issue_test() -> bool:
        value = os.getenv("FORCE_VIRAL_ISSUE_TEST", "")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _extract_viral_test_candidates(scored: list[ScoredNewsCandidate]) -> list[ScoredNewsCandidate]:
        viral_source_types = {"viral_fallback"}
        viral_query_groups = {
            "entertainment_reaction",
            "ott_drama_reaction",
            "sports_reaction",
            "fandom_consumption",
            "community_hot_issue",
        }
        viral_topic_groups = {"entertainment_sports", "ott_platform", "fandom_consumer"}
        result: list[ScoredNewsCandidate] = []
        for item in scored:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            source_type = str(raw.get("source_type") or "").lower()
            query_group = str(raw.get("query_group") or "")
            topic_group = str(raw.get("topic_group") or "")
            content_type = str((raw.get("content_angle") or {}).get("content_type") or "")
            if (
                source_type in viral_source_types
                or query_group in viral_query_groups
                or topic_group in viral_topic_groups
                or content_type == "viral_issue_decode"
            ):
                result.append(item)
        return result

    def _save_artifact(
        self,
        *,
        html: str,
        selected: ScoredNewsCandidate,
        titles: list[dict[str, Any]],
        publish_quality_gate: dict[str, Any],
        image_plan: dict[str, str],
        run_meta: dict[str, Any],
        replacement_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # --- golden preview ---
        golden_preview_result: dict[str, Any] = {}
        try:
            topic = selected.candidate.topic or ""
            _raw_for_gp = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
            _ct_for_gp = str((_raw_for_gp.get("content_angle") or {}).get("content_type") or "")
            _tg_for_gp = str(_raw_for_gp.get("topic_group") or "")
            _summary_parts = [
                str(_raw_for_gp.get("search_demand_topic") or ""),
                " ".join(list(_raw_for_gp.get("reader_search_questions") or [])[:2]),
                str((_raw_for_gp.get("content_angle") or {}).get("reader_question") or ""),
                " ".join(list(_raw_for_gp.get("sample_titles") or [])[:3]),
            ]
            _summary_for_gp = " ".join(p for p in _summary_parts if p)
            golden_preview_result = self.golden_preview_service.build_preview(
                topic=topic,
                content_type=_ct_for_gp,
                topic_group=_tg_for_gp,
                summary=_summary_for_gp,
                candidate_raw=_raw_for_gp,
            )
        except Exception as gp_exc:
            logger.warning("golden preview build failed: %s", gp_exc)

        # --- editorial scoring ---
        editorial_scores = self._compute_editorial_scores(
            selected=selected,
            publish_quality_gate=publish_quality_gate,
            golden_preview_result=golden_preview_result,
        )
        content_candidate_grade = self._compute_content_candidate_grade(
            editorial_scores=editorial_scores,
            golden_preview_result=golden_preview_result,
            publish_quality_gate=publish_quality_gate,
        )
        golden_preview_result["_editorial_scores"] = editorial_scores
        golden_preview_result["_content_candidate_grade"] = content_candidate_grade

        # --- article_candidate 생성 가능 여부 사전 계산 ---
        _pm_for_cand = golden_preview_result.get("pattern_match") or {}
        _is_near_match = bool(golden_preview_result.get("near_match"))
        _pm_conf = int(_pm_for_cand.get("confidence", 0))
        _pm_ct_match = bool(_pm_for_cand.get("content_type_match"))
        _pm_tg_match = bool(_pm_for_cand.get("topic_group_match"))
        # near_match: confidence 75~79 + ct_match + tg_match → article_candidate 허용 (human_review=True)
        _near_match_ok = (
            _is_near_match
            and _pm_conf >= 75
            and _pm_ct_match
            and _pm_tg_match
            and float(golden_preview_result.get("slot_fill_rate", 0)) >= 0.8
            and not [b for b in (golden_preview_result.get("blocking_issues") or [])
                     if "near_match" not in b and "pattern_not_matched" not in b]
        )
        _can_generate_candidate = (
            bool(golden_preview_result.get("matched"))
            and (
                (bool(golden_preview_result.get("ready_for_review")) and _pm_conf >= 80)
                or _near_match_ok
            )
            and float(golden_preview_result.get("slot_fill_rate", 0)) >= 0.8
            and (
                content_candidate_grade in ("A", "B")
                or (_is_near_match and content_candidate_grade in ("A", "B", "C"))
            )
        )
        # --- title candidate engine (A/B 후보일 때만, article_candidate HTML 렌더링 전에 실행) ---
        _title_result: dict[str, Any] = {}
        if _can_generate_candidate:
            try:
                _raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
                _ct = str((_raw.get("content_angle") or {}).get("content_type") or "")
                _tg = str(_raw.get("topic_group") or "")
                _topic = selected.candidate.topic or ""
                _title_result = self.title_candidate_service.generate_candidates(
                    topic=_topic,
                    content_type=_ct,
                    topic_group=_tg,
                    pattern_id=str(_pm_for_cand.get("pattern_id") or ""),
                    candidate_raw=_raw,
                )
            except Exception as _te:
                logger.warning("title_candidate_service failed: %s", _te)
        _selected_title = (_title_result.get("best_title") or {}).get("title", "")
        # --------------------------------------------------

        # --- AI 계열 글: 슬롯을 LLM 주제 특화 본문으로 보강 ---
        # 정적 골든패턴 텍스트가 매 발행마다 그대로 반복되는 문제의 해결 지점.
        # ai_pipeline._enrich_preview_slots와 동일한 in-place 패턴 — 실패/비활성 시
        # 원본 슬롯 유지(폴백)라 발행 흐름은 바뀌지 않는다. 렌더링 직전에만 호출해
        # 탈락 후보에는 LLM 비용을 쓰지 않는다.
        if _can_generate_candidate:
            try:
                from blogspot_automation.services.golden_article_preview_service import _is_ai_family
                _raw_e = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
                _ct_e = str((_raw_e.get("content_angle") or {}).get("content_type") or "")
                _pid_e = str(_pm_for_cand.get("pattern_id") or "")
                if _is_ai_family(_pid_e, _ct_e):
                    from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
                    _sr_e = golden_preview_result.get("slot_result") or {}
                    _slots_e = _sr_e.get("slots") or {}
                    if _slots_e:
                        _enriched = enrich_slots_with_llm(
                            slots=_slots_e,
                            topic=selected.candidate.topic or "",
                            content_type=_ct_e,
                            selected_title=_selected_title,
                            angle_type=str(
                                (_raw_e.get("search_angle") or {}).get("angle_type") or ""
                            ),
                        )
                        _sr_e["slots"] = _enriched
                        golden_preview_result["slot_result"] = _sr_e
                        _llm_t = _enriched.get("_llm_title")
                        if _llm_t:
                            logger.info("NewsPipeline: LLM 제목 채택 — %s", _llm_t)
                            _selected_title = _llm_t
            except Exception as _en_exc:
                logger.warning("NewsPipeline: slot enrich 실패(템플릿 폴백): %s", _en_exc)

        # article_candidate.html 렌더링 (selected_title 반영)
        _article_candidate_html = ""
        if _can_generate_candidate:
            try:
                _article_candidate_html = self.golden_preview_service.render_article_candidate_html(
                    pattern_match=_pm_for_cand,
                    slot_result=golden_preview_result.get("slot_result") or {},
                    selected_title=_selected_title,
                    cover_image_url=str(image_plan.get("cover_image_url") or ""),
                )
            except Exception as _rce:
                logger.warning("render_article_candidate_html failed: %s", _rce)
                _can_generate_candidate = False
        golden_preview_result["_can_generate_candidate"] = _can_generate_candidate
        golden_preview_result["_article_candidate_html"] = _article_candidate_html
        golden_preview_result["_title_result"] = _title_result
        golden_preview_result["_selected_title"] = _selected_title

        # --- topic engine v2 + golden 통합 ---
        _gpr_pm = golden_preview_result.get("pattern_match") or {}
        golden_matched = bool(
            golden_preview_result.get("matched")
            and (
                int(_gpr_pm.get("confidence", 0)) >= 80
                or golden_preview_result.get("near_match")
            )
        )
        raw_candidate = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        initial_grade = str(raw_candidate.get("topic_candidate_grade") or "D")
        # golden 매칭 실패 시 등급 하향 (near_match는 하향 없음)
        if not golden_matched:
            initial_grade = "C" if initial_grade in ("A", "B") else initial_grade
        raw_candidate["topic_candidate_grade"] = initial_grade
        raw_candidate["golden_matched"] = golden_matched
        raw_candidate["near_match"] = _is_near_match

        phase_hold = self._is_publish_hold_phase2()
        # topic_candidate_grade는 golden pattern 매칭 이전, 원본 주제 자체의 점수다.
        # golden pattern이 완전 매칭(near_match 아님)되고 실제 생성된 글이 A/B 등급이면,
        # 원본 주제 점수가 낮았다는 이유만으로 계속 사람 검토 대기시키지 않는다 —
        # 발행 여부는 최종 콘텐츠 품질(content_candidate_grade) 기준을 따른다.
        _content_grade_overrides_topic_grade = (
            golden_matched
            and not _is_near_match
            and content_candidate_grade in ("A", "B")
        )
        human_review_required = (
            phase_hold
            or _is_near_match
            or (initial_grade in ("C", "D") and not _content_grade_overrides_topic_grade)
        )
        why_selected = (
            f"topic_engine_score={raw_candidate.get('topic_engine_score', 0)} "
            f"+ golden_matched={golden_matched} + grade={initial_grade}"
            f"{' + near_match' if _is_near_match else ''}"
            if initial_grade in ("A", "B", "C") and golden_matched else ""
        )
        if not golden_matched:
            _pm = golden_preview_result.get("pattern_match") or {}
            _conf = int(_pm.get("confidence", 0))
            _neg = list(_pm.get("negative_hits") or [])
            _kw_hits = list(_pm.get("matched_keywords") or [])
            if _neg:
                why_held = f"golden_pattern_not_matched:negative_keyword_hit:{','.join(_neg[:2])}"
            elif 0 < _conf < 80:
                why_held = f"golden_pattern_not_matched:confidence_below_80({_conf})"
            elif _conf == 0 and _kw_hits:
                why_held = "golden_pattern_not_matched:content_type_mismatch"
            else:
                why_held = "golden_pattern_not_matched:no_keyword_overlap"
        elif _is_near_match:
            why_held = f"near_match_confidence:{_pm_conf}+human_review_required"
        elif initial_grade in ("C", "D") and not _content_grade_overrides_topic_grade:
            why_held = f"grade={initial_grade}"
        elif phase_hold:
            why_held = "PUBLISH_HOLD_PHASE2=true"
        else:
            why_held = ""
        # ----------------------

        pm = golden_preview_result.get("pattern_match") or {}
        enriched_run_meta: dict[str, Any] = {
            **run_meta,
            "golden_preview_generated": bool(golden_preview_result),
            "golden_preview_ready_for_review": golden_preview_result.get("ready_for_review", False),
            "golden_pattern_id": pm.get("pattern_id") or "",
            "golden_pattern_confidence": int(pm.get("confidence", 0)),
            "golden_slot_fill_rate": float(golden_preview_result.get("slot_fill_rate", 0.0)),
            "golden_missing_required_slots": golden_preview_result.get("missing_required_slots", []),
            "golden_blocking_issues": golden_preview_result.get("blocking_issues", []),
            "golden_warnings": golden_preview_result.get("warnings", []),
            "content_candidate_grade": content_candidate_grade,
            "traffic_potential_score": editorial_scores.get("traffic_potential_score", 0),
            "usefulness_score": editorial_scores.get("usefulness_score", 0),
            "evergreen_asset_score": editorial_scores.get("evergreen_asset_score", 0),
            "viral_safety_score": editorial_scores.get("viral_safety_score", 0),
            "final_editorial_score": editorial_scores.get("final_editorial_score", 0),
            # Topic Engine v2
            "topic_candidate_bucket": raw_candidate.get("topic_candidate_bucket", "general"),
            "topic_engine_score": raw_candidate.get("topic_engine_score", 0),
            "topic_candidate_grade": initial_grade,
            "topic_traffic_potential_score": raw_candidate.get("topic_traffic_potential_score", 0),
            "topic_search_intent_score": raw_candidate.get("topic_search_intent_score", 0),
            "topic_usefulness_score": raw_candidate.get("topic_usefulness_score", 0),
            "topic_safety_score": raw_candidate.get("topic_safety_score", 0),
            "topic_monetization_score": raw_candidate.get("topic_monetization_score", 0),
            "golden_matched": golden_matched,
            "why_topic_selected": why_selected,
            "why_topic_held": why_held,
            "human_review_required": human_review_required,
            # Article Candidate
            "article_candidate_generated": _can_generate_candidate,
            "article_candidate_path": "article_candidate.html" if _can_generate_candidate else "",
            "article_candidate_source": "golden_preview" if _can_generate_candidate else "",
            "publish_allowed_in_phase2": False,
            # Title Candidate Engine
            "title_candidates_generated": bool(_title_result),
            "selected_title": (_title_result.get("best_title") or {}).get("title", ""),
            "selected_title_ctr_score": (_title_result.get("best_title") or {}).get("ctr_score", 0),
            "selected_title_type": (_title_result.get("best_title") or {}).get("title_type", ""),
            "selected_title_risk_score": (_title_result.get("best_title") or {}).get("risk_score", 0),
            "selected_title_promise_match_score": (_title_result.get("best_title") or {}).get("promise_match_score", 0),
            "publish_quality_gate": publish_quality_gate,
        }

        run_path = self.artifact_service.save_dry_run_result(
            html=html,
            selected_topic=selected.to_dict(),
            title_candidates=titles,
            scoring={
                "total_score": selected.total_score,
                "click_potential_score": self._click_potential_score(selected),
                "raw_total_score": selected.candidate.raw.get("raw_total_score"),
                "topic_group": selected.candidate.raw.get("topic_group"),
                "cooldown_penalty": selected.candidate.raw.get("cooldown_penalty", 0),
                "search_angle": selected.candidate.raw.get("search_angle"),
                "search_demand_topic": selected.candidate.raw.get("search_demand_topic"),
                "reader_search_questions": selected.candidate.raw.get("reader_search_questions"),
                "click_reason": selected.candidate.raw.get("click_reason"),
                "reader_benefit": selected.candidate.raw.get("reader_benefit"),
                "reader_interest_score": selected.candidate.raw.get("reader_interest_score"),
                "reader_interest_strategy": selected.candidate.raw.get("reader_interest_strategy"),
                "reader_interest_publish_intent": selected.candidate.raw.get("reader_interest_publish_intent"),
                "reader_interest_brief": selected.candidate.raw.get("reader_interest_brief"),
                "save_value_score": selected.candidate.raw.get("save_value_score"),
                "curiosity_score": selected.candidate.raw.get("curiosity_score"),
                "urgency_reason": selected.candidate.raw.get("urgency_reason"),
                "content_promise": selected.candidate.raw.get("content_promise"),
                "angle_type": selected.candidate.raw.get("angle_type"),
                "commercial_support_signal": selected.candidate.raw.get("commercial_support_signal", False),
                "generic_support_keyword": selected.candidate.raw.get("generic_support_keyword", ""),
                "public_benefit_keyword": selected.candidate.raw.get("public_benefit_keyword", ""),
                "public_benefit_confidence": selected.candidate.raw.get("public_benefit_confidence", "none"),
                "stale_penalty_applied": selected.candidate.raw.get("stale_penalty_applied", False),
                "public_benefit_promotion_blocked": selected.candidate.raw.get("public_benefit_promotion_blocked", False),
                "source_type": run_meta.get("source_type", ""),
                "is_test_candidate": run_meta.get("is_test_candidate", False),
                "fallback_candidate": run_meta.get("fallback_candidate", False),
                "publish_allowed": run_meta.get("publish_allowed", True),
                "evergreen_axis": run_meta.get("evergreen_axis", ""),
                "evergreen_reason": run_meta.get("evergreen_reason", ""),
                "fallback_reason": run_meta.get("fallback_reason", ""),
                "target_reader": run_meta.get("target_reader", ""),
                "article_focus_score": publish_quality_gate.get("article_focus_score"),
                "reader_value_score": publish_quality_gate.get("reader_value_score"),
                "labels": run_meta.get("labels", []),
                "label_count": run_meta.get("label_count", 0),
                "hashtags": run_meta.get("hashtags", []),
                "hashtag_count": run_meta.get("hashtag_count", 0),
                "internal_link_suggestions": run_meta.get("internal_link_suggestions", []),
                "content_angle": selected.candidate.raw.get("content_angle"),
                "hook_angle": selected.candidate.raw.get("hook_angle"),
                "image_prompt": image_plan.get("image_prompt", ""),
                "image_alt_text": image_plan.get("image_alt_text", ""),
                "image_size_recommendation": image_plan.get("image_size_recommendation", ""),
                "image_usage_note": image_plan.get("image_usage_note", ""),
                "search_intent_score": selected.candidate.raw.get("search_intent_score"),
                "money_loss_score": selected.candidate.raw.get("money_loss_score"),
                "mass_relevance_score": selected.candidate.raw.get("mass_relevance_score"),
                "practical_value_score": selected.candidate.raw.get("practical_value_score"),
                "brand_fit_score": selected.candidate.raw.get("brand_fit_score"),
                "strategy_score_breakdown": selected.candidate.raw.get("strategy_score_breakdown"),
                "strategy_risk_penalty": (selected.candidate.raw.get("strategy_score_breakdown") or {}).get("risk_penalty"),
                "freshness_score": selected.freshness_score,
                "search_demand_score": selected.search_demand_score,
                "contrarian_gap_score": selected.contrarian_gap_score,
                "mass_impact_score": selected.mass_impact_score,
                "adsense_value_score": selected.adsense_value_score,
                "hook_score": selected.hook_score,
                "risk_penalty": selected.risk_penalty,
                "publish_quality_gate": publish_quality_gate,
            },
            run_meta=enriched_run_meta,
            image_prompt=image_plan.get("image_prompt", ""),
        )

        # golden preview artifact 저장 (실패해도 파이프라인 중단 안 함)
        if golden_preview_result:
            # labels/hashtags/pattern_id를 artifact 저장에 전달
            try:
                from blogspot_automation.services.news_label_service import NewsLabelService as _LabelSvc
                _lsvc = _LabelSvc()
                _bl = _lsvc.build_blogspot_labels(
                    pattern_id=str(_pm_for_cand.get("pattern_id") or ""),
                    content_type=_ct_for_gp,
                    topic_group=_tg_for_gp,
                )
                golden_preview_result["_blogspot_labels"] = normalize_labels(_bl)
            except Exception:
                golden_preview_result["_blogspot_labels"] = []
            golden_preview_result["_hashtags"] = normalize_hashtags(run_meta.get("hashtags", []))
            golden_preview_result["_labels"] = normalize_labels(run_meta.get("labels", []))
            golden_preview_result["_content_type"] = _ct_for_gp
            golden_preview_result["_topic_group"] = _tg_for_gp
            # stale 정보를 두 경로로 전달 (candidate.raw + quality_gate blocking)
            _raw_for_stale = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
            golden_preview_result["_stale_candidate"] = bool(_raw_for_stale.get("is_stale"))
            golden_preview_result["_scoring_stale_penalty"] = bool(_raw_for_stale.get("stale_penalty_applied"))
            if replacement_meta:
                golden_preview_result["_replacement_meta"] = replacement_meta
            self.artifact_service.save_golden_preview_artifacts(run_path, golden_preview_result)

        # title candidate artifact 저장
        if _title_result:
            self.artifact_service.save_title_candidate_artifacts(run_path, _title_result)

        article_candidate_meta: dict[str, Any] = {}
        article_candidate_meta_path = run_path / "article_candidate_meta.json"
        if article_candidate_meta_path.exists():
            try:
                loaded_meta = json.loads(article_candidate_meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded_meta, dict):
                    article_candidate_meta = loaded_meta
            except Exception as meta_exc:  # noqa: BLE001
                logger.warning("article_candidate_meta read failed: %s", meta_exc)

        return {
            "run_path": run_path,
            "golden_preview_result": golden_preview_result,
            "editorial_scores": editorial_scores,
            "content_candidate_grade": content_candidate_grade,
            "article_candidate_meta": article_candidate_meta,
            "_why_topic_selected": why_selected,
            "_why_topic_held": why_held,
            "_human_review_required": human_review_required,
            "_article_candidate_generated": _can_generate_candidate,
        }

    def _dedup_history_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        records.extend(self.dedup_service.load_history())
        records.extend(self.publish_history_service.recent_records(limit=120, published_only=True))

        unique_records: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for record in records:
            if not TopicDedupService.record_blocks_duplicate(record):
                continue
            key = (
                str(record.get("date", "")),
                str(record.get("selected_topic") or record.get("topic") or ""),
                str(record.get("title") or record.get("selected_title") or ""),
                str(record.get("url") or record.get("post_url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            unique_records.append(record)
        return unique_records

    def _recent_duplicate_issue(self, *, selected_topic: str, selected_title: str) -> str:
        if self._manual_dedup_bypass_enabled():
            return ""
        history_records = self._dedup_history_records()
        topic_norm = self.dedup_service.normalize_text(selected_topic)
        title_norm = self.dedup_service.normalize_text(selected_title)
        for record in history_records:
            if not TopicDedupService.record_blocks_duplicate(record):
                continue
            if not self.dedup_service._is_within_dedup_window(record):
                continue
            record_topic_norms = [
                self.dedup_service.normalize_text(str(record.get("topic", ""))),
                self.dedup_service.normalize_text(str(record.get("selected_topic", ""))),
                self.dedup_service.normalize_text(str(record.get("search_demand_topic", ""))),
            ]
            record_title_norms = [
                self.dedup_service.normalize_text(str(record.get("title", ""))),
                self.dedup_service.normalize_text(str(record.get("selected_title", ""))),
            ]
            if topic_norm and topic_norm in record_topic_norms:
                return "selected_topic_recently_published"
            if title_norm and title_norm in record_title_norms:
                return "selected_title_recently_published"
        return ""

    def _manual_dedup_bypass_enabled(self) -> bool:
        return (
            not self.dry_run
            and self.news_publish_mode == "publish"
            and os.getenv("GITHUB_EVENT_NAME", "").strip().lower() == "workflow_dispatch"
            and os.getenv("NEWS_MANUAL_DEDUP_BYPASS", "").strip().lower() in {"1", "true", "yes", "on"}
        )

    def _apply_topic_group_cooldowns(
        self,
        scored: list[ScoredNewsCandidate],
        history_records: list[dict[str, Any]],
        recent_evergreen_axes: list[str] | None = None,
    ) -> list[ScoredNewsCandidate]:
        ai_blog_mode = self._ai_blog_mode_enabled()
        preferred_axis = "ai_automation" if ai_blog_mode else EvergreenTopicService.preferred_axis_by_weekday()
        for item in scored:
            topic_group = self._candidate_topic_group(item)
            if str(item.candidate.raw.get("source_type") or "").lower() == "evergreen_fallback":
                axis = str(item.candidate.raw.get("evergreen_axis") or "")
                if ai_blog_mode:
                    # ai_blog_mode restricts evergreen fallback to a single axis
                    # (ai_automation, see _collect_evergreen_publish_fallback_candidates),
                    # so there is no rotation to penalize — the weekday-based preferred_axis
                    # rarely matches "ai_automation", which left the full repetition penalty
                    # in place and silently zeroed out the evergreen fallback pool on most days.
                    penalty = 0
                else:
                    penalty = self._evergreen_axis_rotation_penalty(axis, recent_evergreen_axes or [])
                    if axis and axis == preferred_axis:
                        penalty = max(-10, penalty - 5)
                item.candidate.raw["evergreen_rotation_penalty"] = penalty
            else:
                penalty = self._cooldown_penalty(topic_group, history_records)
                # discovery_engine 고buzz 후보는 실시간 핫이슈 — cooldown 면제
                if (
                    item.candidate.raw.get("discovery_engine")
                    and int(item.candidate.raw.get("today_buzz_score") or 0) >= 8
                    and topic_group != "policy_benefit"
                ):
                    penalty = 0
            raw_total_score = self._raw_total_score(item)
            item.candidate.raw["topic_group"] = topic_group
            item.candidate.raw["cooldown_penalty"] = penalty
            item.total_score = max(0, min(100, raw_total_score - penalty))
            # discovery_engine 고buzz 후보 우선 선택 boost (source_count 반영)
            if (
                item.candidate.raw.get("discovery_engine")
                and int(item.candidate.raw.get("today_buzz_score") or 0) >= 8
            ):
                _sc = int(item.candidate.raw.get("source_count") or 0)
                item.total_score = min(100, item.total_score + 5 + min(_sc, 5))
        return sorted(scored, key=lambda candidate: candidate.total_score, reverse=True)

    def _collect_evergreen_publish_fallback_candidates(
        self,
        *,
        topic_group_history: list[dict[str, Any]],
        recent_evergreen_axes: list[str],
    ) -> tuple[list[Any], list[ScoredNewsCandidate], list[ScoredNewsCandidate]]:
        candidates = self.evergreen_topic_service.collect_candidates()
        ai_blog_mode = self._ai_blog_mode_enabled()
        if ai_blog_mode:
            candidates = [
                candidate for candidate in candidates
                if (candidate.raw or {}).get("evergreen_axis") == "ai_automation"
            ]
        scored = self.scoring_service.score_candidates(candidates)
        scored = self._apply_topic_group_cooldowns(
            scored,
            topic_group_history,
            recent_evergreen_axes,
        )
        publishable = [
            item for item in self.scoring_service.get_publishable_candidates(scored)
            if self._is_safe_evergreen_publish_fallback_candidate(item)
        ]
        golden_publishable = self._prefer_golden_matched_candidates(publishable)
        if not golden_publishable:
            golden_publishable = self._prefer_golden_matched_candidates([
                item for item in scored
                if self._is_safe_evergreen_publish_fallback_candidate(item)
                and item.total_score >= self.scoring_service.min_topic_score
            ])
        preferred_axis = "ai_automation" if ai_blog_mode else EvergreenTopicService.preferred_axis_by_weekday()
        selected_pool = sorted(
            golden_publishable,
            key=lambda item: self._evergreen_publish_fallback_sort_key(
                item,
                recent_evergreen_axes=recent_evergreen_axes,
                preferred_axis=preferred_axis,
            ),
        )
        if ai_blog_mode:
            selected_pool = self._rank_evergreen_pool_by_search_demand(selected_pool)
        logger.info(
            "evergreen publish fallback: candidates=%d publishable=%d golden=%d selected=%d",
            len(candidates),
            len(publishable),
            len(golden_publishable),
            len(selected_pool),
        )
        return candidates, scored, selected_pool

    # 가격/구독 축 토큰 — 에버그린 선정 시점의 근접 중복 예방용.
    _PRICING_FAMILY_TOKENS = (
        "pricing", "price", "prices", "cost", "costs", "subscription",
        "subscriptions", "plan", "plans", "fee", "fees",
    )

    @classmethod
    def _topic_is_pricing_family(cls, text: str) -> bool:
        lowered = (text or "").lower()
        return any(
            re.search(rf"\b{re.escape(token)}\b", lowered)
            for token in cls._PRICING_FAMILY_TOKENS
        )

    def _rank_evergreen_pool_by_search_demand(
        self, selected_pool: list[ScoredNewsCandidate]
    ) -> list[ScoredNewsCandidate]:
        """에버그린 폴백 풀을 실검색 수요 + 가격축 쿨다운으로 재정렬한다.

        배경(2026-07-22): 2026-07-21 발행 2건이 둘 다 에버그린 폴백이었고,
        에버그린 후보에는 수요 신호가 전혀 없어 뱅크 정렬 순서대로 뽑혔다 —
        같은 날 가격비교 축 2건("Pricing Compared"/"Student Pricing")이 연속
        발행됐다. 여기서는 (1) 최근 72시간 내 가격축 글이 발행됐으면 가격축
        에버그린 후보를 뒤로 미루고(생성 후 게이트 차단으로 슬롯을 날리는 대신
        선정 단계에서 회피), (2) Google Autocomplete 제안 수(상시 검색 수요
        프록시)가 높은 주제를 앞으로 당긴다. 파이썬 정렬은 안정적이라 기존
        정렬 키(골든 confidence·클릭 점수 등)는 동점 그룹 안에서 그대로 유지.
        실패는 전부 비치명 — 어떤 예외에서도 원래 풀을 그대로 돌려준다.
        """
        if len(selected_pool) <= 1:
            return selected_pool
        try:
            pricing_cooldown = self._recent_pricing_family_published(hours=72)
        except Exception as _pc_exc:  # noqa: BLE001
            logger.warning("pricing family cooldown 조회 실패(무시): %s", _pc_exc)
            pricing_cooldown = False
        demand_by_id: dict[int, int] = {}
        try:
            from blogspot_automation.services.search_autocomplete_signal import (
                score_topic_boost as _autocomplete_boost,
            )
            # 네트워크 호출은 풀 상위 8개만 — 나머지는 수요 0으로 취급.
            for item in selected_pool[:8]:
                raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
                probe_text = str(
                    raw.get("search_demand_topic") or item.candidate.topic or ""
                )
                boost, keywords = _autocomplete_boost(probe_text, max_boost=12)
                demand_by_id[id(item)] = boost
                if boost > 0:
                    raw["demand_signal_boost"] = max(
                        int(raw.get("demand_signal_boost") or 0), boost
                    )
                    raw["demand_signal_keywords"] = list(
                        dict.fromkeys(
                            [*list(raw.get("demand_signal_keywords") or []), *keywords]
                        )
                    )
        except Exception as _ad_exc:  # noqa: BLE001
            logger.warning("evergreen autocomplete demand 실패(무시): %s", _ad_exc)

        def _demand_sort_key(item: ScoredNewsCandidate) -> tuple[int, int]:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            topic_text = " ".join(
                str(part or "")
                for part in (item.candidate.topic, raw.get("search_demand_topic"))
            )
            pricing_penalty = 1 if pricing_cooldown and self._topic_is_pricing_family(topic_text) else 0
            return (pricing_penalty, -demand_by_id.get(id(item), 0))

        reranked = sorted(selected_pool, key=_demand_sort_key)
        if reranked and selected_pool and reranked[0] is not selected_pool[0]:
            logger.info(
                "evergreen demand rerank: '%s' → '%s' (pricing_cooldown=%s)",
                str(selected_pool[0].candidate.topic)[:60],
                str(reranked[0].candidate.topic)[:60],
                pricing_cooldown,
            )
        return reranked

    @staticmethod
    def _recent_pricing_family_published(*, hours: int = 72) -> bool:
        """최근 N시간 내 발행 글 중 가격/구독 축 제목이 있는지 확인한다."""
        from datetime import datetime, timedelta, timezone

        from blogspot_automation.services.publish_history_service import PublishHistoryService

        records = PublishHistoryService().recent_records(limit=10, published_only=True)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        for record in records:
            title = str(record.get("title") or record.get("selected_title") or "")
            if not NewsPipeline._topic_is_pricing_family(title):
                continue
            run_at = str(record.get("run_at") or "")
            try:
                stamp = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
            except ValueError:
                # 타임스탬프가 깨진 레코드는 보수적으로 쿨다운 활성으로 본다.
                return True
            if stamp >= cutoff:
                return True
        return False

    def _is_safe_evergreen_publish_fallback_candidate(self, item: ScoredNewsCandidate) -> bool:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        if source_type != "evergreen_fallback":
            return False
        if bool(raw.get("is_stale")):
            return False
        content_type = self._news_publish_content_type(raw)
        ai_blog_content_allowed = self._ai_blog_mode_enabled() and content_type == "ai_work_tip"
        if content_type not in self.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES and not ai_blog_content_allowed:
            return False
        if content_type in self.NEWS_AUTO_PUBLISH_EXCLUDED_CONTENT_TYPES and not ai_blog_content_allowed:
            return False
        evergreen_axis = str(raw.get("evergreen_axis") or "").strip()
        if evergreen_axis in self.NEWS_AUTO_PUBLISH_EXCLUDED_EVERGREEN_AXES:
            return False
        if item.total_score < self.scoring_service.min_topic_score:
            return False
        focus = evaluate_news_focus(
            topic=item.candidate.topic or "",
            summary=item.candidate.summary or "",
            raw=raw,
        )
        return focus.allowed

    @staticmethod
    def _evergreen_publish_fallback_sort_key(
        item: ScoredNewsCandidate,
        *,
        recent_evergreen_axes: list[str],
        preferred_axis: str,
    ) -> tuple[int, int, int, int, int, int]:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        axis = str(raw.get("evergreen_axis") or "")
        try:
            confidence = int(raw.get("golden_selection_confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        try:
            click_score = int(raw.get("click_potential_score") or 0)
        except (TypeError, ValueError):
            click_score = 0
        tax_rank = 1 if axis == "tax_refund_support" and axis != preferred_axis else 0
        recent_count = recent_evergreen_axes[:3].count(axis)
        preferred_rank = 0 if axis == preferred_axis else 1
        return (
            tax_rank,
            recent_count,
            preferred_rank,
            -confidence,
            -click_score,
            -int(item.total_score),
        )

    # ── fallback_type별 허용/차단 콘텐츠 타입 ────────────────────────────
    _FALLBACK_EXCLUDED_CONTENT_TYPES: frozenset = frozenset({
        "general_life", "ai_work_tip", "blogspot_growth", "evergreen_fallback",
    })
    _FALLBACK_TYPE_MAP: dict = {
        "viral_issue_decode": "viral",
        "ai_work_tip": "evergreen",
        "money_checklist": "useful_news",
        "platform_change": "useful_news",
        "consumer_warning": "useful_news",
        "policy_deadline": "useful_news",
        "policy_benefit": "useful_news",
        "general_life": "evergreen",
        "blogspot_growth": "evergreen",
        "digital_survival": "evergreen",
    }
    _FALLBACK_MIN_SCORE = 70

    def _find_fallback_when_no_fresh_replacement(
        self,
        scored: list[ScoredNewsCandidate],
        original: ScoredNewsCandidate,
    ) -> tuple[ScoredNewsCandidate | None, str, str]:
        """fresh replacement 없을 때 scored 후보 + evergreen 후보에서 fallback을 찾는다.

        1순위: viral_issue_decode
        2순위: ai_work_tip (golden matched)
        3순위: useful_news (money_checklist, platform_change, digital_survival)
        4순위: evergreen useful (general_life, blogspot_growth)
        5순위: 없으면 None
        """
        # scored 후보에서 먼저 탐색
        result = self._search_fallback_in_pool(scored, original)
        if result[0]:
            logger.info("fallback found in scored pool: %s", result[0].candidate.topic[:40])
            return result

        # evergreen 후보에서 탐색
        try:
            _eg_cands = self.evergreen_topic_service.collect_candidates()
            _eg_scored = self.scoring_service.score_candidates(_eg_cands)
        except Exception as _ee:
            logger.warning("evergreen fetch for fallback failed: %s", _ee)
            return None, "evergreen_fetch_failed", "hold"

        result = self._search_fallback_in_pool(_eg_scored, original)
        if result[0]:
            logger.info("fallback found in evergreen pool: %s", result[0].candidate.topic[:40])
        return result

    def _search_fallback_in_pool(
        self,
        pool: list[ScoredNewsCandidate],
        original: ScoredNewsCandidate,
    ) -> tuple[ScoredNewsCandidate | None, str, str]:
        """pool에서 fallback 기준을 통과하는 후보를 우선순위 순으로 반환한다."""
        # fallback_type 우선순위
        _type_priority = {
            "viral": 0,
            "evergreen": 1,  # ai_work_tip 포함
            "useful_news": 2,
        }

        candidates_with_type: list[tuple[int, int, ScoredNewsCandidate, str]] = []

        for c in pool:
            if c.candidate.topic == (original.candidate.topic or ""):
                continue
            if self._is_retry_excluded_candidate(c):
                continue
            raw = c.candidate.raw if isinstance(c.candidate.raw, dict) else {}
            if not self._is_news_auto_publish_candidate(c):
                continue
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            if ct in self._FALLBACK_EXCLUDED_CONTENT_TYPES and not (
                self._ai_blog_mode_enabled() and ct == "ai_work_tip"
            ):
                continue
            if raw.get("stale_penalty_applied") or raw.get("is_stale"):
                continue
            if str(raw.get("source_type") or raw.get("source") or "").lower() == "fallback":
                continue
            if raw.get("is_test_candidate"):
                continue
            if raw.get("publish_allowed") is False:
                continue
            if int(c.risk_penalty or 0) > 0:
                continue
            if c.total_score < self._FALLBACK_MIN_SCORE:
                continue

            fallback_type = self._FALLBACK_TYPE_MAP.get(ct, "evergreen")
            priority = _type_priority.get(fallback_type, 99)
            hook_priority = self._candidate_hook_priority(c)
            candidates_with_type.append((priority, hook_priority, c, fallback_type))

        if not candidates_with_type:
            return None, "no_fallback_in_pool", "hold"

        candidates_with_type.sort(key=lambda x: (x[0], x[1], -x[2].total_score))
        _, _, best, fb_type = candidates_with_type[0]
        _r = best.candidate.raw if isinstance(best.candidate.raw, dict) else {}
        _ct = str(((_r.get("content_angle") or {}).get("content_type")) or "")
        reason = (
            f"fallback_type={fb_type} ct={_ct} "
            f"golden={_r.get('golden_matched', False)} "
            f"hook_priority={_r.get('hook_category_priority', 3)} score={best.total_score}"
        )
        return best, reason, fb_type

    @staticmethod
    def _is_stale_candidate(selected: ScoredNewsCandidate) -> bool:
        """후보의 raw 필드에서 stale 여부를 판단한다.

        - stale_penalty_applied=True
        - is_stale=True
        - policy_benefit/tax_refund 계열 + official_source_check_needed
        """
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        if source_type == "evergreen_fallback":
            return False
        if raw.get("stale_penalty_applied"):
            return True
        if raw.get("is_stale"):
            return True
        topic_group = str(raw.get("topic_group") or "")
        _bd = raw.get("strategy_score_breakdown") or {}
        if (
            topic_group in ("policy_benefit", "tax_refund")
            and bool((_bd or {}).get("official_source_check_needed"))
        ):
            return True
        return False

    @staticmethod
    def _find_fresh_replacement_candidate(
        scored: list[ScoredNewsCandidate],
        original: ScoredNewsCandidate,
        history_records: list[dict[str, Any]] | None = None,
        dedup_service: TopicDedupService | None = None,
    ) -> tuple[ScoredNewsCandidate | None, str]:
        """scored 리스트에서 fresh + publishable 대체 후보를 반환한다.

        우선순위: golden_matched > grade(A/B) > total_score > freshness_score
        제외: stale, fallback, test, publish_allowed=False, risk_penalty>0
        """
        _MIN_SCORE = 75

        pool: list[ScoredNewsCandidate] = []
        for c in scored:
            if c.candidate.topic == original.candidate.topic:
                continue
            raw = c.candidate.raw if isinstance(c.candidate.raw, dict) else {}
            if raw.get("stale_penalty_applied") or raw.get("is_stale"):
                continue
            if not NewsPipeline._is_news_auto_publish_candidate(c):
                continue
            src = str(raw.get("source_type") or raw.get("source") or "").lower()
            if src == "fallback":
                continue
            if raw.get("is_test_candidate"):
                continue
            if raw.get("publish_allowed") is False:
                continue
            if int(c.risk_penalty or 0) > 0:
                continue
            if c.total_score < _MIN_SCORE:
                continue
            if history_records is not None and dedup_service is not None:
                if dedup_service.is_duplicate(c, history_records):
                    continue
            pool.append(c)

        if not pool:
            return None, "no_fresh_candidates_available"

        golden_pool = [
            c for c in pool
            if NewsPipeline._candidate_golden_selection_penalty(c) == 0
        ]
        if golden_pool:
            pool = golden_pool

        def _sort_key(c: ScoredNewsCandidate) -> tuple:
            raw = c.candidate.raw if isinstance(c.candidate.raw, dict) else {}
            golden = bool(raw.get("golden_matched"))
            grade = raw.get("topic_candidate_grade", "D")
            grade_score = {"A": 4, "B": 3, "C": 2, "D": 1}.get(grade, 0)
            issue_priority = NewsPipeline._candidate_issue_selection_priority(c)
            click_score = NewsPipeline._candidate_click_selection_score(c)
            hook_priority = NewsPipeline._candidate_hook_priority(c)
            selection_penalty = NewsPipeline._candidate_selection_quality_penalty(c)
            return (
                selection_penalty,
                NewsPipeline._candidate_golden_selection_penalty(c),
                issue_priority,
                -click_score,
                -int(golden),
                -grade_score,
                hook_priority,
                -c.total_score,
                -float(c.freshness_score or 0),
            )

        pool.sort(key=_sort_key)
        best = pool[0]
        _r = best.candidate.raw if isinstance(best.candidate.raw, dict) else {}
        reason = (
            f"golden_matched={_r.get('golden_matched', False)} "
            f"grade={_r.get('topic_candidate_grade', '?')} "
            f"click_priority={NewsPipeline._candidate_issue_selection_priority(best)} "
            f"click_score={NewsPipeline._candidate_click_selection_score(best)} "
            f"hook_priority={_r.get('hook_category_priority', 3)} "
            f"score={best.total_score}"
        )
        return best, reason

    # ── 깨끗한 트렌딩 선형 발행 경로 (clean rewrite 2026-06-09) ──────────────
    # 소싱 → 필터 → 중복제거 → 랭킹 → (후보마다 렌더·검증) → 통과한 첫 글 발행.
    # 실패 후보는 건너뛰고 다음 후보로(재시도 thrash 없음). 트렌딩이 없거나 모두
    # 탈락하면 None → 기존 파이프라인 폴백. 기존 소비자/에버그린 경로는 불변.
    def _run_clean_trending_publish(self) -> dict[str, Any] | None:
        if str(os.getenv("AI_BLOG_MODE", "false")).strip().lower() in {"1", "true", "yes", "on"}:
            logger.info("clean_trending: AI_BLOG_MODE에서는 AI 전용 파이프라인 사용")
            return None
        if str(os.getenv("ENABLE_CLEAN_TRENDING_PUBLISH", "true")).strip().lower() in {"false", "0", "no", "off"}:
            return None
        candidates = self._collect_clean_trending_candidates()
        if not candidates:
            logger.info("clean_trending: 트렌딩 후보 없음 → 기존 파이프라인 폴백")
            return None
        ranked = self._rank_and_dedup_trending(candidates)
        logger.info(
            "clean_trending: 후보 %d개 수집, 필터·중복제거 후 %d개 랭킹",
            len(candidates), len(ranked),
        )
        try:
            max_attempts = max(1, int(os.getenv("CLEAN_TRENDING_MAX_ATTEMPTS", "6")))
        except ValueError:
            max_attempts = 6
        for cand in ranked[:max_attempts]:
            outcome = self._render_validate_publish_trending(cand)
            if outcome is not None:
                return outcome
        logger.info("clean_trending: 통과 후보 없음 → 기존 파이프라인 폴백")
        return None

    def _collect_clean_trending_candidates(self) -> list[NewsCandidate]:
        cands: list[NewsCandidate] = []
        try:
            from blogspot_automation.services.google_trends_topic_service import GoogleTrendsTopicService
            cands += GoogleTrendsTopicService().collect_trending_candidates(max_candidates=15)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clean_trending: google_trends 소싱 실패: %s", exc)
        try:
            from blogspot_automation.services.trending_news_service import TrendingNewsService
            cands += TrendingNewsService().collect_trending_candidates(max_candidates=15, min_cluster_size=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clean_trending: naver_trending 소싱 실패: %s", exc)
        return cands

    def _rank_and_dedup_trending(
        self, candidates: list[NewsCandidate]
    ) -> list[NewsCandidate]:
        from blogspot_automation.services.news_focus_policy import evaluate_news_focus
        from blogspot_automation.services.google_trends_topic_service import _is_market_noise

        recent_token_sets = self._recent_published_issue_token_sets(days=7)
        seen_keys: set[str] = set()
        kept: list[NewsCandidate] = []
        for c in candidates:
            raw = c.raw if isinstance(c.raw, dict) else {}
            text = f"{c.topic or ''} {c.summary or ''}"
            if not evaluate_news_focus(topic=c.topic or "", summary=c.summary or "", raw=raw).allowed:
                continue
            if _is_market_noise(text):
                continue
            key = self._trend_dedup_key(c)
            if not key or key in seen_keys:
                continue
            # 토큰 overlap 기반 동일 이슈 판정 — 같은 인물·주제라도 '새 전개'는
            # 허용한다(키워드 1개만 겹치면 다른 사건). 같은 사건의 재탕(키워드 +
            # 부주제 2개 이상 겹침)만 차단. 큰 이슈의 후속편이 조회수 기회이므로
            # 과거의 무조건 substring 차단을 완화.
            cand_tokens = self._issue_signature_tokens(c)
            if self._matches_recent_issue(cand_tokens, key, recent_token_sets):
                continue
            seen_keys.add(key)
            kept.append(c)
        kept.sort(
            key=lambda c: (
                int((c.raw or {}).get("click_potential_score") or 0),
                int((c.raw or {}).get("today_buzz_score") or 0),
                int((c.raw or {}).get("source_count") or 0),
            ),
            reverse=True,
        )
        return kept

    @staticmethod
    def _trend_dedup_key(c: NewsCandidate) -> str:
        raw = c.raw if isinstance(c.raw, dict) else {}
        base = str(raw.get("google_trends_keyword") or raw.get("cluster_key") or "")
        if not base:
            toks = raw.get("primary_tokens") or []
            base = str(toks[0]) if toks else (c.topic or "")
        return re.sub(r"[^가-힣a-zA-Z0-9]", "", base.lower())[:24]

    # 이슈 동일성 판정에서 의미 없는 범용 토큰 (overlap 부풀림 방지)
    _ISSUE_STOP_TOKENS: frozenset[str] = frozenset({
        "오늘", "이슈", "뉴스", "정리", "이유", "속보", "단독", "공식", "영상",
        "사진", "종합", "오전", "오후", "관련", "내용", "확인", "기준",
    })

    @classmethod
    def _issue_tokens(cls, text: str) -> set[str]:
        return {
            tok
            for tok in re.findall(r"[가-힣a-zA-Z0-9]{2,}", (text or "").lower())
            if tok not in cls._ISSUE_STOP_TOKENS
        }

    def _issue_signature_tokens(self, c: NewsCandidate) -> set[str]:
        raw = c.raw if isinstance(c.raw, dict) else {}
        parts = [
            str(raw.get("google_trends_keyword") or raw.get("cluster_key") or ""),
            c.topic or "",
        ]
        parts += [str(t) for t in (raw.get("primary_tokens") or [])[:6]]
        return self._issue_tokens(" ".join(parts))

    @staticmethod
    def _matches_recent_issue(
        cand_tokens: set[str], key: str, recent_token_sets: list[set[str]]
    ) -> bool:
        """최근 발행 이슈와 '같은 사건'인지 판정.

        - 토큰 2개 이상 겹침 = 같은 사건의 재탕 → 차단.
        - 토큰 1개 겹침 = 같은 인물·주제의 새 전개 → 허용 (후속편이 조회수 기회).
        - 후보 토큰이 2개 이하로 빈약하면 보수적으로 키워드 일치만으로 차단.
        """
        for rt in recent_token_sets:
            overlap = cand_tokens & rt
            if len(overlap) >= 2:
                return True
            if len(cand_tokens) <= 2 and key and any(key == t or key in t or t in key for t in rt):
                return True
        return False

    def _recent_published_issue_token_sets(self, *, days: int = 7) -> list[set[str]]:
        from datetime import datetime, timedelta

        path = getattr(self.publish_history_service, "history_path", None)
        if not path:
            return []
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        token_sets: list[set[str]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            published = (
                r.get("published")
                or r.get("publish_succeeded")
                or r.get("status") in {"published", "trending_published"}
            )
            if not published:
                continue
            if str(r.get("date") or "") and str(r.get("date")) < cutoff:
                continue
            text = " ".join(
                str(r.get(field) or "")
                for field in ("selected_topic", "title", "selected_title")
            )
            toks = self._issue_tokens(text)
            if toks:
                token_sets.append(toks)
        return token_sets

    def _render_validate_publish_trending(self, cand: NewsCandidate) -> dict[str, Any] | None:
        from blogspot_automation.services.trending_article_service import TrendingArticleService
        from blogspot_automation.services.news_publish_service import _validate_publish_contract

        topic = cand.topic or ""
        content_type = "today_issue_explainer"
        topic_group = "today_issue"
        raw = cand.raw if isinstance(cand.raw, dict) else {}
        try:
            result = TrendingArticleService().generate_article(cand)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clean_trending 렌더 실패 → 다음 후보 (%s): %s", topic[:40], exc)
            return None

        labels = normalize_labels(result.labels)
        hashtags = normalize_hashtags(result.hashtags or labels)
        html = prepare_blogspot_html(result.article_html, strip_document=True)
        html = ensure_answer_engine_optimized_html(
            html,
            title=result.title,
            topic=topic,
            content_type=content_type,
            topic_group=topic_group,
            reader_questions=list(raw.get("reader_search_questions") or []),
            faq_items=result.faq_items,
            confirmed_facts=result.confirmed_facts,
            check_needed=result.check_needed,
        )
        # 재배치 후 해시태그 부착 (순서 중요 — 반대면 해시태그가 글 중간에 낌)
        html = reorder_for_reader_first(html)
        html = append_hashtags_block(html, hashtags=hashtags, labels=labels)
        try:
            _validate_publish_contract(
                html,
                title=result.title,
                topic=topic,
                content_type=content_type,
                topic_group=topic_group,
                labels=labels,
                hashtags=hashtags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("clean_trending 검증 탈락 → 다음 후보 (%s): %s", topic[:36], str(exc)[:140])
            return None

        # 커버 이미지 자동 생성 (Gemini 생성 → imgbb 영구 URL, 엑박 방지).
        # 검증 통과 후보에만 실행해 무료 quota 낭비를 막는다. 실패해도 발행 계속.
        try:
            from blogspot_automation.services.cover_image_service import CoverImageService
            _cov = CoverImageService()
            if _cov.enabled():
                _cover_url = _cov.build_cover_image_url(
                    title=result.title, topic=topic, slug=result.slug,
                    image_concept=result.image_concept,
                )
                if _cover_url:
                    html = ensure_cover_image_html(
                        html, image_url=_cover_url,
                        alt_text=result.title, title=result.title,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("clean_trending 커버 이미지 비치명 실패: %s", exc)

        base = {
            "selected_topic": topic,
            "selected_title": result.title,
            "topic_group": topic_group,
            "content_type": content_type,
            "publish_ready": True,
            "geo_ready": True,
            "sge_ready": True,
            "article_candidate_generated": True,
            "clean_trending": True,
            "trending_engine": True,
        }
        # 최근 발행글 내부 링크 (체류시간·크롤링 — 실패해도 발행은 계속)
        internal_links: tuple[tuple[str, str], ...] = ()
        try:
            _records = self.publish_history_service.recent_records(limit=80)
            internal_links = build_internal_links_from_history(
                _records,
                current_title=result.title,
                current_topic=topic,
                current_topic_group=topic_group,
                current_content_type=content_type,
                limit=3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("clean_trending 내부 링크 수집 실패 (비치명): %s", exc)

        publish_mode_active = (
            not self.dry_run
            and self.auto_publish
            and self.news_publish_mode == "publish"
            and self.publish_service is not None
        )
        if not publish_mode_active:
            logger.info("clean_trending DRY-RUN 통과 ✅ : %s", result.title[:60])
            self._try_record_history(status="trending_dry_run", result={**base, "dry_run": True})
            return {
                "status": "trending_dry_run",
                "publish_attempted": False,
                "publish_succeeded": False,
                "blogger_url": "",
                "dry_run": True,
                **base,
            }
        try:
            flow = self._execute_publish_flow(
                topic=topic,
                publish_args={
                    "title": result.title,
                    "article_html": html,
                    "labels": labels,
                    "meta_description": result.meta_description,
                    "selected_topic": topic,
                    "topic_group": topic_group,
                    "content_type": content_type,
                    "hashtags": hashtags,
                    "internal_links": internal_links,
                    "permalink_slug_hint": result.slug,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("clean_trending 발행 실패 → 다음 후보 (%s): %s", topic[:36], exc)
            return None
        if flow["kind"] == "draft":
            draft_result = flow["draft_result"]
            self._try_record_history(status="draft_saved_for_review", result={**base, **draft_result})
            return {**base, **draft_result}
        if flow["kind"] == "audit_blocked":
            # 통합 전 이 경로에는 발행 후 감사가 아예 없었다(경로 간 표류) —
            # 이제 동일하게 감사·삭제하고, 기록 후 다음 후보로 넘어간다.
            self._try_record_history(
                status="blocked_by_post_publish_audit",
                result={
                    **base,
                    "publish_attempted": True,
                    "publish_succeeded": False,
                    "post_publish_audit": flow["post_publish_audit"],
                    "post_publish_audit_cleanup_deleted": flow["cleanup_deleted"],
                },
            )
            logger.warning(
                "clean_trending 발행 후 감사 차단 → 다음 후보 (%s): %s",
                topic[:36], ",".join(flow["fatal_issues"]),
            )
            return None
        url = flow["post_url"]
        logger.info("clean_trending 발행 성공 ✅ → %s", url)
        self._try_record_history(
            status="trending_published",
            result={
                **base,
                "published": True,
                "publish_attempted": True,
                "publish_succeeded": True,
                "blogger_url": url,
                "post_url": url,
                "published_url": url,
            },
        )
        return {
            "status": "trending_published",
            "publish_attempted": True,
            "publish_succeeded": True,
            "blogger_url": url,
            **base,
        }

    def _handle_trending_candidate(
        self, selected: ScoredNewsCandidate
    ) -> dict[str, Any] | None:
        """Trending 후보 → LLM 직접 생성 + 발행. 결과 dict 반환 (또는 실패 시 None → 일반 흐름)."""
        from blogspot_automation.services.trending_article_service import TrendingArticleService

        topic = selected.candidate.topic or ""
        if not self._is_news_auto_publish_candidate(selected):
            logger.warning("Trending 후보가 auto-publish gate에서 차단됨: %s", topic[:60])
            return None
        logger.info("Trending 분기 진입: %s", topic[:60])

        self._apply_issue_content_profile(selected)

        try:
            svc = TrendingArticleService()
            result = svc.generate_article(selected.candidate)
            result.labels = normalize_labels(result.labels)
            result.hashtags = normalize_hashtags(result.hashtags)
            _raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
            _content_angle = _raw.get("content_angle") or {}
            _content_type = (
                str(_content_angle.get("content_type") or "")
                if isinstance(_content_angle, dict)
                else ""
            ) or "viral_issue_decode"
            history_internal_links = self._history_internal_link_targets(
                selected=selected,
                content_type=_content_type,
            )
            result.article_html = prepare_blogspot_html(
                result.article_html,
                links=history_internal_links,
                strip_document=True,
            )
            result.article_html = ensure_answer_engine_optimized_html(
                result.article_html,
                title=result.title,
                topic=topic,
                content_type=_content_type,
                topic_group=str(_raw.get("topic_group") or "today_issue"),
                reader_questions=list(_raw.get("reader_search_questions") or []),
                faq_items=result.faq_items,
                confirmed_facts=result.confirmed_facts,
                check_needed=result.check_needed,
            )
            result.meta_description = normalize_search_description(
                title=result.title,
                description=result.meta_description,
                html=result.article_html,
                topic=topic,
            )
            trending_image_plan = self.image_prompt_service.build(
                selected=selected,
                selected_title=result.title,
            )
            result.article_html = ensure_cover_image_html(
                result.article_html,
                image_url=cover_image_url_from_env(
                    content_type=_content_type,
                    topic_group=str(_raw.get("topic_group") or "today_issue"),
                ),
                alt_text=trending_image_plan.get("image_alt_text", ""),
                title=result.title,
            )
            # 재배치 후 해시태그 부착 (순서 중요 — 반대면 해시태그가 글 중간에 낌)
            result.article_html = reorder_for_reader_first(result.article_html)
            result.article_html = append_hashtags_block(
                result.article_html,
                hashtags=result.hashtags,
                labels=result.labels,
            )
            final_html_audit = audit_final_html_quality(
                result.article_html,
                topic=topic,
                content_type=_content_type,
                topic_group=str(_raw.get("topic_group") or "today_issue"),
            )
            if not final_html_audit.get("passed"):
                logger.warning(
                    "TrendingArticleService clean layout audit failed: %s",
                    final_html_audit.get("issues"),
                )
                return {
                    "status": "trending_held_for_review",
                    "selected_topic": topic,
                    "selected_title": result.title,
                    "trending_engine": True,
                    "publish_ready": False,
                    "geo_ready": True,
                    "sge_ready": True,
                    "publish_attempted": False,
                    "publish_succeeded": False,
                    "blocking_issues": list(final_html_audit.get("issues") or []),
                    "publish_quality_gate": {
                        "passed": False,
                        "blocking_issues": list(final_html_audit.get("issues") or []),
                        "final_html_audit": final_html_audit,
                    },
                    "content_angle": self._content_angle_summary(selected) or {"content_type": _content_type},
                    "issue_content_profile": _raw.get("issue_content_profile"),
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("TrendingArticleService 실패 → 일반 흐름으로 fallback: %s", exc)
            return None

        # artifact 저장 (검토용)
        from datetime import datetime as _dt
        run_path = Path(getattr(self.artifact_service, "runs_dir", "runs")) / f"news_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
        run_path.mkdir(parents=True, exist_ok=True)
        try:
            (run_path / "article.html").write_text(result.article_html, encoding="utf-8")
            (run_path / "trending_meta.json").write_text(
                json.dumps({
                    "source": "trending_engine",
                    "topic": topic,
                    "title": result.title,
                    "meta_description": result.meta_description,
                    "labels": result.labels,
                    "hashtags": result.hashtags,
                    "faq_count": len(result.faq_items),
                    "html_length": len(result.article_html),
                    "candidate_raw": selected.candidate.raw,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as _se:
            logger.warning("trending artifact 저장 실패: %s", _se)

        publish_attempted = False
        publish_succeeded = False
        blogger_url = ""
        publish_error = ""
        post_publish_audit: dict[str, Any] = {}
        is_draft_saved = False
        draft_review_note = ""

        publish_mode_active = (
            not self.dry_run
            and self.auto_publish
            and self.news_publish_mode == "publish"
            and self.publish_service is not None
        )

        if publish_mode_active:
            try:
                publish_attempted = True
                _html_for_publish = result.article_html
                _final_html = prepare_blogspot_html(_html_for_publish, links=history_internal_links, strip_document=True)
                flow = self._execute_publish_flow(
                    topic=topic,
                    publish_args={
                        "title": result.title,
                        "article_html": _final_html,
                        "labels": normalize_labels(result.labels),
                        "meta_description": result.meta_description,
                        "selected_topic": topic,
                        "total_score": int(selected.total_score),
                        "click_potential_score": int(selected.candidate.raw.get("click_potential_score") or 0),
                        "topic_group": "today_issue",
                        "content_type": "today_issue_explainer",
                        "hashtags": result.hashtags,
                    },
                )
                post_publish_audit = flow["post_publish_audit"]
                blogger_url = flow["post_url"]
                if flow["kind"] == "draft":
                    is_draft_saved = True
                    publish_succeeded = False
                    draft_review_note = flow["draft_result"].get("draft_review_note", "")
                elif flow["kind"] == "audit_blocked":
                    publish_succeeded = False
                    publish_error = "post_publish_audit_failed:" + ",".join(flow["fatal_issues"])
                else:
                    publish_succeeded = True
            except Exception as exc:  # noqa: BLE001
                publish_error = f"{type(exc).__name__}: {exc}"
                logger.error("Trending 발행 실패: %s", publish_error)

        _today_issue_status = (
            "draft_saved_for_review" if is_draft_saved
            else "trending_published" if publish_succeeded
            else "trending_dry_run" if self.dry_run
            else "trending_publish_failed"
        )
        history_recorded = self._try_record_history(
            status=_today_issue_status,
            result={
                "trending_engine": True,
                "selected_topic": topic,
                "selected_title": result.title,
                "publish_ready": True,
                "geo_ready": True,
                "sge_ready": True,
                "publish_attempted": publish_attempted,
                "publish_succeeded": publish_succeeded,
                **({"published": False} if is_draft_saved else {}),
                "blogger_url": blogger_url,
                "post_url": blogger_url,
                "published_url": blogger_url,
                "post_publish_audit": post_publish_audit,
                "draft_review_note": draft_review_note,
                "html_length": len(result.article_html),
                "labels": result.labels,
                "hashtags_count": len(result.hashtags),
                "final_html_audit": final_html_audit,
                "topic_group": "today_issue",
                "content_angle": self._content_angle_summary(selected) or {"content_type": _content_type},
                "issue_content_profile": _raw.get("issue_content_profile"),
                "internal_link_targets": [
                    {"anchor_text": text, "url": url}
                    for text, url in history_internal_links
                ],
                "dry_run": self.dry_run,
            },
        )

        return {
            "status": (
                "draft_saved_for_review" if is_draft_saved
                else "trending_published" if publish_succeeded
                else "trending_dry_run" if self.dry_run
                else "trending_publish_failed" if publish_attempted
                else "trending_held_for_review"
            ),
            "selected_topic": topic,
            "selected_title": result.title,
            "trending_engine": True,
            "article_candidate_generated": True,
            "publish_ready": True,
            "geo_ready": True,
            "sge_ready": True,
            "publish_attempted": publish_attempted,
            "publish_succeeded": publish_succeeded,
            "blogger_url": blogger_url,
            "post_url": blogger_url,
            "post_publish_audit": post_publish_audit,
            "publish_error": publish_error,
            "artifact_dir": str(run_path),
            "html_length": len(result.article_html),
            "final_html_audit": final_html_audit,
            "publish_quality_gate": {
                "passed": bool(final_html_audit.get("passed")),
                "blocking_issues": list(final_html_audit.get("issues") or []),
                "final_html_audit": final_html_audit,
            },
            "content_angle": self._content_angle_summary(selected) or {"content_type": _content_type},
            "issue_content_profile": _raw.get("issue_content_profile"),
            "history_recorded": history_recorded,
        }

    def _select_diverse_candidate(
        self,
        candidates: list[ScoredNewsCandidate],
        history_records: list[dict[str, Any]],
    ) -> ScoredNewsCandidate:
        self._annotate_golden_selection_confidence(candidates)
        golden_ready = [
            item for item in candidates
            if self._candidate_golden_selection_penalty(item) == 0
        ]
        if golden_ready:
            candidates = golden_ready
        top = candidates[0]
        if len(candidates) == 1:
            return top
        weighted_click_candidate = self._weighted_click_candidate(
            candidates,
            history_records=history_records,
        )
        if weighted_click_candidate is not None:
            return weighted_click_candidate
        hot_non_policy = self._hot_non_policy_override_candidate(
            candidates,
            top=top,
            history_records=history_records,
        )
        if hot_non_policy is not None:
            return hot_non_policy
        runner_up = candidates[1]
        top_selection_penalty = self._candidate_selection_quality_penalty(top)
        top_issue_priority = self._candidate_issue_selection_priority(top)
        runner_issue_priority = self._candidate_issue_selection_priority(runner_up)
        top_click_score = self._candidate_click_selection_score(top)
        runner_click_score = self._candidate_click_selection_score(runner_up)
        runner_can_override_score_lead = (
            (
                runner_issue_priority < top_issue_priority
                or runner_click_score - top_click_score >= 20
            )
            and top.total_score - runner_up.total_score <= 15
        )
        if (
            top_selection_penalty == 0
            and top.total_score >= 90
            and top.total_score - runner_up.total_score >= 5
            and not runner_can_override_score_lead
        ):
            return top

        has_higher_issue_candidate = any(
            (
                self._candidate_issue_selection_priority(item) < top_issue_priority
                or self._candidate_click_selection_score(item) - top_click_score >= 20
            )
            and top.total_score - item.total_score <= 15
            for item in candidates[1:]
        )
        score_window = 15 if top_selection_penalty or has_higher_issue_candidate else 5
        near_top = [item for item in candidates if top.total_score - item.total_score <= score_window]
        if len(near_top) == 1:
            return top

        group_counts = self._topic_group_counts(history_records, days=7)
        recent_policy_count = self._topic_group_count("policy_benefit", history_records, days=1)
        return sorted(
            near_top,
            key=lambda item: (
                self._candidate_selection_quality_penalty(item),
                self._candidate_golden_selection_penalty(item),
                self._candidate_issue_selection_priority(item),
                -self._candidate_click_selection_score(item),
                self._candidate_hook_priority(item),
                1 if recent_policy_count and self._is_policy_candidate(item) else 0,
                group_counts.get(self._candidate_topic_group(item), 0),
                -item.total_score,
            ),
        )[0]

    def _weighted_click_candidate(
        self,
        candidates: list[ScoredNewsCandidate],
        *,
        history_records: list[dict[str, Any]],
    ) -> ScoredNewsCandidate | None:
        scored_pool = [
            item for item in candidates
            if self._candidate_selection_quality_penalty(item) == 0
            and self._candidate_golden_selection_penalty(item) == 0
        ]
        if not scored_pool:
            return None

        click_scores = {
            id(item): self._candidate_click_selection_score(item)
            for item in scored_pool
        }
        max_click = max(click_scores.values(), default=0)
        if max_click <= 0:
            return None

        top_total = max(int(item.total_score) for item in scored_pool)
        click_floor = max(60, max_click - 25)
        total_floor = max(65, top_total - 35)
        click_pool = [
            item for item in scored_pool
            if click_scores[id(item)] >= click_floor
            and int(item.total_score) >= total_floor
        ]
        if not click_pool:
            click_pool = [
                item for item in scored_pool
                if click_scores[id(item)] >= max(1, max_click - 15)
            ]
        if not click_pool:
            return None
        if len(click_pool) == 1:
            click_pool[0].candidate.raw["weighted_random_selection_pool_size"] = 1
            click_pool[0].candidate.raw["weighted_random_selected"] = True
            return click_pool[0]

        recent_policy_count = self._topic_group_count("policy_benefit", history_records, days=1)
        weighted_items: list[tuple[ScoredNewsCandidate, int]] = []
        for item in click_pool:
            click_score = click_scores[id(item)]
            weight = max(1, click_score - click_floor + 1)
            weight += max(1, int(item.total_score) // 10)
            if self._is_policy_candidate(item) and recent_policy_count:
                weight = max(1, weight // 4)
            weighted_items.append((item, weight))

        rng = random.Random(
            f"{self._selection_random_seed}:"
            f"{len(candidates)}:{','.join((item.candidate.topic or '')[:20] for item in candidates[:8])}"
        )
        total_weight = sum(weight for _, weight in weighted_items)
        cursor = rng.uniform(0, total_weight)
        upto = 0.0
        selected = weighted_items[-1][0]
        for item, weight in weighted_items:
            upto += weight
            if cursor <= upto:
                selected = item
                break

        for item, weight in weighted_items:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            raw["weighted_random_selection_pool_size"] = len(weighted_items)
            raw["weighted_random_selection_weight"] = weight
            raw["weighted_random_selection_click_floor"] = click_floor
            raw["weighted_random_selected"] = item is selected
        return selected

    def _hot_non_policy_override_candidate(
        self,
        candidates: list[ScoredNewsCandidate],
        *,
        top: ScoredNewsCandidate,
        history_records: list[dict[str, Any]],
    ) -> ScoredNewsCandidate | None:
        if not self._is_policy_candidate(top):
            return None
        recent_policy_count = self._topic_group_count("policy_benefit", history_records, days=1)
        max_score_gap = 35 if recent_policy_count else 20
        alternatives: list[ScoredNewsCandidate] = []
        for item in candidates[1:]:
            if self._is_policy_candidate(item):
                continue
            if top.total_score - item.total_score > max_score_gap:
                continue
            if self._candidate_selection_quality_penalty(item) > 0:
                continue
            if self._candidate_golden_selection_penalty(item) > 0:
                continue
            click_score = self._candidate_click_selection_score(item)
            item_raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            if click_score < 60 and not (
                self._is_trending_candidate(item)
                or bool(item_raw.get("discovery_engine"))
            ):
                continue
            alternatives.append(item)
        if not alternatives:
            return None
        return sorted(
            alternatives,
            key=lambda item: (
                self._candidate_issue_selection_priority(item),
                -self._candidate_click_selection_score(item),
                self._candidate_hook_priority(item),
                -item.total_score,
            ),
        )[0]

    def _annotate_golden_selection_confidence(self, candidates: list[ScoredNewsCandidate]) -> None:
        ps = self.golden_preview_service._ps
        for item in candidates:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            if raw.get("golden_selection_confidence") is not None:
                continue
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            summary_parts = [
                str(raw.get("search_demand_topic") or ""),
                " ".join(list(raw.get("reader_search_questions") or [])[:2]),
            ]
            summary = " ".join(p for p in summary_parts if p)
            try:
                result = ps.match_pattern(
                    topic=item.candidate.topic or "",
                    content_type=ct,
                    topic_group=tg,
                    summary=summary,
                )
                raw["golden_selection_confidence"] = int(result.get("confidence", 0))
                raw["golden_selection_pattern_id"] = str(result.get("pattern_id") or "")
            except Exception:
                raw["golden_selection_confidence"] = 0
                raw["golden_selection_pattern_id"] = ""

    @staticmethod
    def _candidate_golden_selection_penalty(item: ScoredNewsCandidate) -> int:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        if raw.get("trending_engine") or raw.get("discovery_engine"):
            return 0
        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        if source_type in {"fallback", "evergreen_fallback", "viral_fallback"}:
            return 0
        content_type = NewsPipeline._news_publish_content_type(raw)
        if content_type not in NewsPipeline.NEWS_AUTO_PUBLISH_ALLOWED_CONTENT_TYPES:
            return 0
        try:
            confidence = int(raw.get("golden_selection_confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        if confidence >= 80:
            return 0
        if confidence >= 75:
            return 1
        return 3

    @staticmethod
    def _candidate_selection_quality_penalty(item: ScoredNewsCandidate) -> int:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        penalty = 0
        original_topic = str(raw.get("original_topic") or "")
        preservation = NewsPipeline._candidate_original_issue_preservation_score(item)
        if original_topic:
            if preservation < 6:
                penalty += 2
            if preservation == 0:
                penalty += 1

        topic = item.candidate.topic or ""
        public_benefit_keyword = str(raw.get("public_benefit_keyword") or "")
        generic_policy_topic = public_benefit_keyword in {"지원금", "환급금", "정부 지원금", "정부지원금"}
        if generic_policy_topic and original_topic and preservation < 6:
            penalty += 1
        if original_topic and len(topic.strip()) < 18 and preservation < 6:
            penalty += 1
        if NewsPipeline._is_low_today_static_web_policy_candidate(item):
            penalty += 4
        return penalty

    @staticmethod
    def _candidate_original_issue_preservation_score(item: ScoredNewsCandidate) -> int:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        cached = raw.get("selection_original_issue_preservation_score")
        if cached is not None:
            try:
                return int(cached)
            except (TypeError, ValueError):
                pass
        score = NewsQualityGate._compute_original_issue_preservation(
            item,
            title=item.candidate.topic or "",
        )
        raw["selection_original_issue_preservation_score"] = score
        return score

    @staticmethod
    def _candidate_issue_selection_priority(item: ScoredNewsCandidate) -> int:
        click_selection_score = NewsPipeline._candidate_click_selection_score(item)
        if click_selection_score >= 110:
            return 0
        if click_selection_score >= 85:
            return 1
        if click_selection_score >= 60:
            return 2
        return 3

    @staticmethod
    def _candidate_click_selection_score(item: ScoredNewsCandidate) -> int:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}

        def _safe_int(value: Any, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        click_score = _safe_int(raw.get("click_potential_score"), 0)
        buzz = _safe_int(raw.get("today_buzz_score"), 0)
        source_count = _safe_int(raw.get("source_count"), 0)
        topic_traffic = _safe_int(raw.get("topic_traffic_potential_score"), 0)
        topic_search = _safe_int(raw.get("topic_search_intent_score"), 0)
        strategy_search = _safe_int(raw.get("search_intent_score"), 0)
        mass_relevance = _safe_int(raw.get("mass_relevance_score"), 0)
        reader_interest = _safe_int(raw.get("reader_interest_score"), 0)
        save_value = _safe_int(raw.get("save_value_score"), 0)
        curiosity = _safe_int(raw.get("curiosity_score"), 0)

        score = 0
        score += click_score * 6
        score += buzz * 5
        score += min(source_count, 5) * 6
        score += topic_traffic * 2
        score += max(topic_search, strategy_search)
        score += min(mass_relevance, 25)
        score += min(30, reader_interest // 3)
        score += min(10, save_value // 3)
        score += min(10, curiosity // 3)
        if raw.get("trending_engine") or source_type == "naver_trending":
            score += 25
        if raw.get("discovery_engine"):
            score += 12
        if raw.get("search_demand_topic"):
            score += 5
        if str(raw.get("reader_interest_strategy") or "") in {"click_first_context", "save_value_first"}:
            score += 8
        if NewsPipeline._is_policy_candidate(item) and not (
            raw.get("trending_engine") or raw.get("discovery_engine")
        ):
            score -= 25

        score = max(0, score)
        raw["selection_click_score"] = score
        return score

    @staticmethod
    def _is_policy_candidate(item: ScoredNewsCandidate) -> bool:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        topic_group = NewsPipeline._candidate_topic_group(item)
        content_type = NewsPipeline._news_publish_content_type(raw)
        return topic_group == "policy_benefit" or content_type in {
            "policy_deadline",
            "policy_benefit",
            "tax_refund",
        }

    def _cooldown_penalty(self, topic_group: str, history_records: list[dict[str, Any]]) -> int:
        if not topic_group:
            return 0
        count_3d = self._topic_group_count(topic_group, history_records, days=3)
        count_7d = self._topic_group_count(topic_group, history_records, days=7)
        if topic_group == "policy_benefit":
            count_1d = self._topic_group_count(topic_group, history_records, days=1)
            penalty = 0
            if count_1d >= 1:
                penalty = max(penalty, 45)
            if count_3d >= 1:
                penalty = max(penalty, 30)
            if count_7d >= 2:
                penalty = max(penalty, 35)
            return penalty
        if count_7d >= 2:
            return 20
        if count_3d >= 1:
            return 10
        return 0

    def _load_topic_group_history(self) -> list[dict[str, Any]]:
        """Topic group cooldown history.

        Default source: state/news_published_history.json (actual publishes only).
        Optional: COOLDOWN_INCLUDE_LOCAL_RUNS=true 이면 runs/news_*/도 포함.

        로컬 dry_run 누적 runs/ 디렉토리가 cooldown을 부풀려 실제 publish를
        막는 것을 방지하기 위함. 프로덕션 CI에서는 runs/가 매 실행마다 clean이라
        publish_history만으로 충분하다.
        """
        records: list[dict[str, Any]] = []
        records.extend(self.dedup_service.load_history())
        self._last_cooldown_source = "publish_history"

        include_runs = os.getenv("COOLDOWN_INCLUDE_LOCAL_RUNS", "").strip().lower() in {"1", "true", "yes", "on"}
        if not include_runs:
            return records

        runs_dir = Path(getattr(self.artifact_service, "runs_dir", "runs"))
        if not runs_dir.exists():
            return records
        runs_added = 0
        for run_dir in runs_dir.glob("news_*"):
            if not run_dir.is_dir():
                continue
            record_date = self._date_from_run_dir(run_dir)
            if record_date is None or record_date < date.today() - timedelta(days=7):
                continue
            record: dict[str, Any] = {"date": record_date.isoformat()}
            scoring_path = run_dir / "scoring.json"
            selected_path = run_dir / "selected_topic.json"
            try:
                scoring = json.loads(scoring_path.read_text(encoding="utf-8")) if scoring_path.exists() else {}
            except Exception:
                scoring = {}
            try:
                selected = json.loads(selected_path.read_text(encoding="utf-8")) if selected_path.exists() else {}
            except Exception:
                selected = {}
            if isinstance(scoring, dict):
                record["topic_group"] = scoring.get("topic_group")
                record["title"] = scoring.get("selected_title", "")
            if isinstance(selected, dict):
                candidate = selected.get("candidate") if isinstance(selected.get("candidate"), dict) else {}
                record["topic"] = candidate.get("topic", "") if isinstance(candidate, dict) else ""
                raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
                if not record.get("topic_group") and isinstance(raw, dict):
                    record["topic_group"] = raw.get("topic_group")
            if not record.get("topic_group"):
                record["topic_group"] = self._infer_topic_group_from_record(record)
            records.append(record)
            runs_added += 1
        if runs_added > 0:
            self._last_cooldown_source = "publish_history+local_runs"
        return records

    def _load_recent_evergreen_axes(self) -> list[str]:
        """Return evergreen axes from recent run artifacts, most recent first."""
        runs_dir = Path(getattr(self.artifact_service, "runs_dir", "runs"))
        if not runs_dir.exists():
            return []
        run_records: list[tuple[datetime, str]] = []
        cutoff = datetime.now() - timedelta(days=7)
        for run_dir in runs_dir.glob("news_*"):
            if not run_dir.is_dir():
                continue
            try:
                dt = datetime.strptime(run_dir.name.replace("news_", "")[:15], "%Y%m%d_%H%M%S")
            except ValueError:
                try:
                    dt = datetime.strptime(run_dir.name.replace("news_", "")[:8], "%Y%m%d")
                except ValueError:
                    continue
            if dt < cutoff:
                continue
            axis = ""
            for fname in ("run_meta.json", "scoring.json"):
                path = run_dir / fname
                try:
                    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                    if isinstance(data, dict):
                        axis = str(data.get("evergreen_axis") or "").strip()
                        if axis:
                            break
                except Exception:
                    pass
            if axis:
                run_records.append((dt, axis))
        run_records.sort(key=lambda x: x[0], reverse=True)
        return [ax for _, ax in run_records]

    def _load_recent_context(self) -> dict[str, list[str]]:
        """Load recent history context. Uses publish_history_service first, falls back to runs/."""
        recent = self.publish_history_service.recent_records(limit=14, published_only=True)
        if recent:
            return {
                "recent_evergreen_axes": [str(r["evergreen_axis"]) for r in recent if r.get("evergreen_axis")],
                "recent_topic_groups": [str(r["topic_group"]) for r in recent if r.get("topic_group")],
                "recent_content_types": [str(r["content_type"]) for r in recent if r.get("content_type")],
                "source": "publish_history",
            }
        return {
            "recent_evergreen_axes": self._load_recent_evergreen_axes(),
            "recent_topic_groups": [],
            "recent_content_types": [],
            "source": "runs_artifact",
        }

    @staticmethod
    def _build_history_record(*, status: str, result: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        content_angle = result.get("content_angle") or {}
        content_type = content_angle.get("content_type", "") if isinstance(content_angle, dict) else ""
        quality_gate = result.get("publish_quality_gate") or {}
        auto_publish_gate = result.get("auto_publish_gate") or {}
        post_publish_audit = result.get("post_publish_audit") or {}
        scorecard = quality_gate.get("publish_preview_scorecard") if isinstance(quality_gate, dict) else {}
        if not isinstance(scorecard, dict):
            scorecard = {}
        published = status in {"published", "trending_published"} or bool(
            result.get("publish_succeeded")
            or result.get("published")
        )
        quality_blocking = list(quality_gate.get("blocking_issues") or []) if isinstance(quality_gate, dict) else []
        quality_warnings = list(quality_gate.get("warnings") or []) if isinstance(quality_gate, dict) else []
        recommendation_policy = quality_gate.get("recommendation_policy") if isinstance(quality_gate, dict) else {}
        if not isinstance(recommendation_policy, dict):
            recommendation_policy = {}
        auto_blocking = (
            list(auto_publish_gate.get("blocking_reasons") or [])
            if isinstance(auto_publish_gate, dict)
            else []
        )
        post_audit_issues = (
            list(post_publish_audit.get("issues") or [])
            if isinstance(post_publish_audit, dict)
            else []
        )
        learning_signals = NewsPipeline._history_learning_signals(
            status=status,
            quality_gate=quality_gate if isinstance(quality_gate, dict) else {},
            auto_publish_gate=auto_publish_gate if isinstance(auto_publish_gate, dict) else {},
            post_publish_audit=post_publish_audit if isinstance(post_publish_audit, dict) else {},
            result=result,
        )
        return {
            "run_at": now.isoformat(timespec="seconds"),
            "date": now.date().isoformat(),
            "title": result.get("selected_title", ""),
            "selected_topic": result.get("selected_topic", ""),
            "search_demand_topic": result.get("search_demand_topic", ""),
            "topic_group": result.get("topic_group", ""),
            "content_type": content_type,
            "url": result.get("post_url") or result.get("published_url") or result.get("blogger_url") or "",
            "post_id": result.get("post_id", ""),
            "internal_link_targets": result.get("internal_link_targets", []),
            "source_type": result.get("source_type", ""),
            "evergreen_axis": result.get("evergreen_axis", ""),
            "fallback_reason": result.get("fallback_reason", ""),
            "published": published,
            "dry_run": bool(result.get("dry_run", True)),
            "quality_passed": bool(quality_gate.get("passed", False)) if isinstance(quality_gate, dict) else False,
            "reader_value_score": quality_gate.get("reader_value_score") if isinstance(quality_gate, dict) else None,
            "article_focus_score": quality_gate.get("article_focus_score") if isinstance(quality_gate, dict) else None,
            "ai_recommender_score": quality_gate.get("ai_recommender_score") if isinstance(quality_gate, dict) else None,
            "shareability_score": quality_gate.get("shareability_score") if isinstance(quality_gate, dict) else None,
            "policy_specificity_score": quality_gate.get("policy_specificity_score") if isinstance(quality_gate, dict) else None,
            "recommendation_policy_passed": bool(recommendation_policy.get("passed", False)),
            "recommendation_policy_signals": recommendation_policy.get("shareability_signals", []),
            "publish_preview_score": scorecard.get("score"),
            "publish_preview_status": scorecard.get("status", ""),
            "quality_blocking_issues": quality_blocking,
            "quality_warnings": quality_warnings,
            "auto_publish_allowed": bool(auto_publish_gate.get("allowed", False)) if isinstance(auto_publish_gate, dict) else False,
            "auto_publish_blocking_reasons": auto_blocking,
            # 감사 미실행(빈 dict)은 None — False(불합격)와 구분해야 내부링크
            # 후보 필터(`is False`)가 clean trending 발행 글을 잘못 제외하지 않는다.
            "post_publish_audit_passed": (
                bool(post_publish_audit.get("passed", False))
                if isinstance(post_publish_audit, dict) and post_publish_audit
                else None
            ),
            "post_publish_audit_issues": post_audit_issues,
            "topic_engine_score": result.get("topic_engine_score"),
            "topic_candidate_grade": result.get("topic_candidate_grade", ""),
            "content_candidate_grade": result.get("content_candidate_grade", ""),
            "final_editorial_score": result.get("final_editorial_score"),
            "golden_pattern_id": result.get("golden_pattern_id", ""),
            "golden_pattern_confidence": result.get("golden_pattern_confidence"),
            "golden_slot_fill_rate": result.get("golden_slot_fill_rate"),
            "why_topic_selected": result.get("why_topic_selected", ""),
            "why_topic_held": result.get("why_topic_held", ""),
            "learning_signals": learning_signals,
            "hashtags": result.get("hashtags", []),
            "artifact_dir": result.get("artifact_dir", ""),
            "status": status,
            "retry_attempt": result.get("retry_attempt", ""),
            "max_publish_attempts": result.get("max_publish_attempts", ""),
            # 본문 문장 지문 — 이후 발행 후보의 재탕(near-duplicate) 감지에 사용.
            "content_fingerprint": (
                list(quality_gate.get("content_fingerprint") or [])
                if isinstance(quality_gate, dict)
                else []
            ),
        }

    def _try_record_history(self, *, status: str, result: dict[str, Any]) -> bool:
        status = (status or "").strip()
        published = status in {"published", "trending_published"} or bool(
            result.get("publish_succeeded")
            or result.get("published")
        )
        if self.dry_run or bool(result.get("dry_run")) or self.news_publish_mode != "publish":
            return False
        if status not in _HISTORY_RECORDABLE_STATUSES and not published:
            return False
        try:
            record = self._build_history_record(status=status, result=result)
            return self.publish_history_service.append_record(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("history record failed: %s | status=%s", exc, status)
            return False

    @staticmethod
    def _history_learning_signals(
        *,
        status: str,
        quality_gate: dict[str, Any],
        auto_publish_gate: dict[str, Any],
        post_publish_audit: dict[str, Any],
        result: dict[str, Any],
    ) -> list[str]:
        signals: list[str] = []
        if status not in {"published", "trending_published"}:
            signals.append(f"not_published:{status or 'unknown'}")
        if quality_gate and not bool(quality_gate.get("passed")):
            signals.append("quality_gate_failed")
        reader_value = quality_gate.get("reader_value_score")
        if isinstance(reader_value, int | float) and reader_value < 80:
            signals.append("reader_value_below_80")
        article_focus = quality_gate.get("article_focus_score")
        if isinstance(article_focus, int | float) and article_focus < 70:
            signals.append("article_focus_below_70")
        for issue in list(quality_gate.get("blocking_issues") or [])[:5]:
            signals.append(f"quality_issue:{issue}")
        for reason in list(auto_publish_gate.get("blocking_reasons") or [])[:5]:
            signals.append(f"auto_publish_blocked:{reason}")
        # 감사가 실제로 돌지 않은 실행(draft 등, skipped=True)은 실패가 아니다 —
        # 이 오분류가 2026-07 원장에서 전 실행을 audit_failed로 물들여 진짜 실패를
        # 구분 불가능하게 만들었다.
        if (
            post_publish_audit
            and not bool(post_publish_audit.get("skipped"))
            and not bool(post_publish_audit.get("passed"))
        ):
            signals.append("post_publish_audit_failed")
        for issue in list(post_publish_audit.get("issues") or [])[:5]:
            signals.append(f"post_publish_issue:{issue}")
        if bool(result.get("llm_generation_failed")):
            signals.append("llm_generation_failed")
        why_held = str(result.get("why_topic_held") or "").strip()
        if why_held:
            signals.append(f"topic_held:{why_held}")
        return list(dict.fromkeys(signals))

    # Issues that genuinely mean the PUBLISHED artifact is wrong and a re-run could
    # fix it — only these justify deleting a live post. Advisory issues (missing head
    # meta description, canonical [Blogger-theme controlled], answer-engine
    # completeness, cover image, weak slug, sitemap/feed inclusion) must NOT delete a
    # live post: deleting good content produces 404s and zero views.
    _POST_PUBLISH_FATAL_ISSUES = (
        "published_title_mismatch",
        "temporary_permalink_title_visible",
        "ai_topic_leaked_to_news_blog",
        "published_labels_mojibake",
    )

    def _execute_publish_flow(self, *, topic: str, publish_args: dict[str, Any]) -> dict[str, Any]:
        """발행 실행의 단일 경로: publish → 초안 분기 → 발행 후 감사 → 치명 시 삭제.

        배경(2026-07-08 구조 감사 로드맵 5): 이 흐름이 세 발행 경로(main/
        clean_trending/today_issue)에 3벌 복제돼 있었고, 경로별로 미묘하게 달라
        (clean_trending은 발행 후 감사 자체가 없었음, 초안 처리도 각자 구현)
        한 곳 수정이 세 곳 패치를 요구했으며 경로 간 표류가 곧 버그였다(초안
        자멸 수정 때 실측). 이제 발행 메커니즘은 이 메서드 하나다 — 경로들은
        결과의 상태 이름·이력 조립만 각자 한다.

        감사 기대값(제목·라벨·타입)은 publish_args에서 직접 파생한다 — 발행에
        보낸 값과 감사가 기대하는 값이 한 출처라 표류할 수 없다.

        반환: {"kind": "draft"|"published"|"audit_blocked", "post_id", "post_url",
               "post_publish_audit", "fatal_issues", "cleanup_deleted",
               "draft_result"(초안일 때만)}
        """
        outcome = self.publish_service.publish(  # type: ignore[union-attr]
            is_draft=self.publish_as_draft,
            **publish_args,
        )
        post_id = str(getattr(outcome, "post_id", "") or "")
        draft_result = self._draft_review_result(outcome, topic=topic)
        if draft_result is not None:
            logger.info(
                "publish flow: draft saved for review → topic=%s dashboard=%s",
                topic[:50], draft_result.get("blogger_url", ""),
            )
            return {
                "kind": "draft",
                "post_id": post_id,
                "post_url": str(draft_result.get("blogger_url") or ""),
                "post_publish_audit": draft_result.get("post_publish_audit") or {},
                "fatal_issues": [],
                "cleanup_deleted": False,
                "draft_result": draft_result,
            }
        response = getattr(outcome, "response_json", {}) or {}
        post_url = str(getattr(outcome, "post_url", "") or response.get("url") or "")
        post_publish_audit = self._post_publish_audit(
            post_url,
            expected_title=str(publish_args.get("title") or ""),
            expected_permalink_slug=str(response.get("permalink_slug") or ""),
            expected_labels=list(publish_args.get("labels") or []),
            content_type=str(publish_args.get("content_type") or ""),
            topic_group=str(publish_args.get("topic_group") or ""),
            # slug 단독 재검사 오탐 방지(2026-07-18 정상 글 자동삭제 사고):
            # 감사에 후보 메타데이터 원본을 넘겨 news-focus 재평가가 slug 토큰이
            # 아니라 실제 주제·그룹·타입으로 판정하게 한다.
            candidate_meta={
                "topic": str(publish_args.get("selected_topic") or ""),
                "selected_topic": str(publish_args.get("selected_topic") or ""),
                "topic_group": str(publish_args.get("topic_group") or ""),
                "content_type": str(publish_args.get("content_type") or ""),
            },
        )
        fatal_issues = self._post_publish_fatal_issues(post_publish_audit)
        if post_publish_audit and fatal_issues:
            cleanup_deleted = False
            try:
                cleanup_deleted = bool(self.publish_service.delete_post(post_id))  # type: ignore[union-attr]
            except Exception as delete_exc:  # noqa: BLE001
                logger.warning("post publish audit cleanup failed: %s", delete_exc)
            return {
                "kind": "audit_blocked",
                "post_id": post_id,
                "post_url": post_url,
                "post_publish_audit": post_publish_audit,
                "fatal_issues": fatal_issues,
                "cleanup_deleted": cleanup_deleted,
            }
        if post_publish_audit and not bool(post_publish_audit.get("passed")):
            # Advisory issues only — keep the live post; log for operator follow-up.
            logger.warning(
                "post publish audit advisory (post kept): url=%s issues=%s",
                post_url, list(post_publish_audit.get("issues") or []),
            )
        logger.info("publish flow: published → topic=%s url=%s", topic[:50], post_url)
        return {
            "kind": "published",
            "post_id": post_id,
            "post_url": post_url,
            "post_publish_audit": post_publish_audit,
            "fatal_issues": [],
            "cleanup_deleted": False,
        }

    @staticmethod
    def _draft_review_result(publish_outcome: Any, *, topic: str) -> dict[str, Any] | None:
        """초안 발행이면 결과를 만들어 반환, 아니면 None(호출부가 평소 라이브 발행 흐름을 계속 진행).

        배경: Blogger는 초안 post의 url로 블로그 홈 URL을 돌려준다(개별 초안 미리보기
        URL이 아님). 그래서 이 URL로 라이브 fetch 감사(_post_publish_audit)를 돌리면
        '홈페이지에 있던 이전 글'과 새 후보를 비교해 필연적으로 전부 불일치가 나고,
        그 결과 방금 만든 초안이 매번 자동 삭제됐다(2026-07-08 실측). 초안은 원래
        사람이 Blogger 대시보드에서 직접 열어 검토하는 용도라 라이브 fetch 감사
        자체가 성립하지 않는다 — 그래서 초안일 때는 감사를 건너뛰고 대시보드
        편집 링크만 남긴다. publish_succeeded/published는 정직하게 False로 둬서
        dedup·이력이 이걸 실제 발행처럼 취급하지 않게 한다(엔티티 쿨다운도 미적용).
        """
        if not getattr(publish_outcome, "is_draft", False):
            return None
        dashboard_url = getattr(publish_outcome, "dashboard_url", "") or ""
        return {
            "status": "draft_saved_for_review",
            "post_id": getattr(publish_outcome, "post_id", ""),
            "post_url": dashboard_url,
            "published_url": dashboard_url,
            "blogger_url": dashboard_url,
            "publish_attempted": True,
            "publish_succeeded": False,
            "published": False,
            "post_publish_audit": {"skipped": True, "reason": "draft_not_live_fetchable"},
            "draft_review_note": (
                f"Blogger 대시보드에서 '{topic[:60]}' 초안을 열어 직접 검토하세요: {dashboard_url}"
                if dashboard_url else "Blogger 초안 생성됨 — 대시보드에서 확인하세요."
            ),
        }

    @staticmethod
    def _post_publish_fatal_issues(post_publish_audit: dict[str, Any]) -> list[str]:
        """Return only the audit issues that justify deleting the live post."""
        issues = [str(issue) for issue in (post_publish_audit.get("issues") or [])]
        return [
            issue
            for issue in issues
            if issue in NewsPipeline._POST_PUBLISH_FATAL_ISSUES
            or issue.startswith("published_title_integrity:")
        ]

    @staticmethod
    def _post_publish_audit(
        url: str,
        *,
        expected_title: str = "",
        expected_permalink_slug: str = "",
        expected_labels: list[str] | tuple[str, ...] | None = None,
        content_type: str = "",
        topic_group: str = "",
        candidate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not url:
            return {"passed": False, "issues": ["missing_post_url"]}
        try:
            return fetch_and_audit_post(
                url=url,
                expected_title=expected_title,
                expected_permalink_slug=expected_permalink_slug,
                expected_labels=expected_labels,
                content_type=content_type,
                topic_group=topic_group,
                candidate_meta=candidate_meta,
            ).to_dict()
        except Exception as exc:  # noqa: BLE001
            return {
                "passed": False,
                "issues": ["post_publish_audit_failed"],
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _evergreen_axis_rotation_penalty(axis: str, recent_axes: list[str]) -> int:
        """Compute rotation penalty for an evergreen axis based on recent history."""
        if not axis or not recent_axes:
            return 0
        last_2 = recent_axes[:2]
        last_3 = recent_axes[:3]
        penalty = 0
        if axis == "tax_refund_support":
            if axis in last_2:
                penalty += 25
            elif axis in last_3:
                penalty += 15
        else:
            count = last_3.count(axis)
            if count >= 2:
                penalty += 15
            elif count >= 1:
                penalty += 8
        # Boost non-tax axes when tax_refund dominated recently
        if last_2.count("tax_refund_support") >= 1 and axis in ("ai_automation", "adsense_revenue", "digital_survival"):
            penalty -= 10
        return penalty

    def _recommended_next_axis(self, recent_evergreen_axes: list[str]) -> str:
        """Suggest the next evergreen axis based on rotation history."""
        all_axes = ["adsense_revenue", "ai_automation", "money_life", "digital_survival", "tax_refund_support", "blogspot_growth"]
        if not recent_evergreen_axes:
            return EvergreenTopicService.preferred_axis_by_weekday()
        counts = {ax: recent_evergreen_axes.count(ax) for ax in all_axes}
        preferred = EvergreenTopicService.preferred_axis_by_weekday()
        return min(all_axes, key=lambda a: (counts.get(a, 0), 0 if a == preferred else 1))

    @staticmethod
    def _axis_selection_reason(axis: str, recent_axes: list[str], preferred_axis: str) -> str:
        if not axis:
            return "no_evergreen_candidate"
        parts = []
        if axis == preferred_axis:
            parts.append(f"matches_weekday_preferred:{preferred_axis}")
        tax_in_recent = recent_axes[:2].count("tax_refund_support")
        if tax_in_recent >= 1 and axis in ("ai_automation", "adsense_revenue", "digital_survival"):
            parts.append("boosted:recent_tax_refund_rotation")
        same_count = recent_axes[:3].count(axis)
        if same_count >= 2:
            parts.append(f"penalized:appeared_{same_count}x_in_last_3")
        elif same_count == 1:
            parts.append("mild_penalty:appeared_once_in_last_3")
        else:
            parts.append("no_rotation_penalty")
        return ";".join(parts) if parts else "standard_selection"

    def _topic_group_count(self, topic_group: str, history_records: list[dict[str, Any]], *, days: int) -> int:
        cutoff = date.today() - timedelta(days=days)
        return sum(
            1
            for record in history_records
            if self._record_date(record) is not None
            and self._record_date(record) >= cutoff
            and self._record_topic_group(record) == topic_group
        )

    def _topic_group_counts(self, history_records: list[dict[str, Any]], *, days: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        cutoff = date.today() - timedelta(days=days)
        for record in history_records:
            record_date = self._record_date(record)
            if record_date is None or record_date < cutoff:
                continue
            group = self._record_topic_group(record)
            if group:
                counts[group] = counts.get(group, 0) + 1
        return counts

    def _record_topic_group(self, record: dict[str, Any]) -> str:
        group = str(record.get("topic_group") or "").strip()
        return group or self._infer_topic_group_from_record(record)

    def _infer_topic_group_from_record(self, record: dict[str, Any]) -> str:
        text = " ".join(
            str(record.get(field, "") or "")
            for field in ("topic", "title", "selected_title", "keyword", "summary", "url")
        )
        return self.scoring_service.classify_topic_group(text)

    @staticmethod
    def _record_date(record: dict[str, Any]) -> date | None:
        for field in ("date", "published_at", "created_at", "updated_at"):
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                try:
                    return date.fromisoformat(value.strip()[:10])
                except ValueError:
                    continue
        return None

    @staticmethod
    def _date_from_run_dir(run_dir: Path) -> date | None:
        token = run_dir.name.replace("news_", "")[:8]
        try:
            return datetime.strptime(token, "%Y%m%d").date()
        except ValueError:
            return None

    @staticmethod
    def _raw_total_score(item: ScoredNewsCandidate) -> int:
        value = item.candidate.raw.get("raw_total_score", item.total_score)
        try:
            return int(value)
        except (TypeError, ValueError):
            return item.total_score

    @staticmethod
    def _candidate_topic_group(item: ScoredNewsCandidate) -> str:
        return str(item.candidate.raw.get("topic_group") or "general_life")

    @staticmethod
    def _candidate_hook_priority(item: ScoredNewsCandidate) -> int:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        try:
            return int(raw.get("hook_category_priority", 3))
        except (TypeError, ValueError):
            return 3

    def _apply_issue_content_profile(self, item: ScoredNewsCandidate) -> dict[str, Any]:
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        if not isinstance(item.candidate.raw, dict):
            item.candidate.raw = raw
        return self.issue_profile_service.apply_to_raw(
            raw,
            topic=item.candidate.topic or "",
            summary=item.candidate.summary or "",
        )

    @staticmethod
    def _content_angle_summary(item: ScoredNewsCandidate) -> dict[str, Any]:
        content_angle = item.candidate.raw.get("content_angle")
        if not isinstance(content_angle, dict):
            return {}
        return {
            "content_type": content_angle.get("content_type", ""),
            "reader_question": content_angle.get("reader_question", ""),
            "reader_loss": content_angle.get("reader_loss", ""),
            "practical_value": content_angle.get("practical_value", ""),
            "issue_content_profile": content_angle.get("issue_content_profile", ""),
            "intent_mode": content_angle.get("intent_mode", ""),
            "title_mode": content_angle.get("title_mode", ""),
            "answer_engine_mode": content_angle.get("answer_engine_mode", ""),
            "reader_question_style": content_angle.get("reader_question_style", ""),
            "required_sections": content_angle.get("required_sections", []),
            "avoid_sections": content_angle.get("avoid_sections", []),
        }

    def _history_internal_link_targets(
        self,
        *,
        selected: ScoredNewsCandidate,
        content_type: str,
    ) -> tuple[tuple[str, str], ...]:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        try:
            records = self.publish_history_service.recent_records(limit=80)
        except Exception as exc:  # noqa: BLE001
            logger.warning("history internal link load failed: %s", exc)
            records = []
        return build_internal_links_from_history(
            records,
            current_title=str(raw.get("selected_title") or selected.candidate.topic or ""),
            current_topic=selected.candidate.topic or "",
            current_topic_group=str(raw.get("topic_group") or "general_life"),
            current_content_type=content_type,
            limit=3,
        )

    def _resolve_cover_image_url(
        self,
        *,
        selected: ScoredNewsCandidate,
        selected_title: str,
        content_type: str,
        topic_group: str,
        image_plan: dict[str, str],
    ) -> str:
        configured = cover_image_url_from_env(
            content_type=content_type,
            topic_group=topic_group,
            include_default=False,
        )
        if configured:
            return configured
        try:
            from blogspot_automation.services.cover_image_service import CoverImageService

            service = CoverImageService()
            if not service.enabled():
                return cover_image_url_from_env(content_type=content_type, topic_group=topic_group)
            slug = build_english_permalink_slug(
                title=selected_title,
                topic=selected.candidate.topic or "",
                labels=[topic_group, content_type],
                topic_group=topic_group,
            )
            generated = service.build_cover_image_url(
                title=selected_title,
                topic=selected.candidate.topic or "",
                slug=slug,
                image_concept=str(image_plan.get("image_prompt") or "")[:500],
            )
            if generated:
                return generated
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover image generation skipped: %s", exc)
        return cover_image_url_from_env(content_type=content_type, topic_group=topic_group)

    @staticmethod
    def _internal_link_suggestions(*, selected: ScoredNewsCandidate, content_type: str) -> list[str]:
        topic_group = str(selected.candidate.raw.get("topic_group") or "general_life")
        evergreen_axis = str(selected.candidate.raw.get("evergreen_axis") or "").strip()
        public_benefit_keyword = str(selected.candidate.raw.get("public_benefit_keyword") or "").strip()
        generic_support_keyword = str(selected.candidate.raw.get("generic_support_keyword") or "").strip()
        keyword = public_benefit_keyword or generic_support_keyword or selected.candidate.topic
        evergreen_links = {
            "adsense_revenue": [
                "애드센스 수익이 안 오를 때 먼저 볼 체크리스트",
                "검색 의도에 맞는 블로그 제목 고르는 법",
                "광고 수익보다 먼저 점검할 글 구조",
            ],
            "blogspot_growth": [
                "블로그스팟 글쓰기 템플릿 기본 구조",
                "수익형 블로그 내부 링크 설계법",
                "블로그스팟과 네이버블로그 수익화 비교",
            ],
            "ai_automation": [
                "AI 자동화가 시간을 줄이지 못하는 이유",
                "직장인 AI 도구 검수 기준 잡는 법",
                "AI 블로그 자동화에서 버릴 구조",
            ],
            "money_life": [
                "생활비 줄이기 전 구독료 점검법",
                "자동결제 해지 전 확인할 항목",
                "고정비 줄이는 체크리스트",
            ],
            "tax_refund_support": [
                "세금 환급금 조회 전 홈택스에서 볼 항목",
                "환급 계좌와 필요 서류 확인법",
                "국세 환급금 조회 전 주의할 오류",
            ],
            "digital_survival": [
                "구글 검색 변화에 맞춘 블로그 글 구조",
                "AI 검색 시대 FAQ와 요약 블록 쓰는 법",
                "디지털 플랫폼 변경 전 백업 체크리스트",
            ],
        }
        if evergreen_axis in evergreen_links:
            return evergreen_links[evergreen_axis][:5]
        base_by_type = {
            "policy_deadline": [
                "지원금 신청 전 확인해야 할 공통 체크리스트",
                "정부 지원금 공식 페이지 확인하는 법",
                "지원금 대상 조건과 중복 지원 제한 보는 법",
            ],
            "consumer_warning": [
                "환불 지연 때 먼저 남겨야 할 증거",
                "결제 취소 전 확인할 카드사 문의 항목",
                "소비자 피해 상담 전 준비할 기록",
            ],
            "platform_change": [
                "서비스 종료 공지에서 먼저 볼 항목",
                "구형 기기 지원 종료 전 백업 체크리스트",
                "앱 정책 변경 때 계정과 결제 확인하는 법",
            ],
            "ai_work_tip": [
                "AI 기능 켜기 전 확인할 업무 설정",
                "직장인이 AI 도구를 쓸 때 검수 기준 잡는 법",
                "AI 자동화가 오히려 시간을 늘리는 경우",
            ],
            "money_checklist": [
                "무료배달 쿠폰 적용 전 최종 결제금액 비교법",
                "생활비 줄이기 전 확인할 구독료와 수수료",
                "쿠폰 조건 때문에 총액이 커지는 경우",
            ],
            "trend_decode": [
                "오픈런 소비 전 확인할 가격과 필요성",
                "품절 유행이 과소비로 이어지는 이유",
                "SNS 인증 소비 전에 볼 체크리스트",
            ],
        }
        suggestions = list(base_by_type.get(content_type, base_by_type.get(topic_group, [])))
        if content_type == "policy_deadline" and keyword:
            suggestions.insert(0, f"{keyword} 신청 전 공식 공고에서 볼 항목")
        cleaned: list[str] = []
        for item in suggestions:
            text = " ".join(str(item or "").split())
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned[:5]

    @staticmethod
    def _click_potential_score(selected: ScoredNewsCandidate) -> int:
        value = selected.candidate.raw.get("click_potential_score")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _build_labels(selected: ScoredNewsCandidate, hook_type: str) -> list[str]:
        if NewsPipeline._candidate_topic_group(selected) == "policy_benefit":
            return [
                "AI활용",
                "AI도구",
                "업무자동화",
                "프롬프트",
                "생산성",
                "AI보안",
                "체크리스트",
                "news",
            ]
        if NewsQualityGate.is_delivery_money_issue(selected):
            labels = [
                "배달료",
                "배달앱",
                "라이더",
                "생활비",
                "소비자",
                "자영업자",
                "수수료",
                "AI활용",
                "AI도구",
                "news",
            ]
            return labels[:10]
        labels = [
            selected.candidate.category,
            hook_type,
            "AI활용",
            "업무자동화",
            "news",
        ]
        cleaned: list[str] = []
        for label in labels:
            text = str(label or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned or ["AI활용", "AI도구", "news"]

    def _sort_by_golden_confidence(
        self, candidates: list[ScoredNewsCandidate]
    ) -> list[ScoredNewsCandidate]:
        """golden pattern confidence 기준으로 내림차순 정렬한다."""
        ps = self.golden_preview_service._ps
        def _conf(item: ScoredNewsCandidate) -> int:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            try:
                return int(ps.match_pattern(
                    topic=item.candidate.topic or "",
                    content_type=ct,
                    topic_group=tg,
                )["confidence"])
            except Exception:
                return 0
        return sorted(candidates, key=_conf, reverse=True)

    def _prefer_golden_matched_candidates(
        self, candidates: list[ScoredNewsCandidate]
    ) -> list[ScoredNewsCandidate]:
        """content_type·topic_group·summary 포함해 confidence >= 80인 후보를 반환한다."""
        ps = self.golden_preview_service._ps
        matched = []
        for item in candidates:
            raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
            ct = str((raw.get("content_angle") or {}).get("content_type") or "")
            tg = str(raw.get("topic_group") or "")
            summary_parts = [
                str(raw.get("search_demand_topic") or ""),
                " ".join(list(raw.get("reader_search_questions") or [])[:2]),
            ]
            summary = " ".join(p for p in summary_parts if p)
            try:
                result = ps.match_pattern(
                    topic=item.candidate.topic or "",
                    content_type=ct,
                    topic_group=tg,
                    summary=summary,
                )
                confidence = int(result.get("confidence", 0))
                raw["golden_selection_confidence"] = confidence
                raw["golden_selection_pattern_id"] = str(result.get("pattern_id") or "")
                if confidence >= 80:
                    matched.append(item)
            except Exception:
                pass
        return matched

    @staticmethod
    def _is_publish_hold_phase2() -> bool:
        return os.getenv("PUBLISH_HOLD_PHASE2", "true").strip().lower() in ("1", "true", "yes")

    @staticmethod
    def _compute_editorial_scores(
        *,
        selected: ScoredNewsCandidate,
        publish_quality_gate: dict[str, Any],
        golden_preview_result: dict[str, Any],
    ) -> dict[str, Any]:
        raw = selected.candidate.raw if isinstance(selected.candidate.raw, dict) else {}
        content_type = ""
        ca = raw.get("content_angle")
        if isinstance(ca, dict):
            content_type = str(ca.get("content_type") or "")
        click_score = int(raw.get("click_potential_score") or 0)
        reader_value = int(publish_quality_gate.get("reader_value_score") or 0)
        is_viral = content_type == "viral_issue_decode"
        is_evergreen = str(raw.get("source_type") or "").lower() == "evergreen_fallback"
        viral_risk_flags = list(raw.get("viral_risk_flags") or [])
        viral_safety_raw = int(raw.get("viral_safety_score") or 100)
        default_phrase = bool(publish_quality_gate.get("default_phrase_detected"))

        sr = golden_preview_result.get("slot_result") or {}
        slots = sr.get("slots") or {}
        fill_rate = float(golden_preview_result.get("slot_fill_rate", 0.0))
        has_qdt = bool(slots.get("quick_decision_table"))
        has_actions = bool(slots.get("actions"))
        has_faq = bool(slots.get("faq"))
        has_links = bool(slots.get("internal_links"))

        # traffic_potential_score: 0-40
        tp_base = min(32, click_score * 3)
        tp_bonus = (8 if is_viral else 0) + (4 if not is_evergreen and click_score >= 8 else 0) + (4 if is_evergreen else 0)
        traffic_potential_score = max(0, min(40, tp_base + tp_bonus))

        # usefulness_score: 0-40
        u_fill = fill_rate * 16
        u_reader = (reader_value / 100) * 10
        u_bonus = (4 if has_qdt else 0) + (4 if has_actions else 0) + (4 if has_faq else 0) + (2 if has_links else 0)
        usefulness_score = max(0, min(40, int(u_fill + u_reader + u_bonus)))

        # evergreen_asset_score: 0-10
        ea = (5 if is_evergreen else 0) + (3 if has_links else 0) + (2 if fill_rate >= 0.8 else 0)
        evergreen_asset_score = max(0, min(10, ea))

        # viral_safety_score: 0-10
        vs = (5 if not viral_risk_flags else 0) + (3 if viral_safety_raw >= 40 else 0) + (2 if not default_phrase else 0)
        viral_safety_score = max(0, min(10, vs))

        # final_editorial_score: 0-100 (traffic 40 + usefulness 40 + asset+safety 20)
        final_editorial_score = int(traffic_potential_score + usefulness_score + evergreen_asset_score + viral_safety_score)

        return {
            "traffic_potential_score": traffic_potential_score,
            "usefulness_score": usefulness_score,
            "evergreen_asset_score": evergreen_asset_score,
            "viral_safety_score": viral_safety_score,
            "final_editorial_score": final_editorial_score,
        }

    @staticmethod
    def _compute_content_candidate_grade(
        *,
        editorial_scores: dict[str, Any],
        golden_preview_result: dict[str, Any],
        publish_quality_gate: dict[str, Any],
    ) -> str:
        golden_ready = bool(golden_preview_result.get("ready_for_review"))
        is_near_match = bool(golden_preview_result.get("near_match"))
        pm = golden_preview_result.get("pattern_match") or {}
        confidence = int(pm.get("confidence", 0))
        fill_rate = float(golden_preview_result.get("slot_fill_rate", 0.0))
        blocking = list(golden_preview_result.get("blocking_issues") or [])
        traffic = editorial_scores.get("traffic_potential_score", 0)
        usefulness = editorial_scores.get("usefulness_score", 0)
        reader_value = int(publish_quality_gate.get("reader_value_score") or 0)
        default_phrase = bool(publish_quality_gate.get("default_phrase_detected"))
        viral_risk = any("viral_risk" in i for i in (publish_quality_gate.get("blocking_issues") or []))

        if default_phrase or viral_risk:
            return "D"
        if not golden_ready or confidence < 80 or fill_rate < 0.8:
            # near_match: confidence 75~79 + ct_match + tg_match → B 등급 허용
            if is_near_match and confidence >= 75 and fill_rate >= 0.8 and not blocking:
                return "B" if traffic >= 20 else "C"
            return "C" if traffic >= 24 else "D"
        if blocking:
            return "C"
        # golden_ready=True, confidence>=80, fill>=0.8, no blocking
        if traffic >= 24 or usefulness >= 32:
            return "A"
        if reader_value >= 75:
            return "B"
        return "B"

    @staticmethod
    def _top_scored_candidates(scored: list[ScoredNewsCandidate]) -> list[dict[str, Any]]:
        return [
            {
                "topic": item.candidate.topic,
                "category": item.candidate.category,
                "topic_group": item.candidate.raw.get("topic_group"),
                "search_angle": item.candidate.raw.get("search_angle"),
                "search_demand_topic": item.candidate.raw.get("search_demand_topic"),
                "reader_search_questions": item.candidate.raw.get("reader_search_questions"),
                "click_reason": item.candidate.raw.get("click_reason"),
                "reader_benefit": item.candidate.raw.get("reader_benefit"),
                "urgency_reason": item.candidate.raw.get("urgency_reason"),
                "content_promise": item.candidate.raw.get("content_promise"),
                "angle_type": item.candidate.raw.get("angle_type"),
                "commercial_support_signal": item.candidate.raw.get("commercial_support_signal", False),
                "generic_support_keyword": item.candidate.raw.get("generic_support_keyword", ""),
                "public_benefit_keyword": item.candidate.raw.get("public_benefit_keyword"),
                "public_benefit_confidence": item.candidate.raw.get("public_benefit_confidence", "none"),
                "evergreen_axis": item.candidate.raw.get("evergreen_axis", ""),
                "evergreen_reason": item.candidate.raw.get("evergreen_reason", ""),
                "target_reader": item.candidate.raw.get("target_reader", ""),
                "stale_penalty_applied": item.candidate.raw.get("stale_penalty_applied", False),
                "public_benefit_promotion_blocked": item.candidate.raw.get("public_benefit_promotion_blocked", False),
                "transformed_topic": item.candidate.raw.get("transformed_topic"),
                "original_topic": item.candidate.raw.get("original_topic"),
                "promotion_like_title": item.candidate.raw.get("promotion_like_title", False),
                "promoted_from_brand_article": item.candidate.raw.get("promoted_from_brand_article", False),
                "content_angle": NewsPipeline._content_angle_summary(item),
                "total_score": item.total_score,
                "cooldown_penalty": item.candidate.raw.get("cooldown_penalty", 0),
                "click_potential_score": item.candidate.raw.get("click_potential_score"),
                "raw_total_score": item.candidate.raw.get("raw_total_score"),
                "hook_angle": item.candidate.raw.get("hook_angle"),
                "search_intent_score": item.candidate.raw.get("search_intent_score"),
                "money_loss_score": item.candidate.raw.get("money_loss_score"),
                "mass_relevance_score": item.candidate.raw.get("mass_relevance_score"),
                "practical_value_score": item.candidate.raw.get("practical_value_score"),
                "brand_fit_score": item.candidate.raw.get("brand_fit_score"),
                "reader_interest_score": item.candidate.raw.get("reader_interest_score"),
                "reader_interest_strategy": item.candidate.raw.get("reader_interest_strategy"),
                "reader_interest_publish_intent": item.candidate.raw.get("reader_interest_publish_intent"),
                "reader_interest_brief": item.candidate.raw.get("reader_interest_brief"),
                "save_value_score": item.candidate.raw.get("save_value_score"),
                "curiosity_score": item.candidate.raw.get("curiosity_score"),
                "strategy_score_breakdown": item.candidate.raw.get("strategy_score_breakdown"),
                "strategy_risk_penalty": (item.candidate.raw.get("strategy_score_breakdown") or {}).get("risk_penalty"),
                "freshness_score": item.freshness_score,
                "search_demand_score": item.search_demand_score,
                "contrarian_gap_score": item.contrarian_gap_score,
                "mass_impact_score": item.mass_impact_score,
                "adsense_value_score": item.adsense_value_score,
                "hook_score": item.hook_score,
                "risk_penalty": item.risk_penalty,
                "reason": item.reason,
            }
            for item in scored[:5]
        ]
