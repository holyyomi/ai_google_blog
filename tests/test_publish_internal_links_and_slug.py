from __future__ import annotations

import re

from blogspot_automation.config.settings import Settings
from blogspot_automation.services.answer_engine_policy import (
    ensure_answer_engine_optimized_html,
)
from blogspot_automation.services.news_publish_service import NewsPublishService
from blogspot_automation.services.seo_policy import build_english_permalink_slug

# 단방향 계약(2026-07-08 로드맵 4): publish는 검증만 하고 재렌더하지 않는다 —
# GEO/레이아웃 확정은 호출자(파이프라인) 책임이므로 테스트도 상류에서 확정한다.
_RAW_ARTICLE = "<article><h1>제목</h1><p>오늘 이슈의 배경과 영향 범위를 정리했습니다. 정의가 바뀌면 특보 기준과 대비 요령이 함께 달라질 수 있어 기준 변화를 먼저 확인하는 것이 좋다.</p></article>"


def _finalized_article() -> str:
    return ensure_answer_engine_optimized_html(
        _RAW_ARTICLE,
        title="장마 정의 개편, 기상학계가 다시 쓰는 기준",
        topic="장마 정의 개편",
        topic_group="today_issue",
    )


class CapturingBloggerClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish_post(
        self,
        *,
        title: str,
        article_html: str,
        labels: list[str],
        meta_description: str = "",
        permalink_slug: str = "",
        is_draft: bool = False,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "title": title,
                "article_html": article_html,
                "labels": labels,
                "meta_description": meta_description,
                "permalink_slug": permalink_slug,
                "is_draft": is_draft,
            }
        )
        return {
            "id": "post-1",
            "url": f"https://holyyomiai.blogspot.com/2026/06/{permalink_slug}.html",
            "status": "LIVE",
        }


def test_slug_hint_tokens_lead_the_permalink() -> None:
    slug = build_english_permalink_slug(
        title="비 안 와도 장마철? 기상학계가 장마 정의를 다시 쓰는 이유",
        topic="장마 정의 개편",
        labels=["날씨", "AI활용"],
        topic_group="today_issue",
        slug_hint="jangma-definition-change-kma",
    )
    assert slug.startswith("jangma-definition-change-kma")
    assert re.match(r"^[a-z0-9-]+$", slug)


def test_invalid_slug_hint_falls_back_to_default_behavior() -> None:
    base = build_english_permalink_slug(
        title="오늘 이슈 정리", topic="오늘 이슈", labels=["뉴스"], topic_group="today_issue",
    )
    hinted = build_english_permalink_slug(
        title="오늘 이슈 정리", topic="오늘 이슈", labels=["뉴스"], topic_group="today_issue",
        slug_hint="한글만있는힌트!!",
    )
    assert hinted == base


def test_publish_appends_internal_links_inside_article(tmp_path) -> None:
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )

    service.publish(
        title="장마 정의 개편, 기상학계가 다시 쓰는 기준",
        selected_topic="장마 정의 개편",
        article_html=_finalized_article(),
        labels=["날씨", "AI활용"],
        topic_group="today_issue",
        internal_links=(
            ("지난 폭염 특보 기준 정리", "https://holyyomiai.blogspot.com/2026/05/heatwave.html"),
            ("기상청 예보 용어 해설", "https://holyyomiai.blogspot.com/2026/05/forecast-terms.html"),
        ),
        permalink_slug_hint="jangma-definition-change",
    )

    call = client.calls[0]
    html = str(call["article_html"])
    assert "같이 보면 좋은 내부 글" in html
    assert "https://holyyomiai.blogspot.com/2026/05/heatwave.html" in html
    # 내부 링크 섹션이 article 안에 있어야 한다 (밖이면 테마 렌더에서 깨짐)
    assert html.rfind("yomi-internal-links") < html.rfind("</article>")
    assert 'content:"→"' not in html
    assert "&#8594;" not in html
    assert "transform:rotate(45deg)" in html
    assert str(call["permalink_slug"]).startswith("jangma-definition-change")


def test_publish_without_internal_links_keeps_existing_behavior(tmp_path) -> None:
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )

    service.publish(
        title="장마 정의 개편, 기상학계가 다시 쓰는 기준",
        selected_topic="장마 정의 개편",
        article_html=_finalized_article(),
        labels=["날씨", "AI활용"],
        topic_group="today_issue",
    )

    html = str(client.calls[0]["article_html"])
    # 링크 미전달 시 내부 링크 '섹션'이 없어야 한다 (CSS 클래스 정의는 무관)
    assert 'data-yomi-block="internal-links"' not in html
    assert "같이 보면 좋은 내부 글" not in html


def test_final_audit_allows_max_content_hashtags() -> None:
    # MAX_CONTENT_HASHTAGS(4)개 해시태그가 최종 감사를 통과해야 한다.
    # (상향 시 final_html_audit_service의 하드코딩 3이 남아 전 글이 차단됐던 회귀 방지)
    from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
    from blogspot_automation.services.seo_policy import MAX_CONTENT_HASHTAGS

    tags = " ".join(f"#태그{i}" for i in range(MAX_CONTENT_HASHTAGS))
    html = (
        '<article class="yomi-clean-post"><p>본문 문단입니다. 충분한 길이의 설명 텍스트.</p>'
        f'<section class="yomi-hashtags" data-yomi-block="hashtags"><p>{tags}</p></section>'
        "</article>"
    )
    audit = audit_final_html_quality(html, topic="테스트 주제")
    assert not any("too_many_content_hashtags" in str(i) for i in audit.get("issues", []))

    over = " ".join(f"#태그{i}" for i in range(MAX_CONTENT_HASHTAGS + 1))
    html_over = html.replace(tags, over)
    audit_over = audit_final_html_quality(html_over, topic="테스트 주제")
    assert any("too_many_content_hashtags" in str(i) for i in audit_over.get("issues", []))

