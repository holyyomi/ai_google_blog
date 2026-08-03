"""news_quality_gate 오탐(false positive) 교정 회귀 테스트 (2026-08-03).

교정 대상은 "막아야 할 것을 막는 능력"이 아니라 "애초에 막으면 안 되는 것을
막고 있던 버그"다. 그래서 각 항목마다 두 방향을 함께 검증한다:

  (A) 오탐이 사라졌는가  — 정상 후보가 더 이상 차단되지 않는가
  (B) 과교정이 없는가    — 정당한 차단은 그대로 살아 있는가

검증 항목:
1. title_has_no_specific_entity — 영어 모드에서 타이틀케이스 AI 제품명
   (Gemini/Claude/Copilot/Perplexity…)이 엔티티로 인식되는가.
   한국어 모드 판정은 불변인가.
2. issue_specificity — 이벤트 동사의 어형 변화(rolling out / rolls out /
   unveils / previews / expands …)를 인식하는가. 일반론 주제는 여전히 낮은가.
3. pricing_table_without_verified_prices — 가격표가 본문의 두 번째 표여도
   찾는가. 어느 표에도 가격이 없으면 여전히 차단되는가.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.news_quality_gate import NewsQualityGate


class _LanguageMode:
    """BLOG_LANGUAGE 임시 변경 컨텍스트 (테스트 격리)."""

    def __init__(self, value: str) -> None:
        self._value = value
        self._previous: str | None = None

    def __enter__(self) -> "_LanguageMode":
        self._previous = os.environ.get("BLOG_LANGUAGE")
        os.environ["BLOG_LANGUAGE"] = self._value
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._previous is None:
            os.environ.pop("BLOG_LANGUAGE", None)
        else:
            os.environ["BLOG_LANGUAGE"] = self._previous


def _make_scored(
    *,
    topic: str,
    original_topic: str = "",
    summary: str = "",
    content_type: str = "ai_work_tip",
    topic_group: str = "ai_work",
    source_type: str = "google_news_rss",
    reader_questions: list[str] | None = None,
):
    """게이트 입력 후보. 소스 텍스트는 제목과 어휘를 공유하지 않게 둔다.

    `_title_has_source_entity`(제목↔소스 토큰 교집합)가 켜지면 엔티티 어휘집
    경로를 검증할 수 없기 때문이다 — 실제 차단 사례도 소스가 제목과 어휘를
    공유하지 않는 상황이었다.
    """
    raw = {
        "topic_group": topic_group,
        "source_type": source_type,
        "is_stale": False,
        "click_potential_score": 9,
        "content_angle": {"content_type": content_type, "topic_group": topic_group},
        "original_topic": original_topic,
        "reader_search_questions": reader_questions or [],
        "hook_angle": {"safe_title_keyword": ""},
    }
    candidate = NewsCandidate(
        topic=topic,
        category=topic_group,
        summary=summary,
        source_hint="example",
        published_at="2026-08-03T05:00:00+00:00",
        url=None,
        raw=raw,
    )
    scored = MagicMock()
    scored.candidate = candidate
    scored.total_score = 80
    scored.risk_penalty = 0
    scored.freshness_score = 9
    scored.search_demand_score = 8
    scored.contrarian_gap_score = 7
    scored.mass_impact_score = 7
    scored.adsense_value_score = 7
    scored.hook_score = 7
    scored.reason = ""
    return scored


def _minimal_html(title: str) -> str:
    parts = [
        "<!DOCTYPE html><html><head>",
        '<meta name="description" content="A short summary of this article that is between eighty and one hundred sixty characters long for search.">',
        "</head><body>",
        f"<h1>{title}</h1>",
        "<section><h2>Summary</h2><p>A plain paragraph that summarises the issue for readers.</p></section>",
        '<section class="faq">',
    ]
    for index in range(3):
        parts.append(
            f"<h3>Question {index + 1}?</h3><p>This answer is long enough to clear the twenty character minimum.</p>"
        )
    parts.append("</section>")
    parts.append('<script type="application/ld+json">{"@type": "FAQPage"}</script>')
    parts.append("</body></html>")
    return "\n".join(parts)


def _entity_issue_present(title: str, *, language: str, **kwargs) -> bool:
    """게이트를 실제로 돌려 title_has_no_specific_entity 차단 여부만 본다."""
    with _LanguageMode(language):
        scored = _make_scored(topic=title, **kwargs)
        result = NewsQualityGate().evaluate(
            selected=scored,
            selected_title=title,
            html=_minimal_html(title),
            dry_run=True,
        )
    return "title_has_no_specific_entity" in list(result.get("blocking_issues") or [])


class TestEnglishTitleEntityVocabulary(unittest.TestCase):
    """오탐1 (A): 영어 타이틀케이스 제품명을 엔티티로 인식한다."""

    KNOWN_ENTITY_TITLES = (
        "GPT-5.6 Sol Limited Preview Launches 2026",
        "Gemini Robotics 2 Brings Whole Body Intelligence to Robots",
        "Claude Voice Mode Gets Gmail and Calendar Access",
        "Copilot Studio Adds Agent Flows for Teams",
        "Perplexity Comet Browser Opens to Everyone",
        "Midjourney V8 Changes Image Rights",
        "DeepSeek R2 Weights Land on Hugging Face",
        "Google Docs Is Rolling Out Three New Features",
    )

    def test_known_ai_products_are_entities(self):
        for title in self.KNOWN_ENTITY_TITLES:
            with self.subTest(title=title):
                self.assertTrue(
                    NewsQualityGate._title_has_english_entity(title),
                    f"영어 AI 제품/기업 제목이 엔티티 미인식: {title!r}",
                )

    def test_generic_titles_are_not_entities(self):
        """오탐1 (B) 과교정 검사: 엔티티 없는 뭉뚱그린 제목은 여전히 미인식."""
        for title in (
            "Five Habits That Make Your Workday Shorter",
            "How to Choose the Right Tool for Your Team",
            "The Best Way to Automate Boring Work",
            "What Everyone Gets Wrong About Productivity",
            "Three Things to Check Before You Subscribe",
        ):
            with self.subTest(title=title):
                self.assertFalse(
                    NewsQualityGate._title_has_english_entity(title),
                    f"고유명사 없는 제목이 엔티티로 오인됨: {title!r}",
                )

    def test_ambiguous_product_words_require_ai_context(self):
        """영어 제목은 전부 타이틀케이스 → 대문자만으로는 제품명/일반명사 구분 불가."""
        self.assertFalse(
            NewsQualityGate._title_has_english_entity("Move Your Cursor Less and Type More")
        )
        self.assertFalse(
            NewsQualityGate._title_has_english_entity("A Simple Notion of Better Meetings")
        )
        self.assertTrue(
            NewsQualityGate._title_has_english_entity("Cursor 3.0 Ships Background Agents")
        )
        self.assertTrue(
            NewsQualityGate._title_has_english_entity("Notion AI Adds Database Agents")
        )

    def test_common_english_words_that_are_also_model_names(self):
        """Whisper/Bard/Firefly/Granite/Titan — 일반명사 문맥에서는 엔티티가 아니다."""
        for title in (
            "A Whisper of Better Meetings",
            "The Bard Guide to Writing Well",
            "Catch a Firefly on Summer Evenings",
            "Granite Countertops and Kitchen Costs",
        ):
            with self.subTest(title=title, expected=False):
                self.assertFalse(NewsQualityGate._title_has_english_entity(title))
        for title in (
            "Whisper v3 Turbo Cuts Transcription Cost",
            "Adobe Firefly 4 Adds Video Model",
            "Comet Browser Adds Agent Mode",
        ):
            with self.subTest(title=title, expected=True):
                self.assertTrue(NewsQualityGate._title_has_english_entity(title))

    def test_empty_title_is_not_entity(self):
        self.assertFalse(NewsQualityGate._title_has_english_entity(""))
        self.assertFalse(NewsQualityGate._title_has_english_entity("   "))


class TestTitleEntityGateByLanguage(unittest.TestCase):
    """오탐1: 게이트 전체를 돌려 언어별 판정을 확인한다."""

    EN_TITLE = "Gemini Robotics 2 Brings Whole Body Intelligence to Robots"
    GENERIC_TITLE = "Five Habits That Make Your Workday Shorter"

    def test_english_mode_passes_known_entity_title(self):
        self.assertFalse(
            _entity_issue_present(self.EN_TITLE, language="en"),
            "영어 모드에서 Gemini 제목이 title_has_no_specific_entity로 차단됨",
        )

    def test_english_mode_still_blocks_entity_free_title(self):
        """(B) 과교정 검사 — 엔티티 없는 제목은 영어 모드에서도 차단 유지."""
        self.assertTrue(
            _entity_issue_present(self.GENERIC_TITLE, language="en"),
            "엔티티 없는 영어 제목이 차단되지 않음 (정당한 차단이 사라짐)",
        )

    def test_korean_mode_judgment_unchanged(self):
        """한국어 모드는 영어 어휘집을 참조하지 않는다 (판정 불변)."""
        self.assertTrue(
            _entity_issue_present(self.EN_TITLE, language="ko"),
            "한국어 모드에서 영어 어휘집이 참조되어 판정이 바뀌었다",
        )
        self.assertTrue(_entity_issue_present(self.GENERIC_TITLE, language="ko"))

    def test_korean_entity_title_still_passes(self):
        """한국어 어휘집 경로는 그대로 동작한다."""
        self.assertFalse(
            _entity_issue_present("쿠팡 로켓배송 요금 변경, 먼저 확인할 것", language="ko")
        )


class TestIssueSpecificityVerbMorphology(unittest.TestCase):
    """오탐2: 이벤트 동사의 어형 변화 인식."""

    THRESHOLD = 6

    def _score(self, topic: str) -> int:
        return NewsQualityGate._compute_issue_specificity(
            _make_scored(topic=topic, original_topic=topic)
        )

    def test_inflected_event_verbs_reach_threshold(self):
        """(A) 어형만 다를 뿐 같은 사건인 제목들이 모두 통과한다."""
        for topic in (
            "Google Docs Is Rolling Out These Three New Gemini Features",
            "Google Docs rolls out new Gemini features",
            "OpenAI rolled out GPT-5.6 to all Plus users",
            "Anthropic unveils Claude Opus for enterprise",
            "Perplexity previews Comet browser for Windows",
            "Gemini expands to 40 more countries",
            "Microsoft deprecates Copilot GPT Builder",
            "Grok integrates with Telegram",
            "Meta ships Llama weights to partners",
            "OpenAI is shutting down the Codex beta",
        ):
            with self.subTest(topic=topic):
                self.assertGreaterEqual(
                    self._score(topic),
                    self.THRESHOLD,
                    f"정상 AI 뉴스 주제가 issue_specificity 미달: {topic!r}",
                )

    def test_generic_topics_stay_below_threshold(self):
        """(B) 과교정 검사 — 사건이 없는 일반론 주제는 여전히 임계값 미만."""
        for topic in (
            "ChatGPT tips for beginners",
            "How to write better prompts",
            "AI tools for small business owners",
            "Best practices for using Claude every day",
            "Beginner guide to prompt engineering",
            "How to use Gemini for email",
            "Why AI matters for your career",
        ):
            with self.subTest(topic=topic):
                self.assertLess(
                    self._score(topic),
                    self.THRESHOLD,
                    f"구체적 사건이 없는 주제가 통과됨 (과교정): {topic!r}",
                )

    def test_verb_pattern_builder_covers_inflections(self):
        import re

        cases = {
            "roll out": ("rolls out", "rolled out", "rolling out", "roll out"),
            "unveil": ("unveils", "unveiled", "unveiling", "unveil"),
            "deprecate": ("deprecates", "deprecated", "deprecating", "deprecate"),
            "ship": ("ships", "shipped", "shipping", "ship"),
            "shut down": ("shuts down", "shutting down", "shut down"),
        }
        for lemma, forms in cases.items():
            pattern = re.compile(NewsQualityGate._en_verb_inflection_pattern(lemma))
            for form in forms:
                with self.subTest(lemma=lemma, form=form):
                    self.assertTrue(pattern.search(f"openai {form} the model"))

    def test_verb_matcher_does_not_fire_on_unrelated_words(self):
        import re

        pattern = re.compile(NewsQualityGate._en_verb_inflection_pattern("leak"))
        self.assertIsNone(pattern.search("leakage report for the quarter"))
        ban_pattern = re.compile(NewsQualityGate._en_verb_inflection_pattern("ban"))
        self.assertIsNone(ban_pattern.search("banana bread recipes"))

    def test_known_limitation_english_company_names_missing_from_entity_list(self):
        """알려진 한계(2026-08-03, 이번 범위 밖 — 의도적 미수정).

        `_compute_issue_specificity`의 `ai_entity_keywords`는 플랫폼사를 한국어
        표기("구글"/"마이크로소프트")로만 담고 있어 영어 표기는 엔티티로 세지
        않는다. 이벤트 동사는 잡히지만 엔티티가 0이면 가점 조건
        (`ai_entity_hits and ...`)이 성립하지 않아 중립 5점에 머문다.

        영어 표기를 추가하지 않은 이유는 실측 과교정 위험이다 — "Google"을
        넣으면 "How to use Google Docs with AI to update your notes" 같은 순수
        하우투 주제가 엔티티1+이벤트("update")1 = 7점으로 통과한다. 즉 이 한계를
        푸는 것은 게이트 완화에 해당하므로 별도 판단이 필요하다.
        """
        self.assertLess(self._score("Google is shutting down Bard entirely"), self.THRESHOLD)
        self.assertLess(
            self._score("How to use Google Docs with AI to update your notes"),
            self.THRESHOLD,
        )

    def test_korean_topics_are_unaffected(self):
        """한국어 주제 점수는 영어 동사 규칙 도입 전후로 동일해야 한다."""
        korean_topics = (
            "쿠팡 로켓배송 요금 인상 발표",
            "국세청 환급 신청 마감 안내",
            "개인정보위 과징금 부과, 소비자 확인 사항",
            "확인할 조건 정리",
            "AI 활용법 총정리",
        )
        saved = NewsQualityGate._EN_EVENT_VERB_LEMMAS
        try:
            with_rule = [self._score(topic) for topic in korean_topics]
            NewsQualityGate._EN_EVENT_VERB_LEMMAS = ()
            NewsQualityGate._EN_EVENT_VERB_PATTERNS_CACHE = None
            without_rule = [self._score(topic) for topic in korean_topics]
        finally:
            NewsQualityGate._EN_EVENT_VERB_LEMMAS = saved
            NewsQualityGate._EN_EVENT_VERB_PATTERNS_CACHE = None
        self.assertEqual(with_rule, without_rule)


class TestPricingTableAcrossMultipleTables(unittest.TestCase):
    """항목3: 가격표가 본문의 첫 표가 아닐 때의 오탐."""

    TITLE = "ChatGPT vs Claude Pricing Compared 2026"

    def _check(self, html: str) -> dict[str, object]:
        with _LanguageMode("en"):
            return NewsQualityGate._pricing_table_price_cells(
                html, title=self.TITLE, content_type="ai_work_tip"
            )

    def test_price_table_after_comparison_table_is_found(self):
        html = (
            '<div class="quick-decision-table"><table>'
            "<tr><td>Claude</td><td>Long documents</td></tr>"
            "<tr><td>ChatGPT</td><td>General chat</td></tr></table></div>"
            '<div class="quick-decision-table"><table>'
            "<tr><td>Pro</td><td>$20/month</td></tr>"
            "<tr><td>Team</td><td>$30/month</td></tr></table></div>"
        )
        result = self._check(html)
        self.assertTrue(result["table_present"])
        self.assertGreaterEqual(int(result["price_cell_count"]), 2)

    def test_price_table_first_still_works(self):
        html = (
            '<div class="quick-decision-table"><table>'
            "<tr><td>Pro</td><td>$20/month</td></tr>"
            "<tr><td>Free</td><td>Free</td></tr></table></div>"
        )
        self.assertGreaterEqual(int(self._check(html)["price_cell_count"]), 2)

    def test_no_price_cell_anywhere_still_blocks(self):
        """(B) 과교정 검사 — 어느 표에도 검증된 가격이 없으면 여전히 0."""
        html = (
            '<div class="quick-decision-table"><table>'
            "<tr><td>Claude</td><td>Check the official page</td></tr></table></div>"
            '<div class="quick-decision-table"><table>'
            "<tr><td>Gemini</td><td>Not published</td></tr></table></div>"
        )
        result = self._check(html)
        self.assertTrue(result["table_present"])
        self.assertEqual(int(result["price_cell_count"]), 0)

    def test_single_price_cell_still_below_requirement(self):
        html = (
            '<div class="quick-decision-table"><table>'
            "<tr><td>Pro</td><td>$20/month</td></tr>"
            "<tr><td>Team</td><td>Not published</td></tr></table></div>"
        )
        self.assertLess(int(self._check(html)["price_cell_count"]), 2)

    def test_korean_mode_is_untouched(self):
        with _LanguageMode("ko"):
            result = NewsQualityGate._pricing_table_price_cells(
                '<div class="quick-decision-table"><table><tr><td>Pro</td><td>$20</td></tr></table></div>',
                title=self.TITLE,
                content_type="ai_work_tip",
            )
        self.assertFalse(result["is_pricing_family"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
