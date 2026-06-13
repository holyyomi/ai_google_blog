"""오늘의 이슈 editorial gate 회귀 테스트.

검증 항목:
- today_relevance / issue_specificity / original_issue_preservation 점수 계산
- "9월부터" 같은 미래 일정은 today_relevance 낮음
- privacy_security 후보가 환불 제목으로 발행 금지
- AI 내부 라벨이 HTML visible text에 노출되면 차단
- 네이버블로그 CTA 누락 시 차단
- privacy 토픽이 환불 키워드 없을 때 환불 제목 금지
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.news_quality_gate import NewsQualityGate


def _make_scored(
    *,
    topic: str,
    original_topic: str = "",
    content_type: str = "consumer_warning",
    topic_group: str = "refund_consumer",
    total_score: int = 80,
    source_type: str = "google_news_rss",
    is_stale: bool = False,
    reader_questions: list[str] | None = None,
    published_at: str = "2026-05-14T05:00:00+00:00",
    hook_angle: dict | None = None,
    click_potential: int = 9,
):
    cand_raw = {
        "topic_group": topic_group,
        "source_type": source_type,
        "is_stale": is_stale,
        "click_potential_score": click_potential,
        "content_angle": {"content_type": content_type, "topic_group": topic_group},
        "original_topic": original_topic,
        "reader_search_questions": reader_questions or [
            "사례에서 먼저 확인할 것은 무엇인가요?",
            "본인이 영향 대상인지 어떻게 알 수 있나요?",
            "공식 안내는 어디서 확인하나요?",
        ],
        "hook_angle": hook_angle or {"safe_title_keyword": topic[:18]},
    }
    nc = NewsCandidate(
        topic=topic, category=topic_group, summary="",
        source_hint="오늘경제", published_at=published_at, url=None,
        raw=cand_raw,
    )
    scored = MagicMock()
    scored.candidate = nc
    scored.total_score = total_score
    scored.risk_penalty = 0
    scored.freshness_score = 0.8
    scored.search_demand_score = 0
    scored.contrarian_gap_score = 0
    scored.mass_impact_score = 0
    scored.adsense_value_score = 0
    scored.hook_score = 0
    scored.reason = "test"
    return scored


def _minimal_html(title: str, *, with_naver: bool = True, with_ai_label: bool = False, faq_count: int = 3) -> str:
    parts = [
        '<!DOCTYPE html><html><head>',
        '<meta name="description" content="이 글의 핵심 요약은 80자에서 160자 사이로 작성되어 있으며 독자에게 어떤 내용인지를 알려줍니다.">',
        '</head><body>',
        f'<h1>{title}</h1>',
    ]
    if with_ai_label:
        parts.append('<section><h2>AI Overviews 핵심 답변</h2><p>요약입니다.</p></section>')
    else:
        parts.append('<section><h2>핵심 요약</h2><p>이 이슈의 핵심을 자연스럽게 정리한 요약문입니다.</p></section>')
    # FAQ
    parts.append('<section class="faq">')
    for i in range(faq_count):
        parts.append(f'<h3>Q{i+1}. 자주 묻는 질문 {i+1}</h3><p>이 답변은 적당한 길이로 작성된 텍스트로 20자 이상입니다.</p>')
    parts.append('</section>')
    parts.append('<script type="application/ld+json">{"@type": "FAQPage"}</script>')
    if with_naver:
        parts.append('<section><a href="https://blog.naver.com/holyyomi">네이버 블로그</a></section>')
    parts.append('</body></html>')
    return "\n".join(parts)


class TestTodayRelevance(unittest.TestCase):
    """today_relevance_score 계산 테스트."""

    def test_future_date_lowers_score(self):
        scored = _make_scored(
            topic="이슈] 9월부터 개인정보 확인 전에 볼 주의점",
            original_topic="9월부터 개인정보 유출땐 매출 10% 과징금",
        )
        score = NewsQualityGate._compute_today_relevance(scored)
        self.assertLess(score, 7,
                        f"미래 일정 후보 today_relevance가 {score} (7 미만이어야 함)")

    def test_today_signal_raises_score(self):
        scored = _make_scored(
            topic="오늘 카드사 보안 사고 발생, 소비자가 먼저 확인할 것",
            original_topic="오늘 카드사에서 개인정보 유출 사고 발생",
        )
        score = NewsQualityGate._compute_today_relevance(scored)
        self.assertGreaterEqual(score, 6,
                                f"오늘성 신호 있는 후보 today_relevance가 {score} (6 이상이어야 함)")

    def test_trending_engine_signal_reaches_publish_threshold(self):
        scored = _make_scored(
            topic="front page issue",
            content_type="today_issue_explainer",
            topic_group="today_issue",
            source_type="naver_trending",
            published_at="",
        )
        scored.candidate.raw["trending_engine"] = True
        scored.candidate.raw["today_buzz_score"] = 9
        scored.candidate.raw["source_count"] = 4

        score = NewsQualityGate._compute_today_relevance(scored)

        self.assertGreaterEqual(score, 7)

    def test_stale_zero(self):
        scored = _make_scored(
            topic="옛 카드사 보안 사고",
            original_topic="옛 카드사 보안",
            is_stale=True,
        )
        score = NewsQualityGate._compute_today_relevance(scored)
        self.assertEqual(score, 0)


class TestIssueSpecificity(unittest.TestCase):
    """issue_specificity_score 계산 테스트."""

    def test_specific_keywords_raise_score(self):
        scored = _make_scored(
            topic="카드사 개인정보 유출 과징금 매출 10%",
            original_topic="카드사 개인정보 유출 매출 10% 과징금",
        )
        score = NewsQualityGate._compute_issue_specificity(scored)
        self.assertGreaterEqual(score, 7)

    def test_generic_topic_low_score(self):
        scored = _make_scored(
            topic="확인할 조건",
            original_topic="",
        )
        score = NewsQualityGate._compute_issue_specificity(scored)
        self.assertLess(score, 7)

    def test_latin_source_entity_raises_specificity(self):
        scored = _make_scored(
            topic="BTS 공연 주간 비교 전에 확인할 조건",
            original_topic="BTS 공연 주간 부산 추가 결제 요구 주의",
        )

        score = NewsQualityGate._compute_issue_specificity(scored)

        self.assertGreaterEqual(score, 6)

    def test_delivery_money_terms_raise_specificity(self):
        scored = _make_scored(
            topic="배달앱 결제금액 비교 전에 확인할 조건",
            original_topic="공공 배달앱 이용자 10명 중 8명 다시 이용하겠다",
            content_type="money_checklist",
            topic_group="delivery_money",
        )

        score = NewsQualityGate._compute_issue_specificity(scored)

        self.assertGreaterEqual(score, 6)

    def test_ai_evergreen_low_issue_specificity_warns_not_blocks(self):
        gate = NewsQualityGate()
        title = "직장인 ChatGPT, 시간 줄이려면 먼저 볼 3가지"
        scored = _make_scored(
            topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
            original_topic="직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유",
            content_type="ai_work_tip",
            topic_group="ai_work",
            source_type="evergreen_fallback",
            total_score=88,
        )
        scored.candidate.raw["evergreen_axis"] = "ai_automation"
        scored.candidate.raw["target_reader"] = "30~50대 직장인"

        result = gate.evaluate(
            selected=scored,
            selected_title=title,
            html=_minimal_html(title),
            image_prompt="AI 업무 자동화 이미지",
            image_alt_text="AI 업무 자동화 체크리스트",
            labels=["AI활용", "업무자동화", "생산성"],
            hashtags=["#AI활용", "#업무자동화", "#생산성"],
            dry_run=True,
            news_publish_mode="dry_run",
        )

        self.assertFalse(
            any(str(issue).startswith("issue_specificity_below_6:") for issue in result["blocking_issues"]),
            result["blocking_issues"],
        )
        self.assertTrue(
            any(str(warning).startswith("ai_evergreen_issue_specificity_below_6:") for warning in result["warnings"]),
            result["warnings"],
        )

    def test_title_latin_entity_matches_source_entity(self):
        scored = _make_scored(
            topic="BTS 공연 주간 비교 전에 확인할 조건",
            original_topic="BTS 공연 주간 부산 추가 결제 요구 주의",
        )

        self.assertTrue(
            NewsQualityGate._title_has_latin_source_entity(
                "BTS 공연 주간 비교, 결제 전 먼저 볼 3가지",
                scored,
            )
        )


class TestOriginalIssuePreservation(unittest.TestCase):
    """원문 키워드 보존 점수 테스트."""

    def test_preserved_keyword_high_score(self):
        scored = _make_scored(
            topic="개인정보 유출 과징금 카드사",
            original_topic="개인정보 유출 카드사 매출 10% 과징금",
        )
        score = NewsQualityGate._compute_original_issue_preservation(
            scored, title="개인정보 유출 과징금 카드사 보안 부담"
        )
        self.assertGreaterEqual(score, 5)

    def test_lost_keyword_low_score(self):
        scored = _make_scored(
            topic="환불 기다리기 전에 먼저 확인할 것",
            original_topic="9월부터 개인정보 유출땐 매출 10% 과징금 카드사 보안",
        )
        # 환불 제목인데 원문엔 환불 키워드 없음 → preservation 낮음
        score = NewsQualityGate._compute_original_issue_preservation(
            scored, title="환불 기다리기 전에 먼저 확인할 것"
        )
        self.assertLess(score, 7)

    def test_support_title_ignores_hype_tokens_for_preservation(self):
        scored = _make_scored(
            topic="청년 운전면허 지원금 신청방법과 대상 조건",
            original_topic="1인당 최대 50만 원 줍니다 2026 청년 운전면허 지원금, 어떻게 받나? - 위키트리",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )

        score = NewsQualityGate._compute_original_issue_preservation(
            scored,
            title="청년 운전면허 지원금 신청방법과 대상 조건, 신청 전 먼저 볼 3가지",
        )

        self.assertGreaterEqual(score, 6)


class TestTitleLeakGuards(unittest.TestCase):
    """잘못된 환불/policy 제목 누수 차단."""

    def _evaluate(self, *, title: str, topic: str, original_topic: str = "",
                  content_type: str = "consumer_warning", topic_group: str = "refund_consumer",
                  with_naver: bool = True, with_ai_label: bool = False) -> list[str]:
        gate = NewsQualityGate()
        scored = _make_scored(
            topic=topic, original_topic=original_topic,
            content_type=content_type, topic_group=topic_group,
        )
        result = gate.evaluate(
            selected=scored, selected_title=title,
            html=_minimal_html(title, with_naver=with_naver, with_ai_label=with_ai_label),
            image_prompt="prompt", image_alt_text="alt",
            labels=["test"], hashtags=["#test"],
            dry_run=True, news_publish_mode="dry_run",
        )
        return list(result.get("blocking_issues", []))

    def test_refund_phrase_on_privacy_blocked(self):
        issues = self._evaluate(
            title="환불 기다리기 전에 먼저 확인할 것",
            topic="개인정보 확인 안내",
            original_topic="개인정보 유출 카드사 보안",
            topic_group="privacy_security",
        )
        self.assertTrue(
            any("refund_phrase_leak" in i or "privacy_topic_with_refund_title" in i for i in issues),
            f"환불 누수 차단 안 됨: {issues}",
        )

    def test_media_series_prefix_selected_title_blocked(self):
        issues = self._evaluate(
            title="재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지",
            topic="KT초이스 요금제 무료 혜택 반응",
            original_topic="[재계는 지금] KT 초이스 요금제 무료 혜택",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
        )

        self.assertIn("selected_title_malformed_phrase", issues)
        self.assertIn("telecom_plan_topic_using_viral_reaction_template", issues)

    def test_telecom_plan_topic_cannot_use_viral_reaction_template(self):
        issues = self._evaluate(
            title="KT초이스 요금제 무료 반응이 갈린 이유, 먼저 볼 3가지",
            topic="KT초이스 요금제 무료 혜택",
            original_topic="KT 초이스 요금제 무료 혜택",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
        )

        self.assertIn("telecom_plan_topic_using_viral_reaction_template", issues)

    def test_refund_phrase_with_legitimate_refund_topic_ok(self):
        # refund 토픽 + 환불 제목 = OK
        issues = self._evaluate(
            title="서비스 환불 지연 논란, 소비자가 먼저 확인할 3가지",
            topic="환불 지연 결제 취소",
            original_topic="환불 결제 취소 분쟁",
            topic_group="refund_consumer",
        )
        # refund_phrase_leak 없어야 함
        self.assertFalse(
            any("refund_phrase_leak" in i for i in issues),
            f"정당한 refund 제목이 차단됨: {issues}",
        )

    def test_policy_title_target_condition_is_not_truncated_word(self):
        issues = self._evaluate(
            title="청년 운전면허 지원금 신청방법과 대상 조건",
            topic="청년 운전면허 지원금 신청방법과 대상 조건",
            original_topic="2026 청년 운전면허 지원금 어떻게 받나",
            content_type="policy_deadline",
            topic_group="policy_benefit",
        )

        self.assertNotIn("selected_title_has_truncated_word", issues)

    def test_bad_subject_particle_title_is_blocked(self):
        issues = self._evaluate(
            title="티빙가 화제 된 이유, 사람들이 본 핵심 포인트",
            topic="티빙 OTT 신작 반응",
            original_topic="티빙 OTT 신작 공개 후 반응",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
        )

        self.assertIn("selected_title_bad_subject_particle", issues)

    def test_low_value_viral_rating_title_is_blocked(self):
        issues = self._evaluate(
            title="티빙 신작, 평점보다 먼저 볼 포인트",
            topic="티빙 OTT 신작 반응",
            original_topic="티빙 OTT 신작 공개 후 반응",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
        )

        self.assertIn("selected_title_low_value_viral_rating_formula", issues)

    def test_title_terms_only_in_faq_questions_are_blocked(self):
        gate = NewsQualityGate()
        title = "이번엔 티빙 개인정보가 화제 된 반응이 갈린 이유, 먼저 볼 3가지"
        scored = _make_scored(
            topic=title,
            original_topic="티빙 개인정보 안내 관련 온라인 반응",
            content_type="viral_issue_decode",
            topic_group="ott_platform",
            source_type="naver_news_search",
        )
        html = """
        <html><head>
        <meta name="description" content="이 글의 설명입니다. 본문 품질 검사를 위한 충분한 길이의 설명 문장입니다.">
        </head><body>
        <h1>이번엔 티빙 개인정보가 화제 된 반응이 갈린 이유, 먼저 볼 3가지</h1>
        <p>같은 드라마를 봤는데 주변 반응이 전혀 다를 때가 있다.</p>
        <h3>Q. 이번엔 티빙 개인정보가 화제 된 이유는 무엇인가요?</h3>
        <p>시청 방식과 장르 기대값 차이 때문에 반응이 갈릴 수 있습니다.</p>
        <table><tr><td>넷플릭스 순위</td><td>시청 시간 집계 기준</td></tr></table>
        <script type="application/ld+json">{"@type":"FAQPage"}</script>
        </body></html>
        """
        result = gate.evaluate(
            selected=scored,
            selected_title=title,
            html=html,
            image_prompt="prompt",
            image_alt_text="alt",
            labels=["OTT"],
            hashtags=["#OTT"],
            dry_run=False,
            news_publish_mode="publish",
        )

        issues = list(result.get("blocking_issues", []))
        self.assertTrue(
            any(issue.startswith("title_body_entity_mismatch:") for issue in issues),
            f"title/body mismatch was not blocked: {issues}",
        )

    def test_title_terms_in_substantive_body_pass_alignment(self):
        gate = NewsQualityGate()
        title = "티빙 개인정보 안내 반응이 갈린 이유, 먼저 볼 3가지"
        scored = _make_scored(
            topic=title,
            original_topic="티빙 개인정보 안내 관련 온라인 반응",
            content_type="consumer_warning",
            topic_group="privacy_security",
            source_type="naver_news_search",
        )
        html = _minimal_html(title).replace(
            "이 이슈의 핵심을 자연스럽게 정리한 요약문입니다.",
            "티빙 개인정보 안내에서 확인할 것은 공식 공지, 계정 보안, 이용자 영향입니다.",
        )

        result = gate.evaluate(
            selected=scored,
            selected_title=title,
            html=html,
            image_prompt="prompt",
            image_alt_text="alt",
            labels=["개인정보"],
            hashtags=["#개인정보"],
            dry_run=True,
            news_publish_mode="dry_run",
        )

        issues = list(result.get("blocking_issues", []))
        self.assertFalse(
            any(issue.startswith("title_body_entity_mismatch:") for issue in issues),
            f"substantive body alignment should pass: {issues}",
        )

    def test_title_body_alignment_ignores_generic_context_words(self):
        alignment = NewsQualityGate._title_body_alignment(
            title="JTBC 오늘 오후, 지금 확인된 것과 아직 모르는 것",
            html="<p>JTBC 오후 예측조사 관련 확인 내용을 정리합니다.</p>",
        )

        self.assertEqual(alignment["required_terms"], ["jtbc", "오후"])
        self.assertEqual(alignment["missing_terms"], [])


class TestPolicyDeadlineChecklistCount(unittest.TestCase):
    def test_quick_decision_table_counts_as_policy_checklist(self):
        html = """
        <section class="quick-decision-table">
          <table><tbody>
            <tr><td>대상 모름</td><td>공식 공지의 지원 대상 확인</td></tr>
            <tr><td>소득 기준 모름</td><td>소득 기준 확인</td></tr>
            <tr><td>서류 모름</td><td>필요 서류 확인</td></tr>
            <tr><td>신청 경로 모름</td><td>공식 신청 경로 확인</td></tr>
            <tr><td>마감 임박</td><td>보완 가능 여부 확인</td></tr>
          </tbody></table>
        </section>
        """

        self.assertEqual(NewsQualityGate._policy_checklist_count(html), 5)


class TestAILabelAbsent(unittest.TestCase):
    """AI 내부 라벨이 visible html에 노출되면 차단."""

    def test_ai_overview_label_blocks(self):
        gate = NewsQualityGate()
        scored = _make_scored(
            topic="개인정보 확인 카드사 과징금 매출 10%",
            original_topic="개인정보 유출 카드사 과징금 매출 10%",
            topic_group="privacy_security",
        )
        html = _minimal_html(
            title="개인정보 확인 안내 받았다면 먼저 확인할 3가지",
            with_naver=True,
            with_ai_label=True,
        )
        result = gate.evaluate(
            selected=scored, selected_title="개인정보 확인 안내 받았다면 먼저 확인할 3가지",
            html=html, image_prompt="prompt", image_alt_text="alt",
            labels=["test"], hashtags=["#test"],
            dry_run=True, news_publish_mode="dry_run",
        )
        self.assertIn("ai_internal_label_visible_in_html", result.get("blocking_issues", []))

    def test_no_ai_label_passes(self):
        gate = NewsQualityGate()
        scored = _make_scored(
            topic="개인정보 확인 카드사 과징금 매출 10%",
            original_topic="개인정보 유출 카드사 과징금 매출 10%",
            topic_group="privacy_security",
        )
        html = _minimal_html(
            title="개인정보 확인 안내 받았다면 먼저 확인할 3가지",
            with_naver=True,
            with_ai_label=False,
        )
        result = gate.evaluate(
            selected=scored, selected_title="개인정보 확인 안내 받았다면 먼저 확인할 3가지",
            html=html, image_prompt="prompt", image_alt_text="alt",
            labels=["test"], hashtags=["#test"],
            dry_run=True, news_publish_mode="dry_run",
        )
        self.assertNotIn("ai_internal_label_visible_in_html", result.get("blocking_issues", []))


class TestNaverCTAPresence(unittest.TestCase):
    """네이버블로그 CTA 누락 시 차단."""

    def test_naver_cta_missing_not_blocked(self):
        gate = NewsQualityGate()
        scored = _make_scored(
            topic="개인정보 확인 카드사 과징금",
            original_topic="개인정보 유출 카드사 과징금",
            topic_group="privacy_security",
        )
        html = _minimal_html(
            title="개인정보 확인 안내 받았다면 먼저 확인할 3가지",
            with_naver=False,
        )
        result = gate.evaluate(
            selected=scored, selected_title="개인정보 확인 안내 받았다면 먼저 확인할 3가지",
            html=html, image_prompt="prompt", image_alt_text="alt",
            labels=["test"], hashtags=["#test"],
            dry_run=True, news_publish_mode="dry_run",
        )
        self.assertNotIn("naver_blog_cta_missing", result.get("blocking_issues", []))


class TestTopIssuePublishRelaxation(unittest.TestCase):
    """상위 클릭 이슈는 실제 출처와 품질 점수가 충분할 때 점수성 차단만 완화."""

    def test_korean_source_entity_detects_world_cup(self):
        scored = _make_scored(
            topic="2026 월드컵 반응이 갈린 이유",
            original_topic="2026 월드컵 조추첨 발표와 경기 일정 반응",
            content_type="viral_issue_decode",
            topic_group="entertainment_sports",
            source_type="naver_news_search",
        )

        self.assertTrue(
            NewsQualityGate._title_has_source_entity(
                "2026 월드컵이 화제 된 이유, 경기 일정 전 먼저 볼 포인트",
                scored,
            )
        )

    def test_relaxes_only_soft_top_issue_blockers(self):
        scored = _make_scored(
            topic="삼성전자 SK하이닉스 상승 출발",
            original_topic="속보 삼성전자 3% SK하이닉스 1% 상승 출발",
            content_type="today_issue_explainer",
            topic_group="today_issue",
            source_type="google_news_rss",
            total_score=70,
            click_potential=7,
        )
        scored.candidate.raw["topic_engine_score"] = 73
        blocking = [
            "click_potential_score_below_8",
            "raw_topic_repeated_in_html",
            "missing_faq_section",
        ]
        warnings: list[str] = []

        relaxed = NewsQualityGate._relax_top_issue_publish_blockers(
            blocking_issues=blocking,
            warnings=warnings,
            publish_mode_active=True,
            fallback_candidate=False,
            source_type="google_news_rss",
            content_type="today_issue_explainer",
            topic_group="today_issue",
            selected=scored,
            reader_value_score=84,
            article_focus_score=100,
            title_has_source_entity=True,
            raw_topic_count=7,
        )

        self.assertEqual(relaxed, ["click_potential_score_below_8", "raw_topic_repeated_in_html"])
        self.assertEqual(blocking, ["missing_faq_section"])
        self.assertIn("top_issue_publish_relaxed:click_potential_score_below_8", warnings)

    def test_does_not_relax_generic_refund_without_entity(self):
        scored = _make_scored(
            topic="환불 지연 때 소비자가 먼저 남겨야 할 증거",
            original_topic="환불 지연 소비자 증거 정리",
            content_type="consumer_warning",
            topic_group="refund_consumer",
            source_type="naver_webkr_search",
            total_score=73,
            click_potential=7,
        )
        blocking = ["title_has_no_specific_entity", "today_relevance_below_7:6"]
        warnings: list[str] = []

        relaxed = NewsQualityGate._relax_top_issue_publish_blockers(
            blocking_issues=blocking,
            warnings=warnings,
            publish_mode_active=True,
            fallback_candidate=False,
            source_type="naver_webkr_search",
            content_type="consumer_warning",
            topic_group="refund_consumer",
            selected=scored,
            reader_value_score=92,
            article_focus_score=100,
            title_has_source_entity=False,
            raw_topic_count=7,
        )

        self.assertEqual(relaxed, ["today_relevance_below_7:6"])
        self.assertEqual(blocking, ["title_has_no_specific_entity"])


if __name__ == "__main__":
    unittest.main()
