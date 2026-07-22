"""SOURCE_TRUST 인용 신뢰도 정렬 테스트 (2026-07-22).

2026-07-21 라이브 실측: Sources 블록이 GitHub 트래커 레포 2개 + SEO
애그리게이터 2개로 채워졌다(공식 출처 0). 블록은 앞 4개만 쓰므로 공식 벤더
도메인이 앞으로 오고, 코드 레포 링크는 다른 출처가 있으면 빠져야 한다.
"""
from __future__ import annotations

from blogspot_automation.services.llm_content_service import LlmContentService


def _c(name: str, url: str) -> dict[str, str]:
    return {"name": name, "url": url}


def test_repo_links_dropped_when_alternatives_exist():
    citations = [
        _c("tracker", "https://github.com/CloudAxisAi/ai-pricing-comparison"),
        _c("aggregator", "https://aipricecompare.org/"),
        _c("openai pricing", "https://openai.com/chatgpt/pricing/"),
    ]
    ranked = LlmContentService._prefer_trustworthy_citations(citations)
    urls = [c["url"] for c in ranked]
    assert "https://github.com/CloudAxisAi/ai-pricing-comparison" not in urls
    assert urls[0] == "https://openai.com/chatgpt/pricing/"


def test_github_product_pages_survive():
    citations = [
        _c("copilot", "https://github.com/features/copilot"),
        _c("aggregator", "https://aipricecompare.org/"),
    ]
    ranked = LlmContentService._prefer_trustworthy_citations(citations)
    urls = [c["url"] for c in ranked]
    assert "https://github.com/features/copilot" in urls
    assert urls[0] == "https://github.com/features/copilot"


def test_all_repo_citations_kept_as_last_resort():
    citations = [
        _c("tracker a", "https://github.com/owner-a/repo-a"),
        _c("tracker b", "https://github.com/owner-b/repo-b"),
    ]
    ranked = LlmContentService._prefer_trustworthy_citations(citations)
    assert len(ranked) == 2


def test_official_domains_ordered_first():
    citations = [
        _c("seo blog", "https://someseoblog.example.com/pricing"),
        _c("anthropic", "https://www.anthropic.com/pricing"),
        _c("microsoft", "https://microsoft.com/copilot"),
    ]
    ranked = LlmContentService._prefer_trustworthy_citations(citations)
    urls = [c["url"] for c in ranked]
    assert urls[0] == "https://www.anthropic.com/pricing"
    assert urls[1] == "https://microsoft.com/copilot"
    assert urls[2] == "https://someseoblog.example.com/pricing"
