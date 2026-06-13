from __future__ import annotations

from io import BytesIO
import urllib.error

import pytest

from blogspot_automation.services.news_topic_service import NewsTopicService
from blogspot_automation.services.news_topic_service import _google_api_error_summary
from blogspot_automation.services.external_news_search_service import ExternalSearchDocument


@pytest.fixture(autouse=True)
def _legacy_news_mode_by_default(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "false")


def test_ai_blog_mode_keeps_only_ai_query_group(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    svc = NewsTopicService()

    query_groups = {group for _, group in svc._query_plan()}

    assert query_groups == {"ai_work"}


def test_excluded_query_groups_are_removed_from_primary_plan() -> None:
    svc = NewsTopicService(excluded_query_groups=["ai_work"])

    query_groups = {group for _, group in svc._query_plan()}

    assert "ai_work" not in query_groups
    assert "money_life" in query_groups


def test_excluded_query_groups_are_removed_from_fallback_candidates() -> None:
    svc = NewsTopicService(excluded_query_groups=["ai_work"])

    candidates = svc._fallback_candidates()

    assert all(candidate.raw.get("query_group") != "ai_work" for candidate in candidates)


def test_primary_plan_interleaves_categories_without_fixed_order(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_TOPIC_RANDOM_SEED", "unit-test")
    svc = NewsTopicService(excluded_query_groups=["ai_work"])

    plan = svc._query_plan()
    first_20_groups = [group for _, group in plan[:20]]

    assert len(set(first_20_groups)) >= 6
    assert first_20_groups.count("policy_benefit") <= 3
    assert any(
        group in {"entertainment_sports", "ott_drama_reaction", "sports_reaction"}
        for group in first_20_groups
    )
    assert "consumer_warning_issue" in first_20_groups
    assert "platform_consumer" in first_20_groups


def test_custom_search_is_disabled_by_default_even_when_keys_exist(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_GOOGLE_CUSTOM_SEARCH", raising=False)

    svc = NewsTopicService(api_key="search-key", search_cx="cx")

    assert svc.enable_custom_search is False


def test_custom_search_can_be_enabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "true")

    svc = NewsTopicService(api_key="search-key", search_cx="cx")

    assert svc.enable_custom_search is True


def test_google_api_error_summary_extracts_status_reason_and_message() -> None:
    body = (
        b'{"error":{"code":400,"message":"API key not valid.",'
        b'"status":"INVALID_ARGUMENT","errors":[{"reason":"badRequest"}]}}'
    )
    exc = urllib.error.HTTPError(
        url="https://www.googleapis.com/customsearch/v1",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(body),
    )

    summary = _google_api_error_summary(exc)

    assert "INVALID_ARGUMENT" in summary
    assert "badRequest" in summary
    assert "API key not valid." in summary


def test_clean_rss_title_removes_media_series_prefix_before_bracket_strip() -> None:
    svc = NewsTopicService()

    assert svc._clean_rss_title("[재계는 지금] KT 초이스 요금제 무료 혜택") == "KT 초이스 요금제 무료 혜택"
    assert svc._clean_rss_title("재계는 지금] KT 초이스 요금제 무료 혜택") == "KT 초이스 요금제 무료 혜택"


def test_external_search_documents_are_used_before_rss(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_TOPIC_RANDOM_SEED", "unit-test")

    class StubExternalSearch:
        def collect_naver_documents(self, query_plan):
            first_20_groups = [group for _, group in query_plan[:20]]
            assert len(set(first_20_groups)) >= 6
            assert first_20_groups.count("policy_benefit") <= 3
            return [
                ExternalSearchDocument(
                    title="청년 지원금 신청 마감",
                    snippet="대상 조건과 신청 방법",
                    url="https://policy.example.go.kr/post/1",
                    source_hint="policy.example.go.kr",
                    provider="naver",
                    source_type="naver_news_search",
                    query="정부 지원금 신청 마감",
                    query_group="policy_benefit",
                )
            ]

        def annotate_naver_datalab(self, candidates):
            candidates[0].raw["naver_datalab_score"] = 7
            return candidates

        def verify_candidates(self, candidates):
            candidates[0].raw["verified_source_count"] = 2
            return candidates

    svc = NewsTopicService(
        candidate_limit=1,
        excluded_query_groups=["ai_work"],
        external_search_service=StubExternalSearch(),
    )

    candidates = svc.collect_candidates()

    assert len(candidates) == 1
    assert candidates[0].topic == "청년 지원금 신청 마감"
    assert candidates[0].raw["source_type"] == "naver_news_search"
    assert candidates[0].raw["naver_datalab_score"] == 7


def test_external_search_document_marks_primary_official_source() -> None:
    svc = NewsTopicService(candidate_limit=1)

    candidates = svc._documents_to_candidates([
        ExternalSearchDocument(
            title="항공권 구매 취소 시 위약금 과다·환불 지연 피해 많아",
            snippet="한국소비자원 피해예방주의보",
            url="https://www.kca.go.kr/home/sub.do?menukey=4005&mode=view&no=1002032988",
            source_hint="kca.go.kr",
            provider="naver",
            source_type="naver_webkr_search",
            query="소비자원 환불 피해 주의",
            query_group="consumer_warning_issue",
        )
    ])

    assert candidates
    assert candidates[0].raw["official_source_found"] is True
