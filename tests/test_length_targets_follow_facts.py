"""분량은 확보한 팩트를 따라간다 — 그리고 지시·검증·보강이 같은 숫자를 본다.

2026-09-01 드라이런에서 실제로 난 사고: 팩트가 737자라 프롬프트가 800~1200단어를
요구했고 모델이 832단어를 정확히 냈는데, 검증기는 여전히 상수 1500을 보고
"단어 수 부족"으로 거부했다. 폴백 체인이 헛돌다 429까지 맞았다.
"""
from __future__ import annotations

import pytest

from blogspot_automation.services import llm_content_service as L


def test_thin_facts_get_the_short_format():
    assert L._length_targets_for_facts("x" * 500) == (
        L.EN_SHORT_MIN_BODY_WORDS, L.EN_SHORT_TARGET_MIN, L.EN_SHORT_TARGET_MAX
    )


def test_rich_facts_keep_the_full_format():
    assert L._length_targets_for_facts("x" * 6000) == (
        L.EN_MIN_BODY_WORDS, L.EN_TARGET_BODY_WORDS_MIN, L.EN_TARGET_BODY_WORDS_MAX
    )


def test_missing_facts_do_not_demand_a_long_article():
    """팩트가 없으면 할 말도 없다 — 길게 요구하면 지어내게 된다."""
    assert L._length_targets_for_facts("")[0] == L.EN_SHORT_MIN_BODY_WORDS


def test_validator_honours_the_short_minimum(monkeypatch):
    """짧은 포맷의 정상 초안을 검증기가 거부하면 안 된다 (실제 사고 숫자)."""
    monkeypatch.setattr(L, "is_english_mode", lambda: True)
    body = "<section>" + (" word" * 832) + "</section>"
    L._make_content_validator(L.EN_SHORT_MIN_BODY_WORDS)(body)  # 예외 없이 통과해야 함


def test_validator_still_rejects_short_drafts_in_the_full_format(monkeypatch):
    monkeypatch.setattr(L, "is_english_mode", lambda: True)
    body = "<section>" + (" word" * 832) + "</section>"
    with pytest.raises(L._WordCountShortfallError):
        L._make_content_validator(L.EN_MIN_BODY_WORDS)(body)


def test_repair_prompt_does_not_reinflate_a_short_article():
    """보강 목표가 상수면 짧은 글을 다시 긴 포맷으로 부풀린다."""
    prompt = L._build_length_repair_prompt(
        "<p>draft</p>", L._WordCountShortfallError(600, L.EN_SHORT_MIN_BODY_WORDS)
    )
    assert str(L.EN_SHORT_TARGET_MAX) in prompt
    assert str(L.EN_TARGET_BODY_WORDS_MAX) not in prompt


def test_repair_prompt_keeps_the_full_target_for_full_articles():
    prompt = L._build_length_repair_prompt(
        "<p>draft</p>", L._WordCountShortfallError(600, L.EN_MIN_BODY_WORDS)
    )
    assert str(L.EN_TARGET_BODY_WORDS_MAX) in prompt


def test_exa_body_budget_is_not_thrown_away():
    """Exa 본문을 받아놓고 다시 잘라버리면 수집을 늘린 의미가 없다.

    2026-09-01 실측: numResults=3 / maxCharacters=400에 더해 코드에서 [:300]으로
    한 번 더 잘라, 같은 검색 1회로 7,500자를 받을 수 있는데 1,200자만 쓰고 있었다.
    Exa는 검색 건당 과금이라 본문을 더 받는 비용은 사실상 0이다. 그 1,200자로
    2,600단어를 요구한 것이 헤지 포화의 직접 원인이었다.
    """
    import inspect

    from blogspot_automation.services.llm_content_service import LlmContentService

    source = inspect.getsource(LlmContentService._exa_facts_and_citations)
    assert '"maxCharacters": 400' not in source, "본문 수집이 400자로 되돌아갔다"
    assert '[:300]' not in source, "받은 본문을 300자로 다시 자르고 있다"

    sig = inspect.signature(LlmContentService._exa_facts_and_citations)
    assert sig.parameters["num_results"].default >= 5, "검색 결과 수가 줄었다"
