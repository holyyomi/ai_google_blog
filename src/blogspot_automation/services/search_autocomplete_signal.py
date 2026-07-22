"""Google Autocomplete(제안 검색어) 기반 실검색 수요 신호.

배경(2026-07-22): 2026-07-21 발행 2건("AI Assistant Pricing Compared",
"ChatGPT Gemini Copilot Student Pricing")은 둘 다 evergreen_fallback이었고,
에버그린 후보에는 수요 신호가 전혀 없어 뱅크 정렬 순서대로 뽑혔다 — 그 결과
같은 날 가격비교 축 2건이 연속 발행됐다. Google Trends RSS(일일 급상승)는
"오늘 폭발한 이슈"만 잡고, 에버그린 주제("chatgpt pricing" 등)의 상시 검색
수요는 측정하지 못한다.

Google Autocomplete(suggestqueries)는 키 불필요·무과금이며, 어떤 질의에
자동완성 제안이 몇 개나 붙는지가 그 주제의 상시 검색 수요에 대한 실측
프록시가 된다(실측 2026-07-22: "chatgpt pricing" 10건, "claude vs chatgpt"
10건 — 제안이 많을수록 실제로 많이 검색되는 질의).

ENABLE_SEARCH_AUTOCOMPLETE_SIGNAL=false로 끈다. 네트워크 실패는 전부
비치명 — 빈 결과를 돌려주고 호출부는 "신호 없음"으로 폴백한다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from urllib import error, parse, request

logger = logging.getLogger(__name__)

_SUGGEST_URL_TEMPLATE = (
    "https://suggestqueries.google.com/complete/search?client=firefox&hl={hl}&gl={gl}&q={q}"
)
_FETCH_TIMEOUT_SECONDS = 6
_USER_AGENT = "Mozilla/5.0 (compatible; blogspot-automation/1.0)"
_CACHE_TTL_SECONDS = 3600
# 프로세스당 네트워크 호출 상한 — 후보가 아무리 많아도 폭주하지 않는다.
_MAX_FETCHES_PER_PROCESS = 24

# 프로브 질의에서 버리는 토큰 — 연도/불용어는 자동완성 매칭을 방해한다.
_PROBE_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with",
    "best", "top", "guide", "how", "what", "why", "your", "you",
    "2024", "2025", "2026", "2027",
})


def is_signal_enabled() -> bool:
    # pytest 아래 자동 비활성 — 통합 테스트가 후보마다 실 HTTP를 쏘지 않게 한다.
    # (신호 자체의 단위 테스트는 PYTEST_CURRENT_TEST를 지우고 fetch를 패치한다.)
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    raw = (os.getenv("ENABLE_SEARCH_AUTOCOMPLETE_SIGNAL", "true") or "").strip().lower()
    return raw not in {"false", "0", "no", "off"}


def _locale() -> tuple[str, str]:
    lang = (os.getenv("BLOG_LANGUAGE", "ko") or "ko").strip().lower()
    return ("en", "us") if lang == "en" else ("ko", "kr")


def build_probe_query(topic_text: str, *, max_tokens: int = 4) -> str:
    """주제 문자열에서 자동완성 프로브용 핵심 질의를 만든다.

    "AI assistant pricing and limits comparison" → "ai assistant pricing"처럼
    불용어·연도를 걷어낸 앞쪽 핵심 토큰만 남긴다 — 자동완성은 짧은 머리 질의에
    제안이 붙는 구조라 문장 전체로 조회하면 항상 0건이 나온다.
    """
    tokens = re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣.\-]*", (topic_text or "").lower())
    picked = [t for t in tokens if t not in _PROBE_STOPWORDS]
    return " ".join(picked[:max_tokens]).strip()


class SearchAutocompleteSignal:
    """suggestqueries 자동완성 제안 수 기반 수요 스코어러 (프로세스 캐시)."""

    _lock = threading.Lock()
    _cache: dict[str, tuple[float, tuple[str, ...]]] = {}
    _fetch_count = 0

    @classmethod
    def reset_cache(cls) -> None:
        with cls._lock:
            cls._cache = {}
            cls._fetch_count = 0

    @classmethod
    def suggestions_for(cls, query: str) -> tuple[str, ...]:
        query = (query or "").strip().lower()
        if not query or not is_signal_enabled():
            return ()
        now = time.time()
        with cls._lock:
            hit = cls._cache.get(query)
            if hit and (now - hit[0]) < _CACHE_TTL_SECONDS:
                return hit[1]
            if cls._fetch_count >= _MAX_FETCHES_PER_PROCESS:
                return ()
            cls._fetch_count += 1
        fetched = _fetch_suggestions(query)
        with cls._lock:
            cls._cache[query] = (now, fetched)
        return fetched

    @classmethod
    def score_topic_demand(cls, topic_text: str, *, max_boost: int = 12) -> tuple[int, list[str]]:
        """(수요 부스트, 근거 제안어 목록)을 돌려준다.

        제안 수 → 부스트 매핑은 보수적으로: 제안이 아예 없으면 0(수요 근거
        없음), 1~2건이면 낮은 수요, 8건 이상(자동완성 슬롯 포화)이면 강한
        상시 수요로 본다. max_boost로 기존 스코어 체계를 지배하지 않게 캡.
        """
        probe = build_probe_query(topic_text)
        if not probe or len(probe) < 4:
            return 0, []
        suggestions = cls.suggestions_for(probe)
        distinct = [s for s in suggestions if s.strip().lower() != probe]
        count = len(distinct)
        if count >= 8:
            boost = max_boost
        elif count >= 5:
            boost = max(1, (max_boost * 2) // 3)
        elif count >= 2:
            boost = max(1, max_boost // 3)
        elif count >= 1:
            boost = max(1, max_boost // 6)
        else:
            return 0, []
        return min(boost, max_boost), [f"autocomplete:{probe}({count})", *distinct[:3]]


def score_topic_boost(topic_text: str, *, max_boost: int = 12) -> tuple[int, list[str]]:
    """모듈 레벨 래퍼 — google_trends_signal/community_topic_service와 동일 관례."""
    return SearchAutocompleteSignal.score_topic_demand(topic_text, max_boost=max_boost)


def _fetch_suggestions(query: str) -> tuple[str, ...]:
    hl, gl = _locale()
    url = _SUGGEST_URL_TEMPLATE.format(hl=hl, gl=gl, q=parse.quote(query))
    req = request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        raw = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        return tuple(str(s).strip() for s in raw if str(s).strip())[:10]
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, IndexError) as exc:
        logger.warning("autocomplete fetch failed (non-fatal): %s", exc)
        return ()
    except Exception as exc:  # noqa: BLE001 — 수요 신호 실패는 항상 비치명
        logger.warning("autocomplete fetch unexpected error (non-fatal): %s", exc)
        return ()
