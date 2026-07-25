"""lede(AI_OVERVIEW_TARGET_ANSWER)가 주제별 확정 사실로 시작하는지 회귀 테스트.

배경(2026-07-25): Blogger API가 글별 meta description을 저장하지 않으므로
(`docs/INDEXABILITY_RUNBOOK.md` B항 참고) Blogspot은 **첫 문단을 SERP 스니펫으로**
쓴다. 그런데 lede의 재료 3개 중 hook/real은 본문 첫·둘째 문장에서 가져오므로
`_drop_sentences_already_in_body`가 반드시 지우고, 합성 상투어(yomi_judgment)만
살아남아 최근 5개 발행글 중 4개의 스니펫이 같은 문장으로 시작했다.

수정: LLM이 뽑은 confirmed_facts를 lede 1순위 재료로 승격.

**이 테스트가 특히 지키는 것**: 확정 사실에 body-dedup을 걸면 안 된다.
확정 사실은 LLM이 **본문에서** 뽑은 문장이라 정의상 본문에 존재하므로, dedup을
걸면 전부 삭제돼 lede가 다시 상투어로 되돌아간다(리허설 3차에서 실제로 발생 —
초안의 lede가 "The real question is what actually changes for you..."였다).
"""
from __future__ import annotations

import html as _html
import re

import pytest

from blogspot_automation.services.answer_engine_policy import (
    ensure_answer_engine_optimized_html,
)

FACT_A = "OpenAI and Hugging Face are officially partnering to address the July 2026 incident"
FACT_B = "The incident occurred during a controlled model evaluation phase"

# 확정 사실이 본문에도 그대로 등장하는 상황 — 실제 파이프라인의 기본 상태다.
BODY_WITH_FACTS = (
    '<div class="yomi-clean-post">'
    f"<p>{FACT_A}. {FACT_B}.</p>"
    "<h2>What changed</h2><p>Detail paragraph.</p>"
    "</div>"
)


def _lede_text(*, confirmed_facts, body=BODY_WITH_FACTS):
    out = ensure_answer_engine_optimized_html(
        body,
        title="OpenAI Hugging Face Security Incident July 2026",
        topic="OpenAI Hugging Face incident",
        content_type="ai_work_tip",
        topic_group="ai_work",
        today="July 25, 2026",
        confirmed_facts=confirmed_facts,
        check_needed=["Check the official blog", "Check your API permissions"],
    )
    match = re.search(r'id="AI_OVERVIEW_TARGET_ANSWER".*?</section>', out, re.S)
    assert match, "AI_OVERVIEW_TARGET_ANSWER 블록이 없다"
    text = re.sub(r"<[^>]+>", " ", match.group(0))
    text = re.sub(r"\s+", " ", _html.unescape(text)).strip()
    return re.sub(r'^id="[A-Z_]+" class="yomi-lede">\s*', "", text)


# lede에서 걷어내야 하는 상투어들 (answer_engine_policy._YOMI_JUDGMENT_VARIANTS_EN)
PLATITUDES = (
    "separating the actual impact from the noise",
    "telling the confirmed changes apart from the speculation",
    "what actually changes for you versus what's just chatter",
    "sorting what's confirmed from what's still guesswork",
    "separate what's locked in from what's still speculation",
)


def test_lede_leads_with_confirmed_facts_even_when_present_in_body():
    """핵심 회귀 테스트 — 본문에 같은 문장이 있어도 사실이 lede에 남아야 한다."""
    lede = _lede_text(confirmed_facts=[FACT_A, FACT_B])
    assert FACT_A in lede, f"확정 사실이 lede에서 사라졌다 (body-dedup 재발?): {lede}"


def test_lede_drops_platitudes_when_facts_available():
    lede = _lede_text(confirmed_facts=[FACT_A, FACT_B])
    for platitude in PLATITUDES:
        assert platitude not in lede, f"상투어가 lede에 남았다: {platitude}"


def test_lede_drops_region_disclaimer_when_facts_available():
    """SERP 스니펫 앞자리를 110자 면책 문구가 잡아먹지 않아야 한다."""
    lede = _lede_text(confirmed_facts=[FACT_A, FACT_B])
    assert "Availability, pricing, and rollout can vary by account and region" not in lede


def test_lede_falls_back_when_no_confirmed_facts():
    """사실이 없으면 기존 폴백을 유지한다 (빈 lede로 만들면 발행 계약 위반)."""
    lede = _lede_text(confirmed_facts=[])
    assert len(lede) >= 35


@pytest.mark.parametrize("facts", [None, [], [""], ["   "]])
def test_lede_handles_empty_fact_inputs(facts):
    lede = _lede_text(confirmed_facts=facts)
    assert len(lede) >= 35


def test_two_different_topics_produce_different_ledes():
    """스니펫 개별화가 실제로 되는지 — 서로 다른 주제는 서로 다른 lede."""
    lede_a = _lede_text(confirmed_facts=[FACT_A, FACT_B])
    other = "ChatGPT Go costs $8 per month in India and Indonesia only"
    lede_b = _lede_text(
        confirmed_facts=[other, "Plus stays at $20 per month"],
        body=(
            '<div class="yomi-clean-post">'
            f"<p>{other}. Plus stays at $20 per month.</p>"
            "<h2>Detail</h2><p>x</p></div>"
        ),
    )
    assert lede_a != lede_b
    assert "Hugging Face" in lede_a
    assert "$8" in lede_b


def test_confirmed_facts_are_not_body_deduped_in_source():
    """소스 레벨 가드 — 확정 사실 lede에 body-dedup을 다시 걸면 실패시킨다."""
    import inspect

    from blogspot_automation.services import answer_engine_policy as mod

    source = inspect.getsource(mod.ensure_answer_engine_optimized_html)
    # `_fact_lede = _drop_sentences_already_in_body(` 형태가 되살아나면 안 된다.
    assert not re.search(
        r"_fact_lede\s*=\s*_drop_sentences_already_in_body\(", source
    ), "확정 사실 lede에 body-dedup이 다시 걸렸다 (lede가 상투어로 되돌아간다)"


# ---------------------------------------------------------------------------
# 실제 발행 경로 재현: confirmed_facts 파라미터 없이, 본문에 CONFIRMED 블록만 있는 상태
# ---------------------------------------------------------------------------
REAL_CONFIRMED_BLOCK = """
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
  <div class="confirmed-section">
    <h3>What's confirmed</h3>
    <ul>
      <li>OpenAI and Anthropic are collaborating on safety and alignment evaluation standards.</li>
      <li>The companies are prioritizing the protection of proprietary model weights to ensure commercial viability.</li>
      <li>High-capability "frontier" models are being kept behind gated APIs to maintain safety and control.</li>
    </ul>
  </div>
  <div class="check-needed-section">
    <h3>Check for yourself</h3>
    <ul>
      <li>Verify current API pricing tiers on the official pricing pages.</li>
    </ul>
  </div>
</section>
"""


def test_lede_uses_existing_confirmed_block_without_param():
    """실제 발행 경로(news_pipeline.py:1251)는 confirmed_facts를 넘기지 않는다.

    리허설 6차 실측: CONFIRMED 블록에는 주제 특화 사실이 있는데 lede는
    "The article separates what's confirmed from what you should verify yourself."
    폴백이었다. 원인은 lede 계산이 confirmed_map보다 **먼저** 돌면서 파라미터만
    보고 있었던 것. 이제 본문의 CONFIRMED 블록도 사실 출처로 쓴다.
    """
    body = (
        '<div class="yomi-clean-post">'
        "<p>Body opening sentence about the collaboration.</p>"
        "<h2>Detail</h2><p>More body text here.</p>"
        f"{REAL_CONFIRMED_BLOCK}"
        "</div>"
    )
    lede = _lede_text(confirmed_facts=None, body=body)
    assert "OpenAI and Anthropic are collaborating" in lede, lede
    assert "The article separates what's confirmed" not in lede


def test_lede_never_leads_with_template_confirmed_boilerplate():
    """템플릿 확정사실(_AI_CONFIRMED_VARIANTS_EN)이 lede 앞자리를 차지하면 안 된다.

    그걸 앞세우면 스니펫이 다시 글마다 같아져 이 수정의 목적이 사라진다.
    """
    from blogspot_automation.services.geo_intent_service import (
        _AI_CONFIRMED_VARIANTS_EN,
    )

    body = (
        '<div class="yomi-clean-post"><p>Some body text about an AI update.</p>'
        "<h2>Detail</h2><p>More text.</p></div>"
    )
    lede = _lede_text(confirmed_facts=None, body=body)
    for group in _AI_CONFIRMED_VARIANTS_EN:
        # 첫 문장(라벨 직후)이 템플릿 문구로 시작하지 않아야 한다.
        assert not lede.split(". ")[0].endswith(group[0].rstrip(".")), lede


def test_lede_fact_extraction_runs_after_confirmed_map():
    """소스 가드 — lede 사실 계산이 confirmed_map 확정 **뒤**에 있어야 한다."""
    import inspect

    from blogspot_automation.services import answer_engine_policy as mod

    src = inspect.getsource(mod.ensure_answer_engine_optimized_html)
    map_pos = src.index("confirmed_map = service.generate_confirmed_vs_check_needed")
    lede_pos = src.index("_lede_facts = _clean_fact_list")
    assert lede_pos > map_pos, (
        "lede 사실 계산이 confirmed_map보다 먼저 있다 — 파라미터가 없는 실제 발행 "
        "경로에서 사실을 못 보게 된다(리허설 6차 사고 재발)"
    )
