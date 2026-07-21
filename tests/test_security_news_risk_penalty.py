from __future__ import annotations

import unittest

from blogspot_automation.services.news_scoring_service import NewsScoringService


class TestSecurityNewsRiskPenalty(unittest.TestCase):
    """2026-07-21 실측: 이 블로그(AI 도구 선택/비교/가격/활용)와 안 맞는 보안
    취약점 폭로 기사가 "GPT"를 언급한다는 이유만으로 발행까지 갔다
    ("GPT-5.6 WordPress RCE Discovery $500k Broker Value"). 완전 차단 대신
    점수 페널티로 다른 정상 AI 도구 후보에 밀리게 한다.
    """

    def setUp(self) -> None:
        self.svc = NewsScoringService()

    def test_wordpress_rce_story_penalized(self) -> None:
        text = (
            "gpt-5.6 wordpress rce discovery $500k broker value 2026 — "
            "researchers detail a remote code execution exploit chain"
        )
        self.assertGreaterEqual(self.svc._risk_penalty(text), 20)

    def test_generic_cve_mention_penalized(self) -> None:
        text = "cve-2026-63030 unpatched vulnerability affects thousands of sites"
        self.assertGreaterEqual(self.svc._risk_penalty(text), 20)

    def test_zero_day_exploit_broker_penalized(self) -> None:
        text = "zero-day exploit broker pays record price for chrome bug"
        self.assertGreaterEqual(self.svc._risk_penalty(text), 20)

    def test_normal_ai_pricing_topic_not_penalized(self) -> None:
        text = "chatgpt plus vs claude pro vs gemini advanced pricing compared 2026"
        self.assertEqual(self.svc._risk_penalty(text), 0)

    def test_normal_ai_tool_comparison_not_penalized(self) -> None:
        text = "best ai tools for etsy sellers: keepr-etsy-ops vs optimsy pricing 2026"
        self.assertEqual(self.svc._risk_penalty(text), 0)


if __name__ == "__main__":
    unittest.main()
