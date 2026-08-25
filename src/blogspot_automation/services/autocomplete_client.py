"""Google Autocomplete(suggestqueries) 단일 전송 계층.

2026-08-25 정리 전까지 이 저장소에는 같은 엔드포인트를 각자 부르는 구현이 셋
있었다 — `search_autocomplete_signal`(에버그린 상시 수요 점수),
`google_autocomplete_signal`(구체 제품 구문 실검색 확인),
`search_demand_service`(제목·FAQ에 쓸 실제 검색어 수집). 셋의 **목적은 서로
다르지만**(점수냐 문구냐), URL 조립·User-Agent·JSON 파싱·예외 삼키기는 완전히
같은 코드였다. 전송만 여기로 모은다.

정책(캐시 TTL·호출 상한·env 스위치·언어 결정)은 **호출부에 그대로 남긴다** —
세 곳의 정책이 실제로 다르기 때문이다. 여기서 하는 일은 "한 번 물어보고
제안 목록과 성공 여부를 돌려준다"뿐이고, 절대 예외를 밖으로 던지지 않는다.
"""
from __future__ import annotations

import json
import logging
from urllib import error, parse, request

logger = logging.getLogger(__name__)

_ENDPOINT = "https://suggestqueries.google.com/complete/search"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; blogspot-automation/1.0)"


def build_url(query: str, *, hl: str = "en", gl: str = "") -> str:
    params = {"client": "firefox", "hl": hl, "q": query}
    if gl:
        params["gl"] = gl
    return f"{_ENDPOINT}?{parse.urlencode(params)}"


def fetch_suggestions(
    query: str,
    *,
    hl: str = "en",
    gl: str = "",
    timeout: float = 6.0,
    user_agent: str = DEFAULT_USER_AGENT,
    limit: int = 10,
) -> tuple[list[str], bool]:
    """(제안 목록, 성공 여부)를 돌려준다.

    성공 여부를 따로 주는 이유: 빈 목록은 "수요 없음"과 "측정 실패" 둘 다일 수
    있는데, 이 둘을 섞으면 네트워크 오류를 근거 삼아 주제를 버리게 된다.
    호출부가 구분할 수 있도록 명시적으로 나눠 돌려준다.
    """
    text = str(query or "").strip()
    if not text:
        return [], False
    url = build_url(text, hl=hl, gl=gl)
    try:
        req = request.Request(url, headers={"User-Agent": user_agent})
        with request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (error.HTTPError, error.URLError, TimeoutError, ValueError, IndexError, OSError) as exc:
        logger.debug("autocomplete fetch failed (%s): %s", text[:40], exc)
        return [], False
    except Exception as exc:  # noqa: BLE001 — 수요 신호 실패는 언제나 비치명이다
        logger.warning("autocomplete fetch unexpected error (non-fatal): %s", exc)
        return [], False
    items = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    suggestions = [str(item).strip() for item in items if str(item).strip()]
    return suggestions[: max(0, limit)] if limit else suggestions, True
