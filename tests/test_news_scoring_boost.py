"""Fresh news candidate generation boost 회귀 테스트.

목표:
- google_news_rss + allowed_ct + fresh + risk=0 후보는 +5~+11 boost
- evergreen_fallback / fallback / stale / risk>0 / commercial_support은 boost=0
- consumer_warning은 추가 +3 boost (체감 점수가 낮은 카테고리)
- viral_issue_decode는 추가 +1 boost
"""

from __future__ import annotations

import unittest

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.news_scoring_service import NewsScoringService


def _candidate(
    *,
    topic: str = "오늘 배달앱 결제금액 비교 전 확인할 조건",
    summary: str = "쿠팡이츠 배달비 비교, 쿠폰 적용 시 최종 결제금액 확인 방법",
    category: str = "delivery_money",
    source_type: str = "google_news_rss",
    is_stale: bool = False,
    evergreen_axis: str = "",
) -> NewsCandidate:
    return NewsCandidate(
        topic=topic,
        category=category,
        summary=summary,
        source_hint=None,
        published_at="2026-05-13T00:00:00+00:00",
        url="https://example.com",
        raw={
            "source_type": source_type,
            "is_stale": is_stale,
            "query_group": "money_life",
            "evergreen_axis": evergreen_axis,
        },
    )


class TestFreshNewsCandidateBoost(unittest.TestCase):
    """boost 동작 검증."""

    def test_fresh_money_checklist_gets_boost(self):
        sc = NewsScoringService()
        scored = sc.score_candidates([_candidate()])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        self.assertGreaterEqual(sb["fresh_news_candidate_boost"], 5)

    def test_evergreen_fallback_gets_no_boost(self):
        sc = NewsScoringService()
        cand = _candidate(source_type="evergreen_fallback")
        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        self.assertEqual(sb["fresh_news_candidate_boost"], 0)

    def test_fallback_source_gets_no_boost(self):
        sc = NewsScoringService()
        cand = _candidate(source_type="fallback")
        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        self.assertEqual(sb["fresh_news_candidate_boost"], 0)

    def test_stale_gets_no_boost(self):
        sc = NewsScoringService()
        cand = _candidate(is_stale=True)
        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        self.assertEqual(sb["fresh_news_candidate_boost"], 0)

    def test_consumer_warning_gets_extra_boost(self):
        sc = NewsScoringService()
        cand = _candidate(
            topic="환불 논란 결제 오류 피해 대응 체크리스트",
            summary="개인정보 유출 약관 변경 결제 피해 신고",
            category="refund_consumer",
        )
        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        ct = (scored[0].candidate.raw.get("content_angle") or {}).get("content_type")
        self.assertEqual(ct, "consumer_warning")
        # base +5 + consumer_warning +3 = at least 8
        self.assertGreaterEqual(sb["fresh_news_candidate_boost"], 8)

    def test_ai_pricing_candidate_is_not_routed_to_delivery_money_checklist(self):
        """실측 회귀(GHA run 29464514437): "gpt-image-1·Grok Imagine 요금 폭등,
        무료 한도 확인" 같은 AI 가격 뉴스가 topic_group=delivery_money,
        content_type=money_checklist로 강제 분류되어 배달앱 전용 게이트
        (money_checklist_missing_example_box/final_payment_amount,
        delivery_money_specific_terms_missing)에 구조적으로 막혔다.

        원인: news_taxonomy.build_search_angle이 AI "pricing" 이벤트와 배달앱/
        생활비 비교 이벤트에 동일한 angle_type="money_compare"를 부여하는데,
        NewsScoringService._topic_group_from_search_angle/_build_content_angle이
        이 값만 보고 무조건 delivery_money/money_checklist로 강제했다. AI 신호가
        있으면 ai_work(_tip)로 라우팅되어야 한다."""
        sc = NewsScoringService()
        cand = _candidate(
            topic="gpt-image-1·Grok Imagine 요금 폭등, 무료 한도 확인",
            summary="OpenAI와 xAI가 이미지 생성 API 요금을 잇따라 인상하면서 무료 한도 축소 우려가 커졌다.",
            category="ai",
            source_type="google_news_rss",
        )

        scored = sc.score_candidates([cand])[0]
        raw = scored.candidate.raw

        self.assertEqual(raw["search_angle"]["angle_type"], "money_compare")
        self.assertEqual(raw["topic_group"], "ai_work")
        self.assertEqual(raw["content_angle"]["content_type"], "ai_work_tip")
        self.assertNotEqual(raw["topic_group"], "delivery_money")
        self.assertNotEqual(raw["content_angle"]["content_type"], "money_checklist")

    def test_privacy_warning_does_not_become_money_compare(self):
        sc = NewsScoringService()
        cand = _candidate(
            topic='티빙, ID·이름·전화번호 탈탈 털렸다…"비밀번호 변경 권장',
            summary=(
                "걱정된다, 결합 요금제로 구독 중인데 내 정보도 포함된 거냐 등 "
                "이용자들의 우려와 비밀번호 전면 변경 권고가 나왔다."
            ),
            category="life",
            source_type="naver_news_search",
        )

        scored = sc.score_candidates([cand])[0]
        raw = scored.candidate.raw
        search_angle = raw["search_angle"]

        self.assertEqual(raw["topic_group"], "privacy_security")
        self.assertEqual(raw["content_angle"]["content_type"], "consumer_warning")
        self.assertIn("계정 보안", raw["content_angle"]["reader_question"])
        self.assertNotIn("환불", raw["content_angle"]["reader_question"])
        self.assertEqual(search_angle["angle_type"], "consumer_warning")
        self.assertEqual(scored.candidate.topic, "티빙 비밀번호 변경 안내 후 확인할 것")
        self.assertNotIn("쿠폰", " ".join(search_angle["reader_search_questions"]))
        self.assertNotIn("비용비교", " ".join(raw.get("hashtags") or []))

    def test_delivery_worker_safety_issue_stays_platform_change(self):
        sc = NewsScoringService()
        cand = _candidate(
            topic="수익은 줄고, 위험은 늘고… 배달앱 새벽배달 확대에 분통",
            summary="라이더들은 새벽배달 확대가 수익과 안전 조건에 영향을 준다고 우려했다.",
            category="life",
            source_type="naver_news_search",
        )

        scored = sc.score_candidates([cand])[0]
        raw = scored.candidate.raw
        search_angle = raw["search_angle"]

        self.assertEqual(raw["topic_group"], "platform_issue")
        self.assertEqual(raw["content_angle"]["content_type"], "platform_change")
        self.assertEqual(search_angle["angle_type"], "platform_check")
        self.assertEqual(scored.candidate.topic, "배달앱 새벽배달 변경 전에 확인할 것")
        self.assertNotIn("쿠폰", " ".join(search_angle["reader_search_questions"]))

    def test_news_rss_money_checklist_reaches_candidate_generation_threshold(self):
        """fresh real news는 candidate generation min (65) 이상이 되어야 한다."""
        sc = NewsScoringService()
        cand = _candidate(
            topic="배달앱 결제금액 비교 전에 확인할 조건",
            summary="쿠팡이츠 배달비 쿠폰 적용 시 최종 결제금액 확인 방법, 비교 기준",
            category="delivery_money",
        )
        scored = sc.score_candidates([cand])
        self.assertGreaterEqual(scored[0].total_score, 65)

    def test_external_evidence_bonus_is_applied_to_verified_naver_candidate(self):
        sc = NewsScoringService()
        cand = _candidate(source_type="naver_news_search")
        cand.raw["naver_datalab_score"] = 8
        cand.raw["verified_source_count"] = 3
        cand.raw["source_diversity_score"] = 3
        cand.raw["official_source_found"] = True

        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]

        self.assertGreaterEqual(sb["external_evidence_bonus"], 7)
        self.assertGreaterEqual(sb["fresh_news_candidate_boost"], 5)

    def test_evergreen_score_unchanged_by_boost(self):
        """boost 도입 후에도 evergreen 후보의 점수가 부풀려지지 않는다."""
        sc = NewsScoringService()
        cand = _candidate(source_type="evergreen_fallback")
        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        self.assertEqual(sb["fresh_news_candidate_boost"], 0)
        # Evergreen 후보는 score floor가 별도로 적용되지만 boost는 0
        # (evergreen 자체 점수와 boost가 결합되지 않는지만 확인)


class TestScoringBoostSafety(unittest.TestCase):
    """boost가 안전 조건을 우회하지 않는지 검증."""

    def test_general_life_topic_no_boost(self):
        """allowed list에 없는 content_type은 boost 없음."""
        sc = NewsScoringService()
        cand = NewsCandidate(
            topic="오늘 점심 메뉴 추천",
            category="general",
            summary="평범한 일상 정보",
            source_hint=None,
            published_at=None,
            url=None,
            raw={"source_type": "google_news_rss", "is_stale": False},
        )
        scored = sc.score_candidates([cand])
        sb = scored[0].candidate.raw["strategy_score_breakdown"]
        ct = (scored[0].candidate.raw.get("content_angle") or {}).get("content_type")
        if ct not in {
            "viral_issue_decode", "money_checklist", "platform_change",
            "consumer_warning", "policy_deadline", "policy_benefit",
            "tax_refund", "today_issue_explainer",
        }:
            self.assertEqual(sb["fresh_news_candidate_boost"], 0)


if __name__ == "__main__":
    unittest.main()
