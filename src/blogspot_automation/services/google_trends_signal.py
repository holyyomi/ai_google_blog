"""Google Trends trending keyword signal.

Fetches the daily-trending RSS feed for the blog's target market, parses
keyword + approximate
traffic, caches the result for an hour, and exposes a boost helper that scoring
services can call when ranking candidate topics.

The user explicitly asked for trending-driven topic selection
(feedback_blogspot_content_preferences memory: "오늘 가장 많이 클릭된 뉴스
원함, source_count != 실제 클릭률"). This signal augments the existing
NewsScoringService score with an additive boost when a candidate's title or
search-demand topic overlaps with current Google Trends entries.

Disabled via ENABLE_GOOGLE_TRENDS_SIGNAL=false. When the RSS fetch fails the
service silently returns an empty keyword list — callers should treat it as
"no signal available" and fall through to base scoring.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib import error, request


logger = logging.getLogger(__name__)


# Google Trends RSS는 국가 단위만 지원한다(글로벌 피드 없음). 영어 블로그는
# 영어권 최대 검색 시장인 US를 글로벌 프록시로 쓰고, 한국어 모드는 기존 KR 유지.
# GOOGLE_TRENDS_GEO / GOOGLE_TRENDS_HL env로 오버라이드 가능.
_FEED_URL_TEMPLATE = "https://trends.google.com/trending/rss?geo={geo}&hl={hl}"


def _feed_url() -> str:
    lang = (os.getenv("BLOG_LANGUAGE", "ko") or "ko").strip().lower()
    default_geo, default_hl = ("US", "en-US") if lang == "en" else ("KR", "ko")
    geo = (os.getenv("GOOGLE_TRENDS_GEO", "") or "").strip() or default_geo
    hl = (os.getenv("GOOGLE_TRENDS_HL", "") or "").strip() or default_hl
    return _FEED_URL_TEMPLATE.format(geo=geo, hl=hl)
_DEFAULT_TTL_SECONDS = 3600
_FETCH_TIMEOUT_SECONDS = 12
_USER_AGENT = "Mozilla/5.0 (compatible; blogspot-automation/1.0)"


@dataclass(frozen=True, slots=True)
class TrendingKeyword:
    keyword: str
    approx_traffic: str
    related_news_titles: tuple[str, ...]


def is_signal_enabled() -> bool:
    raw = (os.getenv("ENABLE_GOOGLE_TRENDS_SIGNAL", "true") or "").strip().lower()
    return raw not in {"false", "0", "no", "off"}


class GoogleTrendsSignal:
    """Cached fetcher for Korea daily trending RSS feed."""

    _lock = threading.Lock()
    _cache: list[TrendingKeyword] = []
    _cached_at: float = 0.0
    _ttl_seconds: int = _DEFAULT_TTL_SECONDS

    @classmethod
    def get_trending_keywords(cls, *, force_refresh: bool = False) -> list[TrendingKeyword]:
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
        fetched = _fetch_and_parse(_feed_url())
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
    def score_topic_boost(cls, topic_text: str, *, max_boost: int = 20) -> tuple[int, list[str]]:
        """Return (score_boost, matched_keywords) for a candidate topic string.

        Each trending keyword match adds a base of 8 with an extra bump when
        approx_traffic indicates a high search volume (1000+, 10000+, 100000+).
        max_boost caps the total contribution to avoid completely dominating
        the existing scoring system.
        """
        text = (topic_text or "").strip()
        if not text:
            return 0, []
        keywords = cls.get_trending_keywords()
        if not keywords:
            return 0, []
        matched: list[str] = []
        boost = 0
        text_lower = text.lower()
        for kw in keywords:
            if not kw.keyword:
                continue
            # 영어 트렌드 키워드는 대소문자가 제각각이라 case-insensitive 비교.
            # 3자 미만 키워드("AI" 등)는 substring 오탐이 커서 제외한다.
            keyword_lower = kw.keyword.strip().lower()
            if len(keyword_lower) < 3:
                continue
            if keyword_lower in text_lower:
                matched.append(kw.keyword)
                boost += 8 + _traffic_bonus(kw.approx_traffic)
                if boost >= max_boost:
                    break
        return min(boost, max_boost), matched


def _traffic_bonus(approx_traffic: str) -> int:
    digits = "".join(ch for ch in (approx_traffic or "") if ch.isdigit())
    if not digits:
        return 0
    try:
        value = int(digits)
    except ValueError:
        return 0
    if value >= 100_000:
        return 12
    if value >= 10_000:
        return 8
    if value >= 1_000:
        return 4
    return 0


def _fetch_and_parse(url: str) -> list[TrendingKeyword]:
    req = request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        logger.warning("google_trends fetch failed: %s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("google_trends fetch unexpected error: %s", exc)
        return []
    return _parse_rss(body)


def _parse_rss(body: str) -> list[TrendingKeyword]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        logger.warning("google_trends RSS parse failed: %s", exc)
        return []
    items = root.findall(".//item")
    parsed: list[TrendingKeyword] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        approx_traffic = ""
        related: list[str] = []
        for child in item:
            tag = child.tag.split("}")[-1]
            if tag == "approx_traffic":
                approx_traffic = (child.text or "").strip()
            elif tag == "news_item":
                for sub in child:
                    stag = sub.tag.split("}")[-1]
                    if stag == "news_item_title":
                        text = (sub.text or "").strip()
                        if text:
                            related.append(text[:120])
        parsed.append(
            TrendingKeyword(
                keyword=title,
                approx_traffic=approx_traffic,
                related_news_titles=tuple(related),
            )
        )
    return parsed
