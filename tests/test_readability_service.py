from __future__ import annotations

from blogspot_automation.services import llm_content_service
from blogspot_automation.services.llm_content_service import LlmContentService
from blogspot_automation.services.news_quality_gate import NewsQualityGate
from blogspot_automation.services.readability_service import measure, measure_html


def test_easy_text_scores_higher_than_hard_text() -> None:
    easy = (
        "You can start with one task today. Pick a file you already use. "
        "Ask the tool to make a short first draft. Then check each claim."
    )
    hard = (
        "Operationalizing comprehensive interoperability requirements across heterogeneous "
        "enterprise authentication environments substantially increases implementation "
        "complexity, administrative coordination, and downstream governance obligations."
    )

    assert measure(easy)["flesch_reading_ease"] > measure(hard)["flesch_reading_ease"]


def test_measure_html_excludes_code_tables_and_geo_blocks() -> None:
    visible = "Use this tool for one small task. Check the answer before you share it."
    html = f"""
    <article>
      <p>{visible}</p>
      <pre>Comprehensive architectural interoperability requirements.</pre>
      <code>Incomprehensibility institutionalization.</code>
      <div class="quick-decision-table">
        <table><tr><td>Operationalization complexity dominates implementation.</td></tr></table>
      </div>
      <section id="AI_OVERVIEW_TARGET_ANSWER">
        Enterprise administrators coordinate heterogeneous authentication infrastructure.
      </section>
    </article>
    """

    assert measure_html(html)["words"] == measure(visible)["words"]


def test_quality_gate_blocks_readability_below_floor(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    html = (
        "<p>Operationalizing comprehensive interoperability requirements across heterogeneous "
        "enterprise authentication environments substantially increases implementation "
        "complexity, administrative coordination, and downstream governance obligations.</p>"
    )
    fre = float(measure_html(html)["flesch_reading_ease"])
    monkeypatch.setenv("READABILITY_FLOOR_FRE", str(fre + 1))

    blocking, warnings, _ = NewsQualityGate._readability_issues(html)

    assert any(issue.startswith("readability_below_floor:") for issue in blocking)
    assert not any(warning.startswith("readability_below_target:") for warning in warnings)


def test_quality_gate_warns_only_below_target(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    html = (
        "<p>This tool can help with weekly reports, but only if you check each fact. "
        "Start with one repeat task and keep the first run small.</p>"
    )
    fre = float(measure_html(html)["flesch_reading_ease"])
    monkeypatch.setenv("READABILITY_FLOOR_FRE", str(fre - 20))
    monkeypatch.setenv("READABILITY_TARGET_FRE", str(fre + 1))
    monkeypatch.setenv("READABILITY_TARGET_ASL", "999")

    blocking, warnings, _ = NewsQualityGate._readability_issues(html)

    assert not any(issue.startswith("readability_below_floor:") for issue in blocking)
    assert any(warning.startswith("readability_below_target:") for warning in warnings)


def test_quality_gate_does_not_block_when_text_is_unmeasurable(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    html = """
    <article>
      <table><tr><td>Only table text exists.</td></tr></table>
      <section id="SOURCE_TRUST_BLOCK">Only source trust text exists.</section>
    </article>
    """

    blocking, warnings, metrics = NewsQualityGate._readability_issues(html)

    assert blocking == []
    assert warnings == []
    assert metrics["words"] == 0


def test_readability_repair_keeps_original_when_repair_is_worse(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    original = (
        "<p>You can start with one task today. Keep the file small. "
        "Check the answer before you share it.</p>"
    )
    worse = (
        "<p>Operationalizing comprehensive interoperability requirements across heterogeneous "
        "enterprise authentication environments substantially increases implementation "
        "complexity, administrative coordination, and downstream governance obligations.</p>"
    )
    service = LlmContentService()
    monkeypatch.setattr(service, "_call_provider", lambda *args, **kwargs: worse)

    selected = service._attempt_acceptance_repair(
        provider={"name": "test_provider"},
        api_key="key",
        draft=original,
        repair_prompt="make it easier",
        system_prompt=None,
        min_chars=0,
        validator=lambda _html: None,
    )

    assert selected == original


def test_korean_mode_skips_readability_gate_and_repair_prompt(monkeypatch) -> None:
    monkeypatch.setenv("BLOG_LANGUAGE", "ko")
    html = (
        "<p>Operationalizing comprehensive interoperability requirements across heterogeneous "
        "enterprise authentication environments substantially increases implementation complexity.</p>"
    )

    blocking, warnings, metrics = NewsQualityGate._readability_issues(html)

    assert blocking == []
    assert warnings == []
    assert metrics == {}
    assert llm_content_service._build_readability_repair_prompt(html) is None
