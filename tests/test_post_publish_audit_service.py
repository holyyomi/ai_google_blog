from __future__ import annotations

from blogspot_automation.services.answer_engine_policy import ensure_answer_engine_optimized_html
from blogspot_automation.services.post_publish_audit_service import audit_post_html


def test_audit_post_html_passes_complete_news_post() -> None:
    url = "https://holyeverymoments.blogspot.com/2026/05/delivery-fee-refund-checklist.html"
    html = ensure_answer_engine_optimized_html(
        """
        <html><head>
          <link href="https://holyeverymoments.blogspot.com/2026/05/delivery-fee-refund-checklist.html" rel="canonical"/>
          <meta name="description" content="Delivery fee refund checklist with official confirmation points.">
          <meta property="og:description" content="Delivery fee refund checklist with official confirmation points.">
        </head><body>
          <article>
            <h1>Delivery fee refund checklist</h1>
            <p>Refund delays should be checked by payment record, order number, and support response date.</p>
            <section class="faq faq-block">
              <div class="faq-card"><h3>What should be checked first?</h3><p>Payment record, order number, and support response date should be separated before making another request.</p></div>
              <div class="faq-card"><h3>Why does evidence matter?</h3><p>Evidence makes the timeline clear when a refund is delayed or the seller response keeps changing.</p></div>
              <div class="faq-card"><h3>What changes after checking records?</h3><p>The reader can compare the seller notice, platform answer, and payment provider status without repeating the same claim.</p></div>
            </section>
          </article>
        </body></html>
        """,
        title="Delivery fee refund checklist",
        topic="Delivery fee refund",
        content_type="consumer_warning",
        topic_group="refund_consumer",
    )

    result = audit_post_html(
        url=url,
        html=html,
        expected_title="Delivery fee refund checklist",
        expected_permalink_slug="delivery-fee-refund-checklist",
    )

    assert result.passed
    assert result.meta_description_present
    assert result.canonical_self_referencing
    assert result.answer_engine_ready
    assert result.title_matches_expected
    assert result.temporary_slug_title_absent
    assert result.permalink_slug_matches


def test_audit_post_html_flags_weak_post() -> None:
    result = audit_post_html(
        url="https://holyeverymoments.blogspot.com/2026/05/blog-post_23.html",
        html="<html><head></head><body><h1>Title</h1></body></html>",
    )

    assert not result.passed
    assert "weak_permalink_slug" in result.issues
    # head meta description is Blogger-config controlled → advisory, not a hard issue
    assert "missing_meta_description" in result.warnings
    assert "missing_meta_description" not in result.issues
    assert "canonical_not_self_referencing" in result.issues
    assert "answer_engine_blocks_missing_or_incomplete" in result.issues


def test_audit_post_html_flags_body_only_meta_description() -> None:
    result = audit_post_html(
        url="https://holyeverymoments.blogspot.com/2026/05/policy-benefit-government-support-apply.html",
        html="""
        <html><head>
          <link href="https://holyeverymoments.blogspot.com/2026/05/policy-benefit-government-support-apply.html" rel="canonical"/>
          <meta property="og:description" content="정책, 소비자 이슈, 플랫폼 변화를 중심으로 오늘 꼭 확인할 뉴스를 정리합니다.">
        </head><body>
          <article>
            <h1>청년 운전면허 지원금 신청방법과 대상 조건</h1>
            <meta name="description" content="청년 운전면허 지원금 대상 조건과 필요 서류를 정리했습니다.">
          </article>
        </body></html>
        """,
        expected_title="청년 운전면허 지원금 신청방법과 대상 조건",
        expected_permalink_slug="policy-benefit-government-support-apply",
    )

    assert not result.passed
    # meta description placement is advisory (Blogger renders head meta from the
    # dashboard search-description toggle)
    assert "missing_meta_description" in result.warnings
    assert "body_only_meta_description" in result.warnings
    assert "missing_meta_description" not in result.issues
    # og:description is always the blog-level tagline on Blogger (API v3 has no
    # per-post og control) → structural limitation, advisory only
    assert "og_description_not_post_specific" in result.warnings
    assert "og_description_not_post_specific" not in result.issues


def test_og_description_mismatch_is_warning_not_issue() -> None:
    # Blogger API v3에는 per-post og:description 수단이 없어(테마가 customMetaData를
    # 읽지 않음) 라이브 og는 항상 블로그 태그라인이다 — 구조적 한계이므로
    # 감사 실패(issues)가 아니라 정보성(warnings)이어야 한다.
    url = "https://holyyomiai.blogspot.com/2026/07/chatgpt-plus-vs-claude-pro-pricing.html"
    html = f"""
    <html><head>
      <link rel="canonical" href="{url}">
      <meta name="description" content="ChatGPT Plus vs Claude Pro pricing compared with official sources.">
      <meta property="og:description" content="Practical AI tool comparisons, pricing checks, and how-to guides.">
    </head><body>
      <h1>ChatGPT Plus vs Claude Pro: Pricing Breakdown</h1>
    </body></html>
    """

    result = audit_post_html(
        url=url,
        html=html,
        expected_title="ChatGPT Plus vs Claude Pro: Pricing Breakdown",
        expected_permalink_slug="chatgpt-plus-vs-claude-pro-pricing",
    )

    assert "og_description_not_post_specific" in result.warnings
    assert "og_description_not_post_specific" not in result.issues


def test_description_title_match_is_case_insensitive_english() -> None:
    from blogspot_automation.services.post_publish_audit_service import (
        _description_matches_title,
    )

    # 대소문자만 다른 영어 제목/설명은 일치로 판정해야 한다 (영어 전환 2026-07-17).
    assert _description_matches_title(
        "chatgpt plus and claude pro pricing compared for US users.",
        "ChatGPT Plus vs Claude Pro: Best AI Pricing 2026",
    )
    # filler 단어(the/vs/best/2026 등)와 3글자 미만 토큰은 일치 근거가 될 수 없다.
    assert not _description_matches_title(
        "The best guide of 2026 for what is on in AI.",
        "Midjourney Alternatives Compared: Best 2026 Guide",
    )
    # 실제 엔티티 단어가 2개 이상 겹치면 일치.
    assert _description_matches_title(
        "Midjourney alternatives compared with pricing tables.",
        "Midjourney Alternatives Compared: Best 2026 Guide",
    )


def test_candidate_meta_prevents_slug_only_news_focus_false_positive(monkeypatch) -> None:
    # 2026-07-18 실측 사고: 발행 후 감사가 URL 슬러그만으로(raw={}) 뉴스 포커스를
    # 재검사해, 슬러그에 브랜드 토큰이 없는 정상 AI 글을 "AI 주제 아님"으로
    # 오판하고 라이브 글을 자동 삭제했다. candidate_meta가 주어지면 원본
    # topic/topic_group/content_type으로 판정해 오탐이 나면 안 된다.
    monkeypatch.setenv("AI_BLOG_MODE", "true")
    monkeypatch.delenv("ALLOW_AI_NEWS_TOPICS", raising=False)
    url = "https://holyyomiai.blogspot.com/2026/07/workflow-automation-time-savings-report.html"
    html = f"""
    <html><head>
      <link rel="canonical" href="{url}">
      <meta name="description" content="Weekly workflow automation time savings report.">
      <meta property="og:description" content="Weekly workflow automation time savings report.">
    </head><body>
      <h1>Workflow Automation Time Savings Report</h1>
    </body></html>
    """

    # 기본(candidate_meta 없음) = 기존 슬러그 전용 동작 그대로 → 오탐 발생.
    slug_only = audit_post_html(url=url, html=html)
    assert "ai_topic_leaked_to_news_blog" in slug_only.issues

    # candidate_meta의 topic/topic_group/content_type이 판정에 쓰이면 오탐 없음.
    with_meta = audit_post_html(
        url=url,
        html=html,
        candidate_meta={
            "topic": "Grok workflow automation time savings",
            "topic_group": "ai_work",
            "content_type": "ai_work_tip",
        },
    )
    assert "ai_topic_leaked_to_news_blog" not in with_meta.issues


def test_audit_post_html_flags_title_and_slug_mismatch() -> None:
    url = "https://holyeverymoments.blogspot.com/2026/05/blog-post_23.html"
    html = """
    <html><head>
      <title>ai today issue controversy update e6de37 8420a3</title>
      <link rel="canonical" href="https://holyeverymoments.blogspot.com/2026/05/blog-post_23.html">
      <meta name="description" content="Search description long enough for this Blogger publish test case.">
      <meta property="og:description" content="Search description long enough for this Blogger publish test case.">
    </head><body>
      <h1>ai today issue controversy update e6de37 8420a3</h1>
    </body></html>
    """

    result = audit_post_html(
        url=url,
        html=html,
        expected_title="스타벅스 탱크데이 논란, AI 기능 설정 확인",
        expected_permalink_slug="ai-today-issue-controversy-update-e6de37-8420a3",
    )

    assert not result.passed
    assert "weak_permalink_slug" in result.issues
    assert "permalink_slug_mismatch" in result.issues
    assert "published_title_mismatch" in result.issues
    assert "temporary_permalink_title_visible" in result.issues
    assert not result.title_matches_expected
    assert not result.temporary_slug_title_absent
    assert not result.permalink_slug_matches


def test_audit_post_html_flags_published_broken_title_integrity() -> None:
    html = """
    <html><head>
      <title>재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지</title>
      <link rel="canonical" href="https://holyeverymoments.blogspot.com/2026/06/kt-ott-platform-drama-reaction-update.html">
      <meta name="description" content="KT 요금제 혜택과 이용자가 확인할 조건을 정리합니다.">
      <meta property="og:description" content="KT 요금제 혜택과 이용자가 확인할 조건을 정리합니다.">
    </head><body>
      <h1>재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지</h1>
    </body></html>
    """

    result = audit_post_html(
        url="https://holyeverymoments.blogspot.com/2026/06/kt-ott-platform-drama-reaction-update.html",
        html=html,
        expected_title="재계는 지금] KT가 화제 된 이 반응이 갈린 이유, 먼저 볼 3가지",
        content_type="viral_issue_decode",
        topic_group="ott_platform",
    )

    assert not result.passed
    assert "published_title_integrity:source_series_name_leaked:재계는 지금" in result.issues
    assert "published_title_integrity:malformed_reaction_phrase" in result.issues


def test_audit_post_html_prefers_blogger_post_title_over_site_header_h1() -> None:
    html = """
    <html><head>
      <title>젠슨 황 방한 보도, AI 반도체 이슈에서 먼저 볼 3가지</title>
      <link rel="canonical" href="https://holyeverymoments.blogspot.com/2026/06/ai-today-issue-update-news-e15d18.html">
      <meta name="description" content="젠슨 황 방한 보도를 AI 반도체 관점에서 정리했습니다.">
      <meta property="og:description" content="젠슨 황 방한 보도를 AI 반도체 관점에서 정리했습니다.">
    </head><body>
      <h1>오늘의 이슈 해부 | 생활 뉴스 핵심 정리</h1>
      <h3 class="post-title entry-title">젠슨 황 방한 보도, AI 반도체 이슈에서 먼저 볼 3가지</h3>
    </body></html>
    """

    result = audit_post_html(
        url="https://holyeverymoments.blogspot.com/2026/06/ai-today-issue-update-news-e15d18.html",
        html=html,
        expected_title="젠슨 황 방한 보도, AI 반도체 이슈에서 먼저 볼 3가지",
        expected_permalink_slug="ai-today-issue-update-news-e15d18",
    )

    assert result.actual_title == "젠슨 황 방한 보도, AI 반도체 이슈에서 먼저 볼 3가지"
    assert result.title_matches_expected


def test_extract_post_article_scope_survives_nested_article_tags() -> None:
    # 회귀: FAQ 카드가 <article class="faq-item">를 중첩하면, 비탐욕
    # `.*?</article>` 매칭이 첫 중첩 닫힘에서 스코프를 잘라 리드·적응형
    # 모듈이 전부 감사 밖으로 밀렸다(라이브 전건 만성
    # yomi_clean_layout_lede_count:0 원인, 2026-07-11 실측).
    from blogspot_automation.services.post_publish_audit_service import (
        _extract_post_article_html,
    )

    html = """
    <html><body>
    <article class="yomi-clean-post">
      <h1>제목</h1>
      <div class="yomi-faq">
        <article class="faq-item"><p class="faq-a">첫 답변</p></article>
        <article class="faq-item"><p class="faq-a">둘째 답변</p></article>
      </div>
      <div class="yomi-note"><p>포인트</p></div>
      <div class="confirmed-needed-box"><p>확인</p></div>
      <div class="yomi-lede"><p>리드 문단</p></div>
    </article>
    <footer>테마 푸터</footer>
    </body></html>
    """

    scope = _extract_post_article_html(html)

    assert "yomi-lede" in scope
    assert "confirmed-needed-box" in scope
    assert "테마 푸터" not in scope

    from blogspot_automation.services.final_html_audit_service import (
        _clean_layout_metrics,
    )

    metrics = _clean_layout_metrics(scope)
    assert metrics["present"] is True
    assert metrics["lede_count"] == 1
    assert metrics["adaptive_module_count"] >= 2
