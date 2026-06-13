from __future__ import annotations

import unittest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.title_generation_service import TitleGenerationService


def _scored(
    topic: str,
    *,
    content_type: str,
    topic_group: str,
    angle_type: str = "",
) -> ScoredNewsCandidate:
    raw = {
        "topic_group": topic_group,
        "content_angle": {"content_type": content_type, "topic_group": topic_group},
        "search_angle": {
            "search_demand_topic": topic,
            "angle_type": angle_type,
            "reader_search_questions": [],
        },
    }
    candidate = NewsCandidate(topic=topic, category=topic_group, summary="", raw=raw)
    return ScoredNewsCandidate(
        candidate=candidate,
        freshness_score=10,
        search_demand_score=10,
        contrarian_gap_score=10,
        mass_impact_score=10,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=80,
        reason="test",
    )


class TestNewsTitleGenerationService(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = TitleGenerationService()

    def _best_title(self, item: ScoredNewsCandidate) -> str:
        return self.svc.select_best_title(self.svc.generate_titles(item)).title

    def test_platform_news_gets_contextual_hook_title(self) -> None:
        title = self._best_title(
            _scored(
                "카카오톡 지원 종료 구형 스마트폰 이용자 영향",
                content_type="platform_change",
                topic_group="platform_issue",
                angle_type="platform_check",
            )
        )
        self.assertEqual(title, "카카오톡 지원 종료, 기존 이용자가 먼저 볼 3가지")

    def test_money_news_gets_loss_or_check_hook_title(self) -> None:
        title = self._best_title(
            _scored(
                "배달앱 수수료 인상 소비자 부담",
                content_type="money_checklist",
                topic_group="delivery_money",
                angle_type="money_compare",
            )
        )
        self.assertEqual(title, "배달앱 수수료 인상, 결제금액부터 확인할 이유")

    def test_viral_title_does_not_duplicate_reaction_phrase(self) -> None:
        title = self._best_title(
            _scored(
                "기후보험 반응이 갈린 이유와 핵심 포인트",
                content_type="viral_issue_decode",
                topic_group="fandom_consumer",
                angle_type="viral_issue_decode",
            )
        )

        self.assertNotIn("핵심 포인트 반응이 갈린 이유", title)
        self.assertLessEqual(title.count("반응이 갈린 이유"), 1)

    def test_viral_titles_do_not_emit_bad_tving_particle(self) -> None:
        item = _scored(
            "티빙 OTT 신작 공개",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
            angle_type="viral_issue_decode",
        )

        titles = [candidate.title for candidate in self.svc.generate_titles(item)]

        self.assertTrue(titles)
        self.assertFalse(any("티빙가" in title for title in titles), titles)

    def test_privacy_consumer_warning_search_angle_does_not_reference_missing_topic(self) -> None:
        item = _scored(
            "개인정보 유출 안내 이후 계정 점검",
            content_type="consumer_warning",
            topic_group="privacy_security",
            angle_type="consumer_warning",
        )

        titles = [candidate.title for candidate in self.svc.generate_titles(item)]

        self.assertTrue(titles)
        self.assertIn("개인정보 유출 안내 이후 계정 점검", titles)


if __name__ == "__main__":
    unittest.main()
