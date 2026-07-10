from __future__ import annotations

import unittest

from blogspot_automation.services.title_candidate_service import TitleCandidateService

_svc = TitleCandidateService()

_THREE_PATTERNS = [
    ("세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", "tax_refund", "policy_benefit", "tax_refund_hometax_check"),
    ("넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지", "viral_issue_decode", "ott_platform", "viral_ott_reaction_decode"),
    ("직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유", "ai_work_tip", "ai_work", "ai_work_time_savings"),
]


class TestGenerateCandidates(unittest.TestCase):

    def test_tax_refund_generates_8_plus(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[0]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        self.assertGreaterEqual(len(result["candidates"]), 8, f"only {len(result['candidates'])} candidates")

    def test_viral_ott_generates_8_plus(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[1]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        self.assertGreaterEqual(len(result["candidates"]), 8)

    def test_ai_work_generates_8_plus(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[2]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        self.assertGreaterEqual(len(result["candidates"]), 8)

    def test_result_structure(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[0]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        for key in ("topic", "primary_title", "candidates", "best_title", "blocked_titles"):
            self.assertIn(key, result)

    def test_candidate_structure(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[0]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        for c in result["candidates"]:
            for key in ("title", "title_type", "ctr_score", "risk_score", "promise_match_score", "is_allowed", "blocking_issues", "reason"):
                self.assertIn(key, c, f"key '{key}' missing")


class TestContextualHookTitles(unittest.TestCase):

    def test_search_demand_topic_becomes_selected_hook_title(self) -> None:
        topic = "크롬 AI 기능 켜기 전에 확인할 설정"
        result = _svc.generate_candidates(
            topic=topic,
            content_type="ai_work_tip",
            topic_group="ai_work",
            pattern_id="ai_work_time_savings",
            candidate_raw={"search_demand_topic": topic},
        )
        title = result["best_title"].get("title", "")
        self.assertIn("크롬 AI 기능", title)
        self.assertTrue(any(signal in title for signal in ("먼저", "기준", "이유", "3가지")), title)
        self.assertNotEqual(title, "무료 ChatGPT로도 업무 시간 줄이는 3가지 패턴")

    def test_comparison_context_preserves_vs_pair(self) -> None:
        topic = "AI 도구 비교 ChatGPT vs Claude 업무용 선택 기준"
        result = _svc.generate_candidates(
            topic=topic,
            content_type="ai_work_tip",
            topic_group="ai_work",
            pattern_id="ai_tool_comparison",
            candidate_raw={"search_demand_topic": topic},
        )
        title = result["best_title"].get("title", "")
        self.assertIn("ChatGPT vs Claude", title)
        self.assertTrue(any(signal in title for signal in ("먼저", "기준", "고를 때")), title)

    def test_malformed_contextual_title_is_not_selected(self) -> None:
        topic = '게임업계 리밸런싱)③" 서비스 지원 종료 전에 확인할 것'
        result = _svc.generate_candidates(
            topic=topic,
            content_type="platform_change",
            topic_group="platform_issue",
            pattern_id="platform_change_service_update",
            candidate_raw={"search_demand_topic": topic},
        )
        title = result["best_title"].get("title", "")

        self.assertEqual(
            title,
            '게임업계 리밸런싱)③" 서비스 지원 종료, 기존 이용자가 먼저 볼 3가지',
        )
        self.assertNotIn("확인할  전에", title)

    def test_pricing_angle_gets_money_frame_not_work_savings_frame(self) -> None:
        """앵글별 제목 다변화(2026-07-10): 요금 개편 기사가 '반복 업무/시간' 틀 대신
        요금 프레임 제목을 받는지 — ai_work로 뭉치는 모든 사건이 같은 제목 틀을
        쓰던 문제(라이브 실측: 발행 5건 제목 수렴)의 회귀 방지."""
        topic = "챗GPT AI 요금 변화"
        result = _svc.generate_candidates(
            topic=topic,
            content_type="ai_work_tip",
            topic_group="ai_work",
            pattern_id="ai_work_time_savings",
            candidate_raw={
                "search_demand_topic": topic,
                "search_angle": {"angle_type": "money_compare", "search_demand_topic": topic},
            },
        )
        titles = [item.get("title", "") for item in result["candidates"]]
        self.assertTrue(
            any(("무료 기준" in t or "내는 조건" in t or "먼저 볼 3가지" in t) for t in titles), titles
        )

    def test_service_change_angle_gets_fact_frame(self) -> None:
        topic = "네이버 AI 발표 소식"
        result = _svc.generate_candidates(
            topic=topic,
            content_type="ai_work_tip",
            topic_group="ai_work",
            pattern_id="ai_work_time_savings",
            candidate_raw={
                "search_demand_topic": topic,
                "search_angle": {"angle_type": "ai_service_change", "search_demand_topic": topic},
            },
        )
        titles = [item.get("title", "") for item in result["candidates"]]
        self.assertTrue(
            any(("확인된 것" in t or "핵심 포인트" in t) for t in titles), titles
        )

    def test_delivery_money_loss_title_has_separator(self) -> None:
        topic = "배달앱 결제금액 비교 전에 확인할 조건"
        result = _svc.generate_candidates(
            topic=topic,
            content_type="money_checklist",
            topic_group="delivery_money",
            pattern_id="delivery_money_checklist",
            candidate_raw={"search_demand_topic": topic},
        )
        titles = [item.get("title", "") for item in result["candidates"]]

        self.assertTrue(any("비교, 놓치면" in title for title in titles), titles)
        self.assertFalse(any("비교 놓치면" in title for title in titles), titles)


class TestScoreTitle(unittest.TestCase):

    def test_ctr_score_range(self) -> None:
        for title in [
            "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
            "충격 소름 루머 폭로",
            "A",
            "직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유",
        ]:
            scored = _svc.score_title(title)
            self.assertGreaterEqual(scored["ctr_score"], 0, f"title={title}")
            self.assertLessEqual(scored["ctr_score"], 100, f"title={title}")

    def test_blocked_phrase_sets_ctr_zero(self) -> None:
        scored = _svc.score_title("충격 루머 폭로", content_type="viral_issue_decode")
        self.assertEqual(scored["ctr_score"], 0)
        self.assertFalse(scored["is_allowed"])
        self.assertTrue(len(scored["blocking_issues"]) > 0)

    def test_good_title_high_ctr(self) -> None:
        scored = _svc.score_title(
            "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
            pattern_id="tax_refund_hometax_check",
        )
        self.assertGreater(scored["ctr_score"], 60)
        self.assertTrue(scored["is_allowed"])

    def test_number_in_title_boosts_ctr(self) -> None:
        without_num = _svc.score_title("세금 환급금 조회 전 홈택스에서 먼저 볼 것", pattern_id="tax_refund_hometax_check")
        with_num = _svc.score_title("세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", pattern_id="tax_refund_hometax_check")
        self.assertGreaterEqual(with_num["ctr_score"], without_num["ctr_score"])

    def test_malformed_title_is_blocked(self) -> None:
        scored = _svc.score_title(
            '게임업계 리밸런싱)③" 서비스 지원 종료 전에 확인할  전에 먼저 볼 것',
            pattern_id="platform_change_service_update",
        )

        self.assertFalse(scored["is_allowed"])
        self.assertIn("malformed_title_phrase", scored["blocking_issues"])

    def test_bad_subject_particle_is_blocked(self) -> None:
        scored = _svc.score_title(
            "티빙가 화제 된 이유, 사람들이 본 핵심 포인트",
            content_type="viral_issue_decode",
            pattern_id="viral_ott_reaction_decode",
        )

        self.assertFalse(scored["is_allowed"])
        self.assertIn("bad_subject_particle", scored["blocking_issues"])

    def test_low_value_viral_rating_formula_is_blocked(self) -> None:
        scored = _svc.score_title(
            "티빙 신작, 평점보다 먼저 볼 포인트",
            content_type="viral_issue_decode",
            pattern_id="viral_ott_reaction_decode",
        )

        self.assertFalse(scored["is_allowed"])
        self.assertIn("low_value_viral_rating_title", scored["blocking_issues"])

    def test_media_series_prefix_title_is_blocked(self) -> None:
        scored = _svc.score_title(
            "재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지",
            content_type="viral_issue_decode",
            pattern_id="viral_ott_reaction_decode",
        )

        self.assertFalse(scored["is_allowed"])
        self.assertTrue(
            any(issue.startswith("blocked_phrase:재계는 지금") for issue in scored["blocking_issues"]),
            scored["blocking_issues"],
        )
        self.assertIn("malformed_title_phrase", scored["blocking_issues"])

    def test_telecom_plan_title_cannot_use_ott_reaction_pattern(self) -> None:
        scored = _svc.score_title(
            "KT초이스 요금제 무료 반응이 갈린 이유, 먼저 볼 3가지",
            content_type="viral_issue_decode",
            pattern_id="viral_ott_reaction_decode",
        )

        self.assertFalse(scored["is_allowed"])
        self.assertIn("pattern_crossover:요금제", scored["blocking_issues"])


class TestBlockedTitles(unittest.TestCase):

    def test_blocked_phrase_충격(self) -> None:
        s = _svc.score_title("충격적인 세금 환급금 소식")
        self.assertFalse(s["is_allowed"])
        self.assertGreater(s["risk_score"], 0)

    def test_blocked_phrase_루머(self) -> None:
        s = _svc.score_title("루머로 확산된 드라마 반응 이슈")
        self.assertFalse(s["is_allowed"])

    def test_viral_extra_block_사생활(self) -> None:
        s = _svc.score_title("OTT 드라마 배우 사생활 논란", content_type="viral_issue_decode")
        self.assertFalse(s["is_allowed"])

    def test_clean_title_allowed(self) -> None:
        s = _svc.score_title("넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지", content_type="viral_issue_decode")
        self.assertTrue(s["is_allowed"])

    def test_blocked_title_in_candidates(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[1]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        # 모든 blocked_titles는 is_allowed=False
        for bt in result["blocked_titles"]:
            self.assertFalse(bt["is_allowed"])


class TestPromiseMatchScore(unittest.TestCase):

    def test_tax_refund_title_mismatch_low_pms(self) -> None:
        # tax_refund 패턴에 지원금/드라마 → 크로스오버 감점
        s = _svc.score_title("지원금 신청 방법 안내", pattern_id="tax_refund_hometax_check")
        self.assertLess(s["promise_match_score"], 70)

    def test_tax_refund_title_match_high_pms(self) -> None:
        s = _svc.score_title("홈택스 세금 환급금 조회 3단계", pattern_id="tax_refund_hometax_check")
        self.assertGreater(s["promise_match_score"], 70)

    def test_viral_ott_good_pms(self) -> None:
        s = _svc.score_title("넷플릭스 드라마 반응 갈린 이유", pattern_id="viral_ott_reaction_decode")
        self.assertGreater(s["promise_match_score"], 70)

    def test_ai_work_good_pms(self) -> None:
        s = _svc.score_title("직장인 ChatGPT 업무 시간 줄이는 방법", pattern_id="ai_work_time_savings")
        self.assertGreater(s["promise_match_score"], 70)


class TestSelectBestTitle(unittest.TestCase):

    def test_best_title_is_allowed(self) -> None:
        for topic, ct, tg, pid in _THREE_PATTERNS:
            with self.subTest(pattern=pid):
                result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
                best = result["best_title"]
                self.assertTrue(best.get("is_allowed"), f"best title not allowed: {best}")

    def test_best_title_has_highest_ctr_among_allowed(self) -> None:
        topic, ct, tg, pid = _THREE_PATTERNS[0]
        result = _svc.generate_candidates(topic=topic, content_type=ct, topic_group=tg, pattern_id=pid)
        best = result["best_title"]
        allowed = [c for c in result["candidates"] if c["is_allowed"]]
        max_ctr = max(c["ctr_score"] for c in allowed)
        self.assertEqual(best["ctr_score"], max_ctr)

    def test_select_best_title_empty_returns_empty(self) -> None:
        result = _svc.select_best_title([])
        self.assertEqual(result, {})

    def test_validate_title_clean(self) -> None:
        v = _svc.validate_title("세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", content_type="tax_refund")
        self.assertTrue(v["is_valid"])

    def test_validate_title_blocked(self) -> None:
        v = _svc.validate_title("충격 루머 폭로 사생활 이슈")
        self.assertFalse(v["is_valid"])


if __name__ == "__main__":
    unittest.main()
