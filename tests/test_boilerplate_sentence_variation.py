"""발행 글끼리 **똑같은 문장**을 공유하지 않는지 지키는 회귀 테스트.

배경 (2026-09-10): holyyomiai 47편이 색인 0편이었고, 47편 전문을 내려받아 세어
보니 아래처럼 토씨 하나 안 틀리고 같은 문장이 반복되고 있었다.

    42/47  Where can you verify the current details?
    33/47  Test it on one low-stakes task first, review the output yourself, ...
    33/47  Go by the official documentation and announcement pages; ...
    20/47  Plan limits and pricing match what was publicly listed as of this writing.
    16/47  AI output still needs human review before you use it for real work.

구글은 페이지에서 boilerplate 를 걷어낸 뒤 남는 고유 본문으로 가치를 판단하므로,
이 반복은 "크롤링됨 - 색인 안 함" 판정의 유력한 직접 원인이다.

여기서 지키는 계약은 두 가지다.
  1) 같은 유형의 서로 다른 글이 같은 템플릿 문장을 대량으로 공유하지 않는다.
  2) 면책·주의 문구는 **없애지 않는다** — 표현만 글마다 달라진다.
"""

from __future__ import annotations

import collections
import re

import pytest


@pytest.fixture(autouse=True)
def _english_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")


VENDORS = [
    "Claude", "Gemini", "NotebookLM", "Perplexity", "Midjourney", "Grok", "Llama",
    "Copilot", "Mistral", "Runway", "Suno", "ElevenLabs", "Cursor", "Windsurf",
    "Replit", "Notion AI", "Canva AI", "Sora", "Veo", "DeepSeek", "Qwen", "Kimi",
    "Firefly", "Ideogram", "Flux", "Whisper", "Codex", "Devin", "Lovable", "Gamma",
]
FEATURES = [
    "long-context memory", "pricing tiers", "voice mode", "agent mode",
    "image editing", "team seats", "offline export", "API rate limits",
]


def _article_html(i: int) -> str:
    vendor = VENDORS[i % len(VENDORS)]
    feature = FEATURES[i % len(FEATURES)]
    return f"""
<p class="yomi-lede">{vendor} shipped {feature} this week and the change is narrower than the launch post suggests.</p>
<div class="yomi-thesis"><p>The measurable difference is a {i * 3 + 11} percent lift on the cap, nothing more.</p></div>
<h2>What {vendor} actually changed with {feature}</h2>
<p>The {feature} ceiling moved from {i * 100 + 400} to {i * 100 + 900} for paid seats, while the free tier stayed at {i * 10 + 20} per day.</p>
<h2>What {vendor} costs on each plan now</h2>
<p>The paid seat is ${i % 30 + 12} a month billed annually and ${i % 30 + 16} monthly, and team seats add a ${i % 9 + 3} per-seat admin fee that the launch post never mentions.</p>
<h2>Where {vendor} still falls short</h2>
<p>Exports drop formatting above {i * 5 + 40} items and the history is capped at {i + 7} days on every plan, which matters if you have to audit anything later.</p>
<section class="faq-section">
<article class="faq-item"><h3 class="faq-q">Does {feature} work on the {vendor} free plan?</h3><p class="faq-a">Free accounts keep the old {i * 10 + 20} per day ceiling and get none of the new headroom.</p></article>
<article class="faq-item"><h3 class="faq-q">How long is the {vendor} rollout window?</h3><p class="faq-a">The posted window is {i % 3 + 2} weeks for individual accounts, with enterprise tenants landing later than that.</p></article>
</section>
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
<div class="confirmed-section"><h3>Confirmed facts</h3><ul>
<li>{vendor} raised the {feature} cap to {i * 100 + 900} for paid seats.</li>
<li>The free tier ceiling is unchanged at {i * 10 + 20} per day.</li>
<li>Team seats carry a ${i % 9 + 3} per-seat admin fee.</li>
</ul></div>
<div class="check-needed-section"><h3>Check for yourself</h3><ul>
<li>Whether the {i % 3 + 2} week rollout has reached your {vendor} workspace.</li>
<li>Whether the ${i % 30 + 12} annual rate applies in your billing region.</li>
</ul></div>
</section>
"""


def _render(i: int) -> str:
    from blogspot_automation.services.answer_engine_policy import (
        ensure_answer_engine_optimized_html,
    )

    vendor = VENDORS[i % len(VENDORS)]
    feature = FEATURES[i % len(FEATURES)]
    return ensure_answer_engine_optimized_html(
        _article_html(i),
        title=f"{vendor} {feature} update",
        topic=f"{vendor} {feature}",
        content_type="ai_work_tip",
        topic_group="ai_work",
        reader_questions=[f"Is {vendor} worth paying for?", f"What does {vendor} cost?"],
    )


def _sentences(html: str) -> set[str]:
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    return {
        s.strip()
        for s in re.split(r"(?<=[.?!])\s+", text)
        if len(s.strip()) > 30
    }


def test_no_sentence_is_shared_by_a_third_of_articles():
    """서로 다른 30편이 같은 문장을 10편 넘게 공유하면 실패.

    수정 전 실측값이 42/47(89%)였다. 여기서는 30편 렌더로 재현하고,
    한 문장이 10편(33%)을 넘기지 않는 것을 계약으로 잡는다.
    """
    counter: collections.Counter[str] = collections.Counter()
    for i in range(30):
        counter.update(_sentences(_render(i)))

    offenders = [(n, s) for s, n in counter.items() if n > 10]
    assert not offenders, (
        "30편 중 10편 넘게 반복되는 문장이 있다 — 템플릿 보일러플레이트가 다시 늘었다:\n"
        + "\n".join(f"{n}/30  {s[:110]}" for n, s in sorted(offenders, reverse=True)[:10])
    )


def test_two_articles_do_not_share_faq_questions():
    """같은 콘텐츠 타입의 두 글이 FAQ/intent 질문을 그대로 공유하면 안 된다."""

    def questions(html: str) -> set[str]:
        return {
            " ".join(re.sub(r"<[^>]+>", " ", q).split()).lstrip("Q. ").strip().lower()
            for q in re.findall(
                r'class="[^"]*(?:faq-q|intent-q)[^"]*"[^>]*>(.*?)</', html, re.DOTALL
            )
        }

    a, b = questions(_render(3)), questions(_render(11))
    shared = a & b
    assert not shared, f"두 글이 같은 질문을 공유한다: {sorted(shared)}"


def test_generic_intent_pool_prefers_article_headings():
    """본문이 있으면 폴백 Q&A보다 **그 글의 소제목에서 만든 질문**이 앞선다."""
    from blogspot_automation.services.answer_engine_policy import (
        _en_generic_intent_pool,
    )

    html = _article_html(5)
    pool = _en_generic_intent_pool("Grok agent mode", "ai_work_tip", html)
    assert pool, "폴백 풀이 비면 안 된다"
    # 첫 항목은 본문 소제목에서 왔어야 한다 — 그 글에만 있는 고유명사가 들어간다.
    assert "Grok" in pool[0]["Q"], pool[0]["Q"]
    # 그리고 그 답은 본문에서 온 실제 사실이어야 한다(숫자 포함).
    assert re.search(r"\d", pool[0]["A"]), pool[0]["A"]


def test_confirmed_block_uses_body_facts_not_template():
    """본문 CONFIRMED 블록이 있으면 템플릿 확정사실 문장을 쓰지 않는다.

    실제 발행 경로(news_pipeline)는 confirmed_facts 파라미터를 넘기지 않는다 —
    그래서 47편 전부가 템플릿 문장을 받았다. 본문에서 걷어오는 경로가 살아 있는지
    확인한다.
    """
    from blogspot_automation.services.geo_intent_service import (
        _AI_CONFIRMED_ATTRIBUTION_EN,
        _AI_CONFIRMED_PRICING_EN,
    )

    html = _render(7)
    for template in (*_AI_CONFIRMED_ATTRIBUTION_EN, *_AI_CONFIRMED_PRICING_EN):
        assert template not in html, f"템플릿 확정사실이 그대로 실렸다: {template}"
    assert "raised the" in html or "per-seat admin fee" in html, "본문 사실이 사라졌다"


def test_disclaimer_is_kept_just_reworded():
    """면책·주의 문구를 **없애지 않는다** — 표현만 글마다 달라야 한다."""
    review_terms = ("review", "check", "confirm", "verify", "human")
    for i in (0, 4, 9, 15, 22):
        html = _render(i).lower()
        assert any(t in html for t in review_terms), f"{i}번 글에 검증 안내가 사라졌다"


def test_variation_is_deterministic():
    """같은 글은 몇 번을 렌더해도 같은 문장을 얻는다 (재렌더 시 게이트 흔들림 방지)."""
    assert _render(2) == _render(2)


def test_fallback_answers_do_not_repeat_inside_one_article():
    """한 글 안에서 intent 답변이 서로 같으면 안 된다(발행 게이트 조건)."""
    html = _render(1)
    answers = [
        " ".join(re.sub(r"<[^>]+>", " ", a).split())
        for a in re.findall(r'<p>A\.\s*(.*?)</p>', html, re.DOTALL)
    ]
    assert len(answers) == len(set(answers)), answers


def test_extract_faq_reads_h3_p_markup():
    """LLM이 내는 <h3 class="faq-q">/<p class="faq-a"> 형식을 실제로 읽어낸다.

    2026-09-10 이전에는 닫는 태그를 </div>로만 찾아서 영어 글 FAQ가 하나도 안
    잡혔고, FAQPage JSON-LD가 그 글의 진짜 질문 없이 나갔다.
    """
    from blogspot_automation.services.llm_content_service import _extract_faq

    html = (
        '<section class="faq-section">'
        '<article class="faq-item"><h3 class="faq-q">Does Gemini agent mode run offline?</h3>'
        '<p class="faq-a">No. Agent mode needs a live connection for every step of the run.</p></article>'
        "</section>"
    )
    faqs = _extract_faq(html)
    assert faqs, "h3/p 형식 FAQ를 못 읽었다"
    assert faqs[0]["Q"] == "Does Gemini agent mode run offline?"
    assert faqs[0]["A"].startswith("No.")
