from __future__ import annotations

import unittest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.issue_content_profile_service import IssueContentProfileService
from blogspot_automation.services.title_generation_service import TitleGenerationService
from blogspot_automation.services.trending_article_service import TrendingArticleService


def _scored(topic: str, raw: dict) -> ScoredNewsCandidate:
    return ScoredNewsCandidate(
        candidate=NewsCandidate(topic=topic, category=str(raw.get("topic_group") or "today_issue"), summary="", raw=raw),
        freshness_score=10,
        search_demand_score=10,
        contrarian_gap_score=10,
        mass_impact_score=10,
        adsense_value_score=10,
        hook_score=10,
        risk_penalty=0,
        total_score=90,
        reason="test",
    )


class TestIssueContentProfileService(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = IssueContentProfileService()

    def test_problem_issue_keeps_problem_solution_profile(self) -> None:
        raw = {
            "topic_group": "today_issue",
            "content_angle": {"content_type": "today_issue_explainer", "topic_group": "today_issue"},
        }
        profile = self.svc.apply_to_raw(raw, topic="청년 지원금 신청 마감 대상 조건", summary="")

        self.assertEqual(profile["profile_id"], "problem_solution")
        self.assertEqual(raw["content_angle"]["content_type"], "policy_deadline")
        self.assertIn("지금 확인할 순서", raw["content_angle"]["required_sections"])

    def test_entertainment_or_sports_issue_uses_reaction_profile(self) -> None:
        raw = {
            "topic_group": "today_issue",
            "content_angle": {"content_type": "today_issue_explainer", "topic_group": "today_issue"},
        }
        profile = self.svc.apply_to_raw(raw, topic="손흥민 이적설 팬 반응", summary="축구 팬덤 반응")

        self.assertEqual(profile["profile_id"], "reaction_decode")
        self.assertEqual(raw["content_angle"]["content_type"], "viral_issue_decode")
        self.assertIn("억지 해결법", profile["avoid_sections"])

    def test_general_today_issue_uses_timeline_profile(self) -> None:
        profile = self.svc.build_profile(
            topic="국회 본회의 일정 변경 논의",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )

        self.assertEqual(profile["profile_id"], "timeline_context")
        self.assertEqual(profile["recommended_content_type"], "today_issue_explainer")

    def test_economic_gyeonggi_word_does_not_force_sports_profile(self) -> None:
        profile = self.svc.build_profile(
            topic="경기침체 우려에 소비심리 하락",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )

        self.assertEqual(profile["profile_id"], "timeline_context")

    def test_profile_prompt_warns_against_forced_checklists(self) -> None:
        profile = self.svc.build_profile(
            topic="신작 드라마 시청률 반응",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )
        prompt = IssueContentProfileService.prompt_block(profile)

        self.assertIn("반응·관전포인트형", prompt)
        self.assertIn("문제해결형이 아닌 이슈", prompt)
        self.assertIn("외부 사이트로 나가는 링크", prompt)


class TestIssueProfileDownstreamUse(unittest.TestCase):
    def test_title_generation_prefers_reaction_angle_when_profile_is_reaction(self) -> None:
        raw = {
            "topic_group": "today_issue",
            "content_angle": {"content_type": "today_issue_explainer", "topic_group": "today_issue"},
            "search_angle": {"search_demand_topic": "손흥민 이적설 팬 반응", "reader_search_questions": []},
        }
        IssueContentProfileService().apply_to_raw(raw, topic="손흥민 이적설 팬 반응", summary="")

        titles = TitleGenerationService().generate_titles(_scored("손흥민 이적설 팬 반응", raw))
        title_texts = [item.title for item in titles]

        self.assertTrue(any("반응" in title or "포인트" in title or "맥락" in title for title in title_texts))
        self.assertFalse(any("신청" in title or "환급" in title for title in title_texts))

    def test_trending_prompt_includes_issue_profile_block(self) -> None:
        profile = IssueContentProfileService().build_profile(
            topic="프로야구 우승 경쟁 팬 반응",
            content_type="today_issue_explainer",
            topic_group="today_issue",
        )
        prompt = TrendingArticleService._build_user_prompt(
            topic="프로야구 우승 경쟁 팬 반응",
            sample_titles=["프로야구 우승 경쟁, 팬 반응 엇갈려"],
            primary_tokens=["프로야구", "우승", "팬"],
            sample_sources=["테스트뉴스"],
            source_count=3,
            issue_profile=profile,
        )

        self.assertIn("[이슈 맞춤 작성 프로필]", prompt)
        self.assertIn("반응·관전포인트형", prompt)
        self.assertIn("억지 해결법", prompt)


if __name__ == "__main__":
    unittest.main()
