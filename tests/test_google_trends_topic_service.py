from __future__ import annotations

from unittest.mock import patch

from blogspot_automation.services import google_trends_topic_service as gtts
from blogspot_automation.services.google_trends_signal import TrendingKeyword
from blogspot_automation.services.google_trends_topic_service import GoogleTrendsTopicService


def _patch_keywords(keywords):
    return patch.object(
        gtts.GoogleTrendsSignal,
        "get_trending_keywords",
        return_value=keywords,
    )


def test_seeds_on_topic_trending_keywords(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.delenv("ALLOW_CORPORATE_GOVERNANCE_TOPICS", raising=False)
    keywords = [
        TrendingKeyword("길드워3", "50,000+", ("엔씨소프트 길드워3 SGF 2026 공식 공개", "길드워3 PS5 한국어 지원")),
        TrendingKeyword("손흥민", "100,000+", ("손흥민 결승골 대표팀 승리",)),
    ]
    with _patch_keywords(keywords):
        candidates = GoogleTrendsTopicService().collect_trending_candidates()

    assert len(candidates) == 2
    first = candidates[0]
    assert first.topic == "엔씨소프트 길드워3 SGF 2026 공식 공개"
    assert first.raw["trending_engine"] is True
    # discovery_engine=True여야 스코어링이 today_issue_explainer content_angle을 보존한다.
    assert first.raw["discovery_engine"] is True
    assert first.raw["content_angle"]["content_type"] == "today_issue_explainer"
    assert first.raw["source_type"] == "google_trends_trending"
    assert first.raw["today_buzz_score"] >= 8
    assert first.raw["click_potential_score"] >= 7
    assert first.raw["google_trends_keyword"] == "길드워3"


def test_excludes_foreign_language_and_market_finance_noise() -> None:
    keywords = [
        TrendingKeyword("손흥민", "100,000+", ("손흥민 결승골 대표팀 승리",)),
        TrendingKeyword("Giá vàng", "50,000+", ("Giá vàng lao dốc mạnh hôm nay",)),  # 외국어
        TrendingKeyword("코스피", "30,000+", ("코스피 주가 급등 증시 환율 영향",)),  # 시장 금융
    ]
    with _patch_keywords(keywords):
        candidates = GoogleTrendsTopicService().collect_trending_candidates()
    topics = [c.topic for c in candidates]
    assert any("손흥민" in t for t in topics)
    assert not any("vàng" in t.lower() for t in topics)
    assert not any("코스피" in t or "증시" in t for t in topics)


def test_focus_filter_excludes_offscope_trends(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_CORPORATE_GOVERNANCE_TOPICS", raising=False)
    monkeypatch.delenv("ALLOW_POLITICAL_TODAY_ISSUES", raising=False)
    keywords = [
        TrendingKeyword("손흥민", "100,000+", ("손흥민 결승골 대표팀 승리",)),
        TrendingKeyword("이재명", "200,000+", ("이재명 대통령 취임 1주년 기자회견",)),
        TrendingKeyword("신동빈", "20,000+", ("신동빈 롯데 회장 경영 행보",)),
        TrendingKeyword("사고", "10,000+", ("고속도로 추돌 사망 사고 경찰 수사",)),
    ]
    with _patch_keywords(keywords):
        candidates = GoogleTrendsTopicService().collect_trending_candidates()

    topics = [c.topic for c in candidates]
    assert any("손흥민" in t for t in topics)
    assert not any("이재명" in t for t in topics)
    assert not any("롯데" in t for t in topics)
    assert not any("사망" in t for t in topics)


def test_excludes_stock_market_slang_noise() -> None:
    keywords = [
        TrendingKeyword("손흥민", "100,000+", ("손흥민 결승골 대표팀 승리",)),
        TrendingKeyword("삼전닉스", "80,000+", ("삼전닉스 급락, 반도체 피크아웃?…저가매수 기회",)),
        TrendingKeyword("마이크론", "60,000+", ("마이크론 10%, 반도체 다 뛰었다…삼전ㆍSK하닉 다시 힘받나",)),
        TrendingKeyword("비트코인", "50,000+", ("비트코인 1억 돌파 가상자산 급등",)),
    ]
    with _patch_keywords(keywords):
        candidates = GoogleTrendsTopicService().collect_trending_candidates()
    topics = [c.topic for c in candidates]
    assert any("손흥민" in t for t in topics)
    assert not any("삼전닉스" in t for t in topics)
    assert not any("마이크론" in t for t in topics)
    assert not any("비트코인" in t for t in topics)


def test_empty_when_no_keywords() -> None:
    with _patch_keywords([]):
        assert GoogleTrendsTopicService().collect_trending_candidates() == []


def test_dedup_keeps_first_per_keyword() -> None:
    keywords = [
        TrendingKeyword("손흥민", "100,000+", ("손흥민 결승골",)),
        TrendingKeyword("손흥민", "90,000+", ("손흥민 인터뷰",)),
    ]
    with _patch_keywords(keywords):
        candidates = GoogleTrendsTopicService().collect_trending_candidates()
    assert len(candidates) == 1
