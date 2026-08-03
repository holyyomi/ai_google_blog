"""외부 검색 provider 회로차단기 — 2026-08-03.

배경: Tavily(432 한도소진)·Firecrawl(402 크레딧소진)이 매 실행 100% 실패하는데도
후보 재시도 6회 × 쿼리 3개 = 18회를 계속 호출해 실행당 150~180초를 버렸다.
확정 실패(크레딧·인증·권한)는 같은 실행 안에서 회복되지 않으므로 첫 실패에
provider를 차단하고, 일시 장애(5xx·타임아웃)는 차단하지 않는다.
"""
from __future__ import annotations

import urllib.error

import pytest

from blogspot_automation.services.external_news_search_service import (
    ExternalNewsSearchConfig,
    ExternalNewsSearchService,
    ExternalSearchHTTPError,
)
from blogspot_automation.services.news_topic_service import NewsCandidate


def _candidates(count: int = 3) -> list[NewsCandidate]:
    return [
        NewsCandidate(
            topic=f"OpenAI ships feature number {index}",
            category="ai_work",
            summary=f"Summary for candidate {index}",
            source_hint="example",
            published_at=None,
            url=f"https://example.com/news/{index}",
            raw={},
        )
        for index in range(count)
    ]


def _service(**overrides) -> ExternalNewsSearchService:
    config = ExternalNewsSearchConfig(
        tavily_api_key="k",
        exa_api_key="k",
        firecrawl_api_key="k",
        enable_tavily_search=True,
        enable_exa_search=True,
        enable_firecrawl_search=True,
        tavily_max_requests=3,
        exa_max_requests=3,
        firecrawl_max_requests=3,
        **overrides,
    )
    return ExternalNewsSearchService(config)


class _CallCounter:
    """_post_json을 대체해 호출 횟수를 세고 지정한 오류를 던진다."""

    def __init__(self, exc: BaseException | None) -> None:
        self.calls = 0
        self.exc = exc

    def __call__(self, url, payload, *, headers, timeout):  # noqa: ANN001
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return {"results": [], "data": []}


def test_tavily_stops_calling_after_fatal_status() -> None:
    """432(한도 소진) 한 번이면 남은 후보를 아예 호출하지 않는다."""
    service = _service()
    counter = _CallCounter(ExternalSearchHTTPError(432, "quota exhausted"))
    service._post_json = counter  # type: ignore[method-assign]

    service._verify_with_tavily(_candidates(3))
    assert counter.calls == 1, "첫 확정 실패 후에는 더 호출하면 안 된다"

    # 재시도 루프에서 다시 불려도 네트워크 호출이 아예 나가지 않아야 한다.
    service._verify_with_tavily(_candidates(3))
    assert counter.calls == 1


def test_firecrawl_stops_calling_after_payment_required() -> None:
    service = _service()
    counter = _CallCounter(ExternalSearchHTTPError(402, "insufficient credits"))
    service._post_json = counter  # type: ignore[method-assign]

    service._verify_with_firecrawl(_candidates(3))
    service._verify_with_firecrawl(_candidates(3))
    assert counter.calls == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_do_not_trip_the_breaker(status: int) -> None:
    """5xx는 일시 장애 — 다음 후보에서 회복될 수 있으므로 계속 시도한다."""
    service = _service()
    counter = _CallCounter(ExternalSearchHTTPError(status, "server error"))
    service._post_json = counter  # type: ignore[method-assign]

    service._verify_with_tavily(_candidates(3))
    assert counter.calls == 3, "5xx에서는 후보를 끝까지 시도해야 한다"
    assert not service._provider_dead("tavily")


def test_timeouts_do_not_trip_the_breaker() -> None:
    service = _service()
    counter = _CallCounter(urllib.error.URLError("timed out"))
    service._post_json = counter  # type: ignore[method-assign]

    service._verify_with_tavily(_candidates(3))
    assert counter.calls == 3
    assert not service._provider_dead("tavily")


def test_exa_survives_rate_limit_but_dies_on_credit_exhaustion() -> None:
    """Exa는 본문 팩트의 핵심이라 429(일시 rate limit)로 죽이면 안 된다.

    Exa가 꺼지면 팩트가 RSS 헤드라인만 남아 '껍데기 글'이 나온다.
    반면 402(크레딧 소진)는 같은 실행 안에서 회복 불가라 차단 대상이다.
    """
    service = _service()
    rate_limited = _CallCounter(ExternalSearchHTTPError(429, "rate limited"))
    service._post_json = rate_limited  # type: ignore[method-assign]
    service._verify_with_exa(_candidates(3))
    assert rate_limited.calls == 3, "429로는 Exa를 차단하면 안 된다"
    assert not service._provider_dead("exa")

    service = _service()
    out_of_credit = _CallCounter(ExternalSearchHTTPError(402, "no credits"))
    service._post_json = out_of_credit  # type: ignore[method-assign]
    service._verify_with_exa(_candidates(3))
    assert out_of_credit.calls == 1
    assert service._provider_dead("exa")


def test_tavily_breaker_does_not_disable_exa() -> None:
    """provider별로 독립 차단 — 하나가 죽어도 나머지는 계속 돈다."""
    service = _service()
    service._note_provider_failure("tavily", ExternalSearchHTTPError(432, "quota"))
    assert service._provider_dead("tavily")
    assert not service._provider_dead("exa")
    assert not service._provider_dead("firecrawl")


def test_post_json_preserves_status_code() -> None:
    """회로차단 분기의 전제 — HTTPError의 상태코드가 예외 속성으로 살아있어야 한다."""
    service = _service()

    def _raise(*args, **kwargs):  # noqa: ANN002, ANN003
        raise urllib.error.HTTPError(
            url="https://example.com", code=432, msg="quota", hdrs=None, fp=None
        )

    import urllib.request

    original = urllib.request.urlopen
    urllib.request.urlopen = _raise  # type: ignore[assignment]
    try:
        with pytest.raises(ExternalSearchHTTPError) as excinfo:
            service._post_json(
                "https://example.com", {}, headers={}, timeout=1
            )
    finally:
        urllib.request.urlopen = original  # type: ignore[assignment]

    assert excinfo.value.status_code == 432
    assert "HTTP 432" in str(excinfo.value), "기존 로그 메시지 형식이 유지돼야 한다"
