"""도입부가 제목의 질문에 답하는지 검사하는 게이트.

2026-09-01 라이브 사고에서 나왔다. 제목이 "ChatGPT Free Version Limits 2026"인데
도입부(AI 검색이 실제로 인용해가는 AI_OVERVIEW_TARGET_ANSWER 블록)는 한도를 한 마디도
하지 않고 "무료다"를 두 번 반복했다. 기존 헤지 포화도 게이트는 글 전체 비율을 보므로
회피가 도입부에만 몰린 이 글을 통과시켰다.
"""
from __future__ import annotations

from blogspot_automation.services.news_quality_gate import NewsQualityGate


def _block(inner: str) -> str:
    return (
        '<article><section id="AI_OVERVIEW_TARGET_ANSWER" class="yomi-lede">'
        f"<h2>Bottom line first</h2><p>{inner}</p></section>"
        "<div class='post-content'><p>body</p></div></article>"
    )


def test_the_actual_failure_is_caught():
    """9/1 라이브 글의 실제 도입부 — 제목은 한도를 묻는데 답이 없다."""
    html = _block(
        "Free tier users have access to GPT-5.6 Luna as of September 2026 "
        "(OpenAI Help Center). The free plan has no subscription fee and is "
        "completely free (OpenAI Help Center)."
    )
    ok, reason = NewsQualityGate._answer_block_answers_the_title(
        html, "ChatGPT Free Version Limits 2026"
    )
    assert ok is False
    assert "off_topic" in reason


def test_the_corrected_lead_passes():
    """실제로 답하는 도입부는 통과해야 한다 (오탐 방지)."""
    html = _block(
        "ChatGPT's free version has no daily limit on ordinary text chats - "
        "OpenAI's Free Tier FAQ calls them unlimited. The limits that do exist sit "
        "on file uploads, image generation, voice, and data analysis."
    )
    ok, reason = NewsQualityGate._answer_block_answers_the_title(
        html, "ChatGPT Free Version Limits 2026"
    )
    assert ok is True, reason


def test_deferral_in_the_lead_is_blocked():
    """첫 답변이 다른 데를 가리키면 인용될 수도 순위가 나올 수도 없다."""
    html = _block(
        "Gemini free tier limits are not disclosed by Google as of September 2026. "
        "You must check the official pricing page for the current numbers."
    )
    ok, reason = NewsQualityGate._answer_block_answers_the_title(
        html, "Gemini Free Tier Limits Explained"
    )
    assert ok is False
    assert reason.startswith("answer_defers")


def test_missing_block_does_not_block_publishing():
    """블록이 없으면 이 게이트는 판단하지 않는다 — 다른 게이트의 영역이다."""
    ok, reason = NewsQualityGate._answer_block_answers_the_title(
        "<article><p>no answer block here</p></article>", "Some Title About Things"
    )
    assert ok is True
    assert reason == ""


def test_short_block_is_not_judged():
    ok, _ = NewsQualityGate._answer_block_answers_the_title(
        _block("Too short."), "ChatGPT Free Version Limits 2026"
    )
    assert ok is True


def test_year_in_title_is_not_required_in_the_answer():
    """제목의 연도는 내용어가 아니다 — 이것 때문에 오탐이 나면 안 된다."""
    html = _block(
        "Ollama returns a 404 on localhost when the model name does not match "
        "what the local server actually has installed. Run the list command to see them."
    )
    ok, reason = NewsQualityGate._answer_block_answers_the_title(
        html, "Ollama 404 Error on Localhost 2026"
    )
    assert ok is True, reason
