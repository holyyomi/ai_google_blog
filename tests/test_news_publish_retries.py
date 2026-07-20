from __future__ import annotations

from pathlib import Path
import unittest

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.pipelines.news_pipeline import NewsPipeline
from blogspot_automation.services.topic_dedup_service import TopicDedupService


class _ArtifactService:
    def __init__(self) -> None:
        self.status_payloads: list[dict] = []

    def save_status_result(self, *, status_payload: dict, run_meta: dict | None = None) -> Path:
        self.status_payloads.append({"status_payload": status_payload, "run_meta": run_meta or {}})
        return Path("runs/news_retry_limit")


class _RetryPipeline(NewsPipeline):
    def __init__(self, results: list[dict]) -> None:
        self.results = list(results)
        self.dry_run = False
        self.news_publish_mode = "publish"
        self.auto_publish = True
        self.dedup_service = TopicDedupService()
        self._retry_excluded_topics: list[str] = []
        self._current_retry_attempt = 0
        self.artifact_service = _ArtifactService()
        self.history_records: list[tuple[str, dict]] = []
        self.excluded_seen: list[list[str]] = []

    def run_once(self) -> dict:
        self.excluded_seen.append(list(self._retry_excluded_topics))
        return dict(self.results.pop(0))

    def _try_record_history(self, *, status: str, result: dict) -> bool:
        self.history_records.append((status, result))
        return True


def _blocked(topic: str) -> dict:
    return {
        "status": "blocked_by_quality_gate",
        "selected_topic": topic,
        "selected_title": f"{topic} title",
        "publish_attempted": False,
        "publish_succeeded": False,
        "publish_quality_gate": {
            "passed": False,
            "blocking_issues": ["article_focus_score_below_60"],
        },
    }


class NewsPublishRetryTest(unittest.TestCase):
    def test_retries_with_next_candidate_until_published(self) -> None:
        pipeline = _RetryPipeline([
            _blocked("topic A"),
            {
                "status": "published",
                "selected_topic": "topic B",
                "selected_title": "topic B title",
                "publish_attempted": True,
                "publish_succeeded": True,
            },
        ])

        result = pipeline.run_with_retries(max_attempts=3)

        self.assertEqual(result["status"], "published")
        self.assertEqual(len(result["retry_attempts"]), 2)
        self.assertEqual(pipeline.excluded_seen[0], [])
        self.assertEqual(pipeline.excluded_seen[1], ["topic", "topic title"])

    def test_records_terminal_skip_after_retry_limit(self) -> None:
        pipeline = _RetryPipeline([
            _blocked("topic A"),
            _blocked("topic B"),
            _blocked("topic C"),
        ])

        result = pipeline.run_with_retries(max_attempts=3)

        self.assertEqual(result["status"], "skipped_after_retry_limit")
        self.assertEqual(result["reason"], "max_publish_attempts_exhausted")
        self.assertEqual(len(result["retry_attempts"]), 3)
        self.assertEqual(pipeline.history_records[-1][0], "skipped_after_retry_limit")
        self.assertEqual(pipeline.artifact_service.status_payloads[-1]["run_meta"]["max_publish_attempts"], 3)

    def test_post_publish_audit_failure_retries_next_candidate(self) -> None:
        pipeline = _RetryPipeline([
            {
                "status": "blocked_by_post_publish_audit",
                "selected_topic": "topic A",
                "selected_title": "topic A title",
                "publish_attempted": True,
                "publish_succeeded": False,
                "post_publish_audit": {
                    "passed": False,
                    "issues": ["labels_missing"],
                },
            },
            {
                "status": "published",
                "selected_topic": "topic B",
                "selected_title": "topic B title",
                "publish_attempted": True,
                "publish_succeeded": True,
            },
        ])

        result = pipeline.run_with_retries(max_attempts=2)

        self.assertEqual(result["status"], "published")
        self.assertEqual(len(result["retry_attempts"]), 2)
        self.assertEqual(pipeline.excluded_seen[1], ["topic", "topic title"])

    def test_no_golden_skip_does_not_exclude_top_scored_candidates(self) -> None:
        # 2026-07-20: top_scored_candidates 전체를 재시도 배제에 넣던 동작은
        # 한 번의 게이트 실패가 그 실행의 상위 후보 전부를 퍼지 매칭으로 태워
        # 2회 만에 풀이 고갈되는 원인이었다(7/19~20 발행 0건 사슬). 재시도
        # 배제는 실제 선택된 주제로만 한정된다.
        pipeline = _RetryPipeline([
            {
                "status": "skipped",
                "reason": "no_golden_publish_candidate",
                "publish_attempted": False,
                "publish_succeeded": False,
                "top_scored_candidates": [
                    {
                        "topic": "티빙 개인정보 안내 후 먼저 확인할 것",
                        "search_demand_topic": "티빙 개인정보 안내 후 먼저 확인할 것",
                        "search_angle": {
                            "original_topic": "티빙 개인정보 유출 안내",
                            "search_demand_topic": "티빙 개인정보 안내 후 먼저 확인할 것",
                        },
                    }
                ],
            },
            {
                "status": "published",
                "selected_topic": "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
                "selected_title": "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지",
                "publish_attempted": True,
                "publish_succeeded": True,
            },
        ])

        result = pipeline.run_with_retries(max_attempts=2)

        self.assertEqual(result["status"], "published")
        self.assertEqual(len(result["retry_attempts"]), 2)
        # 선택되지 않은 상위 후보는 배제 목록에 오르지 않는다.
        self.assertEqual(pipeline.excluded_seen[1], [])

    def test_retry_exclusion_matches_search_demand_topic_variant(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish")
        pipeline._retry_excluded_topics = pipeline._retry_exclusion_keys_from_result({
            "selected_topic": "transport subsidy application guide",
            "selected_title": "transport subsidy application guide - 3 checks",
        })
        candidate = ScoredNewsCandidate(
            candidate=NewsCandidate(
                topic="disabled worker transport support",
                category="policy_benefit",
                summary="official support page",
                raw={
                    "search_demand_topic": "transport subsidy application guide",
                    "source_type": "naver_webkr_search",
                },
            ),
            freshness_score=0,
            search_demand_score=10,
            contrarian_gap_score=0,
            mass_impact_score=0,
            adsense_value_score=0,
            hook_score=0,
            risk_penalty=0,
            total_score=90,
            reason="test",
        )

        self.assertTrue(pipeline._is_retry_excluded_candidate(candidate))

    def test_retry_exclusion_keeps_korean_topic_keys(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish")

        keys = pipeline._retry_exclusion_keys_from_result({
            "selected_topic": "청주시 지원금 지급일과 신청방법 정리",
            "selected_title": "청주시 지원금 지급일과 신청방법 정리 - 확인할 3가지",
            "search_demand_topic": "청주시 지원금 지급일과 신청방법 정리",
        })

        self.assertIn("청주시 지원금 지급일과 신청방법 정리", keys)
        self.assertGreaterEqual(len(keys), 1)

    def test_retry_exclusion_blocks_same_korean_candidate(self) -> None:
        pipeline = NewsPipeline(dry_run=False, news_publish_mode="publish")
        pipeline._retry_excluded_topics = pipeline._retry_exclusion_keys_from_result({
            "selected_topic": "청주시 지원금 지급일과 신청방법 정리",
            "search_demand_topic": "청주시 지원금 지급일과 신청방법 정리",
        })
        candidate = ScoredNewsCandidate(
            candidate=NewsCandidate(
                topic="청주시 지원금",
                category="policy_benefit",
                summary="official support page",
                raw={
                    "search_demand_topic": "청주시 지원금 지급일과 신청방법 정리",
                    "source_type": "naver_webkr_search",
                },
            ),
            freshness_score=0,
            search_demand_score=10,
            contrarian_gap_score=0,
            mass_impact_score=0,
            adsense_value_score=0,
            hook_score=0,
            risk_penalty=0,
            total_score=90,
            reason="test",
        )

        self.assertTrue(pipeline._is_retry_excluded_candidate(candidate))


if __name__ == "__main__":
    unittest.main()
