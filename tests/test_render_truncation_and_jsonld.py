"""2026-07-20 라이브 감사 결함 회귀 테스트.

실측 결함 4종:
1) 하드 슬라이스로 단어 중간 절단이 본문·앵커에 노출 ("rollout can vary by acco",
   "pricing starts J", "actually sends t")
2) LLM이 쓴 ld+json의 headline raw 개행 → BlogPosting 스키마 전체 무효
3) FAQPage Question.name에 질문+답변 통짜 결합
4) 가격 FAQ 3종 세트가 보안 사고 글에도 동일하게 부착
"""
from __future__ import annotations

import json
import re

import pytest

from blogspot_automation.utils.text_clip import clip_at_word_boundary


def test_clip_short_text_unchanged() -> None:
    assert clip_at_word_boundary("hello world", 90) == "hello world"


def test_clip_cuts_at_word_boundary_not_mid_word() -> None:
    text = (
        "Claude Fable 5 free access extended three times to July 19, "
        "usage credits pricing starts July 22"
    )
    clipped = clip_at_word_boundary(text, 90)
    # 과거 하드컷은 "pricing starts J"로 끝났다 — 단어 중간 절단 금지.
    assert not clipped.endswith(" J")
    assert len(clipped) <= 90
    assert clipped.split()[-1] in text.split()


def test_clip_ellipsis_only_when_clipped() -> None:
    assert clip_at_word_boundary("short", 90, ellipsis="…") == "short"
    long_title = "What xAI Grok Build CLI actually sends to remote servers today"
    clipped = clip_at_word_boundary(long_title, 40, ellipsis="…")
    assert clipped.endswith("…")
    assert "sends t…" not in clipped  # 단어 중간 절단 금지


def test_clip_single_long_token_hard_cuts() -> None:
    assert len(clip_at_word_boundary("a" * 200, 50)) <= 50


def test_invalid_blogposting_json_ld_is_replaced(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    from blogspot_automation.services.answer_engine_policy import (
        ensure_answer_engine_optimized_html,
    )

    broken = (
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@type": "BlogPosting", '
        '"headline": "Copilot Share Falls to 51% as \n ARR (2026)"}'
        "</script>"
    )
    html = f"<article><h1>Copilot vs Cursor</h1>{broken}<p>Body text here about coding assistants and pricing details.</p></article>"
    out = ensure_answer_engine_optimized_html(
        html, title="Copilot vs Cursor", topic="copilot vs cursor", content_type="ai_work_tip"
    )
    scripts = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', out, flags=re.DOTALL
    )
    assert scripts, "ld+json 블록은 반드시 존재해야 한다 (발행 계약)"
    for body in scripts:
        json.loads(body)  # 전부 유효 JSON이어야 한다


def test_faq_name_with_concatenated_answer_is_dropped_and_rebuilt(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    from blogspot_automation.services.answer_engine_policy import (
        _drop_invalid_json_ld_scripts,
    )

    bad_faq = (
        '<script type="application/ld+json">'
        + json.dumps({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [{
                "@type": "Question",
                "name": "Will xAI open source more of their code?The official Grok Build announcement covers the details.",
                "acceptedAnswer": {"@type": "Answer", "text": "See above."},
            }],
        })
        + "</script>"
    )
    out = _drop_invalid_json_ld_scripts(f"<article>{bad_faq}</article>")
    assert "FAQPage" not in out


def test_valid_json_ld_is_kept() -> None:
    from blogspot_automation.services.answer_engine_policy import (
        _drop_invalid_json_ld_scripts,
    )

    good = (
        '<script type="application/ld+json">'
        + json.dumps({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [{
                "@type": "Question",
                "name": "Is it worth paying for right now?",
                "acceptedAnswer": {"@type": "Answer", "text": "Try the free tier first."},
            }],
        })
        + "</script>"
    )
    html = f"<article>{good}</article>"
    assert _drop_invalid_json_ld_scripts(html) == html


def test_generic_intent_pool_is_topic_conditional() -> None:
    from blogspot_automation.services.answer_engine_policy import _en_generic_intent_pool

    incident = _en_generic_intent_pool(
        "Grok Build open sourced after repo exfiltration", "ai_work_tip"
    )
    assert incident[0]["Q"] == "What actually happened?"
    assert all("worth paying" not in qa["Q"].lower() for qa in incident)

    pricing = _en_generic_intent_pool("hidden costs of AI subscriptions", "ai_work_tip")
    assert any("worth paying" in qa["Q"].lower() for qa in pricing)

    neutral = _en_generic_intent_pool("NotebookLM study workflow", "ai_work_tip")
    assert all("worth paying" not in qa["Q"].lower() for qa in neutral)


def test_short_topic_word_boundary(monkeypatch) -> None:
    from blogspot_automation.services.news_topic_service import NewsTopicService

    svc = NewsTopicService.__new__(NewsTopicService)
    long_title = (
        "Claude Fable 5 free access extended three times to July 19, "
        "usage credits pricing starts July 22"
    )
    topic = svc._short_topic(long_title)
    assert len(topic) <= 90
    assert not topic.endswith(" J")
