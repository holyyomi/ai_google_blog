from __future__ import annotations

from blogspot_automation.services.final_html_audit_service import audit_final_html_quality
from blogspot_automation.services.title_integrity_policy import (
    audit_title_integrity,
    contains_foreign_script,
)


def test_cyrillic_in_title_is_blocked() -> None:
    # 실사례: "항공권 싸다고 зарубеж?" 가 LIVE까지 유출됐던 사고 재발 방지
    audit = audit_title_integrity("항공권 싸다고 зарубеж? 30% 저렴 스팟과 베트남 선호의 의미")
    assert "foreign_script_in_title" in audit["blocking_issues"]


def test_normal_korean_english_title_passes_foreign_guard() -> None:
    for title in (
        "손흥민 이적설에 토트넘이 침묵하는 동안 움직인 세 가지",
        "K-패스 환급, 교통카드 정보 업데이트 안 하면 손해입니다",
        "넷플릭스 1위 '참교육'이 사이다인데 씁쓸한 이유",
        "iPhone 17e 사전예약, 통신 3사 조건 비교",
    ):
        audit = audit_title_integrity(title)
        assert "foreign_script_in_title" not in audit["blocking_issues"], title


def test_contains_foreign_script_detects_scripts() -> None:
    assert contains_foreign_script("зарубеж") is True       # 키릴
    assert contains_foreign_script("ありがとう") is True     # 히라가나
    assert contains_foreign_script("カタカナ") is True       # 가타카나
    assert contains_foreign_script("ภาษาไทย") is True       # 태국어
    assert contains_foreign_script("한국어 English 123 #해시태그") is False


def test_cyrillic_in_body_blocks_final_audit() -> None:
    html = (
        '<article class="yomi-clean-post">'
        "<p>여름 휴가철 항공권은 зарубеж 노선이 30% 저렴합니다.</p>"
        "</article>"
    )
    audit = audit_final_html_quality(html, topic="항공권 특가")
    assert any("foreign_script_in_body" in str(i) for i in audit.get("issues", []))


def test_clean_body_passes_foreign_guard() -> None:
    html = (
        '<article class="yomi-clean-post">'
        "<p>여름 휴가철 항공권은 동남아 노선이 30% 저렴합니다. English brand names OK.</p>"
        "</article>"
    )
    audit = audit_final_html_quality(html, topic="항공권 특가")
    assert not any("foreign_script_in_body" in str(i) for i in audit.get("issues", []))


def test_article_ending_with_faq_is_rejected() -> None:
    # 기승전결 '결' 강제 — FAQ로 끝나는 본문은 재생성 (실사례: 푸바오 글이 FAQ로 끝남)
    import pytest
    from blogspot_automation.services.trending_article_service import TrendingArticleService

    base = (
        '<article class="yomi-clean-post">'
        '<span class="yomi-kicker">2026.06.10 기준 오늘 이슈</span>'
        '<section class="yomi-lede"><p>핵심 답변.</p></section>'
        '<div class="yomi-thesis"><div><b>A</b><p>a</p></div><div><b>B</b><p>b</p></div></div>'
        '<ul class="yomi-list"><li data-step="1">확인.</li></ul>'
        "{tail}"
        "</article>"
    )
    payload_tpl = '{{"title": "푸바오 여동생 또 태어났다, 무엇이 달라지나", "content": "{c}"}}'

    bad = base.format(tail='<section class="yomi-faq"><h2>자주 묻는 질문</h2><article><h3>q?</h3><p>a</p></article></section>')
    with pytest.raises(ValueError, match="결"):
        TrendingArticleService._validate_json_response(payload_tpl.format(c=bad.replace('"', '\\"')))

    good = base.format(tail=(
        '<section class="yomi-faq"><h2>자주 묻는 질문</h2><article><h3>q?</h3><p>a</p></article></section>'
        "<h2>아기 판다 이름보다 먼저 볼 것</h2><p>최종 판단과 관전 포인트.</p>"
    ))
    TrendingArticleService._validate_json_response(payload_tpl.format(c=good.replace('"', '\\"')))
