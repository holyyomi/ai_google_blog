from __future__ import annotations

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.news_scoring_service import NewsScoringService
from blogspot_automation.services.reader_interest_brief_service import ReaderInterestBriefService


def test_privacy_issue_gets_actionable_reader_interest_brief() -> None:
    brief = ReaderInterestBriefService.build(
        topic="티빙 개인정보 유출 비밀번호 변경 안내 후 확인할 것",
        summary="ID 이름 연락처 유출 이후 비밀번호 변경과 피싱 주의가 필요하다.",
        topic_group="privacy_security",
        content_type="consumer_warning",
        raw={
            "click_potential_score": 9,
            "reader_search_questions": [
                "티빙 개인정보 유출 뒤 비밀번호만 바꾸면 되나요?",
                "같은 비밀번호를 쓴 계정도 확인해야 하나요?",
                "피싱 문자를 어떻게 구분하나요?",
            ],
            "search_demand_topic": "티빙 개인정보 유출 비밀번호 변경 안내 후 확인할 것",
            "reader_benefit": "유출 항목, 비밀번호 변경, 2차 인증, 공식 신고 채널 확인 순서를 얻는다.",
            "practical_value_score": 14,
        },
    )

    assert brief["reader_interest_score"] >= 75
    assert brief["strategy"] in {"risk_checklist", "save_value_first"}
    assert "계정 보안" in brief["save_asset"]
    assert "비밀번호" in brief["primary_reader_question"]


def test_generic_viral_formula_is_penalized_but_click_topic_can_still_be_click_first() -> None:
    brief = ReaderInterestBriefService.build(
        topic="OTT 화제 된 이유 사람들이 본 핵심 포인트",
        summary="반응이 갈린 이유와 핵심 포인트를 반복 설명한다.",
        topic_group="ott_platform",
        content_type="viral_issue_decode",
        raw={
            "click_potential_score": 10,
            "today_buzz_score": 8,
            "source_count": 4,
            "search_demand_topic": "OTT 신작 반응이 갈린 이유",
            "reader_search_questions": ["OTT 신작 반응이 왜 갈렸나요?", "보기 전에 무엇을 봐야 하나요?"],
        },
    )

    assert brief["generic_penalty"] > 0
    assert brief["publish_intent"] in {"publishable", "click_first"}
    assert brief["curiosity_score"] >= 20


def test_scoring_adds_reader_interest_brief_to_raw_and_selection_score() -> None:
    candidate = NewsCandidate(
        topic="티빙, ID·이름·전화번호 유출 비밀번호 변경 권장",
        category="life",
        summary="이용자들이 같은 비밀번호 계정과 피싱 문자를 우려하고 있다.",
        raw={"query_group": "platform_consumer", "source_type": "google_news_rss"},
    )

    scored = NewsScoringService().score_candidates([candidate])[0]
    raw = scored.candidate.raw

    assert raw["reader_interest_score"] >= 60
    assert isinstance(raw["reader_interest_brief"], dict)
    assert raw["reader_interest_brief"]["primary_reader_question"]
    assert NewsPipeline._candidate_click_selection_score(scored) > 0
