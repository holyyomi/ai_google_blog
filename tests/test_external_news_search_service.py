from __future__ import annotations

import json
import urllib.request

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.external_news_search_service import (
    ExternalNewsSearchConfig,
    ExternalNewsSearchService,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_naver_search_documents_strip_html_and_keep_source(monkeypatch) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: int):
        assert "openapi.naver.com/v1/search/news.json" in req.full_url
        return _Response({
            "items": [
                {
                    "title": "<b>청년 지원금</b> 신청 마감",
                    "description": "대상 조건과 신청 방법 안내",
                    "originallink": "https://policy.example.go.kr/post/1",
                    "link": "https://n.news.naver.com/article/1",
                    "pubDate": "Sun, 31 May 2026 09:00:00 +0900",
                }
            ]
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    service = ExternalNewsSearchService(
        ExternalNewsSearchConfig(
            naver_client_id="id",
            naver_client_secret="secret",
            enable_naver_search=True,
            naver_search_types=("news",),
            naver_max_requests=1,
        )
    )

    docs = service.collect_naver_documents([("정부 지원금 신청 마감", "policy_benefit")])

    assert len(docs) == 1
    assert docs[0].title == "청년 지원금 신청 마감"
    assert docs[0].source_type == "naver_news_search"
    assert docs[0].source_hint == "policy.example.go.kr"
    assert docs[0].query_group == "policy_benefit"


def test_naver_datalab_adds_trend_score(monkeypatch) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: int):
        body = json.loads((req.data or b"{}").decode("utf-8"))
        group_name = body["keywordGroups"][0]["groupName"]
        return _Response({
            "results": [
                {
                    "title": group_name,
                    "data": [
                        {"period": "2026-05-27", "ratio": 10},
                        {"period": "2026-05-28", "ratio": 15},
                        {"period": "2026-05-29", "ratio": 40},
                        {"period": "2026-05-30", "ratio": 70},
                    ],
                }
            ]
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    service = ExternalNewsSearchService(
        ExternalNewsSearchConfig(
            naver_client_id="id",
            naver_client_secret="secret",
            enable_naver_datalab=True,
            naver_datalab_max_requests=1,
        )
    )
    candidate = NewsCandidate(
        topic="청년 지원금 신청 마감",
        category="money",
        summary="대상 조건 확인",
        raw={"source_type": "naver_news_search"},
    )

    service.annotate_naver_datalab([candidate])

    assert candidate.raw["naver_datalab_score"] >= 5
    assert candidate.raw["naver_datalab_latest_ratio"] > 0
    assert "naver_datalab" in candidate.raw["external_search_providers"]


def test_tavily_verification_adds_source_evidence(monkeypatch) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: int):
        assert "api.tavily.com/search" in req.full_url
        return _Response({
            "results": [
                {
                    "title": "청년 지원금 신청 안내",
                    "url": "https://www.gov.kr/portal/service/1",
                    "content": "공식 신청 경로와 대상 조건",
                    "score": 0.9,
                },
                {
                    "title": "지자체 지원금 정리",
                    "url": "https://news.example.com/a",
                    "content": "마감일과 필요 서류",
                    "score": 0.8,
                },
            ]
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    service = ExternalNewsSearchService(
        ExternalNewsSearchConfig(
            tavily_api_key="tvly-key",
            enable_tavily_search=True,
            tavily_max_requests=1,
        )
    )
    candidate = NewsCandidate(
        topic="청년 지원금 신청 마감",
        category="money",
        summary="대상 조건 확인",
        raw={"source_type": "naver_news_search"},
    )

    service.verify_candidates([candidate])

    assert candidate.raw["verified_source_count"] == 2
    assert candidate.raw["source_diversity_score"] >= 2
    assert candidate.raw["official_source_found"] is True
    assert "tavily" in candidate.raw["external_search_providers"]
