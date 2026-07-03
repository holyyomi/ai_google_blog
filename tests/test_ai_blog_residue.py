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

    def test_distinct_from_other_structure(self):
        # 프롬프트 박스가 없는 타입(ai_model_update)과 구조가 다른지 확인 (차별화)
        svc = GoldenArticlePreviewService()
        other = svc.build_preview(
            topic="GPT-5 새 모델 업데이트 무엇이 바뀌었나",
            content_type="ai_model_update", topic_group="ai_model",
        )
        other_html = svc.render_article_candidate_html(
            other["pattern_match"], other["slot_result"], selected_title="x",
        )
        self.assertNotIn('class="prompt-recipe-box"', other_html)

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


class TestAiVisualUpgrade(unittest.TestCase):
    """업그레이드: 테마 색상 다양화 + 히어로 배너 + 모델 이슈형 프레이밍."""

    def _render(self, topic, ct, tg):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic=topic, content_type=ct, topic_group=tg)
        return svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title=topic)

    def test_ai_post_has_theme_and_hero(self):
        html = self._render("보고서 초안용 ChatGPT 프롬프트 템플릿", "ai_prompt_recipe", "ai_prompt")
        self.assertRegex(html, r'class="yomi-clean-post[^"]*\btheme-\w+', "테마 클래스 없음")
        self.assertIn('class="ai-hero', html)
        self.assertIn("ai-hero-badge", html)

    @staticmethod
    def _article_theme(html: str) -> str:
        import re
        m = re.search(r'<article class="yomi-clean-post([^"]*)"', html)
        if not m:
            return ""
        tm = re.search(r'theme-\w+', m.group(1))
        return tm.group(0) if tm else ""

    def test_news_post_has_no_theme_or_hero(self):
        html = self._render("홈택스 종합소득세 환급금 조회 방법", "tax_refund", "policy_benefit")
        self.assertEqual(self._article_theme(html), "", "뉴스 글에 테마 클래스가 붙음")
        self.assertNotIn('class="ai-hero', html)

    def test_themes_vary_by_topic(self):
        svc = GoldenArticlePreviewService()
        themes = set()
        for t in ("AI 글쓰기 도구 후기", "AI 이미지 생성 도구 후기", "AI 코딩 도구 후기", "AI 번역 도구 후기"):
            pv = svc.build_preview(topic=t, content_type="ai_tool_review", topic_group="ai_tool")
            html = svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title=t)
            themes.add(self._article_theme(html))
        self.assertGreaterEqual(len(themes), 2, f"테마가 다양하지 않음: {themes}")

    def test_model_update_uses_issue_framing(self):
        html = self._render("GPT-5 새 모델 업데이트 무엇이 바뀌었나", "ai_model_update", "ai_model")
        self.assertIn("지금 왜 화제인가", html)
        self.assertIn("활용법", html)
        # 일반 AI 프레이밍은 쓰지 않음
        self.assertNotIn("이 글이 도움이 되는 사람", html)


class TestAiFooterAndBadge(unittest.TestCase):
    """해시태그·내부링크 푸터, 'AI' 배지 제거, 실전 프롬프트 검증."""

    @classmethod
    def setUpClass(cls):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(
            topic="직장인이 ChatGPT로 업무 시간 줄이는 방법",
            content_type="ai_work_tip", topic_group="ai_work",
        )
        cls.html = svc.render_article_candidate_html(
            pv["pattern_match"], pv["slot_result"], selected_title="ChatGPT 업무 활용법",
        )

    def test_internal_links_present(self):
        self.assertIn("yomi-internal-links", self.html)
        self.assertIn("/search/label/", self.html)

    def test_hashtags_present(self):
        self.assertTrue(
            "yomi-hashtags" in self.html or "hashtag" in self.html.lower(),
            "해시태그 푸터 없음",
        )
        self.assertRegex(self.html, r"#[가-힣A-Za-z0-9]")

    def test_no_ai_badge_in_stylesheet(self):
        from blogspot_automation.services.seo_policy import YOMI_CLEAN_ARTICLE_STYLE
        self.assertNotIn('content:"AI"', YOMI_CLEAN_ARTICLE_STYLE)

    def test_work_tip_has_ready_prompts(self):
        self.assertIn('class="prompt-recipe-box"', self.html)
        self.assertIn("당신은", self.html)


class TestAiStructuredData(unittest.TestCase):
    """JSON-LD: HowTo(행동/설명 키 인식) + BreadcrumbList 출력."""

    def _html(self, topic, ct, tg):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic=topic, content_type=ct, topic_group=tg)
        return svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title=topic)

    def test_howto_emitted_for_eligible(self):
        html = self._html("보고서 초안용 ChatGPT 프롬프트 템플릿", "ai_prompt_recipe", "ai_prompt")
        self.assertIn('"HowTo"', html)
        self.assertIn('"HowToStep"', html)

    def test_breadcrumb_emitted(self):
        html = self._html("Perplexity AI 사용 후기", "ai_tool_review", "ai_tool")
        self.assertIn('"BreadcrumbList"', html)
        self.assertIn('"ListItem"', html)

    def test_tool_review_full_schema_stack(self):
        html = self._html("Perplexity AI 사용 후기", "ai_tool_review", "ai_tool")
        for t in ('"BlogPosting"', '"FAQPage"', '"Review"', "SoftwareApplication", '"BreadcrumbList"'):
            self.assertIn(t, html, f"누락: {t}")


class TestAiSlotEnricher(unittest.TestCase):
    """LLM 본문 보강: 성공 시 주제 특화 교체, 실패 시 템플릿 폴백."""

    def _fake(self, payload):
        import json
        class _F:
            def call_with_fallback(self, user_prompt, system_prompt=None, min_chars=200, validator=None):
                out = json.dumps(payload, ensure_ascii=False)
                if validator:
                    validator(out)
                return out
        return _F()

    def test_enrich_replaces_slots(self):
        from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
        payload = {
            "hook_opening": "Perplexity는 출처를 함께 보여주는 검색형 AI입니다. 사실 조사에 강합니다. 무료는 제한이 있습니다. 리서치에 적합합니다.",
            "yomi_judgment": "검색·리서치에 최적화된 도구입니다. 무료로 시작해 한계에서 Pro를 고려하세요. 창작보다 조사에 강합니다.",
            "faq": [{"Q": "무료로 되나요?", "A": "기본 검색은 무료로 충분합니다. 고급 기능은 제한이 있습니다."},
                    {"Q": "ChatGPT와 차이는?", "A": "출처를 제시하는 검색형입니다."},
                    {"Q": "출처는 정확한가요?", "A": "유용하지만 직접 확인이 필요합니다."}],
        }
        slots = {"hook_opening": "원본", "yomi_judgment": "원본", "faq": [{"Q": "a", "A": "b"}]}
        out = enrich_slots_with_llm(slots=slots, topic="Perplexity 후기", content_type="ai_tool_review", llm_service=self._fake(payload))
        self.assertIn("Perplexity", out["hook_opening"])
        self.assertEqual(len(out["faq"]), 3)

    def test_enrich_falls_back_on_garbage(self):
        from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
        class _Bad:
            def call_with_fallback(self, *a, **k):
                return "not json at all"
        slots = {"hook_opening": "원본훅", "yomi_judgment": "원본결론", "faq": [{"Q": "a", "A": "b"}]}
        out = enrich_slots_with_llm(slots=slots, topic="x", content_type="ai_tool_review", llm_service=_Bad())
        self.assertEqual(out["hook_opening"], "원본훅")  # 폴백

    def test_llm_title_adopted_and_filtered(self):
        from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
        # 정형구 제목은 거부, 자연스러운 제목은 채택
        good = {"hook_opening": "x"*30, "yomi_judgment": "y"*30, "faq": [{"Q": "q1", "A": "a1"}, {"Q": "q2", "A": "a2"}, {"Q": "q3", "A": "a3"}],
                "title": "미드저니 무료 대안, 실무에서 쓸 만한 3곳"}
        out = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}]},
                                    topic="t", content_type="ai_tool_review", llm_service=self._fake(good))
        self.assertEqual(out.get("_llm_title"), "미드저니 무료 대안, 실무에서 쓸 만한 3곳")
        bad = dict(good, title="AI 이미지 도구, 쓰기 전 먼저 볼 3가지")
        out2 = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}]},
                                     topic="t", content_type="ai_tool_review", llm_service=self._fake(bad))
        self.assertNotIn("_llm_title", out2)  # 정형구 제목 거부

    def test_prompt_block_replaced_and_added(self):
        from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
        payload = {"hook_opening": "x"*30, "yomi_judgment": "y"*30,
                   "faq": [{"Q": "q1", "A": "a1"}, {"Q": "q2", "A": "a2"}, {"Q": "q3", "A": "a3"}],
                   "prompt_block": [{"label": "썸네일", "prompt": "flat illustration -> 16:9"}, {"label": "컨셉", "prompt": "product art"}]}
        # 템플릿에 prompt_block 있으면 교체
        out = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}], "prompt_block": [{"label": "old", "prompt": "old"}]},
                                    topic="t", content_type="ai_prompt_recipe", llm_service=self._fake(payload))
        self.assertEqual(out["prompt_block"][0]["label"], "썸네일")
        # 2026-07-02 저장가치 정책: 템플릿에 없어도 복사형 프롬프트 자산을 추가한다
        out2 = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}]},
                                     topic="t", content_type="ai_tool_review", llm_service=self._fake(payload))
        self.assertEqual(out2["prompt_block"][0]["label"], "썸네일")
        # 항목이 2개 미만이면 추가하지 않음 (형식 불량 폴백)
        thin = dict(payload, prompt_block=[{"label": "하나", "prompt": "only one"}])
        out3 = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}]},
                                     topic="t", content_type="ai_tool_review", llm_service=self._fake(thin))
        self.assertNotIn("prompt_block", out3)

    def test_save_value_slots_enriched(self):
        """pricing_table/checklist/quick_decision_table/actions 저장가치 슬롯 보강."""
        from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
        payload = {
            "hook_opening": "x"*30, "yomi_judgment": "y"*30,
            "faq": [{"Q": "q1", "A": "a1"}, {"Q": "q2", "A": "a2"}, {"Q": "q3", "A": "a3"}],
            "quick_decision_table": [
                {"내 상황": "s1", "할 일": "d1"}, {"내 상황": "s2", "할 일": "d2"},
                {"내 상황": "s3", "할 일": "d3"},
            ],
            "actions": [
                {"행동": "a1", "설명": "d1"}, {"행동": "a2", "설명": "d2"}, {"행동": "a3", "설명": "d3"},
            ],
            "pricing_table": [
                {"플랜": "무료", "가격": "0원", "핵심 기능": "기본 생성", "한계": "일일 한도"},
                {"플랜": "Plus", "가격": "공식 요금 페이지 확인", "핵심 기능": "고급 모델", "한계": "월 구독"},
            ],
            "checklist": ["회사 기밀 입력 금지 항목 확인", "결과물 팩트 직접 검증", "사내 AI 사용 정책 확인", "개인정보 마스킹 후 입력"],
        }
        out = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}]},
                                    topic="t", content_type="ai_work_tip", llm_service=self._fake(payload))
        self.assertEqual(len(out["quick_decision_table"]), 3)
        self.assertEqual(len(out["actions"]), 3)
        self.assertEqual(out["pricing_table"][0]["플랜"], "무료")
        self.assertEqual(len(out["checklist"]), 4)
        # pricing_table 2행 미만이면 미채택
        thin = dict(payload, pricing_table=[{"플랜": "무료", "가격": "0원", "핵심 기능": "f", "한계": "l"}])
        out2 = enrich_slots_with_llm(slots={"hook_opening": "o", "yomi_judgment": "o", "faq": [{"Q": "a", "A": "b"}]},
                                     topic="t", content_type="ai_work_tip", llm_service=self._fake(thin))
        self.assertNotIn("pricing_table", out2)

    def test_disabled_via_env(self):
        import os
        from blogspot_automation.services.ai_slot_enricher import enrich_slots_with_llm
        os.environ["ENABLE_AI_LLM_ENRICH"] = "false"
        try:
            slots = {"hook_opening": "원본훅", "faq": []}
            out = enrich_slots_with_llm(slots=slots, topic="x", content_type="ai_tool_review", llm_service=self._fake({}))
            self.assertEqual(out["hook_opening"], "원본훅")
        finally:
            del os.environ["ENABLE_AI_LLM_ENRICH"]


class TestAiQualityGate(unittest.TestCase):
    """soft 품질 게이트: 정상 글은 통과(매일 발행 안전), 깨진 글만 하드 차단."""

    def test_all_patterns_pass_gate(self):
        from blogspot_automation.services.ai_quality_gate import evaluate_ai_publish_quality
        svc = GoldenArticlePreviewService()
        cases = [
            ("직장인 ChatGPT 업무", "ai_work_tip", "ai_work"),
            ("프롬프트 템플릿", "ai_prompt_recipe", "ai_prompt"),
            ("Perplexity 후기", "ai_tool_review", "ai_tool"),
            ("GPT-5 업데이트", "ai_model_update", "ai_model"),
            ("AI 검색 AEO", "ai_search_change", "ai_search"),
            ("AI 블로그 수익화", "ai_blog_growth", "ai_blog"),
            ("ChatGPT vs Claude", "ai_comparison", "ai_compare"),
            ("AI 보안 환각", "ai_risk_security", "ai_risk"),
            ("AI 입문", "ai_beginner_guide", "ai_beginner"),
        ]
        for topic, ct, tg in cases:
            with self.subTest(ct=ct):
                pv = svc.build_preview(topic=topic, content_type=ct, topic_group=tg)
                h = svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title=topic)
                q = evaluate_ai_publish_quality(h, content_type=ct)
                self.assertTrue(q["passed"], f"{ct} 발행 차단됨: {q['hard_blocks']}")

    def test_broken_html_hard_blocked(self):
        from blogspot_automation.services.ai_quality_gate import evaluate_ai_publish_quality
        self.assertFalse(evaluate_ai_publish_quality("<html><body><p>짧음</p></body></html>")["passed"])

    def test_banned_phrase_hard_blocked(self):
        from blogspot_automation.services.ai_quality_gate import evaluate_ai_publish_quality
        bad = '<h1>x</h1><section id="AI_CITATION_SUMMARY"><p>' + ("내용 " * 400) + ' 월 1000만원 보장</p></section>'
        q = evaluate_ai_publish_quality(bad)
        self.assertFalse(q["passed"])
        self.assertTrue(any("banned_phrase" in b for b in q["hard_blocks"]))


class TestAiInternalLinks(unittest.TestCase):
    """발행 이력 기반 실제 내부링크 우선, 없으면 라벨 링크 폴백."""

    def _render(self, *, pairs=None):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic="ChatGPT vs Claude 비교", content_type="ai_comparison", topic_group="ai_compare")
        return svc.render_article_candidate_html(
            pv["pattern_match"], pv["slot_result"], selected_title="AI 비교",
            internal_link_pairs=pairs,
        )

    def test_real_links_used_when_provided(self):
        pairs = [("ChatGPT 업무 활용법", "https://holyyomiai.blogspot.com/2026/06/chatgpt-work.html")]
        html = self._render(pairs=pairs)
        self.assertIn("https://holyyomiai.blogspot.com/2026/06/chatgpt-work.html", html)
        self.assertIn("ChatGPT 업무 활용법", html)

    def test_label_fallback_without_history(self):
        html = self._render(pairs=None)
        self.assertIn("yomi-internal-links", html)
        self.assertIn("/search/label/", html)


class TestLivePostFixes(unittest.TestCase):
    """라이브 발행에서 발견된 문제 회귀 방지: CSS 글리프·프롬프트 가독성."""

    @classmethod
    def setUpClass(cls):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic="보고서 프롬프트 템플릿", content_type="ai_prompt_recipe", topic_group="ai_prompt")
        cls.html = svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title="프롬프트 모음")

    def test_no_raw_html_entity_in_css_content(self):
        # CSS content에 HTML 엔티티(&#9654; 등)가 들어가면 글자 그대로 노출됨 → 금지
        self.assertNotIn("&#9654", self.html)
        self.assertNotIn("&#10003", self.html)

    def test_css_uses_unicode_escapes(self):
        # 체크/화살표 글리프는 CSS 유니코드 이스케이프로(발행 후에도 안전)
        self.assertIn(r'content:"\2713"', self.html)
        self.assertIn(r'content:"\25B6\00A0"', self.html)

    def test_prompt_code_readable_light_scheme(self):
        # 프롬프트 박스는 밝은 배경+어두운 글씨 + !important (테마 덮어쓰기 방어)
        self.assertIn("background:#f1f5f9!important;color:#0f172a!important", self.html)


class TestForcedPatternFallback(unittest.TestCase):
    """키워드 매칭이 약한 AI 주제도 분류 패턴으로 강제 빌드되어 발행 가능해야 함."""

    def test_forced_pattern_builds_when_keywords_weak(self):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(
            topic="낯선이름툴 사용기",  # 키워드 매칭 안 되는 주제
            content_type="ai_work_tip", topic_group="ai_work",
            forced_pattern_id="ai_work_time_savings",
        )
        self.assertTrue(pv.get("matched"))
        self.assertEqual(pv["pattern_match"]["pattern_id"], "ai_work_time_savings")
        self.assertGreaterEqual(pv.get("slot_fill_rate", 0), 0.8)


class TestAiToc(unittest.TestCase):
    """목차(TOC) 출력 — AI 글에만."""

    def test_toc_present_with_anchors(self):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic="Perplexity AI 사용 후기와 무료 한계", content_type="ai_tool_review", topic_group="ai_tool")
        html = svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title="Perplexity 후기")
        self.assertIn('class="ai-toc"', html)
        import re
        self.assertGreaterEqual(len(re.findall(r'id="sec-\d+"', html)), 4)
        # AI가 썼다고 광고하는 작성자 바이라인은 노출하지 않음
        self.assertNotIn('class="ai-byline"', html)

    def test_news_post_no_toc(self):
        svc = GoldenArticlePreviewService()
        pv = svc.build_preview(topic="홈택스 종합소득세 환급금 조회 방법", content_type="tax_refund", topic_group="policy_benefit")
        html = svc.render_article_candidate_html(pv["pattern_match"], pv["slot_result"], selected_title="홈택스 환급금")
        self.assertNotIn('class="ai-toc"', html)


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
