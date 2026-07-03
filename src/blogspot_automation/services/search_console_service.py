"""Search Console 성과 루프 — 실제 검색 성과 데이터를 주제 선정에 반영한다.

목적: 지금까지 파이프라인은 발행만 하고 결과를 몰랐다. 이 서비스는
Google Search Console API에서 최근 검색 성과(쿼리별 클릭/노출)를 받아와
data/search_performance.json에 저장하고, 다음 발행의 주제 후보 중
"실제로 검색되는 키워드"와 겹치는 후보에 가산점을 준다.

인증: 서비스 계정 JSON (env GSC_SERVICE_ACCOUNT_JSON — JSON 문자열 또는
파일 경로). 해당 서비스 계정 이메일을 Search Console 속성에 사용자로
추가해야 한다. 키가 없거나 호출 실패 시 모든 함수는 비치명으로 동작한다
(부스트 0, 발행 흐름 영향 없음).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_STORE_PATH = "data/search_performance.json"
_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

# 부스트 계산에서 무시할 흔한 토큰 — 이 블로그 글 전부에 해당돼 변별력이 없다.
_BOOST_STOPWORDS = frozenset({
    "ai", "인공지능", "방법", "하는", "위한", "대한", "무료", "활용",
    "정리", "확인", "기능", "도구", "이유", "때",
})


def fetch_search_performance(
    *,
    site_url: str = "",
    days: int = 28,
    row_limit: int = 100,
) -> dict[str, Any]:
    """GSC Search Analytics에서 최근 성과를 가져온다. 실패 시 빈 dict."""
    raw_credential = os.getenv("GSC_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_credential:
        logger.info("search_console: GSC_SERVICE_ACCOUNT_JSON 없음 — 성과 수집 스킵")
        return {}
    site = (site_url or os.getenv("BLOGSPOT_HOME_URL", "https://holyyomiai.blogspot.com/")).strip()
    try:
        credentials = _load_service_account_credentials(raw_credential)
        token = _access_token(credentials)
        end = date.today()
        start = end - timedelta(days=max(7, days))
        rows_by_query = _search_analytics_query(
            token=token, site_url=site,
            start=start.isoformat(), end=end.isoformat(),
            dimensions=["query"], row_limit=row_limit,
        )
        rows_by_page = _search_analytics_query(
            token=token, site_url=site,
            start=start.isoformat(), end=end.isoformat(),
            dimensions=["page"], row_limit=50,
        )
        result = {
            "site_url": site,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "queries": rows_by_query,
            "pages": rows_by_page,
        }
        logger.info(
            "search_console: 성과 수집 완료 — 쿼리 %d행, 페이지 %d행",
            len(rows_by_query), len(rows_by_page),
        )
        return result
    except Exception as exc:  # noqa: BLE001 — 성과 수집 실패는 비치명
        logger.warning("search_console: 성과 수집 실패(비치명) — %s", exc)
        return {}


def _load_service_account_credentials(raw: str):
    from google.oauth2 import service_account
    if raw.lstrip().startswith("{"):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=[_GSC_SCOPE])
    return service_account.Credentials.from_service_account_file(raw, scopes=[_GSC_SCOPE])


def _access_token(credentials) -> str:
    from google.auth.transport.requests import Request
    credentials.refresh(Request())
    return str(credentials.token)


def _search_analytics_query(
    *, token: str, site_url: str, start: str, end: str,
    dimensions: list[str], row_limit: int,
) -> list[dict[str, Any]]:
    import urllib.parse
    import urllib.request
    endpoint = (
        "https://searchconsole.googleapis.com/webmasters/v3/sites/"
        f"{urllib.parse.quote(site_url, safe='')}/searchAnalytics/query"
    )
    payload = json.dumps({
        "startDate": start,
        "endDate": end,
        "dimensions": dimensions,
        "rowLimit": row_limit,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = []
    for row in data.get("rows", []) or []:
        keys = row.get("keys") or [""]
        rows.append({
            "key": str(keys[0]),
            "clicks": float(row.get("clicks") or 0),
            "impressions": float(row.get("impressions") or 0),
            "ctr": float(row.get("ctr") or 0),
            "position": float(row.get("position") or 0),
        })
    return rows


def save_search_performance(data: dict[str, Any], *, path: str | Path = _DEFAULT_STORE_PATH) -> bool:
    if not data:
        return False
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_console: 저장 실패 — %s", exc)
        return False


def load_search_performance(*, path: str | Path = _DEFAULT_STORE_PATH) -> dict[str, Any]:
    try:
        target = Path(path)
        if not target.exists():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_console: 로드 실패 — %s", exc)
        return {}


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", str(text or ""))
        if token.lower() not in _BOOST_STOPWORDS
    }


def topic_boost_for(topic: str, performance: dict[str, Any], *, max_boost: int = 8) -> dict[str, Any]:
    """주제 후보가 실제 검색 성과 쿼리와 얼마나 겹치는지에 따른 가산점.

    - 클릭이 있었던 쿼리와 겹치면 쿼리당 3점, 노출만 있었던 쿼리는 1점.
    - 상한 max_boost. 성과 데이터가 없으면 0점 (비치명).
    """
    queries = list((performance or {}).get("queries") or [])
    if not queries:
        return {"boost": 0, "matched_queries": []}
    # 조사가 붙은 한국어("한도와")도 잡히도록 토큰 동일성 대신
    # "쿼리 토큰이 주제 문자열에 부분문자열로 등장하는가"로 매칭한다.
    topic_norm = str(topic or "").lower()
    if not topic_norm.strip():
        return {"boost": 0, "matched_queries": []}

    boost = 0
    matched: list[str] = []
    for row in queries:
        query = str(row.get("key") or "")
        query_tokens = _tokens(query)
        if not query_tokens:
            continue
        hits = [t for t in query_tokens if t in topic_norm]
        # 흔한 단어 하나 우연 일치 방지: 2개 이상 겹치거나,
        # 쿼리가 유의미 토큰 1개짜리면 그 1개가 정확히 맞을 때만 인정
        if len(hits) < 2 and not (len(query_tokens) == 1 and len(hits) == 1):
            continue
        boost += 3 if float(row.get("clicks") or 0) > 0 else 1
        matched.append(query)
        if boost >= max_boost:
            boost = max_boost
            break
    return {"boost": boost, "matched_queries": matched[:5]}
