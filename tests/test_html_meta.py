from __future__ import annotations

from blogspot_automation.utils.html_meta import extract_meta_description, upsert_meta_description


def test_extract_meta_description_handles_name_before_content() -> None:
    html = '<meta name="description" content="뉴스 설명">'

    assert extract_meta_description(html) == "뉴스 설명"


def test_extract_meta_description_handles_content_before_name() -> None:
    html = '<meta content="뉴스 설명" name="description">'

    assert extract_meta_description(html) == "뉴스 설명"


def test_upsert_meta_description_adds_required_tag() -> None:
    html = "<article><h1>뉴스 제목</h1></article>"

    updated = upsert_meta_description(html, "검색 설명이 반드시 들어가야 합니다.")

    assert updated.startswith('<meta name="description"')
    assert extract_meta_description(updated) == "검색 설명이 반드시 들어가야 합니다."


def test_upsert_meta_description_replaces_existing_tag() -> None:
    html = '<meta name="description" content="old"><article>본문</article>'

    updated = upsert_meta_description(html, "새 검색 설명")

    assert 'content="old"' not in updated
    assert extract_meta_description(updated) == "새 검색 설명"
