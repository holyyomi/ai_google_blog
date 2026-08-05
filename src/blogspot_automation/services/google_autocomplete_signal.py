"""Google Autocomplete real-search-demand signal.

2026-08-05 사용자 지시("사람들이 더 많이 검색하고 궁금해하고 알고싶어하는
내용으로 주제를 골라라, API가 있으면 API로 실측하라") 대응. 이 프로젝트의
한국어 자매 블로그(네이버 AI)는 "신모델명 자체를 자동완성에 직접 넣어
실검색 수요를 실측"하는 게이트로 주제선정 실패를 고쳤다(그쪽 교훈 #17·#20).
같은 방법을 영어 파이프라인에 이식한 것이 이 모듈이다.

방법: 후보 제목에서 구체적 제품/모델 구문("GPT-5.6", "Gemini Robotics 2"
같은 대문자+버전 형태)을 뽑아 Google Autocomplete(suggestqueries — 무료,
키 불필요)에 넣고, 그 구문을 포함한 제안이 실제로 돌아오는 개수를 센다.
제안이 있다는 것은 지금 실제 사용자들이 그 이름을 검색창에 치고 있다는
직접 증거다. 브랜드 단독명("ChatGPT")은 항상 제안이 가득하므로 probing
대상에서 제외한다 — 그걸 넣으면 대형 브랜드 편중(GPT 쏠림)을 오히려
강화한다. 구체 구문만 잰다.

GoogleTrendsSignal과 동일한 계약: 실패는 조용히 0점(신호 없음)으로
떨어지고, ENABLE_GOOGLE_AUTOCOMPLETE_SIGNAL=false로 끌 수 있다.
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

_ENDPOINT = "https://suggestqueries.google.com/complete/search?client=firefox&hl={hl}&q={q}"
_FETCH_TIMEOUT_SECONDS = 6
_CACHE_TTL_SECONDS = 3600
_USER_AGENT = "Mozilla/5.0 (compatible; blogspot-automation/1.0)"

# 대문자 시작 토큰이 이어지는 구문 + 붙는 버전 숫자("Qwen 3.5", "GPT-5.6 Sol").
_PHRASE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*|\d[\w.]*)){0,2})\b"
)
# 문장 첫 단어가 대문자라서 걸리는 일반 영어 표현 배제.
_STOP_HEAD_WORDS = {
    "the", "a", "an", "how", "what", "why", "when", "where", "who", "which",
    "this", "that", "these", "those", "is", "are", "was", "were", "do", "does",
    "can", "will", "should", "here", "there", "new", "best", "top", "free",
    "your", "you", "it", "its", "his", "her", "their", "our", "my", "us",
}
# 브랜드 단독명 — 항상 자동완성이 가득해서 신호가 아니라 소음이다. 이 목록에
# 있는 "한 단어짜리" probe는 버린다("ChatGPT Atlas"처럼 뒤에 뭐가 붙으면 유효).
_BARE_BRAND_TERMS = {
    "chatgpt", "openai", "gpt", "claude", "anthropic", "gemini", "google",
    "copilot", "microsoft", "grok", "xai", "nvidia", "meta", "llama",
    "deepseek", "mistral", "midjourney", "perplexity", "qwen", "alibaba",
    "ai", "apple", "amazon", "alexa",
}


def is_signal_enabled() -> bool:
    raw = (os.getenv("ENABLE_GOOGLE_AUTOCOMPLETE_SIGNAL", "true") or "").strip().lower()
    return raw not in {"false", "0", "no", "off"}


class GoogleAutocompleteSignal:
    """Cached Google Autocomplete prober for candidate topic phrases."""

    _lock = threading.Lock()
    _cache: dict[str, tuple[float, list[str]]] = {}

    @classmethod
    def extract_probe_phrases(cls, text: str, *, limit: int = 3) -> list[str]:
        """제목에서 자동완성에 넣을 구체 구문을 뽑는다 (브랜드 단독명 제외)."""
        if not text:
            return []
        phrases: list[str] = []
        seen: set[str] = set()
        for match in _PHRASE_PATTERN.finditer(text):
            phrase = match.group(1).strip()
            words = phrase.split()
            head = words[0].lower()
            if head in _STOP_HEAD_WORDS:
                continue
            # 한 단어 probe는 버전 숫자가 붙은 형태("GPT-5.6")만 허용,
            # 브랜드 단독명("ChatGPT")은 버린다.
            if len(words) == 1:
                bare = words[0].lower().strip(".,")
                if bare in _BARE_BRAND_TERMS or not any(ch.isdigit() for ch in bare):
                    continue
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            phrases.append(phrase)
            if len(phrases) >= limit:
                break
        return phrases

    @classmethod
    def suggestions(cls, query: str) -> list[str]:
        key = query.strip().lower()
        if not key:
            return []
        now = time.time()
        with cls._lock:
            cached = cls._cache.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
                return list(cached[1])
        hl = "en" if (os.getenv("BLOG_LANGUAGE", "ko") or "ko").strip().lower() == "en" else "ko"
        url = _ENDPOINT.format(hl=hl, q=parse.quote(query))
        try:
            req = request.Request(url, headers={"User-Agent": _USER_AGENT})
            with request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            items = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            result = [str(item) for item in items if str(item).strip()]
        except (error.URLError, TimeoutError, ValueError, IndexError, OSError) as exc:
            logger.debug("autocomplete fetch failed (%s): %s", query, exc)
            result = []
        with cls._lock:
            cls._cache[key] = (now, result)
        return result

    @classmethod
    def score_topic_boost(cls, text: str, *, max_boost: int = 15) -> tuple[int, list[str]]:
        """후보 텍스트의 구체 구문들이 실제 자동완성에 잡히는 만큼 부스트.

        반환: (boost, 매칭된 제안 목록). 구문당 매칭 제안 1개 = +3점,
        max_boost로 캡. 신호 없음/실패는 (0, [])."""
        if not is_signal_enabled():
            return 0, []
        matched: list[str] = []
        for phrase in cls.extract_probe_phrases(text):
            phrase_lower = phrase.lower()
            for suggestion in cls.suggestions(phrase):
                if phrase_lower in suggestion.lower():
                    matched.append(suggestion)
        boost = min(max_boost, len(matched) * 3)
        return boost, matched

    @classmethod
    def reset_cache_for_tests(cls) -> None:
        with cls._lock:
            cls._cache.clear()
