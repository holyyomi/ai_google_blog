"""Community topic signal — "지금 사람들이 가장 많이 이야기하는 AI 주제" 수집기.

Reddit(hot.json, 키 불필요)과 Hacker News(Algolia search API, 키 불필요)에서
최근 48시간 내 화제가 된 AI 관련 글을 모아 CommunityTopic으로 정규화한다.
뉴스 파이프라인 스코어링이 GoogleTrendsSignal과 같은 방식으로
score_topic_boost()를 호출해 커뮤니티 화제성 부스트를 얹을 수 있다.

구조는 google_trends_signal.py를 그대로 따른다:
- 모듈 캐시 + TTL(1800s) + threading.Lock
- env 킬스위치 ENABLE_COMMUNITY_TOPIC_SIGNAL (기본 true)
- 네트워크 실패 시 logger.warning 후 빈 리스트 — 호출자에게 절대 예외를 던지지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from urllib import error, parse, request


logger = logging.getLogger(__name__)


_USER_AGENT = "blogspot-automation/1.0 (holyyomiai.blogspot.com)"
_FETCH_TIMEOUT_SECONDS = 10
_DEFAULT_TTL_SECONDS = 1800
_MAX_AGE_SECONDS = 48 * 3600
_MIN_TITLE_LENGTH = 20

_REDDIT_URL_TEMPLATE = "https://www.reddit.com/r/{sub}/hot.json?limit=25&raw_json=1"
_DEFAULT_REDDIT_SUBS = ("ChatGPT", "OpenAI", "ClaudeAI", "artificial", "LocalLLaMA", "singularity")
# COMMUNITY_REDDIT_SUBS에 이 값을 주면 Reddit만 끄고 HN 신호는 유지한다.
_REDDIT_DISABLED_TOKENS = {"off", "none", "-", "false", "0", "disabled"}
# Reddit이 차단(403/429)으로 응답하면 프로세스 수명 동안 재호출하지 않는다.
# 2026-07 실측: 6개 서브레딧 × 재시도 6회 = 실행당 약 40회가 전부 403이었다.
_REDDIT_BLOCKED_STATUSES = {401, 403, 429}
_REDDIT_BREAKER: dict[str, bool] = {"tripped": False}
# _http_get_json이 마지막 실패의 HTTP 상태코드를 남기는 옆 채널 (아래 주석 참고).
_LAST_HTTP_STATUS: dict[str, int | None] = {"code": None}

# 모듈 레벨 TTL 캐시 — collect_community_topics()가 직접 사용한다(아래 주석 참고).
_MODULE_CACHE_LOCK = threading.Lock()
_MODULE_CACHE: dict[str, object] = {"topics": None, "cached_at": 0.0}

_HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
_HN_QUERIES = ("AI", "GPT", "Claude", "Gemini", "LLM", "OpenAI")
_HN_MIN_POINTS = 40

# AI 관련성 필터 — 제목(lowercase, 양끝 공백 패딩)에 아래 substring이 하나라도
# 있으면 AI 주제로 간주한다. " ai "처럼 공백 포함 항목은 단어 경계 오탐
# (brain, chair 등)을 막기 위한 것이다.
AI_RELEVANCE_TERMS: tuple[str, ...] = (
    "chatgpt",
    "gpt",
    "openai",
    "claude",
    "anthropic",
    "gemini",
    "google ai",
    "llm",
    "copilot",
    "cursor",
    "midjourney",
    "stable diffusion",
    " ai ",
    " ai,",
    " ai.",
    " ai?",
    " ai:",
    "artificial intelligence",
    "machine learning",
    "deepseek",
    "mistral",
    "llama",
    "grok",
    "xai",
    "perplexity",
    "nvidia",
    "hugging face",
    "agent",
    "prompt",
    "diffusion model",
    "neural net",
    "genai",
    "gen ai",
)

# score_topic_boost용 — len>=4 토큰만 매칭하지만, 흔한 영어 기능어는 화제성과
# 무관하게 어느 제목에나 나와 오탐 부스트를 만들기 때문에 제외한다.
_BOOST_STOPWORDS = frozenset(
    {
        "with", "this", "that", "from", "what", "when", "your", "have",
        "will", "just", "about", "they", "been", "more", "like", "into",
        "than", "them", "then", "some", "over", "after", "before", "here",
        "there", "were", "does", "much", "many", "very", "only", "also",
        "make", "made", "using", "used", "uses", "most", "best", "still",
        "even", "every", "should", "could", "would", "which", "where",
        "how", "why", "who", "you", "and", "the", "for", "are", "but",
        "not", "all", "can", "its", "our", "out", "now", "new", "get",
        "why", "really", "think", "know", "want", "need", "people",
    }
)


@dataclass(frozen=True, slots=True)
class CommunityTopic:
    title: str
    url: str
    source: str  # "reddit:ChatGPT" / "hackernews"
    mention_score: int
    comments: int
    created_utc: float


def is_signal_enabled() -> bool:
    raw = (os.getenv("ENABLE_COMMUNITY_TOPIC_SIGNAL", "true") or "").strip().lower()
    return raw not in {"false", "0", "no", "off"}


def _reddit_subs() -> tuple[str, ...]:
    """Reddit 서브레딧 목록. 명시적 비활성 토큰이면 빈 튜플(=Reddit만 끄고 HN 유지).

    2026-08-03: 기존에는 빈 문자열이면 기본 6개로 되돌아가서 env만으로 Reddit을
    끌 방법이 없었다(ENABLE_COMMUNITY_TOPIC_SIGNAL은 HN까지 같이 죽인다).
    Reddit이 403 Blocked로 100% 실패하는 상황에서 HN 신호만 살리려면
    COMMUNITY_REDDIT_SUBS=off 로 둘 수 있어야 한다.
    """
    raw = (os.getenv("COMMUNITY_REDDIT_SUBS", "") or "").strip()
    if raw.lower() in _REDDIT_DISABLED_TOKENS:
        return ()
    if not raw:
        return _DEFAULT_REDDIT_SUBS
    subs = tuple(part.strip() for part in raw.split(",") if part.strip())
    return subs or _DEFAULT_REDDIT_SUBS


def collect_community_topics(
    max_items: int = 30, *, force_refresh: bool = False
) -> list[CommunityTopic]:
    """Reddit + HN을 합쳐 AI 관련·48h 이내·중복 제거된 화제 목록을 반환한다.

    mention_score 내림차순 정렬, 어떤 실패에서도 예외 없이 [] 또는 부분 결과.

    2026-08-03: 모듈 레벨 TTL 캐시를 여기 직접 붙였다. news_pipeline이 이 모듈
    함수를 직접 호출해 CommunityTopicSignal의 클래스 캐시를 우회하는데,
    run_with_retries가 run_once를 최대 6회 돌리므로 같은 sweep(Reddit 6 + HN 6
    = 12회 HTTP)이 실행당 6번 반복됐다. 캐시를 호출부가 아니라 이 함수에 두면
    호출부 수정 없이 중복이 사라진다.
    """
    if not is_signal_enabled():
        return []
    cached = _get_cached_topics(force_refresh=force_refresh)
    if cached is not None:
        return cached[: max(0, max_items)]
    now = time.time()
    merged = _fetch_reddit_topics(now) + _fetch_hn_topics(now)
    relevant = [topic for topic in merged if is_ai_relevant(topic.title)]
    deduped = _dedupe_topics(relevant)
    _store_cached_topics(deduped)
    return deduped[: max(0, max_items)]


def _get_cached_topics(*, force_refresh: bool) -> list[CommunityTopic] | None:
    if force_refresh:
        return None
    with _MODULE_CACHE_LOCK:
        if _MODULE_CACHE["topics"] is None:
            return None
        if (time.time() - _MODULE_CACHE["cached_at"]) >= _DEFAULT_TTL_SECONDS:
            return None
        return list(_MODULE_CACHE["topics"])


def _store_cached_topics(topics: list[CommunityTopic]) -> None:
    # 빈 결과도 캐시한다 — 전부 실패한 실행에서 6번 재시도하는 것이 정확히
    # 이번에 고치려는 낭비다. TTL이 지나면 자연히 재시도된다.
    with _MODULE_CACHE_LOCK:
        _MODULE_CACHE["topics"] = list(topics)
        _MODULE_CACHE["cached_at"] = time.time()


def reset_community_topic_cache() -> None:
    """테스트/강제 갱신용 — 모듈 캐시와 Reddit 회로차단 상태를 함께 초기화한다."""
    with _MODULE_CACHE_LOCK:
        _MODULE_CACHE["topics"] = None
        _MODULE_CACHE["cached_at"] = 0.0
    _REDDIT_BREAKER["tripped"] = False


def is_ai_relevant(title: str) -> bool:
    padded = f" {(title or '').strip().lower()} "
    return any(term in padded for term in AI_RELEVANCE_TERMS)


class CommunityTopicSignal:
    """Cached community-topic fetcher + scoring boost helper.

    GoogleTrendsSignal과 동일한 클래스 구조(모듈 캐시·락·kill-switch)를 쓴다.
    """

    _lock = threading.Lock()
    _cache: list[CommunityTopic] = []
    _cached_at: float = 0.0
    _ttl_seconds: int = _DEFAULT_TTL_SECONDS

    @classmethod
    def get_topics(cls, *, force_refresh: bool = False) -> list[CommunityTopic]:
        if not is_signal_enabled():
            return []
        now = time.time()
        with cls._lock:
            cache_fresh = (
                cls._cache
                and not force_refresh
                and (now - cls._cached_at) < cls._ttl_seconds
            )
            if cache_fresh:
                return list(cls._cache)
        fetched = collect_community_topics()
        with cls._lock:
            if fetched:
                cls._cache = list(fetched)
                cls._cached_at = now
        return fetched

    @classmethod
    def reset_cache(cls) -> None:
        with cls._lock:
            cls._cache = []
            cls._cached_at = 0.0

    @classmethod
    def score_topic_boost(cls, topic_text: str, *, max_boost: int = 15) -> tuple[int, list[str]]:
        """Return (score_boost, matched_tokens) for a candidate topic string.

        커뮤니티 글 제목의 유의미 토큰(len>=4, 기능어 제외)이 topic_text에
        나타나면 그 글의 mention_score 등급에 따라 +5/+8/+12를 더한다.
        (>=500 → +12, >=200 → +8, 그 외 +5). 총합은 max_boost로 캡.
        """
        text_tokens = _significant_tokens(topic_text or "")
        if not text_tokens:
            return 0, []
        topics = cls.get_topics()
        if not topics:
            return 0, []
        matched: list[str] = []
        seen_tokens: set[str] = set()
        boost = 0
        for topic in topics:
            hits = _significant_tokens(topic.title) & text_tokens
            if not hits:
                continue
            if topic.mention_score >= 500:
                boost += 12
            elif topic.mention_score >= 200:
                boost += 8
            else:
                boost += 5
            for token in sorted(hits):
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    matched.append(token)
            if boost >= max_boost:
                break
        return min(boost, max_boost), matched


def score_topic_boost(topic_text: str, *, max_boost: int = 15) -> tuple[int, list[str]]:
    """모듈 함수 편의 래퍼 — CommunityTopicSignal.score_topic_boost와 동일."""
    return CommunityTopicSignal.score_topic_boost(topic_text, max_boost=max_boost)


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _significant_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {tok for tok in tokens if len(tok) >= 4 and tok not in _BOOST_STOPWORDS}


def _title_tokens(title: str) -> frozenset[str]:
    """중복 판정용 정규화 토큰 집합 (3자 미만 토큰은 잡음이라 제외)."""
    return frozenset(
        tok for tok in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(tok) >= 3
    )


def _is_duplicate_title(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    overlap = len(a & b) / min(len(a), len(b))
    return overlap >= 0.8


def _dedupe_topics(topics: list[CommunityTopic]) -> list[CommunityTopic]:
    """제목 토큰 overlap >= 0.8이면 중복 — mention_score 높은 쪽을 남긴다."""
    ordered = sorted(topics, key=lambda t: t.mention_score, reverse=True)
    kept: list[CommunityTopic] = []
    kept_tokens: list[frozenset[str]] = []
    for topic in ordered:
        tokens = _title_tokens(topic.title)
        if any(_is_duplicate_title(tokens, prev) for prev in kept_tokens):
            continue
        kept.append(topic)
        kept_tokens.append(tokens)
    return kept


def _http_get_json(url: str) -> dict | None:
    """HTTP GET → dict. 실패 시 None.

    실패의 HTTP 상태코드는 `_LAST_HTTP_STATUS`에 남긴다 — 반환 시그니처를
    바꾸면 이 함수를 가짜 응답으로 치환하는 기존 테스트 seam이 깨지기 때문에,
    seam은 그대로 두고 상태만 옆 채널로 전달한다. (테스트가 이 함수를 통째로
    치환하면 상태는 None으로 남아 회로차단이 발동하지 않는다 — 의도된 동작.)
    """
    _LAST_HTTP_STATUS["code"] = None
    req = request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
    except error.HTTPError as exc:
        _LAST_HTTP_STATUS["code"] = getattr(exc, "code", None)
        logger.warning("community_topic fetch failed (%s): %s", url, exc)
        return None
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("community_topic fetch failed (%s): %s", url, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("community_topic fetch unexpected error (%s): %s", url, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _fetch_reddit_topics(now: float) -> list[CommunityTopic]:
    """Reddit sweep. 차단 응답(403 등)을 한 번 받으면 남은 서브레딧과
    이후 모든 호출을 건너뛴다 — 되살아날 성질의 실패가 아니기 때문이다.

    5xx·타임아웃은 일시 장애일 수 있으므로 회로를 내리지 않는다(다음 후보에서
    회복될 수 있다). HN은 이 회로와 무관하게 계속 돈다.
    """
    if _REDDIT_BREAKER["tripped"]:
        return []
    topics: list[CommunityTopic] = []
    for sub in _reddit_subs():
        payload = _http_get_json(_REDDIT_URL_TEMPLATE.format(sub=sub))
        if payload is None:
            if _LAST_HTTP_STATUS["code"] in _REDDIT_BLOCKED_STATUSES:
                _REDDIT_BREAKER["tripped"] = True
                logger.warning(
                    "community_topic: Reddit HTTP %s — 이번 프로세스 동안 Reddit 수집을 중단한다"
                    " (HN 신호는 계속 사용). 영구화하려면 COMMUNITY_REDDIT_SUBS=off",
                    _LAST_HTTP_STATUS["code"],
                )
                break
            continue
        topics.extend(_parse_reddit_payload(payload, sub, now))
    return topics


def _parse_reddit_payload(payload: dict, sub: str, now: float) -> list[CommunityTopic]:
    topics: list[CommunityTopic] = []
    children = (payload.get("data") or {}).get("children") or []
    for child in children:
        if not isinstance(child, dict):
            continue
        data = child.get("data") or {}
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        if len(title) < _MIN_TITLE_LENGTH:
            continue
        if data.get("stickied"):
            continue
        try:
            created_utc = float(data.get("created_utc") or 0.0)
        except (TypeError, ValueError):
            continue
        if created_utc <= 0 or (now - created_utc) > _MAX_AGE_SECONDS:
            continue
        try:
            score = int(data.get("score") or 0)
            num_comments = int(data.get("num_comments") or 0)
        except (TypeError, ValueError):
            score, num_comments = 0, 0
        permalink = str(data.get("permalink") or "").strip()
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        topics.append(
            CommunityTopic(
                title=title,
                url=url,
                source=f"reddit:{sub}",
                # 댓글은 토론 열기를 나타내므로 2배 가중.
                mention_score=score + 2 * num_comments,
                comments=num_comments,
                created_utc=created_utc,
            )
        )
    return topics


def _fetch_hn_topics(now: float) -> list[CommunityTopic]:
    cutoff = int(now) - _MAX_AGE_SECONDS
    topics: list[CommunityTopic] = []
    seen_ids: set[str] = set()
    for query in _HN_QUERIES:
        params = parse.urlencode(
            {
                "query": query,
                "tags": "story",
                "numericFilters": f"created_at_i>{cutoff},points>{_HN_MIN_POINTS}",
            }
        )
        payload = _http_get_json(f"{_HN_SEARCH_URL}?{params}")
        if payload is None:
            continue
        topics.extend(_parse_hn_payload(payload, now, seen_ids))
    return topics


def _parse_hn_payload(payload: dict, now: float, seen_ids: set[str]) -> list[CommunityTopic]:
    topics: list[CommunityTopic] = []
    for hit in payload.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        object_id = str(hit.get("objectID") or "").strip()
        if not object_id or object_id in seen_ids:
            continue
        title = str(hit.get("title") or "").strip()
        if len(title) < _MIN_TITLE_LENGTH:
            continue
        try:
            created_utc = float(hit.get("created_at_i") or 0.0)
        except (TypeError, ValueError):
            continue
        # API numericFilters가 이미 48h를 거르지만, 응답을 신뢰하지 않고 재검증.
        if created_utc <= 0 or (now - created_utc) > _MAX_AGE_SECONDS:
            continue
        try:
            points = int(hit.get("points") or 0)
            num_comments = int(hit.get("num_comments") or 0)
        except (TypeError, ValueError):
            points, num_comments = 0, 0
        url = str(hit.get("url") or "").strip()
        if not url:
            url = f"https://news.ycombinator.com/item?id={object_id}"
        seen_ids.add(object_id)
        topics.append(
            CommunityTopic(
                title=title,
                url=url,
                source="hackernews",
                mention_score=points + 2 * num_comments,
                comments=num_comments,
                created_utc=created_utc,
            )
        )
    return topics
