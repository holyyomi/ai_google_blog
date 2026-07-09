from __future__ import annotations

from typing import Any


def build_publish_preview_scorecard(quality_gate: dict[str, Any]) -> dict[str, Any]:
    final_audit = quality_gate.get("final_html_audit") if isinstance(quality_gate, dict) else {}
    final_audit = final_audit if isinstance(final_audit, dict) else {}
    clean_layout = (final_audit.get("metrics") or {}).get("yomi_clean_layout") or {}
    answer_coverage = quality_gate.get("answer_engine_coverage") or {}

    checks = [
        _check("quality_gate_passed", bool(quality_gate.get("passed")), "Quality gate passed"),
        _check("clean_post_layout", bool(clean_layout.get("present")), "Uses yomi-clean-post layout"),
        _check("single_lede", clean_layout.get("lede_count") == 1, "Exactly one first-answer lede"),
        _check(
            "adaptive_modules",
            int(clean_layout.get("adaptive_module_count") or 0) >= 2,
            "At least two 63-cj style adaptive modules",
            value=clean_layout.get("adaptive_module_count", 0),
        ),
        _check(
            "no_inline_styles",
            int(clean_layout.get("inline_style_count") or 0) == 0,
            "No inline styles in clean layout",
            value=clean_layout.get("inline_style_count", 0),
        ),
        _check(
            "no_details_ui",
            int(clean_layout.get("details_count") or 0) == 0,
            "No collapsible details UI",
            value=clean_layout.get("details_count", 0),
        ),
        _check(
            "answer_engine_blocks",
            all(
                bool(answer_coverage.get(key))
                for key in (
                    "ai_overview_target_answer_present",
                    "issue_context_present",
                    "intent_answer_present",
                    "source_trust_block_present",
                    "blogposting_json_ld_present",
                )
            ),
            "AEO/GEO support blocks present",
        ),
        _check(
            "faq_depth",
            int(quality_gate.get("faq_count") or 0) >= 3,
            "FAQ has at least 3 questions",
            value=quality_gate.get("faq_count", 0),
        ),
        _check(
            "reader_value",
            int(quality_gate.get("reader_value_score") or 0) >= 65,
            "Reader value score is publishable",
            value=quality_gate.get("reader_value_score", 0),
        ),
        _check(
            "article_focus",
            int(quality_gate.get("article_focus_score") or 0) >= 60,
            "Article focus score is publishable",
            value=quality_gate.get("article_focus_score", 0),
        ),
        _check(
            "outbound_links_removed",
            int(quality_gate.get("external_anchor_count") or 0) == 0,
            "No outbound clickable anchors",
            value=quality_gate.get("external_anchor_count", 0),
        ),
    ]

    blocking_issues = list(quality_gate.get("blocking_issues") or [])
    warnings = list(quality_gate.get("warnings") or [])
    passed_count = sum(1 for item in checks if item["status"] == "pass")
    score = round((passed_count / len(checks)) * 100) if checks else 0
    if not bool(quality_gate.get("passed")):
        score = min(score, 79)

    return {
        "score": score,
        "status": "pass" if score >= 80 and not blocking_issues else "fail",
        "passed_checks": passed_count,
        "total_checks": len(checks),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "checks": checks,
    }


def render_publish_preview_scorecard_markdown(scorecard: dict[str, Any]) -> str:
    lines = [
        "# Publish Preview Scorecard",
        "",
        f"- Status: {scorecard.get('status', 'unknown')}",
        f"- Score: {scorecard.get('score', 0)}",
        f"- Checks: {scorecard.get('passed_checks', 0)}/{scorecard.get('total_checks', 0)}",
        "",
        "## Checks",
    ]
    for item in scorecard.get("checks", []):
        status = str(item.get("status") or "unknown").upper()
        value = item.get("value")
        suffix = f" ({value})" if value not in (None, "") else ""
        lines.append(f"- {status}: {item.get('label', item.get('id', 'check'))}{suffix}")

    blocking = list(scorecard.get("blocking_issues") or [])
    if blocking:
        lines.extend(["", "## Blocking Issues"])
        lines.extend(f"- {issue}" for issue in blocking)

    warnings = list(scorecard.get("warnings") or [])
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.append("")
    return "\n".join(lines)


def _check(
    check_id: str,
    passed: bool,
    label: str,
    *,
    value: Any = None,
) -> dict[str, Any]:
    payload = {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
    }
    if value is not None:
        payload["value"] = value
    return payload
