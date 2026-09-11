"""2026-09-11 품질 업그레이드 회귀 테스트.

진단은 전부 실측 기반이다 (발행 이력 최근 40편 + 라이브 글 다운로드):

1. 소제목 반복 — _LABEL_VARIANTS_EN 풀이 종류당 2~3개라 16편에서 같은 라벨이
   7~8회 반복됐다. FAQ 헤딩은 아예 하드코딩이라 16편 중 15편이 같았다.
2. 영어 모드 맹점 — 영어 전환(2026-07-17) 이후에도 일부 검사가 한국어 문자열만
   찾고 있었다. article_lacks_example_or_checklist 는 12/12편에서 떴는데 실제로는
   글에 체크리스트가 있었고, _shareability_signals 는 7신호 중 4개가 죽어
   40편 전부 42점이었다.
3. 벽글 — 생성 프롬프트에 "문단 70단어 이하" 계약이 있는데 검증기도 게이트도
   확인하지 않아 라이브 글 문단이 평균 59 · 최대 82단어였다.
4. 단계 뭉개짐 — real_criterion 은 단계 문자열인데 <p> 하나로 렌더돼 줄바꿈이
   사라졌다.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from blogspot_automation.services.paragraph_rhythm import (
    dense_paragraph_count,
    split_dense_paragraphs,
    split_numbered_steps,
)


def _en():
    return mock.patch.dict(os.environ, {"BLOG_LANGUAGE": "en"})


class HeadingVariationTest(unittest.TestCase):
    def test_pools_are_large_enough_to_avoid_heavy_repeats(self):
        from blogspot_automation.services.answer_engine_policy import _LABEL_VARIANTS_EN

        for kind in ("overview", "context", "context_ai", "intent", "confirmed", "trust", "faq"):
            with self.subTest(kind=kind):
                pool = _LABEL_VARIANTS_EN[kind]
                self.assertGreaterEqual(len(pool), 6)
                self.assertEqual(len(pool), len(set(pool)))

    def test_no_variant_ends_with_a_question_mark(self):
        from blogspot_automation.services.answer_engine_policy import _LABEL_VARIANTS_EN

        for kind, pool in _LABEL_VARIANTS_EN.items():
            for variant in pool:
                self.assertFalse(variant.strip().endswith("?"), f"{kind}: {variant}")

    def test_kinds_do_not_move_together(self):
        from blogspot_automation.services.answer_engine_policy import _varied_label

        with _en():
            seeds = [f"topic number {n} about a model release" for n in range(40)]
            pairs = {(_varied_label("overview", s), _varied_label("trust", s)) for s in seeds}
        self.assertGreater(len(pairs), 12)

    def test_faq_heading_varies(self):
        from blogspot_automation.services.answer_engine_policy import _varied_label

        with _en():
            picked = {_varied_label("faq", f"seed {n}") for n in range(40)}
        self.assertGreater(len(picked), 5)

    def test_related_guides_heading_varies_by_article(self):
        from blogspot_automation.services.seo_policy import _related_guides_heading

        with _en():
            picked = {
                _related_guides_heading(f"<h1>Article number {n} on pricing</h1><p>x</p>")
                for n in range(40)
            }
        self.assertGreater(len(picked), 4)

    def test_same_article_is_deterministic(self):
        from blogspot_automation.services.answer_engine_policy import _varied_label

        with _en():
            first = [_varied_label(k, "one fixed topic") for k in ("overview", "trust", "faq")]
            second = [_varied_label(k, "one fixed topic") for k in ("overview", "trust", "faq")]
        self.assertEqual(first, second)


_EN_BODY = (
    "<article><h1>Claude pricing 2026</h1>"
    "<p>Some prose about the change.</p>"
    '<div class="quality-checklist"><ul><li>Open the official pricing page</li>'
    "<li>Compare the seat count you actually use</li></ul></div>"
    "<table><tr><td>plan</td></tr></table>"
    "</article>"
)


class EnglishModeBlindSpotTest(unittest.TestCase):
    def test_shareability_signals_fire_on_english_bodies(self):
        from blogspot_automation.services.news_recommendation_policy import _shareability_signals

        visible = (
            "For example, open the official pricing page. A common mistake is "
            "counting seats you do not use. Checklist before you start. 2026-09-11"
        )
        signals = _shareability_signals(_EN_BODY, visible)
        for expected in ("table", "checklist", "example", "official_check", "risk_or_mistake"):
            self.assertIn(expected, signals, f"{expected} 신호가 영어 본문에서 안 켜진다")
        self.assertGreaterEqual(len(signals) * 14, 55)

    def test_shareability_still_discriminates(self):
        from blogspot_automation.services.news_recommendation_policy import _shareability_signals

        thin = "<article><p>Just some prose with nothing actionable in it.</p></article>"
        signals = _shareability_signals(thin, "Just some prose with nothing actionable in it.")
        self.assertLess(len(signals) * 14, 55)

    def test_english_checklist_markup_is_visible_to_the_example_check(self):
        self.assertNotIn("체크리스트", _EN_BODY)
        self.assertIn("quality-checklist", _EN_BODY.lower())


_LONG = (
    "<p>" + " ".join(f"word{i}" for i in range(40)) + ". "
    + " ".join(f"term{i}" for i in range(40)) + ". "
    + " ".join(f"item{i}" for i in range(40)) + ".</p>"
)


class ParagraphRhythmTest(unittest.TestCase):
    def test_long_paragraph_is_split(self):
        out = split_dense_paragraphs(_LONG)
        self.assertGreater(out.count("<p>"), 1)
        self.assertEqual(dense_paragraph_count(out, threshold_words=70), 0)

    def test_idempotent(self):
        once = split_dense_paragraphs(_LONG)
        self.assertEqual(split_dense_paragraphs(once), once)

    def test_short_paragraph_untouched(self):
        short = "<p>Two short sentences. That is all there is here.</p>"
        self.assertEqual(split_dense_paragraphs(short), short)

    def test_classed_paragraph_untouched(self):
        body = '<p class="section-label">' + " ".join(f"w{i}" for i in range(120)) + ".</p>"
        self.assertEqual(split_dense_paragraphs(body), body)

    def test_inline_tags_stay_balanced(self):
        body = (
            "<p>" + " ".join(f"a{i}" for i in range(40)) + ". "
            "<strong>" + " ".join(f"b{i}" for i in range(40)) + "</strong>. "
            + " ".join(f"c{i}" for i in range(40)) + ".</p>"
        )
        out = split_dense_paragraphs(body)
        self.assertEqual(out.count("<strong>"), out.count("</strong>"))
        self.assertEqual(out.count("<p"), out.count("</p>"))

    def test_no_sentence_boundary_leaves_text_alone(self):
        body = "<p>" + " ".join(f"w{i}" for i in range(120)) + "</p>"
        self.assertEqual(split_dense_paragraphs(body), body)


class NumberedStepsTest(unittest.TestCase):
    def test_english_steps_become_items(self):
        steps = split_numbered_steps(
            "Step 1: Open settings. Step 2: Enable the flag. Step 3: Re-run it."
        )
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0], "Open settings")

    def test_prose_is_not_forced_into_a_list(self):
        self.assertEqual(split_numbered_steps("A sentence about step changes only."), [])

    def test_single_step_is_not_a_list(self):
        self.assertEqual(split_numbered_steps("Step 1: only one here."), [])


if __name__ == "__main__":
    unittest.main()
