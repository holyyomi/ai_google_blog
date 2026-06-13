from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.news_focus_policy import evaluate_news_focus


@pytest.fixture(autouse=True)
def _news_only_mode_by_default(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "false")


def test_evaluate_news_focus_blocks_ai_topic_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="Gemini Omni AI update",
        raw={"topic_group": "platform_issue", "content_angle": {"content_type": "platform_change"}},
    )

    assert not decision.allowed
    assert decision.reason == "ai_topic_blocked_for_news_only_operation"
    assert "ai" in [item.lower() for item in decision.matched_terms]


def test_evaluate_news_focus_allows_ai_when_broad_today_issue(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="OpenAI service update becomes top issue",
        raw={"topic_group": "today_issue", "content_angle": {"content_type": "today_issue_explainer"}},
    )

    assert decision.allowed


def test_evaluate_news_focus_blocks_ai_work_metadata(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="Office workflow checklist",
        raw={"topic_group": "ai_work", "content_angle": {"content_type": "ai_work_tip"}},
    )

    assert not decision.allowed


def test_evaluate_news_focus_allows_consumer_news(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="Delivery fee refund checklist",
        raw={"topic_group": "refund_consumer", "content_angle": {"content_type": "consumer_warning"}},
    )

    assert decision.allowed


def test_evaluate_news_focus_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_AI_NEWS_TOPICS", "true")

    decision = evaluate_news_focus(
        topic="OpenAI service change",
        raw={"topic_group": "platform_issue", "content_angle": {"content_type": "platform_change"}},
    )

    assert decision.allowed


def test_evaluate_news_focus_blocks_political_headline(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="[속보]이재명 대통령 사전투표 참여 독려",
        raw={"topic_group": "refund_consumer", "content_angle": {"content_type": "consumer_warning"}},
    )

    assert not decision.allowed
    assert decision.reason == "political_geopolitical_topic_blocked_for_news_focus"
    assert "대통령" in decision.matched_terms


def test_evaluate_news_focus_blocks_political_when_broad_today_issue_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.delenv("ALLOW_POLITICAL_TODAY_ISSUES", raising=False)

    decision = evaluate_news_focus(
        topic="한강벨트 변심이 오세훈 표심에 미친 영향",
        raw={"topic_group": "today_issue", "content_angle": {"content_type": "today_issue_explainer"}},
    )

    assert not decision.allowed
    assert decision.reason == "political_geopolitical_topic_blocked_for_news_focus"
    assert "표심" in decision.matched_terms


def test_evaluate_news_focus_allows_political_when_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.setenv("ALLOW_POLITICAL_TODAY_ISSUES", "true")

    decision = evaluate_news_focus(
        topic="한강벨트 변심이 오세훈 표심에 미친 영향",
        raw={"topic_group": "today_issue", "content_angle": {"content_type": "today_issue_explainer"}},
    )

    assert decision.allowed


def test_evaluate_news_focus_blocks_defense_cost_headline(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="미 국방장관 부유한 동맹국 방위비 내주던 시대 끝나",
        raw={"topic_group": "trend_meme", "content_angle": {"content_type": "trend_decode"}},
    )

    assert not decision.allowed
    assert decision.reason == "political_geopolitical_topic_blocked_for_news_focus"
    assert "국방장관" in decision.matched_terms


def test_evaluate_news_focus_allows_election_day_delivery_schedule(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="선거일 CJ 택배 배송 일정",
        raw={"topic_group": "refund_consumer", "content_angle": {"content_type": "consumer_warning"}},
    )

    assert decision.allowed


def test_evaluate_news_focus_blocks_foreign_admin_fee(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="日 외국인 체류자격 갱신 수수료 대폭 인상",
        raw={"topic_group": "delivery_money", "content_angle": {"content_type": "money_checklist"}},
    )

    assert not decision.allowed
    assert decision.reason == "foreign_admin_topic_blocked_for_news_focus"
    assert "체류자격" in decision.matched_terms


def test_evaluate_news_focus_blocks_harm_crime_headline(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="경북 상주서 일가족 3명 숨진 채 발견 경찰 조사",
        raw={"topic_group": "trend_meme", "content_angle": {"content_type": "trend_decode"}},
    )

    assert not decision.allowed
    assert decision.reason == "harm_crime_topic_blocked_for_news_focus"
    assert "숨진" in decision.matched_terms


def test_evaluate_news_focus_blocks_search_and_seizure_headline(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="속보 경찰 한화에어로스페이스 압수수색",
        raw={"topic_group": "refund_consumer", "content_angle": {"content_type": "consumer_warning"}},
    )

    assert not decision.allowed
    assert decision.reason == "harm_crime_topic_blocked_for_news_focus"
    assert "압수수색" in decision.matched_terms


def test_evaluate_news_focus_blocks_stalking_arrest_headline(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="[속보] 집 찾아가 '띵동띵동' 유명 유튜버 스토킹한 40대 여성 체포",
        raw={
            "source_type": "naver_trending",
            "topic_group": "entertainment_sports",
            "content_angle": {"content_type": "viral_issue_decode"},
            "click_potential_score": 9,
        },
    )

    assert not decision.allowed
    assert decision.reason == "harm_crime_topic_blocked_for_news_focus"
    assert "스토킹" in decision.matched_terms


def test_stalking_trending_candidate_is_not_boosted(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    candidate = MagicMock()
    candidate.topic = "[속보] 집 찾아가 유명 유튜버 스토킹한 40대 여성 체포"
    candidate.summary = "유튜버 스토킹 혐의로 체포된 사건"
    candidate.raw = {
        "trending_engine": True,
        "source_type": "naver_trending",
        "topic_group": "entertainment_sports",
        "content_angle": {"content_type": "viral_issue_decode"},
        "click_potential_score": 9,
    }
    scored = MagicMock()
    scored.candidate = candidate
    scored.total_score = 82
    scored.risk_penalty = 0

    boosted = NewsPipeline._apply_trending_score_boost([scored])[0]

    assert not NewsPipeline._is_news_auto_publish_candidate(scored)
    assert boosted.total_score == 82
    assert candidate.raw["trending_score_boost_skipped"] == "not_auto_publish_candidate"


def test_trending_ai_candidate_is_blocked_in_news_only_mode(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    candidate = MagicMock()
    candidate.topic = "ChatGPT vs Claude 새 AI 기능 비교"
    candidate.summary = "AI 생산성 도구 업데이트"
    candidate.raw = {
        "trending_engine": True,
        "source_type": "naver_trending",
        "topic_group": "platform_issue",
        "content_angle": {"content_type": "platform_change"},
    }
    scored = MagicMock()
    scored.candidate = candidate

    assert not NewsPipeline._is_news_focus_candidate(scored)
    assert NewsPipeline(dry_run=True)._handle_trending_candidate(scored) is None


def test_trending_political_candidate_is_blocked(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.delenv("ALLOW_POLITICAL_TODAY_ISSUES", raising=False)

    candidate = MagicMock()
    candidate.topic = "한강벨트 변심이 오세훈가 화제 된 이유, 사람들이 본 핵심 포인트"
    candidate.summary = "표심과 선거 구도에 대한 정치권 해석"
    candidate.raw = {
        "trending_engine": True,
        "source_type": "naver_trending",
        "topic_group": "ott_platform",
        "content_angle": {"content_type": "viral_issue_decode"},
        "click_potential_score": 10,
    }
    scored = MagicMock()
    scored.candidate = candidate

    assert not NewsPipeline._is_news_focus_candidate(scored)
    assert NewsPipeline(dry_run=True)._handle_trending_candidate(scored) is None


def test_trending_trend_decode_candidate_is_not_forced(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    candidate = MagicMock()
    candidate.topic = "무난한 SNS 트렌드"
    candidate.summary = "트렌드 해설"
    candidate.raw = {
        "trending_engine": True,
        "source_type": "naver_trending",
        "topic_group": "trend_meme",
        "content_angle": {"content_type": "trend_decode"},
        "click_potential_score": 10,
    }
    scored = MagicMock()
    scored.candidate = candidate

    assert not NewsPipeline._is_news_auto_publish_candidate(scored)
    assert NewsPipeline(dry_run=True)._handle_trending_candidate(scored) is None


def test_evaluate_news_focus_blocks_corporate_governance_gossip(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.delenv("ALLOW_CORPORATE_GOVERNANCE_TOPICS", raising=False)

    for topic in (
        "신동빈 롯데 회장 경영 행보",
        "재계는 지금 KT 요금제",
        "삼성전자 노사 18일 교섭 재개",
        "SK 오너 지분 매각",
        "이재용 삼성 회장 주주총회",
    ):
        decision = evaluate_news_focus(topic=topic)
        assert not decision.allowed, topic
        assert decision.reason == "corporate_governance_topic_blocked_for_news_focus"


def test_evaluate_news_focus_allows_product_and_consumer_news(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.delenv("ALLOW_CORPORATE_GOVERNANCE_TOPICS", raising=False)

    for topic in (
        "엔씨소프트 길드워3 공식 출시",
        "삼성 갤럭시 S26 신제품 공개",
        "배달앱 결제금액 비교 전에 확인할 조건",
        "선거일 CJ 택배 배송 일정",
        "쿠팡 로켓배송 정책 변경",
    ):
        decision = evaluate_news_focus(topic=topic)
        assert decision.allowed, topic


def test_evaluate_news_focus_corporate_block_can_be_overridden(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    monkeypatch.setenv("ALLOW_CORPORATE_GOVERNANCE_TOPICS", "true")

    decision = evaluate_news_focus(topic="삼성전자 노사 교섭 재개")
    assert decision.allowed


def test_ai_blog_mode_allows_ai_topic_without_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="OpenAI service change",
        raw={"topic_group": "platform_issue", "content_angle": {"content_type": "platform_change"}},
    )

    assert decision.allowed


def test_ai_blog_mode_blocks_non_ai_topic(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="스페이스X와 반도체 투자 이슈",
        raw={"topic_group": "today_issue", "content_angle": {"content_type": "today_issue_explainer"}},
    )

    assert not decision.allowed
    assert decision.reason == "non_ai_topic_blocked_for_ai_blog_mode"


def test_ai_blog_mode_does_not_allow_only_ai_query_group(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="퇴근길 7분 뉴스 확인 전에 볼 주의점",
        summary="월드컵과 투자 이슈를 묶은 일반 뉴스 요약",
        raw={
            "query_group": "ai_work",
            "topic_group": "refund_consumer",
            "content_angle": {"content_type": "consumer_warning"},
        },
    )

    assert not decision.allowed
    assert decision.reason == "non_ai_topic_blocked_for_ai_blog_mode"


def test_ai_blog_mode_blocks_non_ai_trending_candidate(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    candidate = MagicMock()
    candidate.topic = "스페이스X와 반도체 투자 이슈"
    candidate.summary = "기업 투자 관련 오늘 이슈"
    candidate.raw = {
        "trending_engine": True,
        "source_type": "naver_trending",
        "topic_group": "today_issue",
        "content_angle": {"content_type": "today_issue_explainer"},
    }
    scored = MagicMock()
    scored.candidate = candidate

    assert not NewsPipeline._is_news_focus_candidate(scored)
    assert NewsPipeline(dry_run=True)._handle_trending_candidate(scored) is None


def test_ai_blog_mode_skips_clean_trending_pipeline(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")

    def _should_not_collect(self):  # noqa: ANN001
        raise AssertionError("clean_trending collection should be skipped in AI blog mode")

    monkeypatch.setattr(NewsPipeline, "_collect_clean_trending_candidates", _should_not_collect)

    assert NewsPipeline(dry_run=True)._run_clean_trending_publish() is None


def test_ai_blog_mode_still_blocks_political_headline(monkeypatch) -> None:
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)

    decision = evaluate_news_focus(
        topic="[속보] AI 대통령 사전투표 참여 독려",
        raw={"topic_group": "ai_work", "content_angle": {"content_type": "ai_work_tip"}},
    )

    assert not decision.allowed
    assert decision.reason == "political_geopolitical_topic_blocked_for_news_focus"
