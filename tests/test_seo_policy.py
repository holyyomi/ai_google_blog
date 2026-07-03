from __future__ import annotations

from blogspot_automation.services.seo_policy import (
    append_hashtags_block,
    build_english_permalink_slug,
    build_internal_links_from_history,
    count_external_anchor_links,
    has_unverified_experience_or_income_claim,
    improve_image_alt_text,
    normalize_hashtags,
    normalize_labels,
    normalize_search_description,
    prepare_blogspot_html,
    strip_inline_style_attributes,
    strip_external_anchor_links,
    url_matches_permalink_slug,
)


def test_normalize_labels_limits_blogspot_label_pages() -> None:
    labels = ["AI", "AI", "자동화", "https://example.com", "블로그수익", "생산성", "콘텐츠", "초과"]

    assert normalize_labels(labels) == ["AI", "자동화", "블로그수익", "생산성", "콘텐츠"]


def test_normalize_hashtags_limits_content_hashtags() -> None:
    hashtags = ["#AI", "#자동화", "#블로그수익", "#AI활용", "#초과", "#AI"]

    # MAX_CONTENT_HASHTAGS(4)개까지만, 중복 제거
    assert normalize_hashtags(hashtags) == ["#AI", "#자동화", "#블로그수익", "#AI활용"]


def test_prepare_blogspot_html_strips_naver_cta_without_internal_links_by_default() -> None:
    html = (
        '<article><p>본문</p>'
        '<a href="https://blog.naver.com/holyyomi">네이버 블로그 보기</a>'
        "</article>"
    )

    cleaned = prepare_blogspot_html(html)

    assert "blog.naver.com/holyyomi" not in cleaned
    assert 'data-yomi-block="internal-links"' not in cleaned
    assert 'class="yomi-clean-post"' in cleaned
    assert ".yomi-clean-post" in cleaned
    assert "/2026/05/ai.html" not in cleaned


def test_prepare_blogspot_html_normalizes_legacy_visual_layout() -> None:
    html = (
        '<article class="golden-preview">'
        '<section id="AI_OVERVIEW_TARGET_ANSWER" class="ai-overview-box"><p>핵심 답변입니다.</p></section>'
        '<section class="hero-summary-box" style="color:red"><p>예전 요약입니다.</p></section>'
        '<section class="core-message-box"><p>예전 핵심입니다.</p></section>'
        '<section id="PEOPLE_ALSO_ASK_BLOCK" class="paa-block"><ul><li class="paa-item">질문</li></ul></section>'
        "</article>"
    )

    cleaned = prepare_blogspot_html(html)

    assert 'class="yomi-clean-post"' in cleaned
    assert 'class="yomi-lede"' in cleaned
    assert 'class="yomi-paa-compact"' in cleaned
    assert 'class="golden-preview"' not in cleaned
    assert 'class="ai-overview-box"' not in cleaned
    assert 'class="hero-summary-box"' not in cleaned
    assert 'class="core-message-box"' not in cleaned
    assert 'class="paa-block"' not in cleaned
    assert "style=" not in cleaned


def test_prepare_blogspot_html_strips_preview_css_links_and_moves_late_sections() -> None:
    html = (
        "<html><head><style>.golden-preview{padding:32px}.internal-links{display:block}</style></head>"
        "<body>"
        '<article class="golden-preview"><h1>제목</h1><p>본문</p>'
        '<section class="internal-links"><ul><li>후보 링크</li></ul></section>'
        "</article>"
        '<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box"><h2>확인</h2></section>'
        '<section id="SOURCE_TRUST_BLOCK" class="source-trust-box"><h2>출처</h2></section>'
        "</body></html>"
    )

    cleaned = prepare_blogspot_html(html)

    assert ".golden-preview" not in cleaned
    assert "후보 링크" not in cleaned
    assert cleaned.count("<style>") == 1
    assert cleaned.find("CONFIRMED_VS_CHECK_NEEDED_BLOCK") < cleaned.find("</article>")
    assert cleaned.find("SOURCE_TRUST_BLOCK") < cleaned.find("</article>")


def test_prepare_blogspot_html_keeps_only_one_yomi_lede_when_ai_overview_exists() -> None:
    html = (
        '<article class="golden-preview">'
        '<section id="AI_OVERVIEW_TARGET_ANSWER" class="ai-overview-box"><p>핵심 답변입니다.</p></section>'
        '<section class="yomi-lede"><p>실제 본문 도입입니다.</p></section>'
        "</article>"
    )

    cleaned = prepare_blogspot_html(html)

    assert cleaned.count('class="yomi-lede"') == 1
    assert 'id="AI_OVERVIEW_TARGET_ANSWER" class="yomi-note"' in cleaned


def test_strip_inline_style_attributes_removes_generated_body_styles() -> None:
    html = '<div style="color:red"><p style="font-size:14px">본문</p></div>'

    cleaned = strip_inline_style_attributes(html)

    assert "style=" not in cleaned
    assert "<p>본문</p>" in cleaned


def test_prepare_blogspot_html_styles_clean_cover_and_strips_hashtag_blocks() -> None:
    html = (
        '<article class="yomi-clean-post">'
        '<figure class="ai-cover-image" data-yomi-block="cover-image">'
        '<img src="https://cdn.example.com/a.jpg" alt="뉴스 이미지" width="1200" height="675" />'
        "</figure>"
        '<section class="yomi-hashtags" data-yomi-block="hashtags"><p>#AI활용</p></section>'
        "</article>"
    )

    cleaned = prepare_blogspot_html(html)

    assert ".ai-cover-image img" in cleaned
    assert 'data-yomi-block="hashtags"' not in cleaned
    assert '<section class="yomi-hashtags"' not in cleaned
    assert "#AI활용" not in cleaned
    assert "style=" not in cleaned


def test_append_hashtags_block_adds_controlled_footer_inside_article() -> None:
    html = '<article class="yomi-clean-post"><h1>제목</h1><p>본문</p></article>'

    result = append_hashtags_block(html, hashtags=["#생활비", "#비용비교", "#절약정보"])

    assert 'data-yomi-block="hashtags"' in result
    assert "#생활비 #비용비교 #절약정보" in result
    assert result.find('data-yomi-block="hashtags"') < result.find("</article>")


def test_prepare_blogspot_html_strips_legacy_tag_list_and_hashtag_source_note() -> None:
    html = (
        '<article class="yomi-clean-post">'
        '<p>본문</p>'
        '<div class="tag-list"><span class="tag">OTT</span></div>'
        '<p class="source-note">#AI활용 #이슈해석 #반응분석</p>'
        '<p class="source-note">이 글은 2026.06.04 기준으로 작성됐습니다.</p>'
        "</article>"
    )

    cleaned = prepare_blogspot_html(html)

    assert 'class="tag-list"' not in cleaned
    assert "#AI활용" not in cleaned
    assert "2026.06.04 기준" in cleaned


def test_strip_external_anchor_links_keeps_internal_links_only() -> None:
    html = (
        '<p><a href="https://news.example.com/a">source name</a></p>'
        '<p><a href="https://holyyomiai.blogspot.com/2026/05/post.html">internal post</a></p>'
        '<p><a href="/2026/05/relative.html">relative post</a></p>'
    )

    cleaned = strip_external_anchor_links(html)

    assert "https://news.example.com/a" not in cleaned
    assert "source name" in cleaned
    assert "https://holyyomiai.blogspot.com/2026/05/post.html" in cleaned
    assert 'href="/2026/05/relative.html"' in cleaned
    assert count_external_anchor_links(cleaned) == 0


def test_prepare_blogspot_html_removes_outbound_source_links() -> None:
    cleaned = prepare_blogspot_html(
        '<article><p><a href="https://external.example/source">official source</a></p></article>'
    )

    assert "https://external.example/source" not in cleaned
    assert "official source" in cleaned
    assert count_external_anchor_links(cleaned) == 0


def test_prepare_blogspot_html_preserves_verified_official_source_links() -> None:
    cleaned = prepare_blogspot_html(
        '<article><section id="SOURCE_TRUST_BLOCK">'
        '<a href="https://www.kca.go.kr">한국소비자원</a>'
        '<a href="https://www.ftc.go.kr">공정거래위원회</a>'
        "</section></article>"
    )

    assert "https://www.kca.go.kr" in cleaned
    assert "https://www.ftc.go.kr" in cleaned
    assert count_external_anchor_links(cleaned) == 0


def test_prepare_blogspot_html_can_strip_full_document_for_publish_body() -> None:
    cleaned = prepare_blogspot_html(
        '<!doctype html><html><head><title>제목</title><meta name="description" content="설명"></head>'
        '<body><article><h1>제목</h1><p>본문</p></article></body></html>',
        strip_document=True,
    )

    assert "<html" not in cleaned.lower()
    assert "<head" not in cleaned.lower()
    assert "<meta" not in cleaned.lower()
    assert "<title" not in cleaned.lower()
    assert "<article" in cleaned


def test_prepare_blogspot_html_can_opt_in_to_real_history_links() -> None:
    html = "<article><p>본문</p></article>"
    links = (("쿠팡 환불 지연 대응 체크리스트", "https://holyyomiai.blogspot.com/2026/05/coupang-refund-news.html"),)

    cleaned = prepare_blogspot_html(html, links=links, include_internal_links=True)

    assert "쿠팡 환불 지연 대응 체크리스트" in cleaned
    assert "coupang-refund-news.html" in cleaned
    assert cleaned.count('data-yomi-block="internal-links"') == 1
    assert "오늘의 이슈 최신 글 보기" not in cleaned


def test_unverified_income_claim_is_blocked() -> None:
    html = "<p>2026년 5월 20일, 제가 블로그에서 50,000원의 수익을 올렸습니다.</p>"

    assert has_unverified_experience_or_income_claim(html)


def test_policy_support_amount_is_not_treated_as_income_claim() -> None:
    html = "<p>이번 지원금은 1인당 최대 60만원까지 지급될 수 있습니다.</p>"

    assert not has_unverified_experience_or_income_claim(html)


def test_policy_direct_check_and_deposit_word_is_not_income_claim() -> None:
    html = "<p>공식 안내에서 직접 조회하세요. 지원금은 자동으로 입금되지 않을 수 있습니다.</p>"

    assert not has_unverified_experience_or_income_claim(html)


def test_improve_image_alt_text_replaces_generic_alt_only() -> None:
    html = '<p><img src="a.jpg" alt="이미지"></p><p><img src="b.jpg" alt="정확한 설명"></p>'

    cleaned = improve_image_alt_text(html, image_alt_text="뉴스 이슈 설명 이미지")

    assert 'alt="뉴스 이슈 설명 이미지"' in cleaned
    assert 'alt="정확한 설명"' in cleaned


def test_build_english_permalink_slug_from_korean_news_title() -> None:
    slug = build_english_permalink_slug(
        title="추경호 46.1% 김부겸 41.9% 접전의 배경은?",
        topic_group="politics",
    )

    assert re_match(r"^[a-z0-9-]+$", slug)
    assert "poll" in slug
    assert "news" in slug
    assert len(slug) <= 48


def test_build_english_permalink_slug_maps_tech_keywords() -> None:
    # AI/게임/OTT 한국어 제목이 generic filler 대신 실제 영어 키워드로 매핑되는지
    ai = build_english_permalink_slug(
        title="직장인 ChatGPT, 시간 줄이려면 먼저 볼 3가지",
        topic="직장인 ChatGPT 업무 자동화 생산성",
        labels=["AI자동화", "업무생산성"],
        topic_group="today_issue",
    )
    assert "chatgpt" in ai
    assert "automation" in ai or "productivity" in ai
    # generic filler가 키워드를 밀어내지 않음
    assert not ai.startswith("today-")

    game = build_english_permalink_slug(
        title="길드워3 공식 공개 PS5 출시 베타 정리",
        labels=["게임", "출시"],
        topic_group="today_issue",
    )
    assert "game" in game and "launch" in game


def test_build_english_permalink_slug_no_midword_truncation() -> None:
    slug = build_english_permalink_slug(
        title="배달 수수료 환불 신청 방법과 대상 조건 총정리 가이드",
        topic="배달 수수료 환불 소비자 피해",
        labels=["소비자", "환불", "배달"],
        topic_group="today_issue",
    )
    assert len(slug) <= 48
    # 마지막 토큰(6자리 digest) 외에는 토막난 단어가 없어야 한다
    tokens = slug.split("-")
    assert all(len(t) >= 2 for t in tokens)


def test_url_matches_permalink_slug_accepts_blogger_returned_url() -> None:
    slug = "poll-politics-update-news-a1b2c3"
    url = "https://holyyomiai.blogspot.com/2026/05/poll-politics-update-news-a1b2c3.html"

    assert url_matches_permalink_slug(url, slug)


def test_url_matches_permalink_slug_rejects_auto_blog_post_url() -> None:
    slug = "poll-politics-update-news-a1b2c3"
    url = "https://holyyomiai.blogspot.com/2026/05/blog-post_23.html"

    assert not url_matches_permalink_slug(url, slug)


def test_build_internal_links_from_history_prefers_same_topic_group() -> None:
    records = [
        {
            "run_at": "2026-05-20T12:00:00",
            "title": "카카오 서비스 오류 보상 기준 확인법",
            "url": "https://holyyomiai.blogspot.com/2026/05/kakao-service-warning-news.html",
            "topic_group": "platform_issue",
            "content_type": "platform_change",
            "published": True,
            "status": "published",
        },
        {
            "run_at": "2026-05-21T12:00:00",
            "title": "드라마 반응이 갈린 이유",
            "url": "https://holyyomiai.blogspot.com/2026/05/drama-reaction-news.html",
            "topic_group": "ott_platform",
            "content_type": "viral_issue_decode",
            "published": True,
            "status": "published",
        },
        {
            "run_at": "2026-05-22T12:00:00",
            "title": "검색 라벨 페이지",
            "url": "https://holyyomiai.blogspot.com/search/label/news",
            "topic_group": "platform_issue",
            "content_type": "platform_change",
            "published": True,
            "status": "published",
        },
    ]

    links = build_internal_links_from_history(
        records,
        current_title="카카오 서비스 변경 전 확인할 조건",
        current_topic_group="platform_issue",
        current_content_type="platform_change",
    )

    assert links[0][0] == "카카오 서비스 오류 보상 기준 확인법"
    assert all("/search/" not in url for _, url in links)


def test_build_internal_links_from_history_uses_real_history_without_fallbacks() -> None:
    records = [
        {
            "run_at": "2026-05-20T12:00:00",
            "title": "택배 휴무 일정 확인법",
            "url": "https://holyyomiai.blogspot.com/2026/05/delivery-schedule-news.html",
            "topic_group": "delivery_money",
            "content_type": "consumer_warning",
            "published": True,
            "status": "published",
        }
    ]

    links = build_internal_links_from_history(
        records,
        current_title="선거일 택배 배송 일정",
        current_topic_group="delivery_money",
        current_content_type="consumer_warning",
    )

    assert len(links) == 1
    assert links[0][0] == "택배 휴무 일정 확인법"
    assert all("holyyomiai.blogspot.com" in url for _, url in links)


def test_build_internal_links_from_history_skips_failed_or_broken_old_posts() -> None:
    records = [
        {
            "run_at": "2026-06-03T12:00:00",
            "title": "KT초이스 요금제 무료가 화제 된 반응이 갈린 이유, 먼저 볼 3가지",
            "selected_topic": "KT초이스 요금제 무료가 화제 된 이유, 사람들이 본 핵심 포인트",
            "url": "https://holyyomiai.blogspot.com/2026/06/kt-ott-platform-fee-drama-reaction.html",
            "topic_group": "ott_platform",
            "content_type": "viral_issue_decode",
            "published": True,
            "status": "published",
            "post_publish_audit_passed": False,
        },
        {
            "run_at": "2026-06-04T12:00:00",
            "title": "하천 물놀이 중 초등생 사망, 안전 수칙 점검이 시급한 이유",
            "url": "https://holyyomiai.blogspot.com/2026/05/blog-post_715.html",
            "topic_group": "today_issue",
            "content_type": "today_issue_explainer",
            "published": True,
            "status": "published",
        },
        {
            "run_at": "2026-06-05T12:00:00",
            "title": "환불 지연 때 소비자가 먼저 남겨야 할 증거",
            "url": "https://holyyomiai.blogspot.com/2026/06/refund-consumer-evidence-news.html",
            "topic_group": "refund_consumer",
            "content_type": "consumer_warning",
            "published": True,
            "status": "published",
            "post_publish_audit_passed": True,
        },
    ]

    links = build_internal_links_from_history(
        records,
        current_title="무료배송인데 결제금액이 커질 때 확인할 것",
        current_topic_group="delivery_money",
        current_content_type="money_checklist",
    )

    assert all("KT초이스" not in title for title, _ in links)
    assert all("blog-post" not in url for _, url in links)
    assert links[0][0] == "환불 지연 때 소비자가 먼저 남겨야 할 증거"


def test_build_internal_links_from_history_skips_dry_run_deleted_success_records() -> None:
    records = [
        {
            "run_at": "2026-06-11T00:05:17+00:00",
            "title": "이정후, 타율 1위 도전의 분수령",
            "url": "https://holyyomiai.blogspot.com/2026/06/lee-jung-hoo-batting-streak-sf-today.html",
            "topic_group": "today_issue",
            "content_type": "today_issue_explainer",
            "published": False,
            "dry_run": True,
            "status": "trending_published",
            "note": "post_deleted_by_user (404, dereferenced 2026-06-11)",
        },
        {
            "run_at": "2026-06-10T17:38:03+00:00",
            "title": "스페이스X 청약 광풍, 380조 몰린 돈의 행방은?",
            "url": "https://holyyomiai.blogspot.com/2026/06/spacex-ipo-fever-unseen-context-today.html",
            "topic_group": "today_issue",
            "content_type": "today_issue_explainer",
            "published": True,
            "dry_run": False,
            "status": "trending_published",
        },
    ]

    links = build_internal_links_from_history(
        records,
        current_title="오늘 스포츠 이슈 확인 기준",
        current_topic_group="today_issue",
        current_content_type="today_issue_explainer",
    )

    assert links == (
        (
            "스페이스X 청약 광풍, 380조 몰린 돈의 행방은?",
            "https://holyyomiai.blogspot.com/2026/06/spacex-ipo-fever-unseen-context-today.html",
        ),
    )


def test_normalize_search_description_fills_required_description() -> None:
    description = normalize_search_description(
        title="박근혜 전 대통령 대구 칠성시장 유세 지원",
        description="",
        html="<p>현장 반응과 정치권 해석을 함께 정리했습니다.</p>",
        topic="대구 유세 지원",
    )

    assert 50 <= len(description) <= 155
    assert "대구" in description


def re_match(pattern: str, value: str) -> bool:
    import re

    return re.match(pattern, value) is not None



def test_strip_hashtag_sections_removes_hashtag_only_paragraph() -> None:
    from blogspot_automation.services.seo_policy import strip_hashtag_sections

    html = "<p>본문 문장이다.</p><p>#카카오 #AI #업무자동화 #생산성 #카카오톡</p>"
    assert strip_hashtag_sections(html) == "<p>본문 문장이다.</p>"


def test_strip_hashtag_sections_trims_trailing_hashtag_run() -> None:
    from blogspot_automation.services.seo_policy import strip_hashtag_sections

    html = "<p>정리하면 이렇다. #카카오AI #업무자동화 #AI도구</p>"
    assert strip_hashtag_sections(html) == "<p>정리하면 이렇다.</p>"


def test_strip_hashtag_sections_keeps_inline_single_hashtag_and_csharp() -> None:
    from blogspot_automation.services.seo_policy import strip_hashtag_sections

    keep1 = "<p>C#은 마이크로소프트 언어다.</p>"
    keep2 = "<p>이번 업데이트는 #카카오 앱에서 확인할 수 있다.</p>"
    assert strip_hashtag_sections(keep1) == keep1
    assert strip_hashtag_sections(keep2) == keep2
