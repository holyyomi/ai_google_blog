from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pytest

from blogspot_automation.services.news_quality_gate import NewsQualityGate


# 2026-07-21 라이브 실측 재현: 일반형 "AI Assistant Pricing Compared" 글이 이미
# 발행된 상태에서, 학생형 "ChatGPT Gemini Copilot Student Pricing" 글이 40분 뒤
# 생성됐다. 사전 주제 문자열은 topic_dedup_service의 키워드 겹침(>=2)을 통과할
# 만큼 달랐지만("best AI tools for students"는 stopword 제거 후 "students" 하나만
# 남음), 실제 생성된 두 글은 ChatGPT/Gemini/Claude/Copilot 구독료를 비교하는
# 사실상 같은 글이었다.
_RECENT_PRICING_RECORD = {
    "title": "AI Assistant Pricing Compared: ChatGPT vs Claude vs Gemini 2026",
    "selected_topic": "AI assistant pricing and limits comparison",
    "content_type": "ai_work_tip",
    "published": True,
    "run_at": "2026-07-20T22:54:50+00:00",
}


@pytest.fixture(autouse=True)
def _en_mode(monkeypatch):
    monkeypatch.setenv("BLOG_LANGUAGE", "en")
    yield


def _patched_history(records):
    return patch(
        "blogspot_automation.services.publish_history_service.PublishHistoryService.recent_records",
        return_value=records,
    )


def test_overlap_detected_when_two_tools_shared_with_recent_pricing_post():
    html = (
        "<p>ChatGPT Plus, Gemini for Students, and Microsoft Copilot all offer "
        "different student pricing paths in 2026.</p>"
    )
    with _patched_history([_RECENT_PRICING_RECORD]):
        result = NewsQualityGate._pricing_comparison_axis_overlap(
            title="ChatGPT Gemini Copilot Student Pricing 2026",
            html=html,
            content_type="ai_work_tip",
        )
    assert result["overlap"] is True
    assert len(result["shared_tools"]) >= 2
    assert result["matched_title"] == _RECENT_PRICING_RECORD["title"]


def test_no_overlap_when_recent_post_is_a_different_family():
    html = "<p>ChatGPT Plus and Gemini for Students both offer free tiers.</p>"
    non_pricing_record = dict(_RECENT_PRICING_RECORD)
    non_pricing_record["title"] = "How to Automate Meeting Notes With AI (2026)"
    with _patched_history([non_pricing_record]):
        result = NewsQualityGate._pricing_comparison_axis_overlap(
            title="ChatGPT Gemini Copilot Student Pricing 2026",
            html=html,
            content_type="ai_work_tip",
        )
    assert result["overlap"] is False


def test_no_overlap_when_fewer_than_two_tools_shared():
    html = "<p>ChatGPT Plus is the only paid option covered here.</p>"
    with _patched_history([_RECENT_PRICING_RECORD]):
        result = NewsQualityGate._pricing_comparison_axis_overlap(
            title="ChatGPT Plus Pricing Explained (2026)",
            html=html,
            content_type="ai_work_tip",
        )
    assert result["overlap"] is False


def test_disabled_outside_english_mode(monkeypatch):
    monkeypatch.delenv("BLOG_LANGUAGE", raising=False)
    html = "<p>ChatGPT Plus, Gemini for Students, and Copilot compared.</p>"
    with _patched_history([_RECENT_PRICING_RECORD]):
        result = NewsQualityGate._pricing_comparison_axis_overlap(
            title="ChatGPT Gemini Copilot Student Pricing 2026",
            html=html,
            content_type="ai_work_tip",
        )
    assert result["overlap"] is False


def _make_selected():
    raw = {
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
        "source_type": "evergreen_fallback",
        "click_potential_score": 10,
        "hook_angle": {"safe_title_keyword": "pricing"},
        "is_test_candidate": False,
        "publish_allowed": True,
    }
    candidate = MagicMock()
    candidate.topic = "best AI tools for students"
    candidate.category = "tech"
    candidate.summary = "summary"
    candidate.raw = raw
    selected = MagicMock()
    selected.total_score = 80
    selected.candidate = candidate
    selected.reason = "test"
    return selected


class TestQualityGatePricingAxisBlocking(unittest.TestCase):
    """게이트 통합 — 가격비교 축 중복이면 발행 모드에서 차단."""

    def test_gate_blocks_when_axis_overlap_detected(self):
        gate = NewsQualityGate()
        with patch.object(
            NewsQualityGate,
            "_pricing_comparison_axis_overlap",
            return_value={
                "overlap": True,
                "shared_tools": ["openai", "google"],
                "matched_title": _RECENT_PRICING_RECORD["title"],
            },
        ):
            result = gate.evaluate(
                selected=_make_selected(),
                selected_title="ChatGPT Gemini Copilot Student Pricing 2026",
                html="<p>ChatGPT and Gemini pricing for students.</p>",
                dry_run=False,
                news_publish_mode="publish",
            )
        self.assertTrue(
            any(
                str(b).startswith("pricing_comparison_axis_recently_published")
                for b in result["blocking_issues"]
            ),
            result["blocking_issues"],
        )
        self.assertTrue(result["pricing_comparison_axis_overlap"])

    def test_gate_does_not_block_when_no_axis_overlap(self):
        gate = NewsQualityGate()
        with patch.object(
            NewsQualityGate,
            "_pricing_comparison_axis_overlap",
            return_value={"overlap": False, "shared_tools": [], "matched_title": ""},
        ):
            result = gate.evaluate(
                selected=_make_selected(),
                selected_title="ChatGPT Gemini Copilot Student Pricing 2026",
                html="<p>ChatGPT and Gemini pricing for students.</p>",
                dry_run=False,
                news_publish_mode="publish",
            )
        self.assertFalse(
            any(
                str(b).startswith("pricing_comparison_axis_recently_published")
                for b in result["blocking_issues"]
            ),
        )


if __name__ == "__main__":
    unittest.main()
