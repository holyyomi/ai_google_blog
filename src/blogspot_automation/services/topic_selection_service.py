from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urlparse
from urllib.request import urlopen
from xml.etree import ElementTree

from blogspot_automation.storage import BlogWorkItem, BlogWorkItemRepository, ContentPillar, PublishStatus, now_iso


logger = logging.getLogger(__name__)


MIN_SOURCE_ARTICLES = 3
MIN_UNIQUE_DOMAINS = 2
RECENT_DUPLICATE_WINDOW_DAYS = 30
TOOL_REUSE_WINDOW_DAYS = 10
MAJOR_AI_BRANDS: frozenset[str] = frozenset({
    "gpt", "chatgpt", "claude", "gemini", "llama", "mistral",
    "copilot", "midjourney", "dall-e", "sora", "grok",
})
MAJOR_AI_UPDATE_KEYWORDS: frozenset[str] = frozenset({
    "releases", "launch", "launches", "update", "new feature",
    "announces", "unveiled", "unveils",
    "출시", "업데이트", "신기능", "새로운 기능", "발표", "공개",
})
PLACEHOLDER_HOST_TOKENS = {"example.com", "placeholder", "dummy", "localhost", "test.com"}
TITLE_TYPE_ORDER = ["문제형", "초보형", "실행형", "비교형", "뉴스해설형"]
STOPWORDS = {
    "오늘",
    "최근",
    "분석",
    "해설",
    "정리",
    "실전",
    "가이드",
    "초보",
    "뉴스",
    "기반",
    "한국",
    "온라인",
    "수익화",
    "부업",
    "투자",
    "주식",
    "시장",
    "대한",
    "에서",
    "으로",
    "하는",
    "있다",
    "한다",
    "대한민국",
}

PILLAR_CONFIG_KEYS: dict[str, ContentPillar] = {
    "daily_side_hustle": ContentPillar.DAILY_SIDE_HUSTLE,
    "ai_side_hustle": ContentPillar.AI_SIDE_HUSTLE,
    "ai_tools_news": ContentPillar.AI_TOOLS_NEWS,
    "korean_stock_news": ContentPillar.KOREAN_STOCK_NEWS,
    "side_hustle_tax": ContentPillar.SIDE_HUSTLE_TAX,
    "korean_stock_beginner": ContentPillar.KOREAN_STOCK_BEGINNER,
}


PILLAR_RULES: dict[ContentPillar, dict[str, object]] = {
    ContentPillar.DAILY_SIDE_HUSTLE: {
        "keywords": ["수익화", "N잡", "프리랜서", "창업", "자동화", "파이프라인"],
        "attention_keywords": ["화제", "이슈", "비법", "공개", "성장", "효율"],
        "practical_keywords": ["실전", "방법", "체크리스트", "단계", "수익 구조", "자동화"],
        "risk_keywords": ["보장", "무조건", "확정 수익", "초단기"],
        "monetization_weight": 0.88,
    },
    ContentPillar.AI_SIDE_HUSTLE: {
        "keywords": ["AI", "챗GPT", "자동화", "생성형", "수익화", "툴", "워크플로", "클로드"],
        "attention_keywords": ["업데이트", "출시", "도입", "확산", "돈버는"],
        "practical_keywords": ["적용", "실전", "자동화", "템플릿", "수익화", "업무", "프롬프트"],
        "risk_keywords": ["보장", "무조건", "수익 인증만", "복붙"],
        "monetization_weight": 0.96,
    },
    ContentPillar.AI_TOOLS_NEWS: {
        "keywords": ["신제품", "AI 모델", "업데이트", "오픈AI", "앤스로픽", "사용법", "신규 툴"],
        "attention_keywords": ["혁신", "성능", "출시", "무료", "기능", "초보"],
        "practical_keywords": ["사용법", "생성", "비교", "테스트", "차이점"],
        "risk_keywords": ["무조건 돈버는", "비밀공개"],
        "monetization_weight": 0.75,
    },
}


PILLAR_RULES.update(
    {
        ContentPillar.KOREAN_STOCK_NEWS: {
            "keywords": ["주식", "증시", "국내 증시", "코스피", "코스닥", "특징주", "종목", "반도체", "공시", "실적", "stock", "kospi", "kosdaq"],
            "attention_keywords": ["이슈", "시황", "변동성", "급등", "하락", "상승", "발표", "공시"],
            "practical_keywords": ["점검", "해설", "체크", "지표", "실적", "공시", "전망"],
            "risk_keywords": ["추천", "확정 수익", "무조건", "급등주"],
            "monetization_weight": 0.62,
        },
        ContentPillar.SIDE_HUSTLE_TAX: {
            "keywords": ["부업", "N잡", "프리랜서", "세금", "종합소득세", "원천징수", "신고", "tax", "freelance"],
            "attention_keywords": ["기준", "신고", "절세", "환급", "세무", "국세청", "소득"],
            "practical_keywords": ["체크", "가이드", "방법", "기록", "신고 기준", "종합소득세", "원천징수"],
            "risk_keywords": ["탈세", "무조건 환급", "확정 절세"],
            "monetization_weight": 0.74,
        },
        ContentPillar.KOREAN_STOCK_BEGINNER: {
            "keywords": ["주식", "초보", "입문", "ETF", "계좌", "국내주식", "투자", "beginner", "invest"],
            "attention_keywords": ["기초", "가이드", "체크리스트", "개념", "순서"],
            "practical_keywords": ["배우는", "시작", "계좌", "ETF", "분산", "리스크", "체크"],
            "risk_keywords": ["추천주", "확정 수익", "단타 필승"],
            "monetization_weight": 0.58,
        },
    }
)


class NewsProvider(Protocol):
    def fetch_articles(self) -> list["SourceArticle"]:
        ...


@dataclass(slots=True)
class SourceArticle:
    provider_name: str
    source_url: str
    title: str
    summary: str
    article_url: str
    published_at: str | None = None


@dataclass(slots=True)
class TopicCandidateScore:
    attention_score: float
    monetization_score: float
    practicality_score: float
    freshness_score: float
    differentiation_score: float
    trustworthiness_score: float
    risk_penalty: float
    topic_score: float


@dataclass(slots=True)
class DuplicateEvaluation:
    status: str = "PASS"
    is_duplicate: bool = False
    short_reason: str = ""
    debug_reason: str = ""
    similarity_score: float = 0.0
    title_similarity: float = 0.0
    keyword_similarity: float = 0.0
    source_overlap: float = 0.0
    angle_similarity: float = 0.0


@dataclass(slots=True)
class TopicCandidateBundle:
    content_pillar: str
    topic_title: str
    primary_keyword: str
    secondary_keywords: list[str]
    source_articles: list[SourceArticle]
    source_summary: str
    why_selected: str
    title_candidates: list[str]
    title_candidate_types: list[str]
    source_domains: list[str]
    source_quality_status: str
    scores: TopicCandidateScore
    duplicate_hit: bool = False
    duplicate_reason: str = ""
    duplicate_debug: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SelectedTopicResult:
    selected_pillar: str
    selected_topic: str
    why_selected: str
    source_articles: list[dict[str, object]]
    source_count: int
    source_domains: list[str]
    keyword_set: dict[str, object]
    title_candidates: list[str]
    title_candidate_types: list[str]
    topic_score: float
    article_pack: dict[str, object] = field(default_factory=dict)
    source_quality_status: str = ""
    discovery_debug: dict[str, object] = field(default_factory=dict)
    raw_candidate_count: int = 0
    parsed_candidate_count: int = 0
    filtered_candidate_count: int = 0
    reject_reason_summary: dict[str, int] = field(default_factory=dict)
    final_discovery_status: str = ""
    retry_count: int = 0
    retry_path: list[str] = field(default_factory=list)
    fallback_strategy_used: str = ""
    fallback_pillar_used: str = ""
    discovery_attempts: list[dict[str, object]] = field(default_factory=list)
    publish_status: str = ""
    stop_reason: str = ""
    saved_work_item_id: str = ""


@dataclass(slots=True)
class ProviderFetchDebug:
    provider_type: str
    provider_name: str
    source_url: str
    query_text: str = ""
    fetch_status: str = "pending"
    parse_status: str = "pending"
    response_length: int = 0
    parse_count: int = 0
    filtered_out_count: int = 0
    filtered_item_reasons: dict[str, int] = field(default_factory=dict)
    error_message: str = ""


@dataclass(slots=True)
class DiscoveryDebugSnapshot:
    selected_pillar: str = ""
    attempted_strategy_type: str = ""
    selected_strategy_type: list[str] = field(default_factory=list)
    provider_mix: dict[str, int] = field(default_factory=dict)
    query_group: list[str] = field(default_factory=list)
    search_queries_used: list[str] = field(default_factory=list)
    final_selected_queries: list[str] = field(default_factory=list)
    source_attempts: list[ProviderFetchDebug] = field(default_factory=list)
    pillar_runs: list[dict[str, object]] = field(default_factory=list)
    discovery_attempts: list[dict[str, object]] = field(default_factory=list)
    raw_candidate_count: int = 0
    parsed_candidate_count: int = 0
    filtered_candidate_count: int = 0
    reject_reason_summary: dict[str, int] = field(default_factory=dict)
    final_failure_reason: str = ""
    final_discovery_status: str = ""
    unique_domain_count: int = 0
    retry_count: int = 0
    retry_reason: str = ""
    retry_path: list[str] = field(default_factory=list)
    fallback_strategy_used: str = ""
    fallback_pillar_used: str = ""


@dataclass(slots=True)
class TopicDiscoveryRuntimeConfig:
    providers: list["NewsProvider"]
    min_source_articles: int = MIN_SOURCE_ARTICLES
    min_unique_domains: int = MIN_UNIQUE_DOMAINS
    test_mode_enabled: bool = False
    pillar_strategy_map: dict[str, "PillarDiscoveryStrategy"] = field(default_factory=dict)


@dataclass(slots=True)
class PillarDiscoveryStrategy:
    pillar_name: str
    strategy_types: list[str]
    provider_priority: list[str]
    query_groups: list[str]
    min_source_articles: int
    min_unique_domains: int
    fallback_pillars: list[str] = field(default_factory=list)
    query_expansion_ko: list[str] = field(default_factory=list)
    query_expansion_en: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiscoveryAttemptPlan:
    pillar_name: str
    strategy_types: list[str]
    provider_types: list[str]
    query_groups: list[str]
    retry_stage: str
    retry_reason: str
    fallback_label: str
    providers: list["NewsProvider"]
    queries: list[str]


class FeedNewsProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        url: str,
        provider_type: str,
        timeout_seconds: int = 8,
        query_text: str = "",
        pillar_name: str = "",
        query_group: str = "",
    ) -> None:
        self.provider_name = provider_name
        self.url = url
        self.provider_type = provider_type
        self.timeout_seconds = timeout_seconds
        self.query_text = query_text
        self.pillar_name = pillar_name
        self.query_group = query_group

    def fetch_articles(self) -> list[SourceArticle]:
        with urlopen(self.url, timeout=self.timeout_seconds) as response:
            raw = response.read()
        return self._parse_articles(raw)

    def fetch_with_debug(self) -> tuple[list[SourceArticle], ProviderFetchDebug]:
        debug = ProviderFetchDebug(
            provider_type=self.provider_type,
            provider_name=self.provider_name,
            source_url=self.url,
            query_text=self.query_text,
        )
        try:
            sanity_error = _feed_url_sanity_error(self.url)
            if sanity_error:
                debug.fetch_status = "failed"
                debug.parse_status = "failed"
                debug.error_message = sanity_error
                return [], debug
            with urlopen(self.url, timeout=self.timeout_seconds) as response:
                raw = response.read()
            debug.fetch_status = "success"
            debug.response_length = len(raw)
            articles = self._parse_articles(raw)
            debug.parse_status = "success"
            debug.parse_count = len(articles)
            return articles, debug
        except Exception as exc:
            debug.fetch_status = "failed"
            debug.parse_status = "failed"
            debug.error_message = f"{type(exc).__name__}: {exc}"
            return [], debug

    def _parse_articles(self, raw: bytes) -> list[SourceArticle]:
        root = ElementTree.fromstring(raw)
        articles: list[SourceArticle] = []
        for item in root.findall(".//item"):
            article = _rss_item_to_article(item, provider_name=self.provider_name, source_url=self.url)
            if article is not None:
                articles.append(article)
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            article = _atom_entry_to_article(entry, provider_name=self.provider_name, source_url=self.url)
            if article is not None:
                articles.append(article)
        _enrich_articles_with_body(articles, limit=3, max_chars=3000)
        return articles


class RssNewsProvider(FeedNewsProvider):
    def __init__(
        self,
        *,
        provider_name: str,
        url: str,
        timeout_seconds: int = 15,
        pillar_name: str = "",
        query_group: str = "rss_sources",
    ) -> None:
        super().__init__(
            provider_name=provider_name,
            url=url,
            provider_type="rss_feed",
            timeout_seconds=timeout_seconds,
            pillar_name=pillar_name,
            query_group=query_group,
        )


class GoogleNewsSearchRssProvider(FeedNewsProvider):
    def __init__(
        self,
        *,
        provider_name: str,
        query_text: str,
        query_language: str = "ko",
        timeout_seconds: int = 15,
        pillar_name: str = "",
        query_group: str = "",
    ) -> None:
        url = build_google_news_rss_url(query_text=query_text, query_language=query_language)
        super().__init__(
            provider_name=provider_name,
            url=url,
            provider_type="google_news_search_rss",
            timeout_seconds=timeout_seconds,
            query_text=query_text,
            pillar_name=pillar_name,
            query_group=query_group or f"search_queries_{query_language}",
        )
        self.query_language = query_language


class InMemoryNewsProvider:
    def __init__(
        self,
        articles: list[SourceArticle],
        *,
        pillar_name: str = "",
        provider_type: str = "in_memory",
        query_group: str = "",
        query_text: str = "",
    ) -> None:
        self._articles = articles
        self.pillar_name = pillar_name
        self.provider_type = provider_type
        self.query_group = query_group
        self.query_text = query_text

    def fetch_articles(self) -> list[SourceArticle]:
        return list(self._articles)

    def fetch_with_debug(self) -> tuple[list[SourceArticle], ProviderFetchDebug]:
        articles = list(self._articles)
        return articles, ProviderFetchDebug(
            provider_type=self.provider_type,
            provider_name="in-memory",
            source_url="memory://articles",
            query_text=self.query_text,
            fetch_status="success",
            parse_status="success",
            response_length=len(articles),
            parse_count=len(articles),
        )


class DefaultTopicSelectionService:
    def __init__(
        self,
        *,
        repository: BlogWorkItemRepository,
        providers: list[NewsProvider],
        min_source_articles: int = MIN_SOURCE_ARTICLES,
        min_unique_domains: int = MIN_UNIQUE_DOMAINS,
        pillar_strategy_map: dict[str, PillarDiscoveryStrategy] | None = None,
    ) -> None:
        self.repository = repository
        self.providers = providers
        self.min_source_articles = max(min_source_articles, 1)
        self.min_unique_domains = max(min_unique_domains, 1)
        self.pillar_strategy_map = pillar_strategy_map or {}

    def discover_and_select_today_topic(self) -> SelectedTopicResult:
        debug = DiscoveryDebugSnapshot(
            attempted_strategy_type=self._infer_strategy_type(),
            search_queries_used=self._collect_queries_used(),
        )
        if self.pillar_strategy_map:
            candidates = self._discover_candidates_with_retry(debug)
        else:
            articles = self._collect_articles(debug)
            candidates = self._build_candidates(articles, debug)
        qualified = [candidate for candidate in candidates if candidate.source_quality_status == "sufficient"]
        non_duplicate = [candidate for candidate in qualified if not candidate.duplicate_hit]

        if non_duplicate:
            # 직전 3개 발행 포스트와 같은 AI 브랜드 반복 방지
            recent_published = self.repository.list_recent_by_status(
                statuses=[PublishStatus.PUBLISHED], limit=3
            )
            banned_brands: set[str] = set()
            for item in recent_published:
                banned_brands |= _extract_ai_brands(item.topic_title or item.final_title or "")
            brand_diverse = [c for c in non_duplicate if not _overlaps_banned_brand(c.topic_title, banned_brands)]
            if brand_diverse:
                logger.info("brand diversity filter: %d → %d candidates (banned: %s)", len(non_duplicate), len(brand_diverse), banned_brands)
            selected = max(brand_diverse or non_duplicate, key=lambda candidate: candidate.scores.topic_score)
            debug.selected_pillar = selected.content_pillar
            self._apply_selected_strategy_metadata(debug, selected.content_pillar)
            debug.final_discovery_status = "selected"
            return self._save_selected_candidate(selected, debug)

        if qualified:
            best_duplicate = max(qualified, key=lambda candidate: candidate.scores.topic_score)
            debug.selected_pillar = best_duplicate.content_pillar
            self._apply_selected_strategy_metadata(debug, best_duplicate.content_pillar)
            debug.final_discovery_status = PublishStatus.PLANNED_FAIL.value
            return self._save_failed_selection(
                publish_status=PublishStatus.PLANNED_FAIL,
                stop_reason="최근 30일 내 유사 주제가 이미 발행되어 오늘 주제 생성을 중단했습니다.",
                candidate=best_duplicate,
                debug=debug,
            )

        best_insufficient = max(
            candidates,
            key=lambda candidate: (
                candidate.scores.trustworthiness_score,
                candidate.scores.topic_score,
                len(candidate.source_articles),
            ),
            default=None,
        )
        reason = "실제 기사 3개 이상 또는 최소 2개 이상의 출처 도메인을 확보하지 못해 주제 생성을 중단했습니다."
        reason = (
            f"실제 기사 {self.min_source_articles}개 이상 또는 최소 {self.min_unique_domains}개 이상의 "
            "출처 도메인을 확보하지 못해 주제 생성을 중단했습니다."
        )
        if best_insufficient is not None:
            debug.selected_pillar = best_insufficient.content_pillar
            self._apply_selected_strategy_metadata(debug, best_insufficient.content_pillar)
        debug.final_failure_reason = reason
        debug.final_discovery_status = PublishStatus.SOURCE_INSUFFICIENT.value
        return self._save_failed_selection(
            publish_status=PublishStatus.SOURCE_INSUFFICIENT,
            stop_reason=reason,
            candidate=best_insufficient,
            debug=debug,
        )

    def _collect_articles(
        self,
        debug: DiscoveryDebugSnapshot,
        *,
        providers: list[NewsProvider] | None = None,
    ) -> list[SourceArticle]:
        import concurrent.futures

        articles: list[SourceArticle] = []
        reject_summary: dict[str, int] = {}
        active_providers = providers or self.providers
        if not active_providers:
            debug.raw_candidate_count = 0
            debug.parsed_candidate_count = 0
            debug.filtered_candidate_count = 0
            debug.reject_reason_summary = {}
            debug.unique_domain_count = 0
            return []

        # ── 병렬 수집: 모든 provider를 동시에 요청 ──
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(active_providers), 12)) as executor:
            future_to_provider = {
                executor.submit(self._fetch_provider_articles, provider): provider
                for provider in active_providers
            }
            for future in concurrent.futures.as_completed(future_to_provider, timeout=30):
                try:
                    fetched, provider_debug = future.result(timeout=10)
                except Exception as exc:
                    provider = future_to_provider[future]
                    provider_debug = ProviderFetchDebug(
                        provider_type=str(getattr(provider, "provider_type", "")),
                        provider_name=str(getattr(provider, "provider_name", "")),
                        source_url=str(getattr(provider, "url", "")),
                        fetch_status="failed",
                        parse_status="failed",
                        error_message=str(exc),
                    )
                    fetched = []
                debug.source_attempts.append(provider_debug)
                articles.extend(fetched)

        debug.raw_candidate_count = len(articles)
        debug.parsed_candidate_count = sum(item.parse_count for item in debug.source_attempts)
        normalized: list[SourceArticle] = []
        seen_urls: set[str] = set()
        for article in articles:
            prepared, reject_reason = _prepare_article(article)
            if prepared is None:
                _increment_counter(reject_summary, reject_reason or "prepare_rejected")
                self._record_provider_reject(debug, article, reject_reason or "prepare_rejected")
                continue
            if prepared.article_url in seen_urls:
                _increment_counter(reject_summary, "duplicate_article_url")
                self._record_provider_reject(debug, prepared, "duplicate_article_url")
                continue
            seen_urls.add(prepared.article_url)
            normalized.append(prepared)
        debug.filtered_candidate_count = len(normalized)
        debug.reject_reason_summary = reject_summary
        debug.unique_domain_count = len(_extract_domains(normalized))
        logger.info(
            "topic discovery collected: strategy=%s raw=%s parsed=%s filtered=%s domains=%s rejects=%s",
            debug.attempted_strategy_type,
            debug.raw_candidate_count,
            debug.parsed_candidate_count,
            debug.filtered_candidate_count,
            debug.unique_domain_count,
            debug.reject_reason_summary,
        )
        return normalized

    def _discover_candidates_with_retry(self, debug: DiscoveryDebugSnapshot) -> list[TopicCandidateBundle]:
        all_candidates: list[TopicCandidateBundle] = []
        seen_attempt_keys: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()

        for pillar_name in self._initial_pillar_order():
            for plan in self._build_retry_attempt_plans(pillar_name, evergreen_only=False):
                attempt_key = (
                    plan.pillar_name,
                    plan.retry_stage,
                    tuple(plan.provider_types),
                    tuple(plan.queries),
                )
                if attempt_key in seen_attempt_keys:
                    continue
                seen_attempt_keys.add(attempt_key)
                candidates = self._execute_retry_attempt(plan, debug)
                all_candidates.extend(candidates)
                qualified = [candidate for candidate in candidates if candidate.source_quality_status == "sufficient"]
                if any(not candidate.duplicate_hit for candidate in qualified):
                    debug.final_discovery_status = "selected"
                    return all_candidates

        for pillar_name in self._evergreen_fallback_pillars():
            for plan in self._build_retry_attempt_plans(pillar_name, evergreen_only=True):
                attempt_key = (
                    plan.pillar_name,
                    plan.retry_stage,
                    tuple(plan.provider_types),
                    tuple(plan.queries),
                )
                if attempt_key in seen_attempt_keys:
                    continue
                seen_attempt_keys.add(attempt_key)
                candidates = self._execute_retry_attempt(plan, debug)
                all_candidates.extend(candidates)
                qualified = [candidate for candidate in candidates if candidate.source_quality_status == "sufficient"]
                if any(not candidate.duplicate_hit for candidate in qualified):
                    debug.final_discovery_status = "selected"
                    if not debug.fallback_strategy_used:
                        debug.fallback_strategy_used = "evergreen_fallback"
                    if not debug.fallback_pillar_used:
                        debug.fallback_pillar_used = pillar_name
                    return all_candidates

        if not debug.final_failure_reason and debug.discovery_attempts:
            last_attempt = debug.discovery_attempts[-1]
            debug.final_failure_reason = str(last_attempt.get("final_failure_reason", ""))
        return all_candidates

    def _execute_retry_attempt(
        self,
        plan: DiscoveryAttemptPlan,
        debug: DiscoveryDebugSnapshot,
    ) -> list[TopicCandidateBundle]:
        strategy = self.pillar_strategy_map[plan.pillar_name]
        attempt_debug = DiscoveryDebugSnapshot(
            selected_pillar=plan.pillar_name,
            attempted_strategy_type="+".join(plan.strategy_types),
            selected_strategy_type=list(plan.strategy_types),
            provider_mix=self._provider_mix(plan.providers),
            query_group=list(plan.query_groups),
            search_queries_used=list(plan.queries),
        )
        articles = self._collect_articles(attempt_debug, providers=plan.providers)
        candidates = self._build_candidates_for_pillar(
            pillar_name=plan.pillar_name,
            articles=articles,
            debug=attempt_debug,
            strategy=strategy,
        )
        fallback_label = plan.fallback_label
        if debug.discovery_attempts and plan.retry_stage == "initial":
            first_pillar = str(debug.discovery_attempts[0].get("pillar_name", ""))
            if first_pillar and first_pillar != plan.pillar_name:
                fallback_label = "pillar_fallback"

        attempt_summary = {
            "pillar_name": plan.pillar_name,
            "strategy_type": list(plan.strategy_types),
            "provider_mix": dict(attempt_debug.provider_mix),
            "query_group": list(plan.query_groups),
            "retry_stage": plan.retry_stage,
            "retry_reason": plan.retry_reason,
            "fallback_label": fallback_label,
            "search_queries_used": list(plan.queries),
            "raw_candidate_count": attempt_debug.raw_candidate_count,
            "parsed_candidate_count": attempt_debug.parsed_candidate_count,
            "filtered_candidate_count": attempt_debug.filtered_candidate_count,
            "source_attempt_count": len(attempt_debug.source_attempts),
            "reject_reason_summary": dict(attempt_debug.reject_reason_summary),
            "final_failure_reason": attempt_debug.final_failure_reason,
        }
        debug.discovery_attempts.append(attempt_summary)
        debug.pillar_runs.append(attempt_summary)
        debug.source_attempts.extend(attempt_debug.source_attempts)
        debug.raw_candidate_count += attempt_debug.raw_candidate_count
        debug.parsed_candidate_count += attempt_debug.parsed_candidate_count
        debug.filtered_candidate_count += attempt_debug.filtered_candidate_count
        debug.unique_domain_count = max(debug.unique_domain_count, attempt_debug.unique_domain_count)
        for key, value in attempt_debug.reject_reason_summary.items():
            debug.reject_reason_summary[key] = debug.reject_reason_summary.get(key, 0) + value

        debug.retry_path.append(f"{plan.pillar_name}:{plan.retry_stage}")
        debug.retry_count = max(len(debug.discovery_attempts) - 1, 0)
        debug.retry_reason = plan.retry_reason

        qualified = [candidate for candidate in candidates if candidate.source_quality_status == "sufficient"]
        if qualified:
            debug.selected_pillar = plan.pillar_name
            debug.selected_strategy_type = list(plan.strategy_types)
            debug.provider_mix = dict(attempt_debug.provider_mix)
            debug.query_group = list(plan.query_groups)
            debug.search_queries_used = list(plan.queries)
            debug.final_selected_queries = list(plan.queries)
            if fallback_label != "primary":
                debug.fallback_strategy_used = fallback_label
                debug.fallback_pillar_used = plan.pillar_name
        elif attempt_debug.final_failure_reason:
            debug.final_failure_reason = attempt_debug.final_failure_reason
        return candidates

    def _initial_pillar_order(self) -> list[str]:
        preferred = [
            ContentPillar.KOREAN_STOCK_NEWS.value,
            ContentPillar.AI_SIDE_HUSTLE.value,
            ContentPillar.DAILY_SIDE_HUSTLE.value,
            ContentPillar.SIDE_HUSTLE_TAX.value,
            ContentPillar.KOREAN_STOCK_BEGINNER.value,
        ]
        available = list(self.pillar_strategy_map.keys())
        ordered: list[str] = []
        for pillar in preferred:
            if pillar not in available or pillar in ordered:
                continue
            ordered.append(pillar)
            for fallback in self.pillar_strategy_map.get(pillar, PillarDiscoveryStrategy("", [], [], [], 1, 1)).fallback_pillars:
                if fallback in available and fallback not in ordered:
                    ordered.append(fallback)
        ordered.extend(pillar for pillar in available if pillar not in ordered)
        return ordered

    def _evergreen_fallback_pillars(self) -> list[str]:
        evergreen = [
            ContentPillar.SIDE_HUSTLE_TAX.value,
            ContentPillar.KOREAN_STOCK_BEGINNER.value,
        ]
        return [pillar for pillar in evergreen if pillar in self.pillar_strategy_map]

    def _build_retry_attempt_plans(self, pillar_name: str, *, evergreen_only: bool) -> list[DiscoveryAttemptPlan]:
        strategy = self.pillar_strategy_map[pillar_name]
        base_providers = [provider for provider in self.providers if getattr(provider, "pillar_name", "") == pillar_name]
        if not base_providers:
            return []

        stages = (
            [("evergreen_fallback", "final evergreen fallback")]
            if evergreen_only
            else [
                ("initial", "initial discovery"),
                ("duplicate_angle_retry", "same pillar different angle re-discovery"),
                ("duplicate_query_retry", "same pillar alternate query re-discovery"),
                ("query_expansion", "same pillar query expansion"),
                ("provider_mix_expansion", "same pillar provider mix expansion"),
            ]
        )
        plans: list[DiscoveryAttemptPlan] = []
        for stage_name, retry_reason in stages:
            providers = self._providers_for_retry_stage(
                strategy,
                base_providers,
                stage_name,
                evergreen_only=evergreen_only,
            )
            if not providers:
                continue
            query_groups = [
                group
                for group in dict.fromkeys(
                    str(getattr(provider, "query_group", "")).strip()
                    for provider in providers
                    if str(getattr(provider, "query_group", "")).strip()
                )
            ]
            plans.append(
                DiscoveryAttemptPlan(
                    pillar_name=pillar_name,
                    strategy_types=list(strategy.strategy_types),
                    provider_types=[
                        provider_type
                        for provider_type in dict.fromkeys(
                            str(getattr(provider, "provider_type", provider.__class__.__name__)) for provider in providers
                        )
                    ],
                    query_groups=query_groups,
                    retry_stage=stage_name,
                    retry_reason=retry_reason,
                    fallback_label=self._fallback_label_for_attempt(pillar_name, stage_name, evergreen_only=evergreen_only),
                    providers=providers,
                    queries=self._collect_queries_used(providers),
                )
            )
        return plans

    def _fallback_label_for_attempt(self, pillar_name: str, stage_name: str, *, evergreen_only: bool) -> str:
        if evergreen_only or stage_name == "evergreen_fallback":
            return "evergreen_fallback"
        if stage_name == "initial":
            return "primary"
        if pillar_name in self._evergreen_fallback_pillars():
            return "evergreen_search"
        if stage_name == "query_expansion":
            return "query_expansion"
        return "provider_mix_expansion"

    def _providers_for_retry_stage(
        self,
        strategy: PillarDiscoveryStrategy,
        providers: list[NewsProvider],
        stage_name: str,
        *,
        evergreen_only: bool,
    ) -> list[NewsProvider]:
        providers_by_type: dict[str, list[NewsProvider]] = {}
        for provider in providers:
            provider_type = str(getattr(provider, "provider_type", provider.__class__.__name__))
            providers_by_type.setdefault(provider_type, []).append(provider)

        if evergreen_only:
            allowed_types = [
                provider_type
                for provider_type in strategy.provider_priority
                if provider_type in {"evergreen_source", "official_blog", "official_newsroom", "google_news_search_rss", "rss_feed"}
            ]
        elif stage_name == "initial":
            allowed_types = strategy.provider_priority[:1] or strategy.provider_priority
        elif stage_name in {"duplicate_angle_retry", "duplicate_query_retry", "query_expansion"}:
            allowed_types = strategy.provider_priority[:2] or strategy.provider_priority
        else:
            allowed_types = list(strategy.provider_priority)

        selected: list[NewsProvider] = []
        for provider_type in allowed_types:
            selected.extend(providers_by_type.get(provider_type, []))
        if stage_name in {"duplicate_angle_retry", "duplicate_query_retry", "query_expansion", "provider_mix_expansion", "evergreen_fallback"}:
            selected.extend(self._expanded_query_providers(strategy, selected or providers))
        return _dedupe_providers(selected)

    def _expanded_query_providers(
        self,
        strategy: PillarDiscoveryStrategy,
        providers: list[NewsProvider],
    ) -> list[NewsProvider]:
        expanded: list[NewsProvider] = []
        for provider in providers:
            if str(getattr(provider, "provider_type", "")) != "google_news_search_rss":
                continue
            for query_text in self._query_expansions_for_provider(strategy, provider):
                if hasattr(provider, "with_query"):
                    clone = provider.with_query(query_text, "en" if re.search(r"[a-zA-Z]", query_text) else "ko")  # type: ignore[attr-defined]
                    expanded.append(clone)
                    continue
                query_language = "en" if re.search(r"[a-zA-Z]", query_text) else "ko"
                expanded.append(
                    GoogleNewsSearchRssProvider(
                        provider_name=f"{getattr(provider, 'provider_name', 'google-news')}-retry-{abs(hash(query_text)) % 10000}",
                        query_text=query_text,
                        query_language=query_language,
                        pillar_name=str(getattr(provider, "pillar_name", strategy.pillar_name)),
                        query_group=f"expanded_{query_language}",
                    )
                )
        return expanded

    def _query_expansions_for_provider(
        self,
        strategy: PillarDiscoveryStrategy,
        provider: NewsProvider,
    ) -> list[str]:
        base_query = str(getattr(provider, "query_text", "")).strip()
        if not base_query:
            return []
        expanded = []
        if re.search(r"[a-zA-Z]", base_query):
            expanded.extend(
                [
                    f"{base_query} guide",
                    f"{base_query} checklist",
                    f"{base_query} beginner",
                ]
            )
            expanded.extend(strategy.query_expansion_en)
        else:
            expanded.extend(
                [
                    f"{base_query} 방법",
                    f"{base_query} 체크리스트",
                    f"{base_query} 가이드",
                ]
            )
            expanded.extend(strategy.query_expansion_ko)
        return [query for query in dict.fromkeys(item.strip() for item in expanded if item.strip())]

    def _discover_candidates_by_pillar(self, debug: DiscoveryDebugSnapshot) -> list[TopicCandidateBundle]:
        all_candidates: list[TopicCandidateBundle] = []
        pillar_runs: list[dict[str, object]] = []
        overall_rejects: dict[str, int] = {}
        all_attempts: list[ProviderFetchDebug] = []
        raw_total = 0
        parsed_total = 0
        filtered_total = 0

        for pillar_name, strategy in self.pillar_strategy_map.items():
            pillar_providers = [provider for provider in self.providers if getattr(provider, "pillar_name", "") == pillar_name]
            pillar_debug = DiscoveryDebugSnapshot(
                selected_pillar=pillar_name,
                attempted_strategy_type="+".join(strategy.strategy_types),
                search_queries_used=self._collect_queries_used(pillar_providers),
            )
            articles = self._collect_articles(pillar_debug, providers=pillar_providers)
            candidates = self._build_candidates_for_pillar(
                pillar_name=pillar_name,
                articles=articles,
                debug=pillar_debug,
                strategy=strategy,
            )
            all_candidates.extend(candidates)
            all_attempts.extend(pillar_debug.source_attempts)
            raw_total += pillar_debug.raw_candidate_count
            parsed_total += pillar_debug.parsed_candidate_count
            filtered_total += pillar_debug.filtered_candidate_count
            for key, value in pillar_debug.reject_reason_summary.items():
                overall_rejects[key] = overall_rejects.get(key, 0) + value
            pillar_runs.append(
                {
                    "pillar_name": pillar_name,
                    "strategy_type": strategy.strategy_types,
                    "provider_mix": self._provider_mix(pillar_providers),
                    "query_group": strategy.query_groups,
                    "raw_candidate_count": pillar_debug.raw_candidate_count,
                    "parsed_candidate_count": pillar_debug.parsed_candidate_count,
                    "filtered_candidate_count": pillar_debug.filtered_candidate_count,
                    "source_attempt_count": len(pillar_debug.source_attempts),
                    "reject_reason_summary": pillar_debug.reject_reason_summary,
                }
            )

        debug.source_attempts = all_attempts
        debug.raw_candidate_count = raw_total
        debug.parsed_candidate_count = parsed_total
        debug.filtered_candidate_count = filtered_total
        debug.reject_reason_summary = overall_rejects
        debug.unique_domain_count = len(
            {
                _domain_from_url(article.article_url)
                for candidate in all_candidates
                for article in candidate.source_articles
                if _domain_from_url(article.article_url)
            }
        )
        debug.final_failure_reason = ""
        debug.pillar_runs = pillar_runs
        return all_candidates

    def _build_candidates(self, articles: list[SourceArticle], debug: DiscoveryDebugSnapshot) -> list[TopicCandidateBundle]:
        classified: dict[str, list[SourceArticle]] = {}
        for article in articles:
            pillar = _classify_pillar(article)
            if pillar is None:
                _increment_counter(debug.reject_reason_summary, "pillar_unclassified")
                self._record_provider_reject(debug, article, "pillar_unclassified")
                continue
            classified.setdefault(pillar.value, []).append(article)

        recent_items = self.repository.list_recent(limit=120)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DUPLICATE_WINDOW_DAYS)
        recent_topics = [item for item in recent_items if _parse_iso(item.updated_at) >= recent_cutoff]

        candidates: list[TopicCandidateBundle] = []
        for pillar_name, pillar_articles in classified.items():
            clustered = _cluster_articles(self._filter_articles_for_pillar(pillar_name, pillar_articles, debug), self.min_source_articles)
            for cluster_articles in clustered:
                source_domains = _extract_domains(cluster_articles)
                primary_keyword = _build_primary_keyword(cluster_articles, pillar_name)
                secondary_keywords = _derive_secondary_keywords(cluster_articles, primary_keyword)
                topic_title = _build_topic_title(pillar_name, primary_keyword, cluster_articles)
                duplicate_evaluation = _evaluate_duplicate_topic(
                    topic_title=topic_title,
                    primary_keyword=primary_keyword,
                    pillar_name=pillar_name,
                    source_domains=source_domains,
                    source_articles=cluster_articles,
                    recent_items=recent_topics,
                )
                scores = _score_candidate(
                    pillar_name=pillar_name,
                    topic_title=topic_title,
                    primary_keyword=primary_keyword,
                    articles=cluster_articles,
                    source_domains=source_domains,
                    recent_items=recent_topics,
                    duplicate_penalty=22.0 if duplicate_evaluation.is_duplicate else 0.0,
                )
                source_quality_status = _source_quality_status(
                    cluster_articles,
                    source_domains,
                    min_source_articles=self.min_source_articles,
                    min_unique_domains=self.min_unique_domains,
                )
                title_candidates, title_candidate_types = _build_title_candidates(topic_title, primary_keyword)
                candidates.append(
                    TopicCandidateBundle(
                        content_pillar=pillar_name,
                        topic_title=topic_title,
                        primary_keyword=primary_keyword,
                        secondary_keywords=secondary_keywords,
                        source_articles=cluster_articles,
                        source_summary=_build_source_summary(cluster_articles),
                        why_selected=_build_selection_reason(
                            pillar_name=pillar_name,
                            article_count=len(cluster_articles),
                            source_domains=source_domains,
                            scores=scores,
                        ),
                        title_candidates=title_candidates,
                        title_candidate_types=title_candidate_types,
                        source_domains=source_domains,
                        source_quality_status=source_quality_status,
                        scores=scores,
                        duplicate_hit=duplicate_evaluation.status == "BLOCK",
                        duplicate_reason=duplicate_evaluation.short_reason,
                        duplicate_debug=asdict(duplicate_evaluation),
                    )
                )
        return sorted(candidates, key=lambda candidate: candidate.scores.topic_score, reverse=True)

    def _build_candidates_for_pillar(
        self,
        *,
        pillar_name: str,
        articles: list[SourceArticle],
        debug: DiscoveryDebugSnapshot,
        strategy: PillarDiscoveryStrategy,
    ) -> list[TopicCandidateBundle]:
        recent_items = self.repository.list_recent(limit=120)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DUPLICATE_WINDOW_DAYS)
        recent_topics = [item for item in recent_items if _parse_iso(item.updated_at) >= recent_cutoff]

        candidates: list[TopicCandidateBundle] = []
        relevant_articles = self._filter_articles_for_pillar(pillar_name, articles, debug)
        for cluster_articles in _cluster_articles(relevant_articles, strategy.min_source_articles):
            source_domains = _extract_domains(cluster_articles)
            primary_keyword = _build_primary_keyword(cluster_articles, pillar_name)
            secondary_keywords = _derive_secondary_keywords(cluster_articles, primary_keyword)
            topic_title = _build_topic_title(pillar_name, primary_keyword, cluster_articles)
            duplicate_evaluation = _evaluate_duplicate_topic(
                topic_title=topic_title,
                primary_keyword=primary_keyword,
                pillar_name=pillar_name,
                source_domains=source_domains,
                source_articles=cluster_articles,
                recent_items=recent_topics,
            )
            scores = _score_candidate(
                pillar_name=pillar_name,
                topic_title=topic_title,
                primary_keyword=primary_keyword,
                articles=cluster_articles,
                source_domains=source_domains,
                recent_items=recent_topics,
                strategy_types=strategy.strategy_types,
                duplicate_penalty=22.0 if duplicate_evaluation.is_duplicate else 0.0,
            )
            source_quality_status = _source_quality_status(
                cluster_articles,
                source_domains,
                min_source_articles=strategy.min_source_articles,
                min_unique_domains=strategy.min_unique_domains,
            )
            title_candidates, title_candidate_types = _build_title_candidates(topic_title, primary_keyword)
            candidates.append(
                TopicCandidateBundle(
                    content_pillar=pillar_name,
                    topic_title=topic_title,
                    primary_keyword=primary_keyword,
                    secondary_keywords=secondary_keywords,
                    source_articles=cluster_articles,
                    source_summary=_build_source_summary(cluster_articles),
                    why_selected=_build_selection_reason(
                        pillar_name=pillar_name,
                        article_count=len(cluster_articles),
                        source_domains=source_domains,
                        scores=scores,
                    ),
                    title_candidates=title_candidates,
                    title_candidate_types=title_candidate_types,
                    source_domains=source_domains,
                    source_quality_status=source_quality_status,
                    scores=scores,
                    duplicate_hit=duplicate_evaluation.status == "BLOCK",
                    duplicate_reason=duplicate_evaluation.short_reason,
                    duplicate_debug=asdict(duplicate_evaluation),
                )
            )

        if not candidates:
            debug.final_failure_reason = (
                f"{pillar_name} pillar에서 {', '.join(strategy.strategy_types)} 전략으로도 충분한 후보를 만들지 못했습니다."
            )
        return candidates

    def _save_selected_candidate(self, candidate: TopicCandidateBundle, debug: DiscoveryDebugSnapshot) -> SelectedTopicResult:
        work_item = _candidate_to_work_item(
            candidate,
            publish_status=PublishStatus.PLANNED,
            stop_reason="",
            debug=debug,
        )
        saved = self.repository.upsert(work_item)
        return _work_item_to_result(saved, stop_reason="")

    def _save_failed_selection(
        self,
        *,
        publish_status: PublishStatus,
        stop_reason: str,
        candidate: TopicCandidateBundle | None,
        debug: DiscoveryDebugSnapshot,
    ) -> SelectedTopicResult:
        if publish_status == PublishStatus.PLANNED_FAIL:
            stop_reason = "최근 30일 유사 주제가 반복되어 오늘 생성이 보류되었습니다."
        if candidate is None:
            candidate = TopicCandidateBundle(
                content_pillar="",
                topic_title="",
                primary_keyword="",
                secondary_keywords=[],
                source_articles=[],
                source_summary="",
                why_selected=stop_reason,
                title_candidates=[],
                title_candidate_types=[],
                source_domains=[],
                source_quality_status="insufficient",
                scores=TopicCandidateScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            )
        work_item = _candidate_to_work_item(
            candidate,
            publish_status=publish_status,
            stop_reason=stop_reason,
            debug=debug,
        )
        saved = self.repository.upsert(work_item)
        return _work_item_to_result(saved, stop_reason=stop_reason)

    def _apply_selected_strategy_metadata(self, debug: DiscoveryDebugSnapshot, pillar_name: str) -> None:
        strategy = self.pillar_strategy_map.get(pillar_name)
        if strategy is None:
            return
        debug.selected_strategy_type = list(strategy.strategy_types)
        debug.query_group = list(strategy.query_groups)
        pillar_providers = [provider for provider in self.providers if getattr(provider, "pillar_name", "") == pillar_name]
        debug.provider_mix = self._provider_mix(pillar_providers)

    def _filter_articles_for_pillar(
        self,
        pillar_name: str,
        articles: list[SourceArticle],
        debug: DiscoveryDebugSnapshot,
    ) -> list[SourceArticle]:
        filtered: list[SourceArticle] = []
        for article in articles:
            relevance_score, reject_reason = _pillar_article_relevance(article=article, pillar_name=pillar_name)
            if relevance_score < 1.0:
                _increment_counter(debug.reject_reason_summary, reject_reason)
                self._record_provider_reject(debug, article, reject_reason)
                continue
            filtered.append(article)
        return filtered

    def _fetch_provider_articles(self, provider: NewsProvider) -> tuple[list[SourceArticle], ProviderFetchDebug]:
        if hasattr(provider, "fetch_with_debug"):
            fetched, debug = provider.fetch_with_debug()  # type: ignore[attr-defined]
        else:
            debug = ProviderFetchDebug(
                provider_type=provider.__class__.__name__,
                provider_name=str(getattr(provider, "provider_name", provider.__class__.__name__)),
                source_url=str(getattr(provider, "url", "")),
                query_text=str(getattr(provider, "query_text", "")),
            )
            try:
                fetched = provider.fetch_articles()
                debug.fetch_status = "success"
                debug.parse_status = "success"
                debug.response_length = len(fetched)
                debug.parse_count = len(fetched)
            except Exception as exc:
                fetched = []
                debug.fetch_status = "failed"
                debug.parse_status = "failed"
                debug.error_message = f"{type(exc).__name__}: {exc}"
        logger.info(
            "topic discovery fetch: provider=%s type=%s url=%s query=%s fetch=%s parse=%s count=%s error=%s",
            debug.provider_name,
            debug.provider_type,
            debug.source_url,
            debug.query_text,
            debug.fetch_status,
            debug.parse_status,
            debug.parse_count,
            debug.error_message,
        )
        return fetched, debug

    def _record_provider_reject(self, debug: DiscoveryDebugSnapshot, article: SourceArticle, reason: str) -> None:
        normalized_source = _normalize_url(article.source_url) or article.source_url
        for attempt in debug.source_attempts:
            if attempt.source_url == normalized_source:
                attempt.filtered_out_count += 1
                _increment_counter(attempt.filtered_item_reasons, reason)
                return
        if debug.source_attempts:
            debug.source_attempts[0].filtered_out_count += 1
            _increment_counter(debug.source_attempts[0].filtered_item_reasons, reason)

    def _infer_strategy_type(self) -> str:
        if not self.providers:
            return "no_provider_configured"
        if self.pillar_strategy_map:
            strategy_types = sorted(
                {
                    strategy_type
                    for strategy in self.pillar_strategy_map.values()
                    for strategy_type in strategy.strategy_types
                }
            )
            return "+".join(strategy_types)
        provider_types = sorted({provider.__class__.__name__ for provider in self.providers})
        return "+".join(provider_types)

    def _collect_queries_used(self, providers: list[NewsProvider] | None = None) -> list[str]:
        queries: list[str] = []
        active_providers = providers or self.providers
        for provider in active_providers:
            query_text = getattr(provider, "query_text", "")
            if isinstance(query_text, str) and query_text.strip():
                queries.append(query_text.strip())
            query_list = getattr(provider, "queries", None)
            if isinstance(query_list, list):
                queries.extend(str(item).strip() for item in query_list if str(item).strip())
        return list(dict.fromkeys(queries))

    def _provider_mix(self, providers: list[NewsProvider]) -> dict[str, int]:
        mix: dict[str, int] = {}
        for provider in providers:
            provider_type = str(getattr(provider, "provider_type", provider.__class__.__name__))
            mix[provider_type] = mix.get(provider_type, 0) + 1
        return mix


def build_google_news_rss_url(*, query_text: str, query_language: str = "ko") -> str:
    cleaned_query = query_text.strip()
    if not cleaned_query:
        raise ValueError("Google News RSS query must not be empty.")
    encoded_query = quote_plus(cleaned_query)
    if query_language == "en":
        return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"


def load_topic_discovery_runtime_config(root_dir: Path) -> TopicDiscoveryRuntimeConfig:
    config_path = root_dir / "config" / "monetization_topic_sources.json"
    if not config_path.exists():
        return TopicDiscoveryRuntimeConfig(providers=[])

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    settings = payload.get("discovery_settings", {})
    test_mode = bool(settings.get("enable_test_mode", False))
    if str(settings.get("enable_test_mode_env", "")).strip():
        env_name = str(settings["enable_test_mode_env"]).strip()
        test_mode = test_mode or str(__import__("os").environ.get(env_name, "")).lower() in {"1", "true", "yes", "on"}
    min_source_articles = int(settings.get("min_source_articles", MIN_SOURCE_ARTICLES))
    min_unique_domains = int(settings.get("min_unique_domains", MIN_UNIQUE_DOMAINS))
    if test_mode:
        thresholds = settings.get("test_mode_thresholds", {})
        min_source_articles = int(thresholds.get("min_source_articles", 2))
        min_unique_domains = int(thresholds.get("min_unique_domains", 1))

    providers: list[NewsProvider] = []
    providers.extend(_load_flat_legacy_providers(payload))
    pillar_strategy_map = _load_pillar_strategy_map(
        payload.get("pillar_sources", {}),
        default_min_source_articles=min_source_articles,
        default_min_unique_domains=min_unique_domains,
    )
    providers.extend(_load_pillar_config_providers(payload.get("pillar_sources", {}), pillar_strategy_map))
    providers = _dedupe_providers(providers)

    return TopicDiscoveryRuntimeConfig(
        providers=providers,
        min_source_articles=min_source_articles,
        min_unique_domains=min_unique_domains,
        test_mode_enabled=test_mode,
        pillar_strategy_map=pillar_strategy_map,
    )


def load_default_topic_providers(root_dir: Path) -> list[NewsProvider]:
    return load_topic_discovery_runtime_config(root_dir).providers


def _load_flat_legacy_providers(payload: dict[str, object]) -> list[NewsProvider]:
    providers: list[NewsProvider] = []
    for item in payload.get("providers", []):
        if not isinstance(item, dict):
            continue
        provider_type = str(item.get("provider_type", "")).strip()
        provider_name = str(item.get("provider_name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not provider_name:
            continue
        if provider_type in {"rss", "rss_feed"} and _normalize_url(url):
            providers.append(RssNewsProvider(provider_name=provider_name, url=url))
    return providers


def _load_pillar_config_providers(
    payload: dict[str, object],
    pillar_strategy_map: dict[str, PillarDiscoveryStrategy],
) -> list[NewsProvider]:
    providers: list[NewsProvider] = []
    if not isinstance(payload, dict):
        return providers
    for pillar_key, config in payload.items():
        if pillar_key not in PILLAR_CONFIG_KEYS or not isinstance(config, dict):
            continue
        providers.extend(_build_google_query_providers(pillar_key, config))
        providers.extend(_build_feed_providers(pillar_key, config.get("rss_sources", []), "rss_feed"))
        providers.extend(_build_feed_providers(pillar_key, config.get("official_sources", []), "official_newsroom"))
        providers.extend(_build_feed_providers(pillar_key, config.get("evergreen_sources", []), "evergreen_source"))
    return providers


def _load_pillar_strategy_map(
    payload: dict[str, object],
    *,
    default_min_source_articles: int,
    default_min_unique_domains: int,
) -> dict[str, PillarDiscoveryStrategy]:
    strategy_map: dict[str, PillarDiscoveryStrategy] = {}
    if not isinstance(payload, dict):
        return strategy_map
    for pillar_key, config in payload.items():
        pillar = PILLAR_CONFIG_KEYS.get(pillar_key)
        if pillar is None or not isinstance(config, dict):
            continue
        strategy_types = [str(item).strip() for item in config.get("strategy_types", []) if str(item).strip()]
        provider_priority = [str(item).strip() for item in config.get("provider_priority", []) if str(item).strip()]
        query_groups = _extract_query_groups(config)
        strategy_map[pillar.value] = PillarDiscoveryStrategy(
            pillar_name=pillar.value,
            strategy_types=strategy_types or ["news_driven"],
            provider_priority=provider_priority or ["rss_feed", "google_news_search_rss"],
            query_groups=query_groups,
            min_source_articles=int(config.get("min_source_articles", default_min_source_articles)),
            min_unique_domains=int(config.get("min_unique_domains", default_min_unique_domains)),
            fallback_pillars=[
                PILLAR_CONFIG_KEYS[item].value
                for item in config.get("fallback_pillars", [])
                if item in PILLAR_CONFIG_KEYS
            ],
            query_expansion_ko=[str(item).strip() for item in config.get("query_expansion_ko", []) if str(item).strip()],
            query_expansion_en=[str(item).strip() for item in config.get("query_expansion_en", []) if str(item).strip()],
        )
    return strategy_map


def _build_google_query_providers(pillar_key: str, config: dict[str, object]) -> list[NewsProvider]:
    providers: list[NewsProvider] = []
    for language_key, query_language in (("search_queries_ko", "ko"), ("search_queries_en", "en")):
        for index, query in enumerate(config.get(language_key, []), start=1):
            query_text = str(query).strip()
            if not query_text:
                continue
            providers.append(
                GoogleNewsSearchRssProvider(
                    provider_name=f"{pillar_key}-google-{query_language}-{index}",
                    query_text=query_text,
                    query_language=query_language,
                    pillar_name=PILLAR_CONFIG_KEYS[pillar_key].value,
                    query_group=language_key,
                )
            )
    return providers


def _build_feed_providers(
    pillar_key: str,
    items: object,
    provider_type: str,
) -> list[NewsProvider]:
    providers: list[NewsProvider] = []
    if not isinstance(items, list):
        return providers
    for index, item in enumerate(items, start=1):
        item_provider_type = provider_type
        if isinstance(item, str):
            provider_name = f"{pillar_key}-{provider_type}-{index}"
            url = item.strip()
        elif isinstance(item, dict):
            provider_name = str(item.get("provider_name") or f"{pillar_key}-{provider_type}-{index}").strip()
            url = str(item.get("url", "")).strip()
            override_type = str(item.get("provider_type", "")).strip()
            if override_type in {
                "rss_feed",
                "official_blog",
                "official_newsroom",
                "evergreen_source",
            }:
                item_provider_type = override_type
        else:
            continue
        normalized_url = _normalize_url(url)
        if not provider_name or not normalized_url or _is_placeholder_url(normalized_url):
            continue
        providers.append(
            FeedNewsProvider(
                provider_name=provider_name,
                url=normalized_url,
                provider_type=item_provider_type,
                pillar_name=PILLAR_CONFIG_KEYS[pillar_key].value,
                query_group=(
                    "rss_sources"
                    if item_provider_type == "rss_feed"
                    else "official_sources"
                    if item_provider_type in {"official_blog", "official_newsroom"}
                    else "evergreen_sources"
                ),
            )
        )
    return providers


def _dedupe_providers(providers: list[NewsProvider]) -> list[NewsProvider]:
    deduped: list[NewsProvider] = []
    seen: set[tuple[str, str, str]] = set()
    for provider in providers:
        provider_type = str(getattr(provider, "provider_type", provider.__class__.__name__))
        source_url = str(getattr(provider, "url", ""))
        query_text = str(getattr(provider, "query_text", ""))
        key = (provider_type, source_url, query_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(provider)
    return deduped


def _extract_query_groups(config: dict[str, object]) -> list[str]:
    groups: list[str] = []
    for key in ("search_queries_ko", "search_queries_en", "rss_sources", "official_sources", "evergreen_sources"):
        values = config.get(key, [])
        if isinstance(values, list) and values:
            groups.append(key)
    return groups


def _prepare_article(article: SourceArticle) -> tuple[SourceArticle | None, str]:
    article_url = _normalize_url(article.article_url)
    source_url = _normalize_url(article.source_url)
    if not article_url or _is_placeholder_url(article_url):
        return None, "invalid_or_placeholder_article_url"
    title = _clean_text(article.title)
    if len(title) < 8:
        return None, "title_too_short"
    summary = _clean_text(article.summary)
    if len(summary) < 20:
        summary = f"{title} 관련 핵심 이슈를 다루는 기사입니다."
    # 2일(48시간) 이내 기사만 허용 — published_at 없으면 통과
    normalized_pub = _normalize_published_at(article.published_at)
    if normalized_pub:
        try:
            age_hours = (datetime.now(timezone.utc) - _parse_iso(normalized_pub)).total_seconds() / 3600
            if age_hours > 48:
                return None, "article_too_old"
        except ValueError:
            pass
    return (
        SourceArticle(
            provider_name=article.provider_name.strip() or "unknown-provider",
            source_url=source_url,
            title=title,
            summary=summary,
            article_url=article_url,
            published_at=normalized_pub,
        ),
        "",
    )


_LAUNCH_SIGNAL_WORDS = {"launches", "released", "announces", "new", "update", "introduces", "unveils"}
_BIG_MODEL_NAMES = {"chatgpt", "claude", "gemini", "gpt-4", "gpt-3", "copilot"}


def _classify_pillar(article: SourceArticle) -> ContentPillar | None:
    haystack = f"{article.title} {article.summary}".lower()
    title_lower = article.title.lower()

    # 신규 출시 신호 키워드가 있으면 AI_TOOLS_NEWS 최우선
    has_launch_signal = any(w in title_lower for w in _LAUNCH_SIGNAL_WORDS)
    if has_launch_signal:
        return ContentPillar.AI_TOOLS_NEWS

    # 대형 모델(ChatGPT/Claude/Gemini 등)은 신규 출시 신호 없으면 스킵
    if any(name in haystack for name in _BIG_MODEL_NAMES) and not has_launch_signal:
        pass  # 아래 일반 분류로 위임
    elif any(keyword in haystack for keyword in ["openai", "오픈ai", "anthropic", "앤스로픽", "claude", "클로드", "gemini", "제미나이", "초거대 ai"]):
        return ContentPillar.AI_TOOLS_NEWS

    # AI 부업/수익화 매핑
    ai_hustle_keywords = ["수익화", "부업", "N잡", "자동화", "템플릿", "워크플로"]
    if ("ai" in haystack or "생성형" in haystack or "gpt" in haystack) and any(kw in haystack for kw in ai_hustle_keywords):
        return ContentPillar.AI_SIDE_HUSTLE
    best_pillar: ContentPillar | None = None
    best_score = 0.0
    for pillar, rules in PILLAR_RULES.items():
        keywords = rules["keywords"]
        practical = rules["practical_keywords"]
        attention = rules["attention_keywords"]
        score = (
            sum(4.0 for keyword in keywords if keyword.lower() in haystack)
            + sum(2.0 for keyword in practical if keyword.lower() in haystack)
            + sum(1.5 for keyword in attention if keyword.lower() in haystack)
        )
        if pillar == ContentPillar.KOREAN_STOCK_NEWS and "추천" in haystack:
            score -= 3.0
        if score > best_score:
            best_score = score
            best_pillar = pillar
    return best_pillar if best_score >= 4.0 else None


def _cluster_articles(articles: list[SourceArticle], min_source_articles: int) -> list[list[SourceArticle]]:
    if len(articles) <= 5:
        return [sorted(articles, key=_freshness_reference, reverse=True)]
    buckets: dict[str, list[SourceArticle]] = {}
    for article in sorted(articles, key=_freshness_reference, reverse=True):
        cluster_key = _build_cluster_key(article)
        buckets.setdefault(cluster_key, []).append(article)
    ordered = sorted(
        buckets.values(),
        key=lambda items: (len(items), max(_freshness_reference(item) for item in items)),
        reverse=True,
    )
    clusters: list[list[SourceArticle]] = [sorted(articles, key=_freshness_reference, reverse=True)[:5]]
    for items in ordered:
        trimmed = items[:5]
        if len(trimmed) < min_source_articles:
            continue
        if {article.article_url for article in trimmed} == {article.article_url for article in clusters[0]}:
            continue
        clusters.append(trimmed)
    return clusters


def _build_cluster_key(article: SourceArticle) -> str:
    tokens = _headline_tokens(article.title)
    if not tokens:
        tokens = _headline_tokens(article.summary)
    return "-".join(tokens[:2]) or "general"


def _build_primary_keyword(articles: list[SourceArticle], pillar_name: str) -> str:
    counts: dict[str, int] = {}
    for article in articles:
        for token in _headline_tokens(f"{article.title} {article.summary}"):
            counts[token] = counts.get(token, 0) + 1
    ranked = [token for token, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])) if count >= 2]
    if ranked:
        return " ".join(ranked[:2])
    if articles:
        fallback_tokens = _headline_tokens(articles[0].title)
        if fallback_tokens:
            return " ".join(fallback_tokens[:2])
    return pillar_name


def _derive_secondary_keywords(articles: list[SourceArticle], primary_keyword: str) -> list[str]:
    counts: dict[str, int] = {}
    primary_tokens = set(primary_keyword.split())
    for article in articles:
        for token in _headline_tokens(f"{article.title} {article.summary}"):
            if token in primary_tokens:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[:6]]


def _build_topic_title(pillar_name: str, primary_keyword: str, articles: list[SourceArticle]) -> str:
    if pillar_name == ContentPillar.KOREAN_STOCK_NEWS.value:
        return f"{primary_keyword} 이슈, 오늘 한국주식에서 무엇을 봐야 하나"
    if pillar_name == ContentPillar.KOREAN_STOCK_BEGINNER.value:
        return f"{primary_keyword} 흐름으로 배우는 한국주식 초보 체크포인트"
    if pillar_name == ContentPillar.SIDE_HUSTLE_TAX.value:
        return f"{primary_keyword} 이슈로 보는 부업 세금 실수 방지 가이드"
    if pillar_name == ContentPillar.AI_SIDE_HUSTLE.value:
        return f"{primary_keyword} 흐름에서 찾은 AI 부업 실전 적용 포인트"
    if articles:
        return f"{primary_keyword} 흐름으로 보는 오늘의 부업 아이디어"
    return primary_keyword


def _score_candidate(
    *,
    pillar_name: str,
    topic_title: str,
    primary_keyword: str,
    articles: list[SourceArticle],
    source_domains: list[str],
    recent_items: list[BlogWorkItem],
    strategy_types: list[str] | None = None,
    duplicate_penalty: float = 0.0,
) -> TopicCandidateScore:
    text = " ".join(f"{article.title} {article.summary}" for article in articles).lower()
    pillar = _pillar_enum_from_value(pillar_name)
    rules = PILLAR_RULES[pillar]
    source_count = len(articles)
    domain_diversity = len(source_domains)
    summary_coverage = sum(1 for article in articles if len(article.summary.strip()) >= 20) / max(source_count, 1)
    article_count_factor = min(1.0, source_count / 5.0)
    domain_factor = min(1.0, domain_diversity / 3.0)
    active_strategies = set(strategy_types or [])
    evergreen_bias = 1.0 if "evergreen_search" in active_strategies else 0.0
    official_bias = 1.0 if "official_source_driven" in active_strategies else 0.0
    news_bias = 1.0 if "news_driven" in active_strategies else 0.0
    hybrid_bias = 1.0 if "hybrid_news_search" in active_strategies else 0.0
    explanation_value = min(
        100.0,
        20.0
        + _keyword_hit_score(text, rules["practical_keywords"]) * 2.4
        + summary_coverage * 34.0
        + min(len(primary_keyword.split()), 3) * 9.0,
    )

    attention_score = min(
        100.0,
        35.0
        + article_count_factor * 24.0
        + domain_factor * 14.0
        + _keyword_hit_score(text, rules["attention_keywords"]) * 1.8,
    )
    monetization_score = min(
        100.0,
        20.0
        + float(rules["monetization_weight"]) * 50.0
        + _keyword_hit_score(text, rules["practical_keywords"]) * 1.4
        + summary_coverage * 16.0,
    )
    practicality_score = min(
        100.0,
        18.0
        + _keyword_hit_score(text, rules["practical_keywords"]) * 2.0
        + summary_coverage * 28.0
        + min(len(primary_keyword.split()), 3) * 8.0,
    )
    freshness_score = min(
        100.0,
        sum(_single_freshness(article) for article in articles) / max(source_count, 1) + news_bias * 4.0 + hybrid_bias * 2.0
    )
    differentiation_score = max(
        0.0,
        min(
            100.0,
            25.0
            + domain_factor * 24.0
            + min(len(primary_keyword.split()), 3) * 10.0
            + source_count * 6.0
            - duplicate_penalty,
        ),
    )
    trustworthiness_score = max(
        0.0,
        min(
            100.0,
            22.0
            + domain_factor * 30.0
            + summary_coverage * 24.0
            + article_count_factor * 14.0
            - (15.0 if domain_diversity == 1 else 0.0),
        ),
    )
    risk_penalty = min(40.0, _keyword_hit_score(text, rules["risk_keywords"]) * 3.5 + (8.0 if domain_diversity == 1 else 0.0))

    weights = {
        "attention": 0.18,
        "monetization": 0.17,
        "practicality": 0.18,
        "freshness": 0.14,
        "differentiation": 0.13,
        "trustworthiness": 0.20,
    }
    if "news_driven" in active_strategies:
        weights.update({"freshness": 0.20, "attention": 0.19, "practicality": 0.15, "trustworthiness": 0.18})
    if "evergreen_search" in active_strategies:
        weights.update({"freshness": 0.08, "practicality": 0.22, "trustworthiness": 0.22, "monetization": 0.19})
    if "official_source_driven" in active_strategies:
        weights["trustworthiness"] += 0.04
        weights["attention"] -= 0.02
    if "hybrid_news_search" in active_strategies:
        weights["differentiation"] += 0.02
        weights["attention"] += 0.01
    total_weight = sum(weights.values())
    normalized_weights = {key: value / total_weight for key, value in weights.items()}
    adjusted_practicality = min(100.0, practicality_score + explanation_value * (0.12 * evergreen_bias + 0.06 * official_bias))
    adjusted_trustworthiness = min(100.0, trustworthiness_score + official_bias * 6.0)
    weighted_score = (
        attention_score * normalized_weights["attention"]
        + monetization_score * normalized_weights["monetization"]
        + adjusted_practicality * normalized_weights["practicality"]
        + freshness_score * normalized_weights["freshness"]
        + differentiation_score * normalized_weights["differentiation"]
        + adjusted_trustworthiness * normalized_weights["trustworthiness"]
    )
    source_quality_multiplier = 0.7 + article_count_factor * 0.15 + domain_factor * 0.15
    topic_score = max(0.0, round(weighted_score * source_quality_multiplier - risk_penalty, 2))

    return TopicCandidateScore(
        attention_score=round(attention_score, 2),
        monetization_score=round(monetization_score, 2),
        practicality_score=round(practicality_score, 2),
        freshness_score=round(freshness_score, 2),
        differentiation_score=round(differentiation_score, 2),
        trustworthiness_score=round(trustworthiness_score, 2),
        risk_penalty=round(risk_penalty, 2),
        topic_score=topic_score,
    )


def _evaluate_duplicate_topic(
    *,
    topic_title: str,
    primary_keyword: str,
    pillar_name: str,
    source_domains: list[str],
    source_articles: list[SourceArticle],
    recent_items: list[BlogWorkItem],
) -> DuplicateEvaluation:
    current_tokens = _normalized_token_set(f"{topic_title} {primary_keyword}")
    current_title_tokens = _normalized_token_set(topic_title)
    current_source_titles = _normalized_token_set(" ".join(article.title for article in source_articles))
    current_domains = {domain for domain in source_domains if domain}
    best = DuplicateEvaluation()
    for item in recent_items:
        if item.content_pillar != pillar_name:
            continue
        existing_tokens = _normalized_token_set(f"{item.topic_title} {item.primary_keyword}")
        title_similarity = _jaccard_similarity(current_title_tokens, _normalized_token_set(item.topic_title))
        keyword_similarity = _jaccard_similarity(
            _normalized_token_set(primary_keyword),
            _normalized_token_set(item.primary_keyword),
        )
        existing_domains = {domain for domain in item.source_domains if domain}
        source_overlap = _jaccard_similarity(current_domains, existing_domains)
        existing_source_titles = _normalized_token_set(
            " ".join(str(article.get("title", "")) for article in item.source_articles if isinstance(article, dict))
        )
        angle_similarity = _jaccard_similarity(current_source_titles, existing_source_titles)
        semantic_similarity = _jaccard_similarity(current_tokens, existing_tokens)

        same_intent = keyword_similarity >= 0.78
        same_source_cluster = source_overlap >= 0.55 or angle_similarity >= 0.72
        same_angle = angle_similarity >= 0.68 and (title_similarity >= 0.68 or semantic_similarity >= 0.9)

        if semantic_similarity >= 0.9 and same_intent and same_source_cluster and same_angle:
            return DuplicateEvaluation(
                status="BLOCK",
                is_duplicate=True,
                short_reason="유사도 높음: 동일 키워드+동일 의도",
                debug_reason=(
                    f"semantic={semantic_similarity:.2f}, title={title_similarity:.2f}, "
                    f"keyword={keyword_similarity:.2f}, source_overlap={source_overlap:.2f}, angle={angle_similarity:.2f}"
                ),
                similarity_score=semantic_similarity,
                title_similarity=title_similarity,
                keyword_similarity=keyword_similarity,
                source_overlap=source_overlap,
                angle_similarity=angle_similarity,
            )
        if (
            semantic_similarity >= 0.94
            and keyword_similarity >= 0.85
            and angle_similarity >= 0.8
            and source_overlap >= 0.45
        ):
            return DuplicateEvaluation(
                status="BLOCK",
                is_duplicate=True,
                short_reason="?좎궗???믪쓬: ?숈씪 ?ㅼ썙???숈씪 ?섎룄",
                debug_reason=(
                    f"semantic={semantic_similarity:.2f}, title={title_similarity:.2f}, "
                    f"keyword={keyword_similarity:.2f}, source_overlap={source_overlap:.2f}, angle={angle_similarity:.2f}"
                ),
                similarity_score=semantic_similarity,
                title_similarity=title_similarity,
                keyword_similarity=keyword_similarity,
                source_overlap=source_overlap,
                angle_similarity=angle_similarity,
            )

        soft_similar = semantic_similarity >= 0.62 or (
            keyword_similarity >= 0.58 and title_similarity >= 0.54
        )
        if semantic_similarity > best.similarity_score:
            best = DuplicateEvaluation(
                status="SOFT_SIMILAR" if soft_similar else "PASS",
                is_duplicate=False,
                short_reason="유사 주제지만 source angle 달라 통과",
                debug_reason=(
                    f"semantic={semantic_similarity:.2f}, title={title_similarity:.2f}, "
                    f"keyword={keyword_similarity:.2f}, source_overlap={source_overlap:.2f}, angle={angle_similarity:.2f}"
                ),
                similarity_score=semantic_similarity,
                title_similarity=title_similarity,
                keyword_similarity=keyword_similarity,
                source_overlap=source_overlap,
                angle_similarity=angle_similarity,
            )
    # tool_id + content_angle 기반 10일 중복 체크
    # 같은 도구 + 같은 각도 → BLOCK / 같은 도구 + 다른 각도 → 허용
    current_tool_id = _extract_tool_id(f"{topic_title} {primary_keyword}")
    if current_tool_id is not None:
        current_angle = _infer_content_angle(f"{topic_title} {primary_keyword}")
        tool_cutoff = datetime.now(timezone.utc) - timedelta(days=TOOL_REUSE_WINDOW_DAYS)
        for item in recent_items:
            if item.content_pillar != pillar_name:
                continue
            try:
                item_dt = _parse_iso(item.updated_at)
            except (ValueError, AttributeError):
                continue
            if item_dt < tool_cutoff:
                continue
            existing_tool_id = _extract_tool_id(
                f"{item.topic_title or ''} {item.primary_keyword or ''}"
            )
            if existing_tool_id != current_tool_id:
                continue
            existing_angle = _infer_content_angle(
                f"{item.topic_title or ''} {item.primary_keyword or ''}"
            )
            if existing_angle == current_angle:
                return DuplicateEvaluation(
                    status="BLOCK",
                    is_duplicate=True,
                    short_reason=f"같은 도구({current_tool_id})+같은 각도({current_angle}) 10일 내 중복",
                    debug_reason=f"tool_id={current_tool_id}, angle={current_angle}",
                    similarity_score=0.9,
                )

    return best


def _is_duplicate_topic(
    *,
    topic_title: str,
    primary_keyword: str,
    pillar_name: str,
    recent_items: list[BlogWorkItem],
) -> bool:
    return _evaluate_duplicate_topic(
        topic_title=topic_title,
        primary_keyword=primary_keyword,
        pillar_name=pillar_name,
        source_domains=[],
        source_articles=[],
        recent_items=recent_items,
    ).is_duplicate


_BRAND_SKIP = frozenset({"The", "New", "Use", "How", "For", "With", "Top", "Best", "Its", "Can", "Are", "Has", "Was", "Not", "All", "But"})
_BRAND_RE = re.compile(r'\b[A-Z][a-zA-Z0-9\-]{2,}\b')


def _extract_ai_brands(title: str) -> set[str]:
    """제목에서 대문자로 시작하는 AI 브랜드/도구명 토큰을 추출."""
    return {t.lower() for t in _BRAND_RE.findall(title) if t not in _BRAND_SKIP}


def _overlaps_banned_brand(title: str, banned: set[str]) -> bool:
    return bool(_extract_ai_brands(title) & banned)


_TOOL_ID_MAP: dict[str, str] = {
    "claude": "claude",
    "anthropic": "claude",
    "chatgpt": "chatgpt",
    "gpt-4": "chatgpt",
    "gpt-3": "chatgpt",
    "openai": "chatgpt",
    "gemini": "gemini",
    "bard": "gemini",
    "llama": "llama",
    "mistral": "mistral",
    "copilot": "copilot",
    "midjourney": "midjourney",
    "dall-e": "dall-e",
    "sora": "sora",
    "grok": "grok",
}


def _extract_tool_id(text: str) -> str | None:
    """텍스트에서 AI 도구/브랜드명을 추출한다."""
    text_lower = text.lower()
    for token, brand_id in _TOOL_ID_MAP.items():
        if token in text_lower:
            return brand_id
    # 대문자 고유명사 추출 (기타 AI 툴)
    for token in _BRAND_RE.findall(text):
        if token not in _BRAND_SKIP and len(token) >= 3:
            return token.lower()
    return None


def _infer_content_angle(text: str) -> str:
    """콘텐츠 각도 추론: monetization/review/comparison/tutorial/automation/news/analysis."""
    t = text.lower()
    if any(kw in t for kw in ["비교", " vs ", "versus", "comparison", "차이"]):
        return "comparison"
    if any(kw in t for kw in ["수익", "monetization", "돈버", "수익화", "money", "earn"]):
        return "monetization"
    if any(kw in t for kw in ["자동화", "automation", "workflow", "워크플로"]):
        return "automation"
    if any(kw in t for kw in ["사용법", "tutorial", "how to", "가이드", "guide", "단계별"]):
        return "tutorial"
    if any(kw in t for kw in ["리뷰", "review", "후기", "평가"]):
        return "review"
    if any(kw in t for kw in ["출시", "releases", "launches", "업데이트", "update", "발표", "새로운", "신규"]):
        return "news"
    return "analysis"


def _build_source_summary(articles: list[SourceArticle]) -> str:
    return " / ".join(article.title.strip() for article in articles[:3] if article.title.strip())


def _build_selection_reason(
    *,
    pillar_name: str,
    article_count: int,
    source_domains: list[str],
    scores: TopicCandidateScore,
) -> str:
    return (
        f"{pillar_name} 축에서 실제 기사 {article_count}건과 출처 도메인 {len(source_domains)}개가 같은 흐름을 보여 "
        f"신뢰도 {scores.trustworthiness_score:.1f}, 실전성 {scores.practicality_score:.1f}, "
        f"차별성 {scores.differentiation_score:.1f} 기준으로 우선 선정했습니다."
    )


def _build_title_candidates(topic_title: str, primary_keyword: str) -> tuple[list[str], list[str]]:
    keyword = primary_keyword.strip() or topic_title.strip()
    raw_titles = [
        (f"{keyword}, 지금 놓치면 안 되는 핵심 문제는 무엇인가", "문제형"),
        (f"초보도 이해하는 {keyword} 이슈 읽는 법", "초보형"),
        (f"{keyword} 흐름에서 바로 실행할 체크리스트", "실행형"),
        (f"{keyword} 이슈 해설 vs 바로 따라하기, 무엇이 다른가", "비교형"),
        (topic_title, "뉴스해설형"),
    ]
    seen: set[str] = set()
    titles: list[str] = []
    types: list[str] = []
    for title, title_type in raw_titles:
        normalized = re.sub(r"\s+", " ", title.strip())
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        titles.append(normalized)
        types.append(title_type)
    return titles[:5], types[:5]


def _source_quality_status(
    articles: list[SourceArticle],
    source_domains: list[str],
    *,
    min_source_articles: int,
    min_unique_domains: int,
) -> str:
    if len(articles) < min_source_articles:
        return "insufficient_source_count"
    if len(source_domains) < min_unique_domains:
        return "insufficient_domain_diversity"
    return "sufficient"


def _candidate_to_work_item(
    candidate: TopicCandidateBundle,
    *,
    publish_status: PublishStatus,
    stop_reason: str,
    debug: DiscoveryDebugSnapshot,
) -> BlogWorkItem:
    timestamp = now_iso()
    item_id = f"topic-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    discovery_debug_payload = _discovery_debug_to_dict(debug)
    discovery_debug_payload["duplicate_evaluation"] = candidate.duplicate_debug
    article_pack = _build_article_pack(
        selected_pillar=candidate.content_pillar,
        selected_topic=candidate.topic_title,
        why_selected=stop_reason or candidate.why_selected,
        source_articles=[asdict(article) for article in candidate.source_articles],
        source_domains=candidate.source_domains,
        keyword_set={
            "primary_keyword": candidate.primary_keyword,
            "secondary_keywords": candidate.secondary_keywords,
        },
        title_candidates=candidate.title_candidates,
        title_candidate_types=candidate.title_candidate_types,
    )
    keyword_set = {
        "primary_keyword": candidate.primary_keyword,
        "secondary_keywords": candidate.secondary_keywords,
    }
    _topic_text = f"{candidate.topic_title} {candidate.primary_keyword}"
    notes = {
        "selected_pillar": candidate.content_pillar,
        "selected_topic": candidate.topic_title,
        "why_selected": candidate.why_selected,
        "source_count": len(candidate.source_articles),
        "source_domains": candidate.source_domains,
        "source_quality_status": candidate.source_quality_status,
        "article_pack": article_pack,
        "stop_reason": stop_reason,
        "discovery_debug": discovery_debug_payload,
        "tool_id": _extract_tool_id(_topic_text),
        "content_angle": _infer_content_angle(_topic_text),
        "retry_count": debug.retry_count,
        "retry_path": debug.retry_path,
        "fallback_strategy_used": debug.fallback_strategy_used,
        "fallback_pillar_used": debug.fallback_pillar_used,
        "score_breakdown": {
            "attention_score": candidate.scores.attention_score,
            "monetization_score": candidate.scores.monetization_score,
            "practicality_score": candidate.scores.practicality_score,
            "freshness_score": candidate.scores.freshness_score,
            "differentiation_score": candidate.scores.differentiation_score,
            "trustworthiness_score": candidate.scores.trustworthiness_score,
            "risk_penalty": candidate.scores.risk_penalty,
            "topic_score": candidate.scores.topic_score,
        },
    }
    return BlogWorkItem(
        id=item_id,
        created_at=timestamp,
        updated_at=timestamp,
        content_pillar=candidate.content_pillar,
        topic_title=candidate.topic_title,
        primary_keyword=candidate.primary_keyword,
        secondary_keywords=candidate.secondary_keywords,
        source_urls=[article.article_url for article in candidate.source_articles],
        source_summary=candidate.source_summary,
        selected_pillar=candidate.content_pillar,
        selected_topic=candidate.topic_title,
        why_selected=stop_reason or candidate.why_selected,
        source_articles=list(article_pack.get("source_articles", [])),
        source_count=len(candidate.source_articles),
        source_domains=candidate.source_domains,
        keyword_set=keyword_set,
        title_candidates=candidate.title_candidates,
        title_candidate_types=candidate.title_candidate_types,
        topic_score=candidate.scores.topic_score,
        source_quality_status=candidate.source_quality_status,
        discovery_debug=discovery_debug_payload,
        raw_candidate_count=debug.raw_candidate_count,
        parsed_candidate_count=debug.parsed_candidate_count,
        filtered_candidate_count=debug.filtered_candidate_count,
        reject_reason_summary=debug.reject_reason_summary,
        final_discovery_status=debug.final_discovery_status or publish_status.value,
        retry_count=debug.retry_count,
        retry_path=debug.retry_path,
        fallback_strategy_used=debug.fallback_strategy_used,
        fallback_pillar_used=debug.fallback_pillar_used,
        discovery_attempts=debug.discovery_attempts,
        publish_status=publish_status.value,
        notes=json.dumps(notes, ensure_ascii=False),
    )


def _work_item_to_result(item: BlogWorkItem, *, stop_reason: str) -> SelectedTopicResult:
    article_pack = _build_article_pack(
        selected_pillar=item.selected_pillar or item.content_pillar,
        selected_topic=item.selected_topic or item.topic_title,
        why_selected=item.why_selected,
        source_articles=item.source_articles,
        source_domains=item.source_domains,
        keyword_set=item.keyword_set,
        title_candidates=item.title_candidates,
        title_candidate_types=item.title_candidate_types,
    )
    return SelectedTopicResult(
        selected_pillar=item.selected_pillar or item.content_pillar,
        selected_topic=item.selected_topic or item.topic_title,
        why_selected=item.why_selected,
        source_articles=item.source_articles,
        source_count=item.source_count,
        source_domains=item.source_domains,
        keyword_set=item.keyword_set,
        title_candidates=item.title_candidates,
        title_candidate_types=item.title_candidate_types,
        topic_score=item.topic_score,
        article_pack=article_pack,
        source_quality_status=item.source_quality_status,
        discovery_debug=item.discovery_debug,
        raw_candidate_count=item.raw_candidate_count,
        parsed_candidate_count=item.parsed_candidate_count,
        filtered_candidate_count=item.filtered_candidate_count,
        reject_reason_summary=item.reject_reason_summary,
        final_discovery_status=item.final_discovery_status,
        retry_count=item.retry_count,
        retry_path=item.retry_path,
        fallback_strategy_used=item.fallback_strategy_used,
        fallback_pillar_used=item.fallback_pillar_used,
        discovery_attempts=item.discovery_attempts,
        publish_status=item.publish_status,
        stop_reason=stop_reason,
        saved_work_item_id=item.id,
    )


def _discovery_debug_to_dict(debug: DiscoveryDebugSnapshot) -> dict[str, object]:
    payload = asdict(debug)
    payload["source_attempts"] = [asdict(attempt) for attempt in debug.source_attempts]
    return payload


def _build_article_pack(
    *,
    selected_pillar: str,
    selected_topic: str,
    why_selected: str,
    source_articles: list[dict[str, object]],
    source_domains: list[str],
    keyword_set: dict[str, object],
    title_candidates: list[str],
    title_candidate_types: list[str],
) -> dict[str, object]:
    enriched_articles = [_enrich_source_article(article, selected_topic, selected_pillar) for article in source_articles]
    hard_facts = _build_article_pack_hard_facts(enriched_articles)
    source_consensus = _build_article_pack_consensus(enriched_articles, selected_topic)
    source_differences = _build_article_pack_differences(enriched_articles)
    reader_relevance = _build_article_pack_reader_relevance(selected_pillar, selected_topic, keyword_set)
    return {
        "selected_pillar": selected_pillar,
        "selected_topic": selected_topic,
        "why_selected": why_selected,
        "source_articles": enriched_articles,
        "source_domains": source_domains,
        "source_count": len(enriched_articles),
        "keyword_set": keyword_set,
        "search_intent_guess": _article_pack_search_intent(selected_pillar, keyword_set),
        "source_consensus": source_consensus,
        "source_differences": source_differences,
        "hard_facts": hard_facts,
        "reader_relevance": reader_relevance,
        "title_candidates": title_candidates,
        "title_candidate_types": title_candidate_types,
    }


def _enrich_source_article(article: dict[str, object], selected_topic: str, selected_pillar: str) -> dict[str, object]:
    article_url = str(article.get("article_url", ""))
    domain = _domain_from_url(article_url)
    title = str(article.get("title", "")).strip()
    summary = str(article.get("summary", "")).strip()
    published_at = str(article.get("published_at", "") or "")
    enriched = dict(article)
    enriched["domain"] = domain
    enriched["one_line_summary"] = summary or title
    enriched["selection_contribution"] = _selection_contribution_summary(
        title=title,
        summary=summary,
        selected_topic=selected_topic,
        selected_pillar=selected_pillar,
    )
    enriched["freshness_summary"] = _article_freshness_summary(published_at)
    enriched["trustworthiness_summary"] = _article_trust_summary(domain=domain, provider_name=str(article.get("provider_name", "")))
    return enriched


def _build_article_pack_hard_facts(source_articles: list[dict[str, object]]) -> list[str]:
    facts: list[str] = []
    seen: set[str] = set()
    for article in source_articles:
        domain = str(article.get("domain") or _domain_from_url(str(article.get("article_url", ""))))
        title = str(article.get("title", "")).strip()
        summary = str(article.get("one_line_summary", "")).strip()
        published_at = str(article.get("published_at", "") or "")
        published_label = published_at[:10] if published_at else "날짜 미상"
        candidates = [
            f"{published_label} 기준 {domain} 기사: {title}",
            f"{domain} 핵심 요약: {summary}",
        ]
        for item in candidates:
            lowered = item.lower()
            if not item.strip() or lowered in seen:
                continue
            seen.add(lowered)
            facts.append(item)
    return facts[:6]


def _build_article_pack_consensus(source_articles: list[dict[str, object]], selected_topic: str) -> list[str]:
    if not source_articles:
        return []
    first = source_articles[0]
    return [
        f"여러 기사에서 '{selected_topic}'이 단순 화제가 아니라 실제 실행 조건과 연결된다고 본다.",
        f"{first.get('domain') or 'source'}를 포함한 복수 출처가 시간, 비용, 검증 포인트를 같이 확인하라고 말한다.",
    ]


def _build_article_pack_differences(source_articles: list[dict[str, object]]) -> list[str]:
    if len(source_articles) < 2:
        return []
    first = source_articles[0]
    second = source_articles[1]
    return [
        f"{first.get('domain') or '첫 출처'}는 이슈 배경을, {second.get('domain') or '둘째 출처'}는 실행 조건을 더 강하게 다룬다.",
        "출처마다 강조점은 다르지만 공통적으로 막연한 기대보다 숫자와 조건 확인을 우선한다.",
    ]


def _build_article_pack_reader_relevance(
    selected_pillar: str,
    selected_topic: str,
    keyword_set: dict[str, object],
) -> list[str]:
    primary_keyword = str(keyword_set.get("primary_keyword") or "").strip()
    if selected_pillar == ContentPillar.SIDE_HUSTLE_TAX.value:
        return [
            f"{selected_topic}은 바로 수익보다 기록과 신고 기준을 먼저 잡아야 하는 독자에게 직접 연결된다.",
            "세금형 주제는 뉴스가 약한 날에도 실수 비용을 줄이는 실행 가이드로 읽을 가치가 있다.",
        ]
    if selected_pillar in {ContentPillar.KOREAN_STOCK_NEWS.value, ContentPillar.KOREAN_STOCK_BEGINNER.value}:
        return [
            f"{primary_keyword or selected_topic} 관련 기사를 추천주가 아니라 해설형으로 읽고 싶은 독자에게 맞는다.",
            "여러 출처의 공통점과 차이점을 같이 보면 감정적 대응보다 체크리스트 기반 판단이 쉬워진다.",
        ]
    return [
        f"{selected_topic}은 시간, 비용, 수익 범위를 먼저 따져보고 싶은 실행형 독자에게 맞는다.",
        "기사 기반 하드팩트와 실행 단계가 같이 있어 바로 첫 행동으로 옮기기 쉽다.",
    ]


def _article_pack_search_intent(selected_pillar: str, keyword_set: dict[str, object]) -> str:
    primary_keyword = str(keyword_set.get("primary_keyword") or "").strip()
    if selected_pillar == ContentPillar.SIDE_HUSTLE_TAX.value:
        return f"{primary_keyword or '부업 세금'} 기준으로 언제부터 기록하고 신고를 준비해야 하는지 알고 싶다."
    if selected_pillar == ContentPillar.KOREAN_STOCK_NEWS.value:
        return f"{primary_keyword or '한국 주식 이슈'}가 왜 중요한지와 어떤 숫자를 먼저 봐야 하는지 알고 싶다."
    return f"{primary_keyword or '선택 주제'}가 실제로 가능한지 시간, 비용, 실행 순서를 기준으로 알고 싶다."


def _selection_contribution_summary(*, title: str, summary: str, selected_topic: str, selected_pillar: str = "") -> str:
    summary_seed = summary or title
    normalized = re.sub(r"\s+", " ", summary_seed).strip()
    if not normalized:
        return f"{selected_topic} 선택에 기여한 핵심 맥락 기사다."
    clipped = normalized[:90]
    if selected_pillar == ContentPillar.AI_SIDE_HUSTLE.value:
        return f"{clipped} 내용이 AI 수익화/실전성 근거를 보강했다."
    return f"{clipped} 내용이 '{selected_topic}' 선택 근거를 보강했다."


def _article_freshness_summary(published_at: str) -> str:
    if not published_at:
        return "발행 시점 확인 필요"
    age_hours = max((datetime.now(timezone.utc) - _parse_iso(published_at)).total_seconds() / 3600.0, 0.0)
    if age_hours <= 24:
        return f"최근 24시간 내 기사 ({int(age_hours)}시간 전)"
    if age_hours <= 24 * 7:
        return f"최근 7일 내 기사 ({int(age_hours // 24)}일 전)"
    return "상시 참고용 기사"


def _article_trust_summary(*, domain: str, provider_name: str) -> str:
    if any(token in domain for token in [".go.kr", ".or.kr", "openai.com", "google.com", "investopedia.com"]):
        return "공식 또는 준공식 출처 성격이 강함"
    if provider_name:
        return f"{provider_name} 기준으로 수집된 기사"
    return "출처 도메인 기준 기본 검증 통과"


def _increment_counter(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _keyword_hit_score(text: str, keywords: list[str]) -> float:
    return float(sum(1 for keyword in keywords if keyword.lower() in text))


def _single_freshness(article: SourceArticle) -> float:
    if not article.published_at:
        return 58.0
    published = _parse_iso(article.published_at)
    age_hours = max((datetime.now(timezone.utc) - published).total_seconds() / 3600.0, 0.0)
    return max(28.0, 100.0 - math.log1p(age_hours) * 16.0)


def _freshness_reference(article: SourceArticle) -> float:
    return _single_freshness(article)


def _extract_domains(articles: list[SourceArticle]) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for article in articles:
        domain = _domain_from_url(article.article_url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


def _headline_tokens(value: str) -> list[str]:
    normalized = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", value.lower())
    tokens = [token for token in normalized.split() if len(token) >= 2 and token not in STOPWORDS]
    return tokens


def _normalized_token_set(value: str) -> set[str]:
    return set(_headline_tokens(value))


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _pillar_article_relevance(*, article: SourceArticle, pillar_name: str) -> tuple[float, str]:
    text = f"{article.title} {article.summary}".lower()
    rules = PILLAR_RULES[_pillar_enum_from_value(pillar_name)]
    base_score = (
        _keyword_hit_score(text, rules["keywords"]) * 2.0
        + _keyword_hit_score(text, rules["practical_keywords"]) * 1.8
        + _keyword_hit_score(text, rules["attention_keywords"]) * 0.8
    )
    if pillar_name != ContentPillar.AI_SIDE_HUSTLE.value:
        # AI_TOOLS_NEWS: 대형 모델 단순 언급 기사 스킵 (출시/업데이트 키워드 없으면)
        if pillar_name == ContentPillar.AI_TOOLS_NEWS.value:
            has_major_brand = any(brand in text for brand in MAJOR_AI_BRANDS)
            if has_major_brand and not any(kw in text for kw in MAJOR_AI_UPDATE_KEYWORDS):
                return 0.0, "major_brand_mention_only"
        return (max(base_score, 1.0), "")

    monetization_keywords = [
        "monetization",
        "revenue",
        "side hustle",
        "creator",
        "affiliate",
        "income",
        "automation business",
        "workflow",
        "freelancer",
        "agency",
        "blog",
        "adsense",
        "ecommerce",
        "saas",
        "pricing",
        "audience growth",
        "lead generation",
        "content automation",
        "수익",
        "부업",
        "자동화",
        "워크플로",
        "창작자",
        "프리랜서",
        "광고",
        "전자상거래",
        "가격",
    ]
    business_applicability_keywords = [
        "pricing",
        "package",
        "offer",
        "service",
        "client",
        "lead",
        "sales",
        "conversion",
        "blog",
        "agency",
        "freelancer",
        "creator",
        "workflow",
        "automation",
        "adsense",
        "affiliate",
        "ecommerce",
        "saas",
        "서비스",
        "고객",
        "전환",
        "리드",
        "판매",
        "가격",
        "상품",
        "블로그",
        "대행",
    ]
    generic_ai_only = [
        "game development",
        "gaming",
        "allergy",
        "food allergy",
        "recipe",
        "medical",
        "science",
        "research",
        "benchmark",
        "dataset",
        "논문",
        "의료",
        "과학",
        "모델 연구",
        "게임 개발",
        "제품 소개",
        "알러지",
        "음식",
        "요리",
    ]
    monetization_hits = _keyword_hit_score(text, monetization_keywords)
    business_hits = _keyword_hit_score(text, business_applicability_keywords)
    negative_hits = _keyword_hit_score(text, generic_ai_only)
    relevance_score = base_score + monetization_hits * 3.8 + business_hits * 2.4 - negative_hits * 5.0
    if negative_hits >= 1.0 and monetization_hits < 2.0 and business_hits < 2.0:
        return 0.0, "ai_generic_non_business_article"
    if monetization_hits < 1.0 and business_hits < 2.0 and base_score < 3.5:
        return 0.0, "ai_monetization_relevance_low"
    if relevance_score < 6.5:
        return 0.0, "ai_practicality_relevance_low"
    return relevance_score, ""


def _pillar_enum_from_value(value: str) -> ContentPillar:
    for pillar in ContentPillar:
        if pillar.value == value:
            return pillar
    return ContentPillar.AI_SIDE_HUSTLE


def _normalize_url(value: str) -> str:
    compact = value.strip()
    if not compact:
        return ""
    compact = _sanitize_feed_url(compact)
    parsed = urlparse(compact)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return compact


def _sanitize_feed_url(value: str) -> str:
    sanitized = value.strip()
    if "rss.mk.co.kr/rss/" in sanitized:
        sanitized = sanitized.replace("https://rss.mk.co.kr/rss/", "https://www.mk.co.kr/rss/")
        sanitized = sanitized.replace("http://rss.mk.co.kr/rss/", "https://www.mk.co.kr/rss/")
    return sanitized


def _feed_url_sanity_error(value: str) -> str:
    normalized = _normalize_url(value)
    if not normalized:
        return "feed_url_sanity_check_failed: invalid url"
    domain = _domain_from_url(normalized)
    if _is_placeholder_url(normalized):
        return "feed_url_sanity_check_failed: placeholder url"
    if "mk.co.kr" in domain and "/rss/" not in urlparse(normalized).path:
        return "feed_url_sanity_check_failed: malformed mk rss path"
    return ""


def _domain_from_url(value: str) -> str:
    parsed = urlparse(value)
    return parsed.netloc.lower()


def _is_placeholder_url(value: str) -> bool:
    domain = _domain_from_url(value)
    return any(token in domain for token in PLACEHOLDER_HOST_TOKENS)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    import html
    value = html.unescape(value)
    value = value.replace("\xa0", " ").replace("&nbsp;", " ").replace("nbsp", " ")
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def _normalize_published_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _parse_iso(value).isoformat()
    except ValueError:
        return None


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _text_or_empty(element: ElementTree.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _text_or_none(element: ElementTree.Element | None) -> str | None:
    value = _text_or_empty(element)
    return value or None


def _enrich_articles_with_body(articles: list[SourceArticle], *, limit: int = 3, max_chars: int = 3000) -> None:
    """상위 N개 기사 URL을 크롤링해서 summary를 본문으로 교체한다. 실패하면 기존 summary 유지."""
    from blogspot_automation.topic_discovery.fetcher import fetch_article_body
    crawled = 0
    for article in articles:
        if crawled >= limit:
            break
        if not article.article_url.startswith("http"):
            continue
        body = fetch_article_body(article.article_url, timeout=10, max_chars=max_chars)
        if body:
            article.summary = body
            logger.debug("article body crawled (%d chars): %s", len(body), article.article_url)
        crawled += 1


def _rss_item_to_article(
    item: ElementTree.Element,
    *,
    provider_name: str,
    source_url: str,
) -> SourceArticle | None:
    title = _text_or_empty(item.find("title"))
    summary = _text_or_empty(item.find("description"))
    article_url = _text_or_empty(item.find("link"))
    published_at = _text_or_none(item.find("pubDate"))
    if not title or not article_url:
        return None
    # Product Hunt: name 필드 우선 파싱, 없으면 title에서 제품명 추출
    if "producthunt.com" in (source_url or ""):
        ph_name = _text_or_empty(item.find("name"))
        if ph_name:
            title = ph_name
        elif " - " in title:
            title = title.split(" - ", 1)[0].strip()
    return SourceArticle(
        provider_name=provider_name,
        source_url=source_url,
        title=title,
        summary=summary,
        article_url=article_url,
        published_at=published_at,
    )


def _atom_entry_to_article(
    entry: ElementTree.Element,
    *,
    provider_name: str,
    source_url: str,
) -> SourceArticle | None:
    ns = "{http://www.w3.org/2005/Atom}"
    title = _text_or_empty(entry.find(f"{ns}title"))
    summary = _text_or_empty(entry.find(f"{ns}summary")) or _text_or_empty(entry.find(f"{ns}content"))
    link = entry.find(f"{ns}link")
    article_url = ""
    if link is not None:
        article_url = (link.attrib.get("href") or "").strip()
    if not article_url:
        article_url = _text_or_empty(entry.find(f"{ns}id"))
    published_at = _text_or_none(entry.find(f"{ns}published")) or _text_or_none(entry.find(f"{ns}updated"))
    if not title or not article_url:
        return None
    return SourceArticle(
        provider_name=provider_name,
        source_url=source_url,
        title=title,
        summary=summary,
        article_url=article_url,
        published_at=published_at,
    )
