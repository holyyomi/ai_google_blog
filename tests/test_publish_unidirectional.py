"""발행 서비스 단방향 계약 테스트 (2026-07-08 구조 감사 로드맵 4).

배경: NewsPublishService.publish 내부의 ensure_answer_engine 2차 호출이,
파이프라인 단계에서 확정한 본문(faq-item 정규화 등)을 발행 직전에 다시
재렌더해 무효화했다. dry_run에는 없는 이 변형이 실발행에서만 최종 계약
크래시를 냈다(PR #29 사건). 새 계약:

- 확정(GEO 부착·재렌더)은 파이프라인(발행 전 단계)의 단독 책임.
- publish는 본문을 재렌더하지 않는다 — 허용된 추가(커버 이미지·내부 링크·
  해시태그 꼬리 블록)와 안전 제거(외부 앵커·내부 h1)만 하고, 확정 안 된
  본문은 조용히 고치는 대신 _validate_publish_contract가 시끄럽게 거부한다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.config.settings import Settings
from blogspot_automation.services.answer_engine_policy import (
    ensure_answer_engine_optimized_html,
)
from blogspot_automation.services.news_publish_service import NewsPublishService

from test_news_publish_service import CapturingBloggerClient  # 동일 fake 재사용


def _service(tmp_path) -> tuple[NewsPublishService, CapturingBloggerClient]:
    client = CapturingBloggerClient()
    service = NewsPublishService(
        settings=Settings(blogger_blog_id="blog-1"),
        blogger_client=client,  # type: ignore[arg-type]
        history_path=tmp_path / "history.json",
    )
    return service, client


def test_publish_does_not_rerender_finalized_faq_structure(tmp_path) -> None:
    """PR #29 회귀: 파이프라인이 확정한 faq-item이 발행 단계에서 faq-card로
    되돌아가면 안 된다 (과거 2차 ensure 호출이 정확히 이 회귀를 만들었다)."""
    service, client = _service(tmp_path)
    finalized = ensure_answer_engine_optimized_html(
        (
            "<article><h1>구글 AI 검색 설정 정리</h1>"
            "<p>구글 AI 검색 설정은 검색 결과에 AI 요약이 보이는 방식과 개인정보 사용 범위를 좌우한다. "
            "업무 계정이라면 관리자가 잠근 항목이 있을 수 있어, 개인 계정과 다른 화면이 보여도 오류가 아니다.</p>"
            "<p>가장 먼저 볼 것은 검색 기록 사용 여부다. 기록 사용을 켜면 답변이 맥락을 반영하지만, "
            "업무 자료 검색이 많은 계정이라면 회사 보안 정책과 충돌하지 않는지 확인한 뒤 켜는 것이 안전하다. "
            "설정 위치는 계정과 앱 버전에 따라 다를 수 있어 공식 도움말에서 최신 경로를 확인하는 것이 좋다.</p>"
            # faq-item 2개(3개부터는 intent/paa와 합쳐 overstack 게이트에 걸린다 —
            # 이 계약 덕에 픽스처도 실게이트 기준을 지켜야 한다), 답변은 실질 문장.
            '<div class="faq-section">'
            '<article class="faq-item"><h3 class="faq-q">구글 AI 검색 설정은 어디에서 바꾸나요?</h3>'
            '<p class="faq-a">검색 설정 메뉴에서 바꿀 수 있고, 계정과 앱 버전에 따라 위치가 다를 수 있어 공식 도움말 확인이 안전하다.</p></article>'
            '<article class="faq-item"><h3 class="faq-q">업무 계정에서도 같은 설정이 적용되나요?</h3>'
            '<p class="faq-a">회사 관리 정책에 따라 일부 항목이 잠겨 있을 수 있어 관리자 설정을 먼저 확인하는 것이 좋다.</p></article>'
            "</div></article>"
        ),
        title="구글 AI 검색 설정 정리",
        topic="구글 AI 검색 설정",
        topic_group="ai_work",
    )
    # 주의: <style> 블록의 CSS 선택자에는 faq-card 문자열이 남을 수 있다 —
    # 계약 대상은 "본문 마크업이 faq-card 클래스를 쓰지 않는 것"이므로 속성 기준으로 검사.
    finalized_faq_items = finalized.count('class="faq-item"')
    assert finalized_faq_items >= 2
    assert 'class="faq-card"' not in finalized

    service.publish(
        title="구글 AI 검색 설정 정리",
        selected_topic="구글 AI 검색 설정",
        article_html=finalized,
        labels=["AI활용", "업무자동화"],
        topic_group="ai_work",
    )

    sent = str(client.calls[0]["article_html"])
    assert 'class="faq-card"' not in sent, "발행 단계가 확정 본문을 재렌더했다 (PR #29 회귀)"
    assert sent.count('class="faq-item"') == finalized_faq_items


def test_publish_preserves_finalized_geo_blocks_verbatim_body(tmp_path) -> None:
    """확정 본문의 GEO 블록·본문 문장이 발행 후에도 그대로 존재해야 한다."""
    service, client = _service(tmp_path)
    marker_sentence = "이 문장은 확정 본문 보존 검증용 마커다."
    finalized = ensure_answer_engine_optimized_html(
        f"<article><h1>확정 본문 보존 검증</h1><p>{marker_sentence}</p></article>",
        title="확정 본문 보존 검증",
        topic="확정 본문 보존",
        topic_group="ai_work",
    )
    service.publish(
        title="확정 본문 보존 검증",
        selected_topic="확정 본문 보존",
        article_html=finalized,
        labels=["AI활용", "업무자동화"],
        topic_group="ai_work",
    )
    sent = str(client.calls[0]["article_html"])
    assert marker_sentence in sent
    for block_id in (
        "AI_OVERVIEW_TARGET_ANSWER",
        "INTENT_ANSWER_BLOCK",
        "SOURCE_TRUST_BLOCK",
    ):
        assert f'id="{block_id}"' in sent, f"확정된 GEO 블록 유실: {block_id}"


def test_publish_rejects_unfinalized_html_loudly(tmp_path) -> None:
    """확정 안 된 본문(GEO 블록 없음)은 조용히 고쳐지는 대신 계약 위반으로 거부.

    과거에는 2차 ensure가 몰래 고쳐줘서 미확정 본문도 발행됐다 — 그 관용이
    "파이프라인 수정이 발행 단계에서 무효화되는" 사고의 뿌리였다.
    """
    service, _client = _service(tmp_path)
    with pytest.raises(ValueError):
        service.publish(
            title="미확정 본문 거부 검증",
            selected_topic="미확정 본문",
            article_html="<article><h1>미확정 본문 거부 검증</h1><p>GEO 확정 없이 온 본문.</p></article>",
            labels=["AI활용", "업무자동화"],
            topic_group="ai_work",
        )
