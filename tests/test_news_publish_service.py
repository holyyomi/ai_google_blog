from __future__ import annotations

import re

from blogspot_automation.config.settings import Settings
from blogspot_automation.services.answer_engine_policy import (
    ensure_answer_engine_optimized_html,
)
from blogspot_automation.services.news_publish_service import NewsPublishService


def _finalized(html: str, *, title: str, topic: str, topic_group: str = "") -> str:
    """파이프라인이 발행 전에 하는 GEO 확정을 테스트에서 재현.

    단방향 계약(로드맵 4): publish는 본문을 재렌더하지 않고 검증만 한다 —
    확정(ensure_answer_engine)은 호출자(파이프라인)의 책임이므로 테스트도
    같은 책임을 진다.
    """
    return ensure_answer_engine_optimized_html(
        html, title=title, topic=topic, topic_group=topic_group
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
            "url": f"https://holyyomiai.blogspot.com/2026/05/{permalink_slug}.html",
            "status": "LIVE",
            "permalink_slug": permalink_slug,
            "search_description": meta_description,
        }


def test_news_publish_service_forces_permalink_and_search_description(tmp_path) -> None:
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )

    service.publish(
        title="추경호 46.1% 김부겸 41.9% 접전의 배경은?",
        selected_topic="대구 여론조사 접전",
        article_html=_finalized(
            "<article><h1>제목</h1><p>현장 반응과 정치권 해석을 함께 정리했습니다.</p></article>",
            title="추경호 46.1% 김부겸 41.9% 접전의 배경은?",
            topic="대구 여론조사 접전",
            topic_group="politics",
        ),
        labels=["정치", "여론조사", "AI활용"],
        topic_group="politics",
    )

    call = client.calls[0]
    slug = str(call["permalink_slug"])
    description = str(call["meta_description"])

    assert re.match(r"^[a-z0-9-]+$", slug)
    assert "poll" in slug
    assert "news" in slug
    assert "blog-post" not in slug
    assert 50 <= len(description) <= 155
    assert '<meta name="description"' not in str(call["article_html"])
    assert str(call["meta_description"]) == description
    assert 'id="AI_OVERVIEW_TARGET_ANSWER"' in str(call["article_html"])
    assert 'id="INTENT_ANSWER_BLOCK"' in str(call["article_html"])
    assert 'id="SOURCE_TRUST_BLOCK"' in str(call["article_html"])
    assert '"@type": "BlogPosting"' in str(call["article_html"])


def test_news_publish_service_removes_external_anchor_links(tmp_path) -> None:
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )

    service.publish(
        title="CJ delivery schedule check",
        selected_topic="CJ delivery schedule",
        article_html=_finalized(
            '<article><h1>CJ delivery schedule check</h1>'
            '<p><a href="https://external.example/news">external source</a></p>'
            '<p><a href="https://holyyomiai.blogspot.com/2026/05/related.html">related post</a></p>'
            "</article>",
            title="CJ delivery schedule check",
            topic="CJ delivery schedule",
            topic_group="general_life",
        ),
        labels=["news", "delivery"],
        topic_group="general_life",
    )

    article_html = str(client.calls[0]["article_html"])
    assert "https://external.example/news" not in article_html
    assert "external source" in article_html
    assert "https://holyyomiai.blogspot.com/2026/05/related.html" in article_html


def test_news_publish_service_preserves_official_source_links_for_consumer_posts(tmp_path) -> None:
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )

    service.publish(
        title="환불 지연 때 남길 증거 체크리스트",
        selected_topic="환불 지연 소비자 피해",
        article_html=_finalized(
            '<article><h1>환불 지연 때 남길 증거 체크리스트</h1>'
            '<p>결제 내역과 접수 번호를 먼저 남겨야 합니다.</p>'
            '<section id="SOURCE_TRUST_BLOCK" class="yomi-source">'
            '<a href="https://www.kca.go.kr">한국소비자원</a>'
            '<a href="https://www.ftc.go.kr">공정거래위원회</a>'
            "</section></article>",
            title="환불 지연 때 남길 증거 체크리스트",
            topic="환불 지연 소비자 피해",
            topic_group="refund_consumer",
        ),
        labels=["환불", "소비자피해", "AI활용"],
        hashtags=["#환불", "#소비자피해", "#AI활용"],
        content_type="consumer_warning",
        topic_group="refund_consumer",
    )

    article_html = str(client.calls[0]["article_html"])
    assert "https://www.kca.go.kr" in article_html
    assert "https://www.ftc.go.kr" in article_html
    assert "#환불" in article_html


def test_news_publish_service_preserves_research_citation_links_when_allowlisted(tmp_path) -> None:
    """2026-07-18 실측 사고 회귀 테스트.

    Naver/Exa 등 실제 리서치로 얻은 인용 URL(정부/공식 도메인이 아닌 일반
    도메인, 예: dev.to)은 host allowlist(_ALLOWED_LINK_HOSTS)에 안 걸린다 —
    호출부가 extra_allowed_urls로 명시적으로 넘겨야만 살아남는다. 파이프라인이
    SOURCE_TRUST_BLOCK에 이 링크를 <a href>로 넣어도, publish()가
    extra_allowed_urls 없이 내부 strip_external_anchor_links를 두 번(prepare_
    blogspot_html 안 + 마지막 강제 strip) 돌리면 href만 벗겨지고 앵커 텍스트만
    남는다 — 라이브 발행 글의 "Sources & where to verify" 목록이 링크 없는
    잘린 텍스트로 나간 원인이었다.
    """
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )
    citation_url = "https://dev.to/alexmercedcoder/a-frontier-model-goes-dark-ai-week"

    service.publish(
        title="Copilot Share Falls to 51% as Cursor Hits $2B ARR",
        selected_topic="Copilot vs Cursor market share",
        article_html=_finalized(
            "<article><h1>Copilot Share Falls to 51% as Cursor Hits $2B ARR</h1>"
            "<p>Verified market-share figures are covered below.</p>"
            '<section id="SOURCE_TRUST_BLOCK" class="yomi-source">'
            f'<a href="{citation_url}">A Frontier Model Goes Dark</a>'
            "</section></article>",
            title="Copilot Share Falls to 51% as Cursor Hits $2B ARR",
            topic="Copilot vs Cursor market share",
            topic_group="ai_work",
        ),
        labels=["News", "AITools"],
        topic_group="ai_work",
        content_type="ai_work_tip",
        extra_allowed_urls=(citation_url,),
    )

    article_html = str(client.calls[0]["article_html"])
    assert citation_url in article_html
    assert f'href="{citation_url}"' in article_html


def test_news_publish_service_strips_unallowlisted_citation_link(tmp_path) -> None:
    """extra_allowed_urls를 넘기지 않으면 host-allowlist 밖 URL은 여전히 벗겨진다.

    위 회귀 테스트와 짝을 이뤄 strip 메커니즘 자체가 살아있는지 확인한다 —
    이 테스트가 실패(링크가 안 벗겨짐)하면 화이트리스트 우회 경로가 생겼다는
    뜻이므로 별개의 보안 회귀다.
    """
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )
    citation_url = "https://dev.to/alexmercedcoder/a-frontier-model-goes-dark-ai-week"

    service.publish(
        title="Copilot Share Falls to 51% as Cursor Hits $2B ARR",
        selected_topic="Copilot vs Cursor market share",
        article_html=_finalized(
            "<article><h1>Copilot Share Falls to 51% as Cursor Hits $2B ARR</h1>"
            "<p>Verified market-share figures are covered below.</p>"
            '<section id="SOURCE_TRUST_BLOCK" class="yomi-source">'
            f'<a href="{citation_url}">A Frontier Model Goes Dark</a>'
            "</section></article>",
            title="Copilot Share Falls to 51% as Cursor Hits $2B ARR",
            topic="Copilot vs Cursor market share",
            topic_group="ai_work",
        ),
        labels=["News", "AITools"],
        topic_group="ai_work",
        content_type="ai_work_tip",
    )

    article_html = str(client.calls[0]["article_html"])
    assert citation_url not in article_html
    assert "A Frontier Model Goes Dark" in article_html


def test_news_publish_service_inserts_cover_image_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_COVER_IMAGE_URL", "https://cdn.example.com/ai-cover.jpg")
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )

    service.publish(
        title="UAE 바라카 원전 드론 공격 안전 확인",
        selected_topic="UAE 바라카 원전 드론 공격",
        article_html=_finalized(
            "<article><h1>UAE 바라카 원전 드론 공격 안전 확인</h1><p>공식 확인과 영향 범위를 정리합니다.</p></article>",
            title="UAE 바라카 원전 드론 공격 안전 확인",
            topic="UAE 바라카 원전 드론 공격",
            topic_group="platform_issue",
        ),
        labels=["국제뉴스", "원전", "AI활용"],
        topic_group="platform_issue",
        image_alt_text="UAE 원전 안전 점검 이미지",
    )

    article_html = str(client.calls[0]["article_html"])
    assert '<figure class="ai-cover-image"' in article_html
    assert '<img src="https://cdn.example.com/ai-cover.jpg"' in article_html
    assert 'alt="UAE 원전 안전 점검 이미지"' in article_html

