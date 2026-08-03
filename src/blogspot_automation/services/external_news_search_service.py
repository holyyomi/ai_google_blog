from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
import html
import json
import logging
import re
from typing import Any
from urllib.parse import urlencode, urlsplit
import urllib.error
import urllib.request

from blogspot_automation.models.news_models import NewsCandidate

logger = logging.getLogger(__name__)


NAVER_SEARCH_ENDPOINTS = {
    "news": "https://openapi.naver.com/v1/search/news.json",
    "blog": "https://openapi.naver.com/v1/search/blog.json",
    "webkr": "https://openapi.naver.com/v1/search/webkr.json",
}
NAVER_DATALAB_SEARCH_ENDPOINT = "https://openapi.naver.com/v1/datalab/search"
TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
EXA_SEARCH_ENDPOINT = "https://api.exa.ai/search"
FIRECRAWL_SEARCH_ENDPOINT = "https://api.firecrawl.dev/v2/search"


# ---------------------------------------------------------------------------
# 회로차단기(circuit breaker) — 2026-08-03
#
# 배경(실측): Tavily는 HTTP 432(크레딧/플랜 한도 소진), Firecrawl은 HTTP 402
# (Insufficient credits)를 매 호출마다 돌려주는데도 파이프라인은 재시도
# (run_with_retries, 최대 6회) × 후보 수만큼 같은 호출을 반복했다 —
# Tavily 18회/실행(약 150~180초), Firecrawl 6회/실행. 한 번 "돈·권한·한도"
# 계열 실패가 나오면 그 실행 안에서는 절대 회복되지 않으므로, 해당 provider를
# 그 실행 동안 꺼서 낭비를 자동으로 멈춘다.
#
# 크레딧을 다시 채우면 프로세스가 새로 뜨는 순간(GHA/Cloud Run 1회 실행 =
# 1 프로세스) 차단 상태도 사라지므로, env 플래그를 되돌리는 것 외에 별도
# 복구 작업이 필요 없다.
#
# 5xx·타임아웃·네트워크 오류는 일시 장애다 — 다음 후보에서 회복될 수 있으므로
# 절대 차단 대상이 아니다.
# ---------------------------------------------------------------------------
_FATAL_HTTP_STATUSES = frozenset({401, 402, 403, 429, 432})

# Exa만 예외로 429(rate limit)를 차단 사유에서 뺀다.
# 근거: Exa 응답은 후보 검증 소스(source_urls/web_verification)의 핵심이고,
# 429는 "잠깐 너무 빨리 불렀다"는 일시 신호라 다음 후보에서 회복될 수 있다.
# 반면 401(인증 실패)/402(크레딧 소진)/403(플랜 권한 없음)/432는 같은 실행
# 안에서 회복 불가능한 확정 상태이므로 Exa도 차단한다.
_EXA_FATAL_HTTP_STATUSES = frozenset({401, 402, 403, 432})


def _fatal_statuses_for(provider: str) -> frozenset[int]:
    return _EXA_FATAL_HTTP_STATUSES if provider == "exa" else _FATAL_HTTP_STATUSES


class ExternalSearchHTTPError(RuntimeError):
    """HTTP 상태코드를 속성으로 보존하는 외부 검색 API 오류.

    기존에는 ``RuntimeError(f"HTTP {code}: ...")``로 상태코드를 문자열에
    묻어버려서 호출부가 코드로 분기할 수 없었다. 메시지 형식은 그대로 두고
    ``status_code``만 추가한다(로그 출력 호환).
    """

    def __init__(self, status_code: int, summary: str) -> None:
        super().__init__(f"HTTP {status_code}: {summary}")
        self.status_code = status_code


@dataclass(slots=True)
class ExternalNewsSearchConfig:
    naver_client_id: str = ""
    naver_client_secret: str = ""
    tavily_api_key: str = ""
    exa_api_key: str = ""
    firecrawl_api_key: str = ""
    enable_naver_search: bool = False
    enable_naver_datalab: bool = False
    enable_tavily_search: bool = False
    enable_exa_search: bool = False
    enable_firecrawl_search: bool = False
    naver_search_types: tuple[str, ...] = ("news", "webkr")
    naver_max_requests: int = 18
    naver_display: int = 2
    naver_datalab_max_requests: int = 5
    tavily_max_requests: int = 3
    exa_max_requests: int = 1
    firecrawl_max_requests: int = 1


@dataclass(slots=True)
class ExternalSearchDocument:
    title: str
    snippet: str
    url: str | None = None
    source_hint: str | None = None
    published_at: str | None = None
    provider: str = ""
    source_type: str = ""
    query: str = ""
    query_group: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class ExternalNewsSearchService:
    def __init__(self, config: ExternalNewsSearchConfig) -> None:
        self.config = config
        # 이 실행에서 확정 실패(크레딧·인증·권한 소진)로 판정된 provider.
        # 인스턴스는 cli_news.py에서 1회 생성돼 run_with_retries의 재시도
        # 전체(최대 6회)에 공유되므로, 인스턴스 필드면 실행 전체를 덮는다.
        self._dead_providers: set[str] = set()

    def _provider_dead(self, provider: str) -> bool:
        return provider in self._dead_providers

    def _note_provider_failure(self, provider: str, exc: BaseException) -> None:
        """확정 실패면 provider를 차단 목록에 넣고 딱 한 번만 로그를 남긴다."""
        status = getattr(exc, "status_code", None)
        if status is None or status not in _fatal_statuses_for(provider):
            return
        if provider in self._dead_providers:
            return
        self._dead_providers.add(provider)
        logger.warning(
            "%s HTTP %s — 이번 실행 동안 %s 호출을 중단한다 (크레딧/인증/권한 소진). "
            "복구하려면 크레딧을 채우거나 해당 ENABLE_* 플래그를 확인할 것.",
            provider,
            status,
            provider,
        )

    def collect_naver_documents(self, query_plan: list[tuple[str, str]]) -> list[ExternalSearchDocument]:
        if not self._naver_search_ready():
            return []

        collected: list[ExternalSearchDocument] = []
        request_count = 0
        search_types = tuple(
            item
            for item in self.config.naver_search_types
            if item in NAVER_SEARCH_ENDPOINTS
        ) or ("news",)
        for query, query_group in query_plan:
            for search_type in search_types:
                if request_count >= max(0, self.config.naver_max_requests):
                    return collected
                display = self._naver_display_for(search_type, query_group)
                if display <= 0:
                    continue
                request_count += 1
                try:
                    collected.extend(
                        self._request_naver_search(
                            query=query,
                            query_group=query_group,
                            search_type=search_type,
                            display=display,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Naver %s search failed(query=%s): %s",
                        search_type,
                        query,
                        exc,
                    )
        return collected

    def annotate_naver_datalab(self, candidates: list[NewsCandidate]) -> list[NewsCandidate]:
        if not candidates or not self._naver_datalab_ready():
            return candidates

        max_groups = max(0, self.config.naver_datalab_max_requests) * 5
        targets = candidates[:max_groups]
        for chunk_start in range(0, len(targets), 5):
            chunk = targets[chunk_start : chunk_start + 5]
            keyword_groups: list[dict[str, Any]] = []
            group_to_candidate: dict[str, NewsCandidate] = {}
            for offset, candidate in enumerate(chunk):
                keyword = _trend_keyword(candidate)
                if not keyword:
                    continue
                group_name = f"g{chunk_start + offset}"
                keyword_groups.append({"groupName": group_name, "keywords": [keyword]})
                group_to_candidate[group_name] = candidate

            if not keyword_groups:
                continue

            payload = self._naver_datalab_payload(keyword_groups)
            try:
                response = self._post_json(
                    NAVER_DATALAB_SEARCH_ENDPOINT,
                    payload,
                    headers=self._naver_headers(),
                    timeout=10,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Naver DataLab request failed: %s", exc)
                continue
            results = response.get("results") if isinstance(response, dict) else None
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                group_name = str(result.get("title") or "").strip()
                candidate = group_to_candidate.get(group_name)
                if candidate is None:
                    continue
                trend = _score_datalab_result(result)
                raw = candidate.raw if isinstance(candidate.raw, dict) else {}
                candidate.raw = raw
                raw["naver_datalab_score"] = trend["score"]
                raw["naver_datalab_latest_ratio"] = trend["latest_ratio"]
                raw["naver_datalab_growth_ratio"] = trend["growth_ratio"]
                raw["naver_datalab_keyword"] = _trend_keyword(candidate)
                _append_unique(raw, "external_search_providers", "naver_datalab")
        return candidates

    def verify_candidates(self, candidates: list[NewsCandidate]) -> list[NewsCandidate]:
        if not candidates:
            return candidates
        self._verify_with_tavily(candidates)
        self._verify_with_exa(candidates)
        self._verify_with_firecrawl(candidates)
        return candidates

    def _verify_with_tavily(self, candidates: list[NewsCandidate]) -> None:
        if not self.config.enable_tavily_search or not self.config.tavily_api_key.strip():
            return
        if self._provider_dead("tavily"):
            return
        for candidate in self._verification_targets(candidates, self.config.tavily_max_requests):
            query = _verification_query(candidate)
            if not query:
                continue
            payload = {
                "query": query,
                "search_depth": "basic",
                "topic": "news",
                "max_results": 3,
                "include_answer": False,
                "include_raw_content": False,
            }
            try:
                response = self._post_json(
                    TAVILY_SEARCH_ENDPOINT,
                    payload,
                    headers={
                        "Authorization": f"Bearer {self.config.tavily_api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    timeout=12,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tavily verification failed(query=%s): %s", query, exc)
                self._note_provider_failure("tavily", exc)
                if self._provider_dead("tavily"):
                    return
                continue
            results = response.get("results") if isinstance(response, dict) else None
            if isinstance(results, list):
                self._attach_verification_results(candidate, "tavily", results)

    def _verify_with_exa(self, candidates: list[NewsCandidate]) -> None:
        if not self.config.enable_exa_search or not self.config.exa_api_key.strip():
            return
        if self._provider_dead("exa"):
            return
        start_date = (date.today() - timedelta(days=3)).isoformat()
        for candidate in self._verification_targets(candidates, self.config.exa_max_requests):
            query = _verification_query(candidate)
            if not query:
                continue
            payload = {
                "query": query,
                "type": "auto",
                "numResults": 3,
                "startPublishedDate": start_date,
            }
            try:
                response = self._post_json(
                    EXA_SEARCH_ENDPOINT,
                    payload,
                    headers={
                        "x-api-key": self.config.exa_api_key.strip(),
                        "Content-Type": "application/json",
                    },
                    timeout=12,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Exa verification failed(query=%s): %s", query, exc)
                self._note_provider_failure("exa", exc)
                if self._provider_dead("exa"):
                    return
                continue
            results = response.get("results") if isinstance(response, dict) else None
            if isinstance(results, list):
                self._attach_verification_results(candidate, "exa", results)

    def _verify_with_firecrawl(self, candidates: list[NewsCandidate]) -> None:
        if not self.config.enable_firecrawl_search or not self.config.firecrawl_api_key.strip():
            return
        if self._provider_dead("firecrawl"):
            return
        for candidate in self._verification_targets(candidates, self.config.firecrawl_max_requests):
            query = _verification_query(candidate)
            if not query:
                continue
            payload = {
                "query": query,
                "limit": 3,
                "sources": [{"type": "news"}, {"type": "web"}],
                "scrapeOptions": {
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
            }
            try:
                response = self._post_json(
                    FIRECRAWL_SEARCH_ENDPOINT,
                    payload,
                    headers={
                        "Authorization": f"Bearer {self.config.firecrawl_api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    timeout=18,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Firecrawl verification failed(query=%s): %s", query, exc)
                self._note_provider_failure("firecrawl", exc)
                if self._provider_dead("firecrawl"):
                    return
                continue
            results = response.get("data") if isinstance(response, dict) else None
            if isinstance(results, list):
                self._attach_verification_results(candidate, "firecrawl", results)

    def _verification_targets(
        self,
        candidates: list[NewsCandidate],
        max_requests: int,
    ) -> list[NewsCandidate]:
        if max_requests <= 0:
            return []
        targets: list[NewsCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            raw = candidate.raw if isinstance(candidate.raw, dict) else {}
            if raw.get("is_test_candidate") or raw.get("publish_allowed") is False:
                continue
            query = _verification_query(candidate)
            key = _norm(query)
            if not key or key in seen:
                continue
            seen.add(key)
            targets.append(candidate)
            if len(targets) >= max_requests:
                break
        return targets

    def _attach_verification_results(
        self,
        candidate: NewsCandidate,
        provider: str,
        results: list[Any],
    ) -> None:
        raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        candidate.raw = raw
        normalized: list[dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url") or result.get("link") or "").strip()
            title = _clean_text(str(result.get("title") or result.get("name") or ""))
            snippet = _clean_text(
                str(
                    result.get("content")
                    or result.get("snippet")
                    or result.get("description")
                    or result.get("text")
                    or result.get("markdown")
                    or ""
                )
            )
            if not title and not url:
                continue
            normalized.append({
                "provider": provider,
                "title": title[:180],
                "url": url,
                "host": _host(url),
                "snippet": snippet[:500],
                "score": result.get("score"),
                "published_at": result.get("published_date") or result.get("publishedDate"),
            })
        if not normalized:
            return

        verification = raw.setdefault("web_verification", {})
        if isinstance(verification, dict):
            verification[provider] = normalized
        _append_unique(raw, "external_search_providers", provider)
        source_urls = raw.setdefault("source_urls", [])
        if not isinstance(source_urls, list):
            source_urls = []
            raw["source_urls"] = source_urls
        source_titles = raw.setdefault("source_titles", [])
        if not isinstance(source_titles, list):
            source_titles = []
            raw["source_titles"] = source_titles
        for item in normalized:
            url = str(item.get("url") or "")
            title = str(item.get("title") or "")
            if url and url not in source_urls:
                source_urls.append(url)
            if title and title not in source_titles:
                source_titles.append(title)
        hosts = {_host(url) for url in source_urls if _host(url)}
        providers = set(raw.get("external_search_providers") or [])
        raw["verified_source_count"] = len(source_urls)
        raw["source_diversity_score"] = min(5, len(hosts) + max(0, len(providers) - 1))
        raw["official_source_found"] = bool(raw.get("official_source_found")) or any(
            _is_official_source(str(item.get("url") or "")) for item in normalized
        )

    def _request_naver_search(
        self,
        *,
        query: str,
        query_group: str,
        search_type: str,
        display: int,
    ) -> list[ExternalSearchDocument]:
        params: dict[str, Any] = {
            "query": query,
            "display": max(1, min(display, 10)),
            "start": 1,
        }
        if search_type in {"news", "blog"}:
            params["sort"] = "date"
        request = urllib.request.Request(
            f"{NAVER_SEARCH_ENDPOINTS[search_type]}?{urlencode(params)}",
            headers=self._naver_headers(),
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []

        documents: list[ExternalSearchDocument] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _clean_text(str(item.get("title") or ""))
            snippet = _clean_text(str(item.get("description") or ""))
            link = str(item.get("originallink") or item.get("link") or "").strip()
            fallback_link = str(item.get("link") or "").strip()
            url = link or fallback_link or None
            if not title:
                continue
            source_hint = _host(link or fallback_link)
            documents.append(
                ExternalSearchDocument(
                    title=title,
                    snippet=snippet,
                    url=url,
                    source_hint=source_hint,
                    published_at=str(item.get("pubDate") or "").strip() or None,
                    provider="naver",
                    source_type=f"naver_{search_type}_search",
                    query=query,
                    query_group=query_group,
                    raw={
                        "naver_item": item,
                        "naver_search_type": search_type,
                        "link": fallback_link,
                        "originallink": str(item.get("originallink") or "").strip(),
                    },
                )
            )
        return documents

    def _naver_display_for(self, search_type: str, query_group: str) -> int:
        if search_type == "news":
            return max(1, min(self.config.naver_display, 5))
        if search_type == "webkr":
            if query_group in {
                "policy_benefit",
                "consumer_warning_issue",
                "money_life",
                "platform_consumer",
                "breaking_issue",
            }:
                return 1
            return 0
        if search_type == "blog":
            return 1 if query_group in {"trend_meme", "community_hot_issue"} else 0
        return 0

    def _naver_search_ready(self) -> bool:
        return (
            self.config.enable_naver_search
            and bool(self.config.naver_client_id.strip())
            and bool(self.config.naver_client_secret.strip())
        )

    def _naver_datalab_ready(self) -> bool:
        return (
            self.config.enable_naver_datalab
            and bool(self.config.naver_client_id.strip())
            and bool(self.config.naver_client_secret.strip())
            and self.config.naver_datalab_max_requests > 0
        )

    def _naver_headers(self) -> dict[str, str]:
        return {
            "X-Naver-Client-Id": self.config.naver_client_id.strip(),
            "X-Naver-Client-Secret": self.config.naver_client_secret.strip(),
            "Content-Type": "application/json",
            "User-Agent": "blogspot-news-automation/1.0",
        }

    def _naver_datalab_payload(self, keyword_groups: list[dict[str, Any]]) -> dict[str, Any]:
        end_date = datetime.now(UTC).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        return {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "timeUnit": "date",
            "keywordGroups": keyword_groups,
        }

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        timeout: int,
    ) -> dict[str, Any]:
        request_headers = {"Content-Type": "application/json", **headers}
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            summary = _safe_error_summary(body)
            # ExternalSearchHTTPError는 RuntimeError 하위라 기존 except 절과
            # 메시지 형식이 그대로 호환되고, status_code로 회로차단 분기가 가능하다.
            raise ExternalSearchHTTPError(exc.code, summary) from exc


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \"'“”‘’[]()")


def _trend_keyword(candidate: NewsCandidate) -> str:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    value = str(
        raw.get("search_demand_topic")
        or raw.get("cleaned_title")
        or raw.get("original_title")
        or candidate.topic
        or ""
    )
    value = _clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value[:60].strip()


def _verification_query(candidate: NewsCandidate) -> str:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    query = str(raw.get("search_demand_topic") or candidate.topic or "").strip()
    if not query:
        query = str(raw.get("original_title") or "").strip()
    return _clean_text(query)[:120]


def _score_datalab_result(result: dict[str, Any]) -> dict[str, float | int]:
    rows = result.get("data")
    ratios: list[float] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                try:
                    ratios.append(float(row.get("ratio") or 0))
                except (TypeError, ValueError):
                    ratios.append(0.0)
    if not ratios:
        return {"score": 0, "latest_ratio": 0.0, "growth_ratio": 0.0}
    latest = _avg(ratios[-3:])
    previous = _avg(ratios[-10:-3]) if len(ratios) > 3 else 0.0
    growth = latest - previous
    score = round(min(10.0, max(0.0, latest / 12.0 + max(0.0, growth) / 8.0)))
    if max(ratios) >= 70 and latest >= 25:
        score = max(score, 6)
    if latest >= 50:
        score = max(score, 7)
    return {
        "score": int(score),
        "latest_ratio": round(latest, 2),
        "growth_ratio": round(growth, 2),
    }


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _append_unique(raw: dict[str, Any], key: str, value: str) -> None:
    values = raw.setdefault(key, [])
    if not isinstance(values, list):
        values = []
        raw[key] = values
    if value and value not in values:
        values.append(value)


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _is_official_source(url: str) -> bool:
    host = _host(url)
    return host.endswith(".go.kr") or host.endswith(".or.kr") or host in {
        "gov.kr",
        "bokjiro.go.kr",
        "epeople.go.kr",
        "consumer.go.kr",
    }


def _safe_error_summary(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return " ".join(body.split())[:300]
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(error, dict):
            parts = [
                str(error.get("code") or "").strip(),
                str(error.get("status") or "").strip(),
                str(error.get("message") or "").strip(),
            ]
            return " | ".join(part for part in parts if part)[:300]
        if error:
            return str(error)[:300]
    return " ".join(body.split())[:300]
