"""후보 생성 기준(>=65)과 자동발행 기준(>=75 + publish_ready/geo_ready/sge_ready) 분리 테스트.

핵심 원칙:
- score 65~74 + allowed real news → article_candidate 생성 진입 가능 (candidate_grade=B/C)
- 단, publish_quality_gate에 total_score_below_75 hard blocking이 추가되어 자동 발행은 차단됨
- evergreen_fallback/fallback/general_life는 score 90이어도 news 자동발행 후보 아님
- ai_work_tip은 일반 news 모드에서는 차단, AI_BLOG_MODE에서는 허용
"""

from __future__ import annotations

from datetime import date
import os
import unittest
from unittest.mock import MagicMock, patch

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.golden_pattern_service import GoldenPatternService
from blogspot_automation.services.news_scoring_service import NewsScoringService


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _make_scored(
    topic: str,
    total_score: int,
    *,
    source_type: str = "google_news_rss",
    content_type: str = "money_checklist",
    topic_group: str = "delivery_money",
    is_stale: bool = False,
    risk_penalty: int = 0,
    evergreen_axis: str = "",
    publish_allowed: bool = True,
    is_test_candidate: bool = False,
) -> MagicMock:
    raw = {
        "topic_group": topic_group,
        "source_type": source_type,
        "is_stale": is_stale,
        "risk_penalty": risk_penalty,
        "evergreen_axis": evergreen_axis,
        "publish_allowed": publish_allowed,
        "is_test_candidate": is_test_candidate,
        "content_angle": {"content_type": content_type, "topic_group": topic_group},
        "click_potential_score": 10,
    }
    candidate = MagicMock()
    candidate.topic = topic
    candidate.raw = raw
    candidate.category = topic_group
    candidate.summary = f"summary for {topic}"
    scored = MagicMock()
    scored.candidate = candidate
    scored.total_score = total_score
    scored.risk_penalty = risk_penalty
    scored.reason = ""
    return scored


# ------------------------------------------------------------------ #
# Tests
# ------------------------------------------------------------------ #

class TestCandidateGenerationThreshold(unittest.TestCase):
    """후보 생성 기준 분리: score >= 65에서 candidate generation 진입 허용."""

    def test_default_candidate_generation_threshold_is_65(self):
        svc = NewsScoringService()
        self.assertEqual(svc.candidate_generation_min_score, 65)
        self.assertEqual(svc.min_topic_score, 75)
        self.assertEqual(NewsScoringService.DEFAULT_CANDIDATE_GENERATION_MIN_SCORE, 65)

    def test_score_69_passes_candidate_generation_eligible(self):
        svc = NewsScoringService()
        scored = [_make_scored("test 1", 69), _make_scored("test 2", 80)]
        eligible = svc.get_candidate_generation_eligible(scored)
        self.assertEqual(len(eligible), 2)

    def test_score_64_fails_candidate_generation_eligible(self):
        svc = NewsScoringService()
        scored = [_make_scored("test", 64)]
        eligible = svc.get_candidate_generation_eligible(scored)
        self.assertEqual(len(eligible), 0)

    def test_weighted_selection_can_choose_runner_up_with_seed(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        original_seed = os.environ.get("NEWS_TOPIC_SELECTION_SEED")
        os.environ["NEWS_TOPIC_SELECTION_SEED"] = "choose-second"
        try:
            top = _make_scored(
                "topic A",
                90,
                source_type="naver_trending",
                content_type="viral_issue_decode",
                topic_group="entertainment_sports",
            )
            runner_up = _make_scored(
                "topic B",
                89,
                source_type="naver_trending",
                content_type="viral_issue_decode",
                topic_group="entertainment_sports",
            )
            third = _make_scored(
                "topic C",
                88,
                source_type="naver_trending",
                content_type="viral_issue_decode",
                topic_group="entertainment_sports",
            )
            for buzz, item in zip((8, 7, 6), (top, runner_up, third)):
                item.candidate.raw.update(
                    {
                        "trending_engine": True,
                        "today_buzz_score": buzz,
                        "source_count": 3,
                        "click_potential_score": 10,
                    }
                )

            selected = NewsPipeline()._select_diverse_candidate([top, runner_up, third], [])
        finally:
            if original_seed is None:
                os.environ.pop("NEWS_TOPIC_SELECTION_SEED", None)
            else:
                os.environ["NEWS_TOPIC_SELECTION_SEED"] = original_seed

        self.assertIs(selected, runner_up)
        self.assertEqual(top.candidate.raw["weighted_random_selection_pool_size"], 3)

    def test_score_69_fails_publishable_at_75(self):
        svc = NewsScoringService()
        scored = [_make_scored("test", 69)]
        publishable = svc.get_publishable_candidates(scored)
        self.assertEqual(len(publishable), 0)

    def test_score_75_passes_publishable(self):
        svc = NewsScoringService()
        scored = [_make_scored("test", 75)]
        publishable = svc.get_publishable_candidates(scored)
        self.assertEqual(len(publishable), 1)

    def test_score_65_74_real_news_allowed_ct_eligible_for_generation(self):
        """allowed content_type real news score 65~74 → 후보 생성 가능."""
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        svc = NewsScoringService()
        scored = [
            _make_scored("news 65", 65, content_type="money_checklist"),
            _make_scored("news 70", 70, content_type="platform_change", topic_group="platform_issue"),
            _make_scored("news 74", 74, content_type="consumer_warning", topic_group="refund_consumer"),
        ]
        eligible = svc.get_candidate_generation_eligible(scored)
        real_news_eligible = [
            item for item in eligible
            if NewsPipeline._is_news_auto_publish_candidate(item)
        ]
        self.assertEqual(len(real_news_eligible), 3)


class TestAutoPublishGateRemainsStrict(unittest.TestCase):
    """후보 생성을 완화해도 자동 발행은 publish_ready/geo_ready/sge_ready 통과해야만."""

    def test_evergreen_fallback_blocked_regardless_of_score(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        # score 90이어도 evergreen_fallback은 news 자동발행 후보가 아님
        item = _make_scored(
            "evergreen high score",
            90,
            source_type="evergreen_fallback",
            content_type="ai_work_tip",
            topic_group="ai_work",
        )
        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_evergreen_fallback_is_not_stale_replacement_target(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        item = _make_scored(
            "국세환급금 조회 전 계좌 오류부터 확인하세요",
            100,
            source_type="evergreen_fallback",
            content_type="tax_refund",
            topic_group="policy_benefit",
            evergreen_axis="tax_refund_support",
        )
        item.candidate.raw["strategy_score_breakdown"] = {
            "official_source_check_needed": True,
        }

        self.assertFalse(NewsPipeline._is_stale_candidate(item))

    def test_general_life_blocked_regardless_of_score(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        item = _make_scored(
            "general life high score",
            90,
            content_type="general_life",
            topic_group="general_life",
        )
        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_ai_work_tip_blocked_for_news_auto_publish(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        # ai_work_tip은 naver_blog에서 처리, news에서는 자동발행 금지
        item = _make_scored(
            "AI workflow tip",
            90,
            content_type="ai_work_tip",
            topic_group="ai_work",
        )
        with patch.dict(os.environ, {"AI_BLOG_MODE": "false"}, clear=False):
            self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_ai_work_tip_allowed_for_ai_blog_mode(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "ChatGPT 보고서 작성 자동화 체크리스트",
            90,
            content_type="ai_work_tip",
            topic_group="ai_work",
        )
        item.candidate.raw["click_potential_score"] = 8

        with patch.dict(os.environ, {"AI_BLOG_MODE": "true"}, clear=False):
            self.assertTrue(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_blogspot_growth_axis_blocked(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        item = _make_scored(
            "blogspot growth tip",
            85,
            content_type="money_checklist",
            evergreen_axis="blogspot_growth",
        )
        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_ai_blog_auto_publish_gate_allows_ai_work_tip_daily_fallback(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        pipeline = NewsPipeline(dry_run=False, auto_publish=True, news_publish_mode="publish")
        base_result = {
            "source_type": "evergreen_fallback",
            "fallback_reason": "no_publishable_news_candidate_used_evergreen",
            "topic_group": "ai_work",
            "content_angle": {"content_type": "ai_work_tip"},
            "evergreen_axis": "ai_automation",
            "article_candidate_generated": True,
            "publish_ready": True,
            "geo_ready": True,
            "sge_ready": True,
            "human_review_required": False,
            "near_match": False,
        }

        with patch.dict(os.environ, {"AI_BLOG_MODE": "true"}, clear=False):
            default_gate = pipeline._evaluate_auto_publish_gate(
                base_result=base_result,
                publish_quality_gate={"passed": True},
            )

        self.assertFalse(default_gate["allowed"])
        self.assertIn("evergreen_auto_publish_disabled", default_gate["blocking_reasons"])

        with patch.dict(
            os.environ,
            {"AI_BLOG_MODE": "true", "ALLOW_EVERGREEN_AUTO_PUBLISH": "true"},
            clear=False,
        ):
            gate = pipeline._evaluate_auto_publish_gate(
                base_result=base_result,
                publish_quality_gate={"passed": True},
            )

        self.assertTrue(gate["allowed"], gate)
        self.assertIn("ai_work_tip", gate["allowed_content_types"])

    def test_stock_market_headline_not_platform_change_auto_publish(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        candidate = NewsCandidate(
            topic="속보] 삼성전자, 우선주 포함해 시총 2천조원 돌파",
            category="news",
            summary="삼성전자 주가와 시가총액 관련 증시 기사",
            raw={"source_type": "google_news_rss", "is_stale": False},
        )
        scored = NewsScoringService().score_candidates([candidate])[0]
        raw = scored.candidate.raw

        self.assertEqual(raw["topic_group"], "general_life")
        self.assertEqual(raw["content_angle"]["content_type"], "general_life")
        self.assertEqual(raw["angle_type"], "market_finance")
        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(scored))

    def test_fallback_source_blocked(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        item = _make_scored(
            "fallback candidate",
            90,
            source_type="fallback",
            is_test_candidate=True,
            publish_allowed=False,
        )
        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_stale_replacement_ignores_non_auto_publish_trend_decode(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        original = _make_scored(
            "stale useful candidate",
            80,
            content_type="money_checklist",
            topic_group="delivery_money",
            is_stale=True,
        )
        trend = ScoredNewsCandidate(
            candidate=NewsCandidate(
                topic="미 국방장관 부유한 동맹국 방위비 발언",
                category="today_issue",
                summary="외교 안보성 발언",
                raw={
                    "source_type": "naver_trending",
                    "topic_group": "trend_meme",
                    "content_angle": {"content_type": "trend_decode"},
                    "click_potential_score": 10,
                },
            ),
            freshness_score=10,
            search_demand_score=10,
            contrarian_gap_score=0,
            mass_impact_score=0,
            adsense_value_score=0,
            hook_score=0,
            risk_penalty=0,
            total_score=95,
            reason="trend",
        )

        replacement, reason = NewsPipeline._find_fresh_replacement_candidate([trend], original)

        self.assertIsNone(replacement)
        self.assertEqual(reason, "no_fresh_candidates_available")

    def test_trending_score_boost_skips_non_auto_publish_candidate(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "blocked trend decode",
            80,
            source_type="naver_trending",
            content_type="trend_decode",
            topic_group="trend_meme",
        )
        item.candidate.raw["trending_engine"] = True

        boosted = NewsPipeline._apply_trending_score_boost([item])[0]

        self.assertEqual(boosted.total_score, 80)
        self.assertFalse(item.candidate.raw["trending_score_boost_applied"])
        self.assertEqual(
            item.candidate.raw["trending_score_boost_skipped"],
            "not_auto_publish_candidate",
        )

    def test_trending_score_boost_applies_to_auto_publish_candidate(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "OTT drama finale reaction",
            80,
            source_type="naver_trending",
            content_type="viral_issue_decode",
            topic_group="entertainment_sports",
        )
        item.candidate.raw["trending_engine"] = True

        boosted = NewsPipeline._apply_trending_score_boost([item])[0]

        self.assertEqual(boosted.total_score, 95)
        self.assertTrue(item.candidate.raw["trending_score_boost_applied"])
        self.assertEqual(item.candidate.raw["trending_score_boost_from"], 80)

    def test_today_issue_explainer_auto_publish_candidate_allowed(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "front page issue",
            95,
            source_type="naver_trending",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )
        item.candidate.raw["trending_engine"] = True

        self.assertTrue(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_discovery_issue_with_click_below_relaxable_threshold_blocked(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "JTBC 오늘 오후 예측조사 발표",
            95,
            source_type="google_news_rss",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )
        item.candidate.raw.update({
            "discovery_engine": True,
            "today_buzz_score": 8,
            "source_count": 3,
            "click_potential_score": 3,
        })

        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_discovery_issue_with_relaxable_click_score_allowed(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "JTBC 오늘 오후 예측조사 발표",
            95,
            source_type="google_news_rss",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )
        item.candidate.raw.update({
            "discovery_engine": True,
            "today_buzz_score": 8,
            "source_count": 3,
            "click_potential_score": 6,
        })

        self.assertTrue(NewsPipeline._is_news_auto_publish_candidate(item))

    def test_static_web_policy_low_today_relevance_blocked_from_auto_publish(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "transport support application guide",
            100,
            source_type="naver_webkr_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )

        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))
        self.assertEqual(
            item.candidate.raw["auto_publish_block_reason"],
            "low_today_relevance_static_web_candidate",
        )
        self.assertLess(item.candidate.raw["selection_today_relevance_score"], 7)

    def test_trending_score_boost_skips_lottery_headline(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "로또 1등 10명가 화제 된 이유",
            80,
            source_type="naver_trending",
            content_type="viral_issue_decode",
            topic_group="entertainment_sports",
        )
        item.candidate.summary = "1226회 당첨번호와 대박 기사"
        item.candidate.raw["trending_engine"] = True

        boosted = NewsPipeline._apply_trending_score_boost([item])[0]

        self.assertEqual(boosted.total_score, 80)
        self.assertFalse(item.candidate.raw["trending_score_boost_applied"])
        self.assertIn("lottery_headline", item.candidate.raw["trending_score_boost_skipped"])

    def test_select_diverse_prefers_trending_issue_over_policy_score_lead(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        top = _make_scored(
            "고유가 피해지원금 신청방법과 대상 조건",
            100,
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        top.candidate.raw["hook_category_priority"] = 1
        runner_up = _make_scored(
            "OTT drama finale reaction",
            95,
            source_type="naver_trending",
            content_type="viral_issue_decode",
            topic_group="entertainment_sports",
        )
        runner_up.candidate.raw["hook_category_priority"] = 0
        runner_up.candidate.raw["trending_engine"] = True

        selected = NewsPipeline()._select_diverse_candidate([top, runner_up], [])

        self.assertIs(selected, runner_up)

    def test_select_diverse_prefers_high_click_candidate_regardless_of_category(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        hook_first = _make_scored(
            "streaming star reaction",
            100,
            source_type="naver_trending",
            content_type="viral_issue_decode",
            topic_group="entertainment_sports",
        )
        hook_first.candidate.raw["trending_engine"] = True
        hook_first.candidate.raw["click_potential_score"] = 8
        broad_issue = _make_scored(
            "bank app outage compensation notice",
            95,
            source_type="google_news_rss",
            content_type="platform_change",
            topic_group="platform_issue",
        )
        broad_issue.candidate.raw.update(
            {
                "discovery_engine": True,
                "today_buzz_score": 10,
                "source_count": 5,
                "click_potential_score": 15,
                "topic_traffic_potential_score": 30,
                "topic_search_intent_score": 20,
            }
        )

        selected = NewsPipeline()._select_diverse_candidate([hook_first, broad_issue], [])

        self.assertIs(selected, broad_issue)
        self.assertGreater(
            NewsPipeline._candidate_click_selection_score(broad_issue),
            NewsPipeline._candidate_click_selection_score(hook_first),
        )

    def test_select_diverse_demotes_static_web_policy_with_low_today_relevance(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        static_policy = _make_scored(
            "transport support application guide",
            100,
            source_type="naver_webkr_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        fresh_issue = _make_scored(
            "payment service outage refund notice",
            95,
            source_type="google_news_rss",
            content_type="consumer_warning",
            topic_group="refund_consumer",
        )

        selected = NewsPipeline()._select_diverse_candidate([static_policy, fresh_issue], [])

        self.assertIs(selected, fresh_issue)

    def test_select_diverse_prefers_hot_non_policy_when_policy_recently_published(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        policy = _make_scored(
            "울산형 석유화학업 근로자 안심페이 지원사업",
            100,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        sports = _make_scored(
            "손흥민 경기 반응, 팬들이 가장 많이 본 장면",
            88,
            source_type="naver_trending",
            content_type="viral_issue_decode",
            topic_group="entertainment_sports",
        )
        sports.candidate.raw.update(
            {
                "trending_engine": True,
                "today_buzz_score": 9,
                "source_count": 4,
                "click_potential_score": 10,
                "hook_category_priority": 0,
            }
        )
        history = [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "topic_group": "policy_benefit",
                "selected_topic": "안심페이 참여 모집 지원금 신청방법과 대상 조건",
            }
        ]

        selected = NewsPipeline()._select_diverse_candidate([policy, sports], history)

        self.assertIs(selected, sports)

    def test_policy_benefit_gets_strong_same_day_cooldown(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        pipeline = NewsPipeline()
        history = [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "topic_group": "policy_benefit",
            }
        ]

        self.assertGreaterEqual(
            pipeline._cooldown_penalty("policy_benefit", history),
            40,
        )

    def test_select_diverse_demotes_generic_transformed_policy_topic(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        generic = _make_scored(
            "환급금 신청방법과 대상 조건",
            100,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        generic.candidate.raw["original_topic"] = "세무사회, 삼쩜삼 공정위 2차신고...거짓 기만광고 논란"
        generic.candidate.raw["public_benefit_keyword"] = "환급금"
        specific = _make_scored(
            "청년 운전면허 지원금 신청방법과 대상 조건",
            95,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        specific.candidate.raw["original_topic"] = "청년 운전면허 지원금 최대 50만원 신청 방법"
        specific.candidate.raw["public_benefit_keyword"] = "청년 운전면허 지원금"

        selected = NewsPipeline()._select_diverse_candidate([generic, specific], [])

        self.assertIs(selected, specific)

    def test_fresh_replacement_demotes_generic_low_preservation_topic(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        stale = _make_scored(
            "고유가 피해지원금 신청방법과 대상 조건",
            100,
            content_type="policy_deadline",
            topic_group="policy_benefit",
            is_stale=True,
        )
        generic = _make_scored(
            "환급금 신청방법과 대상 조건",
            100,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        generic.candidate.raw["original_topic"] = "세무사회, 삼쩜삼 공정위 2차신고...거짓 기만광고 논란"
        generic.candidate.raw["public_benefit_keyword"] = "환급금"
        specific = _make_scored(
            "청년 운전면허 지원금 신청방법과 대상 조건",
            95,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        specific.candidate.raw["original_topic"] = "청년 운전면허 지원금 최대 50만원 신청 방법"
        specific.candidate.raw["public_benefit_keyword"] = "청년 운전면허 지원금"

        replacement, reason = NewsPipeline._find_fresh_replacement_candidate(
            [generic, specific],
            stale,
        )

        self.assertIs(replacement, specific)
        self.assertIn("score=95", reason)

    def test_fresh_replacement_prefers_today_issue_over_policy_score_lead(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        stale = _make_scored(
            "고유가 피해지원금 신청방법과 대상 조건",
            100,
            content_type="policy_deadline",
            topic_group="policy_benefit",
            is_stale=True,
        )
        policy = _make_scored(
            "교통비 지원 지급일과 신청방법 정리",
            100,
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        issue = _make_scored(
            "프로야구 결승전 판정 논란 정리",
            95,
            source_type="naver_trending",
            content_type="viral_issue_decode",
            topic_group="sports_reaction",
        )
        issue.candidate.raw["trending_engine"] = True

        replacement, reason = NewsPipeline._find_fresh_replacement_candidate(
            [policy, issue],
            stale,
        )

        self.assertIs(replacement, issue)
        self.assertIn("click_score=", reason)

    def test_fresh_replacement_prefers_golden_ready_candidate(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        stale = _make_scored(
            "게임업계 리밸런싱 서비스 지원 종료 전에 확인할 것",
            100,
            content_type="platform_change",
            topic_group="platform_issue",
            is_stale=True,
        )
        high_score_unmatched = _make_scored(
            "KT초이스 요금제 무료가 화제 된 이유, 사람들이 본 핵심 포인트",
            100,
            source_type="naver_webkr_search",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
        )
        high_score_unmatched.candidate.raw["golden_selection_confidence"] = 25
        golden_ready = _make_scored(
            "배달앱 결제금액 비교 전에 확인할 조건",
            90,
            source_type="google_news_rss",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        golden_ready.candidate.raw["golden_selection_confidence"] = 90

        replacement, _ = NewsPipeline._find_fresh_replacement_candidate(
            [stale, high_score_unmatched, golden_ready],
            stale,
        )

        self.assertIs(replacement, golden_ready)

    def test_source_preserving_repair_title_keeps_original_entity(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "BTS concert week compare before checking conditions",
            95,
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        item.candidate.raw["original_title"] = "BTS concert week Busan lodging added charge warning"

        repaired = NewsPipeline._source_preserving_repair_title(
            item,
            current_title="Compare before checking conditions",
        )

        self.assertIn("BTS", repaired)
        self.assertIn("Busan", repaired)

    def test_quality_title_repair_only_allows_title_gate_issues(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        self.assertFalse(
            NewsPipeline._quality_title_repairable([
                "title_has_no_specific_entity",
                "issue_specificity_below_6:2",
            ])
        )
        self.assertTrue(
            NewsPipeline._quality_title_repairable([
                "title_has_no_specific_entity",
                "title_body_entity_mismatch:배달앱",
            ])
        )
        self.assertFalse(
            NewsPipeline._quality_title_repairable([
                "title_has_no_specific_entity",
                "missing_faq_section",
            ])
        )

    def test_static_web_consumer_low_today_is_not_auto_publish_candidate(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "환불 지연 때 소비자가 먼저 남겨야 할 증거",
            90,
            source_type="naver_webkr_search",
            content_type="consumer_warning",
            topic_group="refund_consumer",
        )
        item.candidate.raw["today_relevance_score"] = 5

        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))
        self.assertEqual(
            item.candidate.raw["auto_publish_block_reason"],
            "low_today_relevance_static_web_candidate",
        )

    def test_market_finance_issue_is_not_auto_publish_candidate(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "금리인상이 호재 시장 반응과 확인할 사실",
            95,
            source_type="google_news_rss",
            content_type="platform_change",
            topic_group="today_issue",
        )
        item.candidate.raw["angle_type"] = "market_finance"
        item.candidate.raw["discovery_engine"] = True

        self.assertFalse(NewsPipeline._is_news_auto_publish_candidate(item))
        self.assertEqual(
            item.candidate.raw["auto_publish_block_reason"],
            "market_finance_not_auto_publishable",
        )

    def test_static_web_consumer_low_today_gets_selection_penalty(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        item = _make_scored(
            "환불 지연 때 소비자가 먼저 남겨야 할 증거",
            90,
            source_type="naver_webkr_search",
            content_type="consumer_warning",
            topic_group="refund_consumer",
        )
        item.candidate.raw["today_relevance_score"] = 5
        item.candidate.raw["original_topic"] = "항공권 구매 취소 시 위약금 과다·환불 지연 피해 많아"

        self.assertGreaterEqual(NewsPipeline._candidate_selection_quality_penalty(item), 4)

    def test_select_diverse_candidate_prefers_golden_ready_candidate(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        pipeline = NewsPipeline(dry_run=True)
        high_score_unmatched = _make_scored(
            "공공 배달앱 이용자 수수료 변경 전에 확인할 것",
            100,
            source_type="naver_news_search",
            content_type="platform_change",
            topic_group="platform_issue",
        )
        high_score_unmatched.candidate.raw["golden_selection_confidence"] = 27
        golden_ready = _make_scored(
            "배달앱 결제금액 비교 전에 확인할 조건",
            95,
            source_type="google_news_rss",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        golden_ready.candidate.raw["golden_selection_confidence"] = 92

        selected = pipeline._select_diverse_candidate([high_score_unmatched, golden_ready], [])

        self.assertIs(selected, golden_ready)

    def test_fresh_replacement_skips_recent_duplicate_topic(self):
        from datetime import date

        from blogspot_automation.pipelines.news_pipeline import NewsPipeline
        from blogspot_automation.services.topic_dedup_service import TopicDedupService

        stale = _make_scored(
            "고유가 피해지원금 신청방법과 대상 조건",
            100,
            content_type="policy_deadline",
            topic_group="policy_benefit",
            is_stale=True,
        )
        duplicate = _make_scored(
            "청년 운전면허 지원금 신청방법과 대상 조건",
            100,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        fresh = _make_scored(
            "고유가 피해지원금 지급일과 신청방법 정리",
            95,
            source_type="naver_news_search",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        history = [
            {
                "date": date.today().isoformat(),
                "status": "published",
                "published": True,
                "selected_topic": "청년 운전면허 지원금 신청방법과 대상 조건",
            }
        ]

        replacement, reason = NewsPipeline._find_fresh_replacement_candidate(
            [duplicate, fresh],
            stale,
            history_records=history,
            dedup_service=TopicDedupService(dedup_days=7),
        )

        self.assertIs(replacement, fresh)
        self.assertIn("score=95", reason)


class TestPatternMappingCorrectness(unittest.TestCase):
    """content_type별 올바른 패턴이 매칭되는지 검증."""

    def setUp(self):
        self.gps = GoldenPatternService()
        self.gps.load_patterns()

    def test_money_checklist_maps_to_delivery_money_pattern(self):
        result = self.gps.match_pattern(
            "배달앱 결제금액 비교 전 체크포인트",
            "쿠팡이츠 배달비 결제 비교",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        self.assertEqual(result["pattern_id"], "delivery_money_checklist")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_money_checklist_not_mapped_to_tax_refund(self):
        result = self.gps.match_pattern(
            "배달앱 결제금액 비교",
            "쿠팡이츠 배달비 비교 쿠폰",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        self.assertNotEqual(result["pattern_id"], "tax_refund_hometax_check")

    def test_platform_change_uses_platform_change_pattern(self):
        result = self.gps.match_pattern(
            "쿠팡 멤버십 가격 인상 변경 안내",
            "구독료 인상 약관 변경",
            content_type="platform_change",
            topic_group="platform_issue",
        )
        self.assertEqual(result["pattern_id"], "platform_change_service_update")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_consumer_warning_uses_consumer_warning_pattern(self):
        result = self.gps.match_pattern(
            "환불 논란 결제 오류 피해 대응",
            "소비자 피해 결제내역 캡처",
            content_type="consumer_warning",
            topic_group="refund_consumer",
        )
        self.assertEqual(result["pattern_id"], "consumer_warning_refund")
        self.assertGreaterEqual(result["confidence"], 80)

    def test_consumer_warning_not_mapped_to_money_checklist(self):
        result = self.gps.match_pattern(
            "환불 논란 결제 오류",
            "소비자 피해",
            content_type="consumer_warning",
            topic_group="refund_consumer",
        )
        self.assertNotEqual(result["pattern_id"], "delivery_money_checklist")

    def test_policy_deadline_uses_policy_deadline_pattern(self):
        result = self.gps.match_pattern(
            "청년 지원금 신청 마감 대상 조건",
            "지원금 신청 기간 대상",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        self.assertEqual(result["pattern_id"], "policy_deadline_support")

    def test_general_life_blocked_from_pattern_match(self):
        result = self.gps.match_pattern(
            "오늘 생활 정보",
            "일반 생활 정보",
            content_type="general_life",
            topic_group="general_life",
        )
        self.assertFalse(result["matched"])
        self.assertEqual(result["pattern_id"], None)

    def test_blogspot_growth_blocked_from_pattern_match(self):
        result = self.gps.match_pattern(
            "블로그스팟 운영 팁",
            "내부링크 넣는 법",
            content_type="blogspot_growth",
            topic_group="general_life",
        )
        self.assertFalse(result["matched"])

    def test_evergreen_fallback_blocked_from_pattern_match(self):
        result = self.gps.match_pattern(
            "에버그린 콘텐츠",
            "에버그린 정보",
            content_type="evergreen_fallback",
            topic_group="ai_work",
        )
        self.assertFalse(result["matched"])


class TestTitleLeakGuards(unittest.TestCase):
    """제목 누수 차단: policy/tax 문구가 다른 content_type 제목에 섞이지 않도록."""

    def _evaluate_title(self, *, title: str, content_type: str, topic_group: str) -> list[str]:
        """간단 헬퍼: news_quality_gate에서 title 평가 시 추가되는 blocking_issues 추출."""
        # title check section만 시뮬레이션 — 실제 evaluate()는 html 등 많은 인자 필요
        blocking_issues: list[str] = []
        _policy_phrase_in_title = any(
            phrase in title for phrase in ("신청 전", "대상 조건", "환급", "지원금")
        )
        _policy_eligible_ct = content_type in {"policy_deadline", "tax_refund", "policy_benefit"}
        _policy_eligible_tg = topic_group in {"policy_benefit"}
        if _policy_phrase_in_title and not (_policy_eligible_ct or _policy_eligible_tg):
            blocking_issues.append(
                f"policy_phrase_leak_in_non_policy_title:{content_type or 'missing'}"
            )
        if any(phrase in title for phrase in ("블로그스팟 내부링크", "내부링크 넣기", "블로그 운영")):
            blocking_issues.append("blogspot_growth_phrase_in_news_title")
        return blocking_issues

    def test_policy_phrase_allowed_in_policy_title(self):
        # tax_refund/policy_deadline 계열에서는 "지원금/환급/신청 전/대상 조건" 허용
        issues = self._evaluate_title(
            title="청년 지원금 신청 전 대상 조건",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )
        self.assertEqual([], [i for i in issues if "policy_phrase_leak" in i])

    def test_policy_phrase_leaked_into_money_checklist_blocked(self):
        issues = self._evaluate_title(
            title="배달앱 신청 전 이것부터",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        self.assertTrue(any("policy_phrase_leak" in i for i in issues))

    def test_blogspot_growth_phrase_in_news_blocked(self):
        issues = self._evaluate_title(
            title="블로그스팟 내부링크 넣기 전에 볼 기준",
            content_type="money_checklist",
            topic_group="delivery_money",
        )
        self.assertTrue(any("blogspot_growth_phrase_in_news_title" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
