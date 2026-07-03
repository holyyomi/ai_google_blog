from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from blogspot_automation.services.content_similarity_service import (
    max_overlap_ratio,
    sentence_fingerprints,
)
from blogspot_automation.services.news_quality_gate import NewsQualityGate


_BODY_A = """
<article>
  <h1>ChatGPT 업무 활용</h1>
  <p>ChatGPT를 쓰기 시작했는데 오히려 시간이 더 걸리는 경험을 한 적 있다면 나만 그런 게 아니다.</p>
  <p>작성 시간은 줄지만 검수 시간이 늘어나면 총 업무 시간은 오히려 늘어날 수 있다.</p>
  <p>검수 비용이 작은 업무부터 적용하면 실질적인 시간 절감이 생긴다.</p>
  <p>매번 프롬프트를 새로 작성하면 AI 사용 자체에 시간이 더 들어가므로 고정 템플릿이 핵심이다.</p>
</article>
"""

_BODY_B = """
<article>
  <h1>완전히 다른 글</h1>
  <p>노션 데이터베이스로 프로젝트 마감일을 자동 추적하는 설정을 단계별로 정리했다.</p>
  <p>수식 속성에 dateBetween 함수를 넣으면 남은 일수가 자동으로 계산된다.</p>
  <p>알림은 리마인더 속성과 슬랙 연동으로 이중화하는 것이 안전하다.</p>
</article>
"""


class TestSentenceFingerprints(unittest.TestCase):
    def test_extracts_stable_fingerprints(self):
        fp1 = sentence_fingerprints(_BODY_A)
        fp2 = sentence_fingerprints(_BODY_A)
        self.assertTrue(fp1)
        self.assertEqual(fp1, fp2)

    def test_strips_script_and_style(self):
        html = "<style>.a{color:red}</style><script>var x=1;</script><p>본문 문장이 하나 들어있는 예시 텍스트입니다.</p>"
        fps = sentence_fingerprints(html)
        self.assertEqual(len(fps), 1)

    def test_short_sentences_excluded(self):
        self.assertEqual(sentence_fingerprints("<p>짧다.</p>"), [])

    def test_whitespace_and_markup_insensitive(self):
        a = sentence_fingerprints("<p>검수 비용이 작은 업무부터 적용하면 실질적인 시간 절감이 생긴다.</p>")
        b = sentence_fingerprints("<div>검수  비용이 작은 업무부터   적용하면 실질적인 시간 절감이 생긴다.</div>")
        self.assertEqual(a, b)


class TestMaxOverlapRatio(unittest.TestCase):
    def test_identical_body_ratio_is_one(self):
        fps = sentence_fingerprints(_BODY_A)
        records = [{"title": "과거 글", "content_fingerprint": list(fps)}]
        result = max_overlap_ratio(fps, records)
        self.assertEqual(result["ratio"], 1.0)
        self.assertEqual(result["matched_title"], "과거 글")
        self.assertEqual(result["compared_records"], 1)

    def test_disjoint_body_ratio_is_zero(self):
        result = max_overlap_ratio(
            sentence_fingerprints(_BODY_A),
            [{"title": "다른 글", "content_fingerprint": sentence_fingerprints(_BODY_B)}],
        )
        self.assertEqual(result["ratio"], 0.0)

    def test_records_without_fingerprint_are_skipped(self):
        result = max_overlap_ratio(
            sentence_fingerprints(_BODY_A),
            [{"title": "지문 없는 과거 글"}, {"title": "빈 지문", "content_fingerprint": []}],
        )
        self.assertEqual(result["compared_records"], 0)
        self.assertEqual(result["ratio"], 0.0)

    def test_empty_candidate_is_safe(self):
        result = max_overlap_ratio([], [{"content_fingerprint": ["abc"]}])
        self.assertEqual(result["ratio"], 0.0)


def _make_selected() -> MagicMock:
    raw = {
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
        "source_type": "news",
        "click_potential_score": 10,
        "hook_angle": {"safe_title_keyword": "확인"},
        "is_test_candidate": False,
        "publish_allowed": True,
    }
    candidate = MagicMock()
    candidate.topic = "ChatGPT 업무 활용"
    candidate.category = "tech"
    candidate.summary = "요약"
    candidate.raw = raw
    selected = MagicMock()
    selected.total_score = 80
    selected.candidate = candidate
    selected.reason = "테스트"
    return selected


class TestQualityGateRehashBlocking(unittest.TestCase):
    """게이트 통합 — 과거 발행 글과 본문이 사실상 같으면 발행 모드에서 차단."""

    def _evaluate(self, *, history_fps: list[str], publish_mode: bool):
        gate = NewsQualityGate()
        with patch.object(
            NewsQualityGate,
            "_max_history_overlap",
            side_effect=lambda fps: (
                {"ratio": 1.0, "matched_title": "과거 글", "compared_records": 1}
                if history_fps else
                {"ratio": 0.0, "matched_title": "", "compared_records": 0}
            ),
        ):
            return gate.evaluate(
                selected=_make_selected(),
                selected_title="ChatGPT 업무 활용 기준",
                html=_BODY_A,
                dry_run=not publish_mode,
                news_publish_mode="publish" if publish_mode else "dry_run",
            )

    def test_rehash_blocks_in_publish_mode(self):
        result = self._evaluate(history_fps=["x"], publish_mode=True)
        self.assertTrue(
            any(str(b).startswith("content_near_duplicate_of_recent_post") for b in result["blocking_issues"]),
            result["blocking_issues"],
        )
        self.assertEqual(result["content_rehash_ratio"], 1.0)
        self.assertEqual(result["content_rehash_matched_title"], "과거 글")

    def test_no_block_when_history_has_no_fingerprints(self):
        result = self._evaluate(history_fps=[], publish_mode=True)
        self.assertFalse(
            any(str(b).startswith("content_near_duplicate_of_recent_post") for b in result["blocking_issues"]),
        )

    def test_fingerprint_included_in_gate_result(self):
        result = self._evaluate(history_fps=[], publish_mode=True)
        self.assertTrue(result["content_fingerprint"])
        self.assertEqual(result["content_fingerprint"], sentence_fingerprints(_BODY_A))


if __name__ == "__main__":
    unittest.main()
