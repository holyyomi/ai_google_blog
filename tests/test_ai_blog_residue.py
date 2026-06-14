from __future__ import annotations

import unittest

from blogspot_automation.services.golden_article_preview_service import GoldenArticlePreviewService


# AI 글에 절대 나오면 안 되는 뉴스/오늘이슈 잔재 문구
_NEWS_RESIDUE = (
    "왜 지금 봐야 하나",
    "관련 이슈입니다",
    "흔한 착각 vs 실제",
    "30초 판단표",
    "확인된 내용과 직접 확인할 내용",
    "먼저 볼 핵심",
    "오늘 이슈",
    "터졌나",
    "news-cover-image",
)

# AI 글에 나타나야 하는 가이드형 라벨
_AI_LABELS = (
    "30초 요약",
    "이 글이 도움이 되는 사람",
    "자주 하는 오해와 실제",
    "📋 따라 하는 순서",
    "상황별 추천",
    "결론부터 말하면",
    "지금 바로 해보기",
    "검증된 점과 직접 확인할 점",
    "자주 묻는 질문",
)


def _render(topic: str, content_type: str, topic_group: str, title: str) -> str:
    svc = GoldenArticlePreviewService()
    pv = svc.build_preview(topic=topic, content_type=content_type, topic_group=topic_group)
    return svc.render_article_candidate_html(
        pv["pattern_match"], pv["slot_result"], selected_title=title
    )


class TestAiBlogResidue(unittest.TestCase):
    """AI 플로우 발행 HTML에 뉴스/오늘이슈 잔재가 없고 AI 라벨이 적용되는지 검증."""

    @classmethod
    def setUpClass(cls):
        cls.html = _render(
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            content_type="ai_work_tip",
            topic_group="ai_work",
            title="ChatGPT 업무 자동화, 처음 맡기면 좋은 일과 안 되는 일",
        )

    def test_no_news_residue(self):
        leaked = [m for m in _NEWS_RESIDUE if m in self.html]
        self.assertEqual(leaked, [], f"뉴스 잔재 문구 노출: {leaked}")

    def test_ai_labels_present(self):
        missing = [m for m in _AI_LABELS if m not in self.html]
        self.assertEqual(missing, [], f"AI 라벨 누락: {missing}")

    def test_ai_cover_markup_only(self):
        # ai-cover-image 사용 / news-cover-image 미사용 (커버는 별 정책이나, 잔재 방지)
        self.assertNotIn("news-cover-image", self.html)

    def test_gate_classes_preserved(self):
        # geo_score 게이트가 의존하는 CSS 클래스/섹션 ID는 라벨 변경에도 그대로 유지
        for marker in (
            'class="yomi-judgment-box"',
            'class="quick-decision-table"',
            'class="actions-box"',
            'class="real-criterion"',
            'id="ISSUE_CONTEXT_BLOCK"',
            'id="AI_OVERVIEW_TARGET_ANSWER"',
            'id="AI_CITATION_SUMMARY"',
        ):
            self.assertIn(marker, self.html, f"게이트 의존 마커 누락: {marker}")


class TestNewsFlowUnchanged(unittest.TestCase):
    """뉴스 패턴은 기존 뉴스 라벨을 그대로 유지해야 한다 (AI 라벨 누출 금지)."""

    @classmethod
    def setUpClass(cls):
        cls.html = _render(
            topic="홈택스 종합소득세 환급금 조회 방법",
            content_type="tax_refund",
            topic_group="policy_benefit",
            title="홈택스 환급금 조회, 놓치기 쉬운 확인 순서",
        )

    def test_news_labels_present(self):
        for marker in ("왜 지금 봐야 하나", "30초 판단표", "핵심 관점"):
            self.assertIn(marker, self.html, f"뉴스 라벨 누락: {marker}")

    def test_no_ai_labels_leak(self):
        leaked = [m for m in ("30초 요약", "상황별 추천", "결론부터 말하면") if m in self.html]
        self.assertEqual(leaked, [], f"AI 라벨이 뉴스 글에 누출: {leaked}")


class TestAiPromptRecipeFlagship(unittest.TestCase):
    """Phase B 플래그십: ai_prompt_recipe 패턴이 프롬프트 박스/체크리스트 구조를 갖는지 검증."""

    @classmethod
    def setUpClass(cls):
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService

        topic = "보고서 초안용 ChatGPT 프롬프트 템플릿 만들기"
        ps = GoldenPatternService()
        cls.pm = ps.match_pattern(
            topic=topic, content_type="ai_prompt_recipe", topic_group="ai_prompt"
        )
        svc = GoldenArticlePreviewService()
        sf = SlotFillerService()
        cls.sr = sf.fill_slots(pattern_id="ai_prompt_recipe", topic=topic)
        cls.html = svc.render_article_candidate_html(
            cls.pm, cls.sr, selected_title="복사해서 쓰는 보고서 초안 프롬프트 템플릿"
        )

    def test_pattern_matched_high_confidence(self):
        self.assertEqual(self.pm.get("pattern_id"), "ai_prompt_recipe")
        self.assertGreaterEqual(self.pm.get("confidence", 0), 80)

    def test_prompt_block_rendered(self):
        # CSS 규칙이 아닌 실제 섹션 마크업으로 확인
        self.assertIn('class="prompt-recipe-box"', self.html)
        self.assertIn('class="prompt-code"', self.html)
        self.assertIn("복사해서 쓰는 프롬프트", self.html)
        # 복사 가능한 실제 프롬프트 텍스트(대괄호 변수) 포함
        self.assertIn("당신은 [", self.html)

    def test_quality_checklist_rendered(self):
        self.assertIn('class="quality-checklist"', self.html)
        self.assertIn("결과물 품질 체크리스트", self.html)

    def test_distinct_from_ai_work_structure(self):
        # ai_work_time_savings에는 없는 프롬프트 박스가 prompt_recipe에는 있어야 함 (구조 차별화)
        svc = GoldenArticlePreviewService()
        work = svc.build_preview(
            topic="직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유",
            content_type="ai_work_tip", topic_group="ai_work",
        )
        work_html = svc.render_article_candidate_html(
            work["pattern_match"], work["slot_result"], selected_title="x",
        )
        self.assertNotIn('class="prompt-recipe-box"', work_html)

    def test_no_news_residue(self):
        leaked = [m for m in _NEWS_RESIDUE if m in self.html]
        self.assertEqual(leaked, [], f"뉴스 잔재: {leaked}")

    def test_risk_note_rendered(self):
        # 위험 알림(보안/저작권/환각) 모듈이 렌더링되는지 (Phase C 디자인 모듈)
        self.assertIn('class="risk-note"', self.html)
        self.assertIn("쓰기 전 주의할 점", self.html)


class TestAiTitleDiversity(unittest.TestCase):
    """AI 제목이 '먼저 볼 N가지' 정형에 고정되지 않고 다양화되는지 (Phase C, point 6)."""

    def _best(self, topic, pid, ct, tg):
        from blogspot_automation.services.title_candidate_service import TitleCandidateService
        r = TitleCandidateService().generate_candidates(
            topic=topic, content_type=ct, topic_group=tg, pattern_id=pid
        )
        return (r.get("best_title") or {}).get("title", "")

    def test_prompt_recipe_title_not_formulaic(self):
        import re
        title = self._best(
            "보고서 초안용 ChatGPT 프롬프트 템플릿",
            "ai_prompt_recipe", "ai_prompt_recipe", "ai_prompt",
        )
        self.assertTrue(title, "best_title 비어 있음")
        self.assertIsNone(
            re.search(r"먼저\s*(볼|확인할|정할|해야)\s*\d+\s*가지", title),
            f"정형 패턴 제목이 선택됨: {title!r}",
        )


class TestAiToolReviewFlagship(unittest.TestCase):
    """플래그십 #2: ai_tool_review (master_guide Category A) 구조/스키마 검증."""

    @classmethod
    def setUpClass(cls):
        from blogspot_automation.services.golden_pattern_service import GoldenPatternService
        from blogspot_automation.services.slot_filler_service import SlotFillerService
        topic = "Perplexity AI 사용 후기와 무료 한계"
        ps = GoldenPatternService()
        cls.pm = ps.match_pattern(topic=topic, content_type="ai_tool_review", topic_group="ai_tool")
        sf = SlotFillerService()
        cls.sr = sf.fill_slots(pattern_id="ai_tool_review", topic=topic)
        cls.html = GoldenArticlePreviewService().render_article_candidate_html(
            cls.pm, cls.sr, selected_title="Perplexity AI 후기: 무료로 어디까지 되나",
        )

    def test_pattern_matched(self):
        self.assertEqual(self.pm.get("pattern_id"), "ai_tool_review")
        self.assertGreaterEqual(self.pm.get("confidence", 0), 80)

    def test_guide_modules_rendered(self):
        for marker in (
            'class="tool-summary"', 'class="who-for"', 'class="pricing-table"',
            'class="verdict-box"', "한 줄 요약", "추천 대상", "비추 대상",
            "무료 / 유료 경계", "최종 판정",
        ):
            self.assertIn(marker, self.html, f"모듈 누락: {marker}")

    def test_review_jsonld(self):
        self.assertIn("SoftwareApplication", self.html)
        self.assertIn('"@type": "Review"', self.html)
        self.assertIn('"reviewRating"', self.html)

    def test_no_news_residue(self):
        leaked = [m for m in _NEWS_RESIDUE if m in self.html]
        self.assertEqual(leaked, [], f"뉴스 잔재: {leaked}")

    def test_routes_to_tool_review(self):
        from blogspot_automation.pipelines.ai_pipeline import _classify_ai_topic
        self.assertEqual(_classify_ai_topic("ChatGPT 사용 후기"), ("ai_tool_review", "ai_tool"))


class TestAllAiPatternsComplete(unittest.TestCase):
    """9개 AI content_type 전체가 매칭·생성·잔재없음·라우팅을 만족하는지."""

    # (topic, content_type, topic_group, pattern_id)
    CASES = [
        ("직장인이 ChatGPT로 업무 시간 줄이기", "ai_work_tip", "ai_work", "ai_work_time_savings"),
        ("보고서 초안용 ChatGPT 프롬프트 템플릿", "ai_prompt_recipe", "ai_prompt", "ai_prompt_recipe"),
        ("Perplexity AI 사용 후기와 무료 한계", "ai_tool_review", "ai_tool", "ai_tool_review"),
        ("GPT-5 새 모델 업데이트 무엇이 바뀌었나", "ai_model_update", "ai_model", "ai_model_update"),
        ("AI 검색 시대 블로그 인용되는 글 구조 AEO GEO", "ai_search_change", "ai_search", "ai_search_change"),
        ("AI 블로그 자동화 조회수 망치는 글 구조 애드센스", "ai_blog_growth", "ai_blog", "ai_blog_growth"),
        ("ChatGPT vs Claude 업무용 비교 요금제", "ai_comparison", "ai_compare", "ai_comparison"),
        ("AI에 회사 자료 넣기 전 보안 개인정보 환각 주의", "ai_risk_security", "ai_risk", "ai_risk_security"),
        ("AI 처음 쓰는 초보 입문 기초 사용법", "ai_beginner_guide", "ai_beginner", "ai_beginner_guide"),
    ]

    def test_all_patterns_match_and_render_clean(self):
        svc = GoldenArticlePreviewService()
        for topic, ct, tg, pid in self.CASES:
            with self.subTest(pattern=pid):
                pm = svc._ps.match_pattern(topic=topic, content_type=ct, topic_group=tg)
                self.assertEqual(pm.get("pattern_id"), pid, f"매칭 실패: {pid}")
                self.assertGreaterEqual(pm.get("confidence", 0), 80)
                sr = svc._sf.fill_slots(pattern_id=pid, topic=topic)
                self.assertGreaterEqual(sr.get("slot_fill_rate", 0), 0.8, f"fill 부족: {pid}")
                html = svc.render_article_candidate_html(pm, sr, selected_title=topic)
                leaked = [m for m in _NEWS_RESIDUE if m in html]
                self.assertEqual(leaked, [], f"{pid} 뉴스 잔재: {leaked}")

    def test_all_patterns_route_correctly(self):
        from blogspot_automation.pipelines.ai_pipeline import _classify_ai_topic
        for topic, ct, tg, pid in self.CASES:
            with self.subTest(pattern=pid):
                if pid == "ai_work_time_savings":
                    continue  # 기본값(default) — 별도 키워드 없음
                r_ct, r_tg = _classify_ai_topic(topic)
                self.assertEqual(r_ct, ct, f"{topic!r} → {r_ct} (기대 {ct})")


class TestAiContentScoring(unittest.TestCase):
    """Phase D: AI 콘텐츠 점수 루브릭이 신호에 따라 합리적으로 산출되는지."""

    def _scores(self, topic, ct, tg, pid):
        from blogspot_automation.pipelines.ai_pipeline import compute_ai_content_scores
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic=topic, content_type=ct, topic_group=tg)
        html = svc.render_article_candidate_html(
            pv["pattern_match"], pv["slot_result"], selected_title=topic
        )
        return compute_ai_content_scores(
            slots=pv["slot_result"].get("slots") or {},
            candidate_html=html, content_type=ct, geo_score=85,
        )

    def test_rubric_dimensions_present(self):
        sc = self._scores(
            "보고서 초안용 ChatGPT 프롬프트 템플릿",
            "ai_prompt_recipe", "ai_prompt", "ai_prompt_recipe",
        )
        for key in (
            "search_intent_clarity", "practical_applicability", "save_worthiness",
            "tool_specificity", "comparison_value", "beginner_clarity",
            "monetization_value", "freshness", "risk_coverage",
            "ai_citation_likelihood", "ai_content_score_avg",
        ):
            self.assertIn(key, sc)
            self.assertGreaterEqual(sc[key], 0)
            self.assertLessEqual(sc[key], 100)

    def test_prompt_recipe_high_save_worth_and_risk(self):
        sc = self._scores(
            "보고서 초안용 ChatGPT 프롬프트 템플릿",
            "ai_prompt_recipe", "ai_prompt", "ai_prompt_recipe",
        )
        # 프롬프트박스+체크리스트 → 저장가치 높음, risk_note → 리스크 충족
        self.assertGreaterEqual(sc["save_worthiness"], 90)
        self.assertGreaterEqual(sc["risk_coverage"], 90)


class TestAiTopicRouting(unittest.TestCase):
    """프롬프트형 주제가 ai_prompt_recipe로, 그 외는 ai_work_tip로 라우팅되는지."""

    def test_prompt_topic_routes_to_recipe(self):
        from blogspot_automation.pipelines.ai_pipeline import _classify_ai_topic
        ct, tg = _classify_ai_topic("ChatGPT 프롬프트 템플릿 모음")
        self.assertEqual((ct, tg), ("ai_prompt_recipe", "ai_prompt"))

    def test_generic_ai_topic_routes_to_work_tip(self):
        from blogspot_automation.pipelines.ai_pipeline import _classify_ai_topic
        ct, tg = _classify_ai_topic("AI로 업무 시간 줄이는 방법")
        self.assertEqual((ct, tg), ("ai_work_tip", "ai_work"))


if __name__ == "__main__":
    unittest.main()
