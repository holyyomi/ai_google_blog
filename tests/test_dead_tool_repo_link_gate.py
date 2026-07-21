from __future__ import annotations

import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from blogspot_automation.services.news_quality_gate import NewsQualityGate


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_urlopen_factory(status_by_url: dict[str, int]):
    def _fake_urlopen(req, timeout=None):
        url = req.full_url
        if url not in status_by_url:
            raise AssertionError(f"unexpected url checked: {url}")
        status = status_by_url[url]
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "error", {}, None)
        return _FakeResponse(status)

    return _fake_urlopen


class TestDeadToolRepoLinks(unittest.TestCase):
    """2026-07-21 라이브 실측 재현: 존재하지 않는 GitHub 저장소
    (PCSAdmin081/keepr-etsy-ops, 실제 404)를 추천 툴로 링크한 사고."""

    def test_detects_404_repo(self):
        html = (
            '<p>Try <a href="https://github.com/PCSAdmin081/keepr-etsy-ops">keepr-etsy-ops</a> '
            "for automated compliance.</p>"
        )
        fake = _fake_urlopen_factory({"https://github.com/PCSAdmin081/keepr-etsy-ops": 404})
        with patch.object(urllib.request, "urlopen", fake):
            dead = NewsQualityGate._dead_tool_repo_links(html)
        self.assertEqual(dead, ["PCSAdmin081/keepr-etsy-ops"])

    def test_live_repo_not_flagged(self):
        html = '<p>See <a href="https://github.com/abutun/etsy-seo-optimizer">etsy-seo-optimizer</a>.</p>'
        fake = _fake_urlopen_factory({"https://github.com/abutun/etsy-seo-optimizer": 200})
        with patch.object(urllib.request, "urlopen", fake):
            dead = NewsQualityGate._dead_tool_repo_links(html)
        self.assertEqual(dead, [])

    def test_network_failure_is_non_blocking(self):
        html = '<p><a href="https://github.com/someone/some-repo">some-repo</a></p>'

        def _raise(req, timeout=None):
            raise TimeoutError("network unreachable")

        with patch.object(urllib.request, "urlopen", _raise):
            dead = NewsQualityGate._dead_tool_repo_links(html)
        self.assertEqual(dead, [])

    def test_known_org_root_links_skipped(self):
        html = (
            '<p><a href="https://github.com/anthropics/claude-code">Claude Code</a> and '
            '<a href="https://github.com/openai/openai-python">openai-python</a></p>'
        )
        with patch.object(urllib.request, "urlopen", MagicMock(side_effect=AssertionError("should not be called"))):
            dead = NewsQualityGate._dead_tool_repo_links(html)
        self.assertEqual(dead, [])

    def test_no_github_links_returns_empty_without_network_calls(self):
        html = "<p>No repo links here, just prose about ChatGPT pricing.</p>"
        with patch.object(urllib.request, "urlopen", MagicMock(side_effect=AssertionError("should not be called"))):
            dead = NewsQualityGate._dead_tool_repo_links(html)
        self.assertEqual(dead, [])


def _make_selected():
    raw = {
        "topic_group": "ai_work",
        "content_angle": {"content_type": "ai_work_tip"},
        "source_type": "evergreen_fallback",
        "click_potential_score": 10,
        "hook_angle": {"safe_title_keyword": "tools"},
        "is_test_candidate": False,
        "publish_allowed": True,
    }
    candidate = MagicMock()
    candidate.topic = "best AI tools for Etsy sellers"
    candidate.category = "tech"
    candidate.summary = "summary"
    candidate.raw = raw
    selected = MagicMock()
    selected.total_score = 80
    selected.candidate = candidate
    selected.reason = "test"
    return selected


class TestQualityGateDeadToolLinkBlocking(unittest.TestCase):
    """게이트 통합 — 존재하지 않는 툴 저장소 링크면 발행 모드에서 차단."""

    def test_gate_blocks_when_dead_link_detected(self):
        gate = NewsQualityGate()
        with patch.object(
            NewsQualityGate, "_dead_tool_repo_links", return_value=["PCSAdmin081/keepr-etsy-ops"]
        ):
            result = gate.evaluate(
                selected=_make_selected(),
                selected_title="Best AI Tools for Etsy Sellers 2026",
                html="<p>Etsy AI tools comparison.</p>",
                dry_run=False,
                news_publish_mode="publish",
            )
        self.assertTrue(
            any(str(b).startswith("nonexistent_tool_repo_linked") for b in result["blocking_issues"]),
            result["blocking_issues"],
        )
        self.assertEqual(result["dead_tool_repo_links"], ["PCSAdmin081/keepr-etsy-ops"])

    def test_gate_does_not_block_when_no_dead_links(self):
        gate = NewsQualityGate()
        with patch.object(NewsQualityGate, "_dead_tool_repo_links", return_value=[]):
            result = gate.evaluate(
                selected=_make_selected(),
                selected_title="Best AI Tools for Etsy Sellers 2026",
                html="<p>Etsy AI tools comparison.</p>",
                dry_run=False,
                news_publish_mode="publish",
            )
        self.assertFalse(
            any(str(b).startswith("nonexistent_tool_repo_linked") for b in result["blocking_issues"]),
        )


if __name__ == "__main__":
    unittest.main()
