"""출처 대조 차단 승격(2026-09-27) 회귀 방지.

- 걸리면 바로 버리지 않고 1회 재작성한다.
- 재작성 뒤에도 부재 단정·출처 없는 $가격이 남으면 blocked.
- 퍼센트·요청 수만 남으면 차단하지 않는다(가정 예시 오탐, 관찰 12일 실측).
- SOURCE_GROUNDING_GATE=observe 면 예전처럼 기록만 한다.
"""
import pytest

from blogspot_automation.services import llm_content_service as L
from blogspot_automation.services.source_grounding_service import (
    audit_grounding,
    grounding_gate_mode,
)

FACTS = "Gemini CLI free tier: 250 requests per day with an API key. Google AI Pro costs $19.99 per month."
PAD = "<p>" + "Plain sentence about the tool. " * 60 + "</p>"


def _html(extra: str) -> str:
    return f"<h2>Limits</h2><p>{extra}</p>{PAD}"


def test_hard_violations_are_absence_and_dollars_only():
    report = audit_grounding(
        _html("The vendor does not publish exact quotas. Ultra costs $249.99. About 30 requests per session, 40% faster."),
        FACTS,
    )
    hard = report.hard_violations
    assert any("does not publish" in h for h in hard)
    assert "$249.99" in hard
    assert "30 requests" not in hard and "40%" not in hard
    assert len(hard) == 2


def test_gate_mode_defaults_to_block(monkeypatch):
    monkeypatch.delenv("SOURCE_GROUNDING_GATE", raising=False)
    assert grounding_gate_mode() == "block"
    monkeypatch.setenv("SOURCE_GROUNDING_GATE", "observe")
    assert grounding_gate_mode() == "observe"


def _run(monkeypatch, drafts: list[str], mode: str = "block"):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    monkeypatch.setenv("SOURCE_GROUNDING_GATE", mode)
    svc = L.LlmContentService()
    monkeypatch.setattr(svc, "gather_facts_with_citations", lambda topic: (FACTS, []))
    calls: list[str] = []

    def fake_chain(prompt, **kwargs):
        calls.append(prompt)
        return drafts[min(len(calls) - 1, len(drafts) - 1)]

    monkeypatch.setattr(svc, "_run_fallback_chain", fake_chain)
    out = svc.generate_html(title="Gemini CLI free limits", topic="gemini cli free limits")
    return svc, out, calls


def test_repair_that_removes_claims_is_not_blocked(monkeypatch):
    bad = _html("The vendor does not publish exact quotas. Ultra costs $249.99.")
    good = _html("The free tier gives 250 requests per day. Google AI Pro costs $19.99 per month.")
    svc, out, calls = _run(monkeypatch, [bad, good])
    assert len(calls) == 2
    assert "[FLAGGED]" in calls[1] and "$249.99" in calls[1]
    assert svc.last_grounding_report["blocked"] is False
    assert "$249.99" not in (out or "")


def test_repair_that_keeps_fake_price_is_blocked(monkeypatch):
    bad = _html("Ultra costs $249.99.")
    svc, _, calls = _run(monkeypatch, [bad, bad])
    assert len(calls) == 2
    assert svc.last_grounding_report["blocked"] is True
    assert "$249.99" in svc.last_grounding_report["hard_violations"]


def test_soft_numbers_only_are_not_blocked(monkeypatch):
    soft = _html("If one session uses 30 requests, you get a few sessions.")
    svc, _, _ = _run(monkeypatch, [soft, soft])
    assert svc.last_grounding_report["blocked"] is False


def test_observe_mode_does_not_rewrite_or_block(monkeypatch):
    bad = _html("Ultra costs $249.99.")
    svc, _, calls = _run(monkeypatch, [bad], mode="observe")
    assert len(calls) == 1
    assert svc.last_grounding_report["blocked"] is False
