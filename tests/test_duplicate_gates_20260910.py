"""색인 0 근본원인 회귀 테스트 (2026-09-10).

holyyomiai 47편 전부 구글 색인 0편. 원인 조사에서 확인된 두 구멍:

1. 본문 재탕 게이트의 임계값이 0.6(60%)이라 사실상 게이트가 아니었다. 실측
   (최근 발행 60편, 순서쌍 3,540개) 최대 겹침이 0.25라 0.6은 단 한 번도
   걸릴 수 없는 값이었고, 문장 md5 완전일치라 "명사만 바꾼 재사용"은
   원리상 못 잡았다.
2. 제목 유사도 차단 규칙은 코드에 있었지만(topic_selection_service) 호출자가
   topic_pipeline/ui 뿐이라 **실제 발행 경로에서는 한 번도 안 돌았다**.
   그 결과 9/1~9/5에 "ChatGPT free version limits" 계열 제목이 자카드
   0.67~0.80으로 5일 연속 발행됐다 — 그것도 클러스터 경로로.

이 파일은 그 두 구멍이 다시 열리는 것을 막는다.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from blogspot_automation.services.content_similarity_service import (
    max_ngram_jaccard,
    ngram_fingerprints,
)
from blogspot_automation.services.news_quality_gate import NewsQualityGate


_BODY = """
<article>
  <h1>ChatGPT free version limits</h1>
  <p>Free users can upload images and files inside chat prompts, per the OpenAI
  Free Tier FAQ, and the Library storage cap applies to everything you keep.</p>
  <p>The attachment window resets on a rolling basis, so the practical limit you
  hit depends on how many long files you pushed through in the last few hours.</p>
  <p>If you need a hard number for planning, check the Help Center page for your
  own region because the published caps differ by country and by plan tier.</p>
  <p>Think is a longer-reasoning mode that burns more tokens per message, which
  is why heavy attachment users notice the free ceiling sooner than others do.</p>
  <p>A spreadsheet exported as a comma separated file counts against the same
  storage budget as a scanned contract, even though one of them is far smaller
  on disk, and that surprises people who only ever attach documents.</p>
  <p>When the ceiling arrives the interface does not always explain which limit
  you crossed, so keep a rough tally of the uploads you made that morning
  before you conclude that your account has been throttled for another reason.</p>
  <p>Teams that share a single free login run out far earlier than a solo user
  would, because every seat draws from one pool and nothing in the product
  surfaces who consumed what during the current rolling window.</p>
  <p>The cheapest fix is often not an upgrade at all but a habit change, such as
  cropping screenshots before you send them and pasting plain text instead of
  a formatted export whenever the formatting carries no meaning.</p>
  <p>If you decide to pay, run one real week of your own work on the free tier
  first and write down every point where the ceiling actually cost you time,
  because that list is the only honest way to size the upgrade.</p>
</article>
"""

_OTHER_BODY = """
<article>
  <h1>Notion database automation</h1>
  <p>A rollup property can pull the latest deadline from a linked database so the
  parent page always shows the nearest due date without any manual editing.</p>
  <p>Formula properties using dateBetween return the remaining days directly, and
  that value can drive a coloured status without a third party integration.</p>
  <p>Reminders are safest when duplicated across a Slack webhook and a native
  notification, because one channel silently failing is the common outage.</p>
  <p>Relations should point at exactly one source of truth; two databases each
  claiming to own the schedule will drift within a fortnight and nobody will
  notice until a milestone quietly disappears from the board view.</p>
  <p>Filters that hide completed rows keep boards readable, yet they also hide
  mistakes, so pair every hiding filter with a weekly audit view that shows
  everything regardless of state before anyone trusts the numbers.</p>
  <p>Templates carry their own properties, which means renaming a property later
  breaks every template that referenced it, and the failure mode is silent
  emptiness rather than an error message anyone can act upon.</p>
  <p>Exporting to comma separated files loses relations entirely, so treat the
  export as a snapshot for reporting rather than a backup you could restore
  the workspace from if somebody deleted the wrong page tree.</p>
  <p>Permissions inherit downward, and a single shared parent page can expose an
  entire tree to guests, so grant access at the narrowest node that still lets
  collaborators finish the task they were invited to complete.</p>
</article>
"""


def _make_selected(*, cluster: bool = False) -> MagicMock:
    raw: dict[str, object] = {
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
        "source_type": "news",
        "click_potential_score": 10,
        "hook_angle": {"safe_title_keyword": "limits"},
        "is_test_candidate": False,
        "publish_allowed": True,
    }
    if cluster:
        # topic_dedup_service가 dedup을 면제하는 바로 그 형태의 후보.
        raw["topic_cluster"] = "chatgpt_free_limits"
        raw["cluster_slot"] = "image_limits"
    candidate = MagicMock()
    candidate.topic = "ChatGPT free version limits"
    candidate.category = "tech"
    candidate.summary = "summary"
    candidate.raw = raw
    selected = MagicMock()
    selected.total_score = 80
    selected.candidate = candidate
    selected.reason = "test"
    return selected


class TestNgramFingerprints(unittest.TestCase):
    def test_deterministic_and_nonempty(self):
        first = ngram_fingerprints(_BODY)
        self.assertTrue(first)
        self.assertEqual(first, ngram_fingerprints(_BODY))

    def test_identical_body_jaccard_is_one(self):
        fps = ngram_fingerprints(_BODY)
        result = max_ngram_jaccard(
            fps, [{"title": "past", "content_ngram_fingerprint": list(fps)}]
        )
        self.assertEqual(result["jaccard"], 1.0)
        self.assertEqual(result["compared_records"], 1)

    def test_unrelated_body_jaccard_is_low(self):
        result = max_ngram_jaccard(
            ngram_fingerprints(_BODY),
            [{"title": "other", "content_ngram_fingerprint": ngram_fingerprints(_OTHER_BODY)}],
        )
        self.assertLess(result["jaccard"], 0.05)

    def test_boilerplate_sections_are_excluded(self):
        """면책·출처 정형 블록은 재탕이 아니라 템플릿 가구다 — 지문에서 뺀다."""
        boiler = (
            '<section id="AI_CITATION_SUMMARY" class="yomi-citation-summary">'
            "<p>Every claim here is tied to the sources named at the end of this "
            "article and prices are as published at the time of writing.</p>"
            "</section>"
            '<section id="SOURCE_TRUST_BLOCK" class="yomi-source">'
            "<p>Sources for this article are listed below and named inline for "
            "every number you can act on today.</p></section>"
        )
        self.assertEqual(
            ngram_fingerprints(_BODY), ngram_fingerprints(_BODY + boiler)
        )

    def test_history_without_ngram_fingerprints_is_not_compared(self):
        """비교 대상 0건은 '깨끗함'이 아니라 '안 봄'이다 — 필드로 구분된다."""
        result = max_ngram_jaccard(
            ngram_fingerprints(_BODY),
            [{"title": "legacy record with no ngram field"}],
        )
        self.assertEqual(result["compared_records"], 0)
        self.assertEqual(result["jaccard"], 0.0)

    def test_sample_too_small_is_reported(self):
        result = max_ngram_jaccard(["a", "b"], [])
        self.assertTrue(result["sample_too_small"])


class TestGateNgramBlocking(unittest.TestCase):
    def _evaluate(self, *, ngram_result: dict, publish_mode: bool = True):
        gate = NewsQualityGate()
        clean_overlap = {
            "ratio": 0.0,
            "matched_title": "",
            "compared_records": 3,
            "shared_sentences": 0,
            "shared_sentences_title": "",
        }
        with (
            patch.object(NewsQualityGate, "_max_history_overlap", return_value=clean_overlap),
            patch.object(NewsQualityGate, "_max_history_ngram_jaccard", return_value=ngram_result),
            patch.object(
                NewsQualityGate,
                "_max_history_title_similarity",
                return_value={"similarity": 0.0, "matched_title": "", "compared_records": 5},
            ),
        ):
            return gate.evaluate(
                selected=_make_selected(),
                selected_title="ChatGPT free version limits 2026",
                html=_BODY,
                dry_run=not publish_mode,
                news_publish_mode="publish" if publish_mode else "dry_run",
            )

    def test_ngram_over_threshold_blocks(self):
        result = self._evaluate(
            ngram_result={
                "jaccard": 0.42,
                "matched_title": "chatgpt free version image limits 2026",
                "compared_records": 4,
                "candidate_sample_size": 200,
                "sample_too_small": False,
            }
        )
        self.assertTrue(
            any(
                str(issue).startswith("content_ngram_near_duplicate_of_recent_post")
                for issue in result["blocking_issues"]
            ),
            result["blocking_issues"],
        )
        self.assertEqual(result["content_ngram_jaccard"], 0.42)

    def test_ngram_under_threshold_passes(self):
        result = self._evaluate(
            ngram_result={
                "jaccard": 0.03,
                "matched_title": "",
                "compared_records": 4,
                "candidate_sample_size": 200,
                "sample_too_small": False,
            }
        )
        self.assertFalse(
            any(
                str(issue).startswith("content_ngram_near_duplicate_of_recent_post")
                for issue in result["blocking_issues"]
            ),
        )

    def test_zero_comparisons_is_recorded_not_silently_passed(self):
        """진짜 원인은 임계값보다 '비교 대상 0건인데 통과'였다."""
        result = self._evaluate(
            ngram_result={
                "jaccard": 0.0,
                "matched_title": "",
                "compared_records": 0,
                "candidate_sample_size": 200,
                "sample_too_small": False,
            }
        )
        self.assertEqual(result["content_ngram_compared_records"], 0)
        self.assertIn("content_ngram_history_unavailable", result["warnings"])

    def test_ngram_fingerprint_is_exported_for_history(self):
        result = self._evaluate(
            ngram_result={
                "jaccard": 0.0,
                "matched_title": "",
                "compared_records": 2,
                "candidate_sample_size": 200,
                "sample_too_small": False,
            }
        )
        self.assertEqual(result["content_ngram_fingerprint"], ngram_fingerprints(_BODY))


class TestGateSharedSentenceCap(unittest.TestCase):
    def _evaluate(self, *, shared: int):
        gate = NewsQualityGate()
        with (
            patch.object(
                NewsQualityGate,
                "_max_history_overlap",
                return_value={
                    "ratio": 0.0,
                    "matched_title": "",
                    "compared_records": 3,
                    "shared_sentences": shared,
                    "shared_sentences_title": "past post",
                },
            ),
            patch.object(
                NewsQualityGate,
                "_max_history_ngram_jaccard",
                return_value={
                    "jaccard": 0.0,
                    "matched_title": "",
                    "compared_records": 3,
                    "candidate_sample_size": 200,
                    "sample_too_small": False,
                },
            ),
            patch.object(
                NewsQualityGate,
                "_max_history_title_similarity",
                return_value={"similarity": 0.0, "matched_title": "", "compared_records": 5},
            ),
        ):
            return gate.evaluate(
                selected=_make_selected(),
                selected_title="ChatGPT free version limits 2026",
                html=_BODY,
                dry_run=False,
                news_publish_mode="publish",
            )

    def test_absolute_shared_sentence_cap_blocks(self):
        result = self._evaluate(shared=200)
        self.assertTrue(
            any(
                str(issue).startswith("content_shared_sentences_with_recent_post")
                for issue in result["blocking_issues"]
            ),
            result["blocking_issues"],
        )

    def test_under_cap_passes(self):
        result = self._evaluate(shared=1)
        self.assertFalse(
            any(
                str(issue).startswith("content_shared_sentences_with_recent_post")
                for issue in result["blocking_issues"]
            ),
        )


class TestGateTitleSimilarityBlocking(unittest.TestCase):
    """실사고 재현: 제목 자카드 0.8짜리가 발행 경로에서 차단되어야 한다."""

    _HISTORY = [
        {"title": "ChatGPT Free Version Limits 2026", "content_fingerprint": ["x"]},
        {"title": "Notion Database Automation Basics", "content_fingerprint": ["y"]},
    ]

    def _evaluate(self, *, title: str, cluster: bool = False, publish_mode: bool = True):
        gate = NewsQualityGate()
        history = MagicMock()
        history.recent_records.return_value = list(self._HISTORY)
        clean_overlap = {
            "ratio": 0.0,
            "matched_title": "",
            "compared_records": 3,
            "shared_sentences": 0,
            "shared_sentences_title": "",
        }
        clean_ngram = {
            "jaccard": 0.0,
            "matched_title": "",
            "compared_records": 3,
            "candidate_sample_size": 200,
            "sample_too_small": False,
        }
        with (
            patch.object(NewsQualityGate, "_max_history_overlap", return_value=clean_overlap),
            patch.object(NewsQualityGate, "_max_history_ngram_jaccard", return_value=clean_ngram),
            patch(
                "blogspot_automation.services.publish_history_service.PublishHistoryService",
                return_value=history,
            ),
        ):
            return gate.evaluate(
                selected=_make_selected(cluster=cluster),
                selected_title=title,
                html=_BODY,
                dry_run=not publish_mode,
                news_publish_mode="publish" if publish_mode else "dry_run",
            )

    @staticmethod
    def _title_blocked(result: dict) -> bool:
        return any(
            str(issue).startswith("title_near_duplicate_of_recent_post")
            for issue in result["blocking_issues"]
        )

    def test_high_similarity_title_is_blocked(self):
        # 실측 5연타 중 한 쌍 (자카드 0.833).
        result = self._evaluate(title="chatgpt free version image limits 2026")
        self.assertTrue(self._title_blocked(result), result["blocking_issues"])
        self.assertGreaterEqual(result["title_similarity_max"], 0.6)
        self.assertEqual(
            result["title_similarity_matched_title"], "ChatGPT Free Version Limits 2026"
        )

    def test_cluster_candidate_is_not_exempt(self):
        """클러스터는 topic_dedup을 면제받지만 제목 게이트는 면제받지 않는다 —
        5연타가 정확히 클러스터 경로에서 나왔다."""
        result = self._evaluate(
            title="chatgpt free version image limits 2026", cluster=True
        )
        self.assertTrue(self._title_blocked(result), result["blocking_issues"])

    def test_distinct_title_passes(self):
        result = self._evaluate(title="Notion rollup formulas for deadline tracking")
        self.assertFalse(self._title_blocked(result), result["blocking_issues"])
        self.assertGreater(result["title_similarity_compared_records"], 0)

    def test_dry_run_does_not_block(self):
        result = self._evaluate(
            title="chatgpt free version image limits 2026", publish_mode=False
        )
        self.assertFalse(self._title_blocked(result))
        # 차단은 안 해도 측정치는 남긴다.
        self.assertGreaterEqual(result["title_similarity_max"], 0.6)

    def test_empty_history_is_recorded_not_silently_passed(self):
        gate = NewsQualityGate()
        history = MagicMock()
        history.recent_records.return_value = []
        with patch(
            "blogspot_automation.services.publish_history_service.PublishHistoryService",
            return_value=history,
        ):
            result = gate.evaluate(
                selected=_make_selected(),
                selected_title="chatgpt free version image limits 2026",
                html=_BODY,
                dry_run=False,
                news_publish_mode="publish",
            )
        self.assertEqual(result["title_similarity_compared_records"], 0)
        self.assertIn("title_similarity_history_unavailable", result["warnings"])


class TestHistoryRecordCarriesNgramFingerprint(unittest.TestCase):
    """게이트가 지문을 만들어도 원장에 안 실리면 다음 후보는 비교 대상이 0건이다."""

    def test_ngram_fingerprint_written_to_history_record(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        record = NewsPipeline._build_history_record(
            status="published",
            result={
                "selected_title": "ChatGPT free version limits 2026",
                "selected_topic": "ChatGPT free version limits",
                "topic_group": "ai_work",
                "content_angle": {"content_type": "ai_work_tip"},
                "post_url": "https://holyyomiai.blogspot.com/2026/09/x.html",
                "publish_quality_gate": {
                    "passed": True,
                    "content_fingerprint": ["aaa", "bbb"],
                    "content_ngram_fingerprint": ["ccc", "ddd"],
                },
            },
        )
        self.assertEqual(record["content_ngram_fingerprint"], ["ccc", "ddd"])

    def test_missing_ngram_fingerprint_defaults_to_empty_list(self):
        from blogspot_automation.pipelines.news_pipeline import NewsPipeline

        record = NewsPipeline._build_history_record(
            status="published",
            result={
                "selected_title": "legacy post",
                "selected_topic": "legacy post",
                "publish_quality_gate": {"passed": True},
            },
        )
        self.assertEqual(record["content_ngram_fingerprint"], [])


class TestThresholdDefaults(unittest.TestCase):
    """임계값 기본값이 조용히 되돌아가는 것을 막는다."""

    def test_defaults(self):
        from blogspot_automation.services import news_quality_gate as gate_module

        self.assertEqual(gate_module._content_rehash_block_ratio(), 0.15)
        self.assertEqual(gate_module._max_ngram_jaccard(), 0.15)
        self.assertEqual(gate_module._max_title_similarity(), 0.6)
        self.assertEqual(gate_module._title_similarity_history_limit(), 30)

    def test_env_override(self):
        import os
        from unittest.mock import patch as _patch

        from blogspot_automation.services import news_quality_gate as gate_module

        with _patch.dict(
            os.environ,
            {
                "NEWS_MAX_NGRAM_JACCARD": "0.08",
                "NEWS_MAX_TITLE_SIMILARITY": "0.5",
                "NEWS_CONTENT_REHASH_BLOCK_RATIO": "0.05",
                "NEWS_MAX_SHARED_SENTENCES": "2",
            },
        ):
            self.assertEqual(gate_module._max_ngram_jaccard(), 0.08)
            self.assertEqual(gate_module._max_title_similarity(), 0.5)
            self.assertEqual(gate_module._content_rehash_block_ratio(), 0.05)
            self.assertEqual(gate_module._max_shared_sentences(), 2)


if __name__ == "__main__":
    unittest.main()
