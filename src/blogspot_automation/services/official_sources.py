"""Pattern-aware official authority source mapping.

Each golden pattern is mapped to a tuple of authoritative Korean public/regulator
URLs so that every published article can carry verifiable outbound links.
Used by golden_article_preview_service to auto-inject a links block into
the source_trust_box section.

Verified URLs only (no guessing). Patterns without a clear authority are
mapped to empty tuples so the renderer falls back to plain text.
"""
from __future__ import annotations

from typing import Iterable


_PATTERN_OFFICIAL_SOURCES: dict[str, tuple[dict[str, str], ...]] = {
    "tax_refund_hometax_check": (
        {"name": "홈택스", "url": "https://www.hometax.go.kr"},
        {"name": "국세청", "url": "https://www.nts.go.kr"},
        {"name": "손택스 (모바일)", "url": "https://m.hometax.go.kr"},
    ),
    "policy_deadline_support": (
        {"name": "정부24", "url": "https://www.gov.kr"},
        {"name": "복지로", "url": "https://www.bokjiro.go.kr"},
        {"name": "보조금24", "url": "https://www.gov.kr/portal/service/subsidy"},
    ),
    "delivery_money_checklist": (
        {"name": "공정거래위원회", "url": "https://www.ftc.go.kr"},
        {"name": "한국소비자원", "url": "https://www.kca.go.kr"},
    ),
    "consumer_warning_refund": (
        {"name": "한국소비자원 1372", "url": "https://www.kca.go.kr"},
        {"name": "공정거래위원회", "url": "https://www.ftc.go.kr"},
        {"name": "금융감독원 (금융 분쟁)", "url": "https://www.fss.or.kr"},
    ),
    "platform_change_service_update": (
        {"name": "방송통신위원회", "url": "https://www.kcc.go.kr"},
        {"name": "한국소비자원", "url": "https://www.kca.go.kr"},
    ),
    "corporate_issue_decode": (
        {"name": "전자공시시스템 (DART)", "url": "https://dart.fss.or.kr"},
        {"name": "한국거래소 KIND", "url": "https://kind.krx.co.kr"},
    ),
    "viral_ott_reaction_decode": (),
    "ai_work_time_savings": (),
    "ai_tool_comparison": (),
    "ai_automation_workflow": (),
}


def get_official_sources_for_pattern(pattern_id: str) -> tuple[dict[str, str], ...]:
    """Return verified authority sources for a given pattern_id.

    Empty tuple means the pattern has no fixed authority and the renderer
    should fall back to the existing source_trust_box text without auto-injected links.
    """
    return _PATTERN_OFFICIAL_SOURCES.get(pattern_id, ())


def render_official_sources_html(sources: Iterable[dict[str, str]]) -> str:
    """Render a small ul of clickable authority links.

    Returns empty string when no sources are provided so callers can simply
    concatenate the result without conditional logic.
    """
    items = []
    for s in sources:
        name = (s.get("name") or "").strip()
        url = (s.get("url") or "").strip()
        if not name or not url:
            continue
        items.append(
            f'      <li><a href="{url}" rel="noopener nofollow" target="_blank">{name}</a></li>'
        )
    if not items:
        return ""
    body = "\n".join(items)
    return (
        '\n    <p class="source-trust-links-label"><strong>공식 출처</strong></p>\n'
        '    <ul class="source-trust-links">\n'
        f'{body}\n'
        '    </ul>'
    )
