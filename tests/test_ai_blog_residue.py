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


if __name__ == "__main__":
    unittest.main()
