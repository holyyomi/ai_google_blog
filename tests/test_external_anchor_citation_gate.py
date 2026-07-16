"""external_outbound_anchor_present 게이트 — extra_allowed_urls 예외 회귀 테스트.

2026-07-16 실측 리허설(run 29467013844)에서 발견된 갭: fix/official-source-link-citations가
SOURCE_TRUST_BLOCK에 실제 Naver/Exa 인용 URL을 <a href>로 넣도록 했지만,
news_quality_gate.evaluate()의 external_outbound_anchor_present 검사는 그 URL을
모르는 채로 정부기관 호스트 allowlist만 봐서 publish_mode에서 후보를 전부 차단했다.
evaluate()에 extra_allowed_urls를 추가해 seo_policy.strip_external_anchor_links와
같은 계약(정확히 일치하는, 실제로 fetch된 URL만 예외)을 공유하도록 맞춘다.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))


def _make_candidate(title: str = "삼성 이슈, 소비자와 투자자가 궁금해할 3가지") -> object:
    raw: dict = {
        "source_type": "google_news_rss",
        "topic_group": "platform_issue",
        "content_angle": {"content_type": "viral_issue_decode"},
        "hook_angle": {"safe_title_keyword": "삼성 파업"},
        "click_potential_score": 9,
        "total_score": 85,
        "raw_total_score": 85,
        "evergreen_axis": "",
        "is_test_candidate": False,
        "publish_allowed": True,
        "discovery_engine": True,
        "today_buzz_score": 10,
        "viral_safety_score": 80,
    }
    candidate = types.SimpleNamespace(
        topic="삼성전자 노조 총파업",
        category="platform_issue",
        summary="",
        source_hint=None,
        published_at=None,
        url=None,
        raw=raw,
    )
    return types.SimpleNamespace(candidate=candidate, total_score=85, reason="test")


def _min_valid_html(source_trust_extra: str = "") -> str:
    return f"""<html><head>
<meta name="description" content="삼성전자 노조 파업 소비자 투자자 궁금증 3가지 정리">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[]}}</script>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BlogPosting","headline":"삼성 이슈"}}</script>
</head><body>
<h1>삼성 이슈, 소비자와 투자자가 궁금해할 3가지</h1>
<section class="hero-summary-box">핵심요약</section>
<section class="target-reader-box">독자</section>
<section class="core-message-box">핵심메시지</section>
<section class="key-fact-cards">팩트카드</section>
<div class="checklist">체크리스트 항목</div>
<div class="warning">주의사항</div>
<section class="faq-card"><h3>Q1 파업이 소비자에게 미치는 영향은?</h3><p>답변 내용입니다 답변 내용입니다 답변 내용입니다.</p></section>
<section class="faq-card"><h3>Q2 투자자는 어떻게 봐야 하나?</h3><p>답변 내용입니다 답변 내용입니다 답변 내용입니다.</p></section>
<section class="faq-card"><h3>Q3 파업 종료 시점은?</h3><p>답변 내용입니다 답변 내용입니다 답변 내용입니다.</p></section>
<section class="yomi-judgment-box">요미 판단</section>
<section class="misconception-box">오해</section>
<section class="quick-decision-table">결정표</section>
<section id="SOURCE_TRUST_BLOCK">{source_trust_extra}</section>
<p>이슈 내용입니다. 반응이 갈리고 있습니다. 오늘 발표 이후 소비자 이슈가 됐습니다.</p>
{'<p>' + 'A' * 200 + '</p>'}
</body></html>"""


def _evaluate(html: str, *, extra_allowed_urls=(), dry_run: bool = False, news_publish_mode: str = "publish") -> dict:
    from blogspot_automation.services.news_quality_gate import NewsQualityGate

    scored = _make_candidate()
    gate = NewsQualityGate()
    return gate.evaluate(
        selected=scored,
        selected_title=scored.candidate.topic,
        html=html,
        labels=["삼성", "파업", "노조", "기업이슈", "소비자", "오늘이슈"],
        hashtags=["#삼성", "#파업", "#기업이슈", "#소비자", "#오늘이슈", "#뉴스"],
        image_prompt="삼성 파업 관련 사무실",
        image_alt_text="삼성전자 노조 파업",
        dry_run=dry_run,
        news_publish_mode=news_publish_mode,
        extra_allowed_urls=extra_allowed_urls,
    )


class TestExternalOutboundAnchorCitationExemption(unittest.TestCase):
    def test_unlisted_external_anchor_still_blocks_in_publish_mode(self):
        html = _min_valid_html(
            '<a href="https://news.example.com/real-citation">관련 보도</a>'
        )
        result = _evaluate(html)
        self.assertIn("external_outbound_anchor_present", result["blocking_issues"])

    def test_extra_allowed_url_exempts_real_citation_from_block(self):
        html = _min_valid_html(
            '<a href="https://news.example.com/real-citation">관련 보도</a>'
        )
        result = _evaluate(
            html,
            extra_allowed_urls=("https://news.example.com/real-citation",),
        )
        self.assertNotIn("external_outbound_anchor_present", result["blocking_issues"])
        self.assertNotIn("external_outbound_anchor_present", result["warnings"])

    def test_extra_allowed_url_is_exact_match_not_host_wide(self):
        # SOURCE_TRUST_BLOCK 안에 실제 인용 URL과 무관한 다른 외부 링크가 섞여 있으면
        # 여전히 차단돼야 한다 — 호스트 전체를 풀어주는 게 아니라 fetch된 그 URL만 예외.
        html = _min_valid_html(
            '<a href="https://news.example.com/real-citation">관련 보도</a>'
            '<a href="https://news.example.com/unrelated-article">임의 기사</a>'
        )
        result = _evaluate(
            html,
            extra_allowed_urls=("https://news.example.com/real-citation",),
        )
        self.assertIn("external_outbound_anchor_present", result["blocking_issues"])

    def test_extra_allowed_url_downgrades_to_warning_outside_publish_mode(self):
        html = _min_valid_html(
            '<a href="https://random.example/not-a-citation">임의 링크</a>'
        )
        result = _evaluate(html, dry_run=True, news_publish_mode="dry_run")
        self.assertNotIn("external_outbound_anchor_present", result["blocking_issues"])
        self.assertIn("external_outbound_anchor_present", result["warnings"])


if __name__ == "__main__":
    unittest.main()
