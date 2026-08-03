"""영어 본문 길이 미달 시 '전면 재생성' 대신 '보강(repair)' 경로 테스트 (2026-08-03).

배경: 프롬프트("1,600+ words" / "under 1,500 rejected")와 검증기(1400 하한)가 서로
다른 숫자를 요구해, 모델이 1,336~1,393단어를 내면 초안을 통째로 버리고 처음부터
재생성했다(호출 1회 ≈2분, 재시도 루프에서 반복 → 타임아웃 주범). 지금은 하한이
EN_MIN_BODY_WORDS 하나로 통일됐고, 길이만 모자란 초안은 같은 provider에 초안을
돌려주며 보강을 요청한다.
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from blogspot_automation.services import llm_content_service as module
from blogspot_automation.services.llm_content_service import LlmContentService


@pytest.fixture(autouse=True)
def _english_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)


def _en_article(sentence_count: int) -> str:
    """검증기의 다른 검사(태그 균형·반복·FAQ·헤지)를 통과하는 EN 본문 골격."""
    body = " ".join(
        f"Paragraph {i} explains how the Pro plan handles {i + 3} exports per day "
        f"and what that changes for your weekly workload."
        for i in range(sentence_count)
    )
    return (
        "<h2>Pricing and limits</h2>"
        f"<p>{body}</p>"
        '<section class="faq-section"><article class="faq-item">'
        '<h3 class="faq-q">Is the paid plan worth it?</h3>'
        "<p class=\"faq-a\">Yes once your daily exports pass the free cap, because the paid "
        "tier lifts that ceiling far beyond casual use and keeps batch jobs running.</p>"
        "</article></section>"
    )


SHORT_DRAFT = _en_article(70)   # ≈1,380단어 — 하한 미달
LONG_DRAFT = _en_article(110)   # ≈2,150단어 — 하한 통과


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": self._content}}]}
        ).encode("utf-8")


def test_word_counter_counts_numbers_and_prices() -> None:
    # 예전 정규식 [A-Za-z]... 는 숫자를 안 세서 가격·스펙이 많은 글이 불리했다.
    assert module.count_body_words("ChatGPT Plus costs $20 a month for 200K tokens.") == 9


def test_short_draft_is_below_floor_and_long_draft_passes() -> None:
    from blogspot_automation.services.llm_content_service import _validate_generated_content

    with pytest.raises(module._WordCountShortfallError) as exc_info:
        _validate_generated_content(SHORT_DRAFT)
    assert exc_info.value.word_count < module.EN_MIN_BODY_WORDS
    _validate_generated_content(LONG_DRAFT)  # 예외 없어야 함


def test_length_repair_builder_only_handles_length_shortfall() -> None:
    length_error = module._WordCountShortfallError(1393, module.EN_MIN_BODY_WORDS)
    prompt = module._build_length_repair_prompt(SHORT_DRAFT, length_error)
    assert prompt and "REVISION TASK" in prompt
    assert "1393" in prompt and str(module.EN_MIN_BODY_WORDS) in prompt
    assert SHORT_DRAFT in prompt  # 원본 초안을 그대로 돌려줘야 보존이 가능하다

    # 길이 외 결함(절단·태그 불균형 등)은 보강 대상이 아니라 기존대로 폴백한다.
    assert module._build_length_repair_prompt(
        SHORT_DRAFT, module._ContentValidationError("응답이 태그로 끝나지 않음")
    ) is None


def test_short_draft_triggers_repair_call_not_regeneration(monkeypatch) -> None:
    """짧은 초안 → 보강 호출 1회 → 하한 통과하면 채택 (유료 폴백 없음)."""
    payloads: list[dict] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        del timeout
        payloads.append(json.loads(req.data.decode("utf-8")))
        return _FakeResponse(SHORT_DRAFT if len(payloads) == 1 else LONG_DRAFT)

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._run_fallback_chain("Write a post about ChatGPT pricing")

    assert result == LONG_DRAFT
    # 정확히 2회: 최초 생성 + 보강. 전면 재생성도, 유료 폴백도 없다.
    assert len(payloads) == 2
    first_user = payloads[0]["messages"][1]["content"]
    repair_user = payloads[1]["messages"][1]["content"]
    assert "Write a post about ChatGPT pricing" in first_user
    assert "REVISION TASK" in repair_user
    assert "expand" in repair_user.lower()
    # 보강 호출은 원본 초안을 그대로 포함해야 한다(백지 재생성이 아님).
    assert SHORT_DRAFT in repair_user
    assert payloads[1]["model"] == payloads[0]["model"]  # 같은 provider/모델


def test_repair_failure_falls_back_and_is_bounded(monkeypatch) -> None:
    """보강본도 미달이면 기존대로 폴백하고, 보강 호출 총량은 상한에 묶인다."""
    payloads: list[dict] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        del timeout
        body = json.loads(req.data.decode("utf-8"))
        payloads.append(body)
        # OpenAI 유료 폴백만 정상 길이를 낸다 — 무료 3단계는 계속 짧게.
        if "api.openai.com" in req.full_url:
            return _FakeResponse(LONG_DRAFT)
        return _FakeResponse(SHORT_DRAFT)

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._run_fallback_chain("Write a post about ChatGPT pricing")

    assert result == LONG_DRAFT
    repair_calls = [p for p in payloads if "REVISION TASK" in p["messages"][1]["content"]]
    # max_repairs=2 상한 — 무한 보강 루프가 없어야 한다.
    assert len(repair_calls) <= 2
    # 보강 실패 후에는 같은 provider 전면 재생성을 태우지 않는다(시간 낭비 방지):
    # OpenRouter 3단계 각각 최대 (생성 1 + 보강 0~1)회.
    assert len(payloads) <= 8
