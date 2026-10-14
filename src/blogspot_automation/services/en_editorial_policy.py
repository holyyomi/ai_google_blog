"""영어 블로그 편집 정책 스위치 + 발행 직전 최종 HTML 품질 게이트 (2026-10-14).

왜 만들었나 — 2026-10-14 진단(라이브 71편):
- 모든 글이 같은 골격이었다. 최근 15편 전부 후처리 블록 6개가 같은 순서로 붙었고
  본문의 35~50%가 그 덧붙임이었다. 덧붙인 블록은 본문 문장을 동의어로 바꿔 다시
  말했고, 블록을 걷어내면 문장 중복이 0이 된다(10-08·10-13·10-14 실측: 블록 포함
  중복문장 11개 → 블록 제거 0개).
- AdSense 정책("자동 생성 콘텐츠는 수동 검토·큐레이션 없이 광고 금지", "unique and
  relevant content")과 Search 스팸정책(scaled content abuse)에 정면으로 걸리는 모양이다.

그래서 영어 모드의 기본값을 바꾼다.
- 후처리 블록 INTENT_ANSWER_BLOCK / ISSUE_CONTEXT_BLOCK / AI_CITATION_SUMMARY /
  CONFIRMED_VS_CHECK_NEEDED_BLOCK 은 **기본 off**. `EN_LEGACY_GEO_BLOCKS=on` 으로만 되살린다.
- 한국어 경로(`BLOG_LANGUAGE` 기본 ko)는 이 스위치와 무관하게 예전 그대로다.

최종 HTML 게이트(`audit_final_publish_html`)는 후처리가 다 끝난 **발행 직전 HTML** 을 본다.
(a) 40자 이상 정규화 문장이 한 글 안에 2회 이상 → 차단
(b) 공식 출처(제품 회사 도메인·공식 docs·help center·공식 블로그·논문) 0개 → 차단
    GitHub 저장소·포럼·커뮤니티만 있으면 0개로 센다.
(c) 본문 숫자 토큰(가격·퍼센트·요청/메시지 수·용량)이 출처 자료 텍스트에 없으면 → 차단
    (재작성 1회는 llm_content_service 의 출처 대조 재작성이 이미 한다)

눈금(tests/test_final_publish_quality_gate.py): 공식 출처를 인용한 10-08 Perplexity×Amex,
10-13 ChatGPT vs Codex 글(블록 제거본)은 통과, 10-14 Grok vs ChatGPT(GitHub 2개만 출처,
"roughly 200 messages per day" 무출처 수치)는 차단.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from html import unescape
from urllib.parse import urlparse

from blogspot_automation.services.blog_language import is_english_mode

__all__ = [
    "LEAN_DISABLED_BLOCK_IDS",
    "legacy_geo_blocks_enabled",
    "lean_en_mode",
    "final_quality_gate_mode",
    "ai_disclosure_text",
    "classify_source_url",
    "official_source_urls",
    "duplicate_sentences",
    "unsourced_numbers",
    "audit_final_publish_html",
]

_TRUE = {"1", "true", "yes", "on"}

# 영어 모드에서 기본으로 끄는 후처리 블록.
LEAN_DISABLED_BLOCK_IDS: tuple[str, ...] = (
    "INTENT_ANSWER_BLOCK",
    "ISSUE_CONTEXT_BLOCK",
    "AI_CITATION_SUMMARY",
    "CONFIRMED_VS_CHECK_NEEDED_BLOCK",
)


def legacy_geo_blocks_enabled() -> bool:
    """후처리 GEO 블록을 예전처럼 붙이는가.

    한국어 모드는 항상 True(동작 불변). 영어 모드는 `EN_LEGACY_GEO_BLOCKS` 가
    켜져 있을 때만 True — 기본 off.
    """
    if not is_english_mode():
        return True
    return (os.getenv("EN_LEGACY_GEO_BLOCKS", "") or "").strip().lower() in _TRUE


def lean_en_mode() -> bool:
    """영어 모드 + 후처리 블록 off (새 기본값)."""
    return is_english_mode() and not legacy_geo_blocks_enabled()


def final_quality_gate_mode() -> str:
    """FINAL_QUALITY_GATE: block(기본) | observe | off."""
    mode = (os.getenv("FINAL_QUALITY_GATE", "block") or "").strip().lower()
    return mode if mode in {"block", "observe", "off"} else "block"


# ── 공개 문구 ─────────────────────────────────────────────────────────────────
_DISCLOSURE_AUTO = "Drafted with AI assistance from the official sources linked above."
_DISCLOSURE_REVIEWED = (
    "Drafted with AI assistance from the official sources linked above, "
    "then reviewed before publishing."
)


def ai_disclosure_text() -> str:
    """글 끝 공개 문구. 사람 검토 문구는 초안 저장+사람 검토 모드일 때만.

    `AI_DISCLOSURE_MODE`: reviewed | auto | off. 지정이 없으면 발행 모드로 정한다 —
    `NEWS_PUBLISH_AS_DRAFT=true`(Blogger 초안까지만, 사람이 검토 후 발행)면 reviewed,
    그 밖(자동 발행)이면 auto. 사람이 실제로 검토하지 않는 경로에서 "reviewed" 를
    쓰면 그 자체가 거짓 표기다.
    """
    mode = (os.getenv("AI_DISCLOSURE_MODE", "") or "").strip().lower()
    if mode == "off":
        return ""
    if mode not in {"reviewed", "auto"}:
        as_draft = (os.getenv("NEWS_PUBLISH_AS_DRAFT", "") or "").strip().lower() in _TRUE
        mode = "reviewed" if as_draft else "auto"
    return _DISCLOSURE_REVIEWED if mode == "reviewed" else _DISCLOSURE_AUTO


# ── (b) 출처 분류 ─────────────────────────────────────────────────────────────
# 제품 회사(벤더) 루트 도메인. 이 도메인과 그 하위 도메인은 공식으로 본다 —
# 단 아래 커뮤니티 하위 도메인(community./forum. 등)은 먼저 제외한다.
_VENDOR_DOMAINS: tuple[str, ...] = (
    "openai.com", "chatgpt.com", "anthropic.com", "claude.ai", "claude.com",
    "google.com", "blog.google", "googleblog.com", "google.dev", "ai.google.dev",
    "deepmind.google", "deepmind.com", "gemini.google", "withgoogle.com",
    "microsoft.com", "azure.com", "github.blog", "docs.github.com", "githubnext.com",
    "x.ai", "perplexity.ai", "meta.com", "llama.com", "mistral.ai", "cohere.com",
    "deepseek.com", "apple.com", "amazon.com", "aws.amazon.com", "nvidia.com",
    "cursor.com", "notion.so", "notion.com", "midjourney.com", "elevenlabs.io",
    "runwayml.com", "stability.ai", "huggingface.co", "ollama.com", "adobe.com",
    "samsung.com", "americanexpress.com", "slack.com", "salesforce.com",
    "zoom.us", "canva.com", "grammarly.com", "jasper.ai", "character.ai",
    "suno.com", "pika.art", "lumalabs.ai", "replit.com", "vercel.com",
    "langchain.com", "openrouter.ai", "groq.com", "cerebras.ai", "qwenlm.ai",
    "alibabacloud.com", "moonshot.ai", "baidu.com", "tesla.com", "ibm.com",
    "intel.com", "amd.com", "qualcomm.com", "databricks.com", "snowflake.com",
)
# 논문·표준·공공 출처.
_PAPER_DOMAINS: tuple[str, ...] = (
    "arxiv.org", "openreview.net", "aclanthology.org", "doi.org", "acm.org",
    "ieee.org", "nature.com", "science.org", "neurips.cc", "nist.gov",
)
# 커뮤니티·코드저장소·UGC — 공식으로 세지 않는다(공식 도메인 하위여도).
_COMMUNITY_DOMAINS: tuple[str, ...] = (
    "github.com", "gist.github.com", "gitlab.com", "reddit.com", "news.ycombinator.com",
    "stackoverflow.com", "stackexchange.com", "medium.com", "substack.com",
    "x.com", "twitter.com", "youtube.com", "youtu.be", "quora.com", "dev.to",
    "linkedin.com", "facebook.com", "discord.com", "discord.gg", "hashnode.dev",
    "producthunt.com", "tiktok.com", "threads.net",
)
_COMMUNITY_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "community.", "forum.", "forums.", "discuss.", "discourse.", "answers.",
    "techcommunity.", "users.", "groups.",
)
# 하위 도메인 이름만으로 공식 문서로 보는 접두사(벤더 목록에 없는 회사용).
_OFFICIAL_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "docs.", "help.", "support.", "developer.", "developers.", "platform.",
    "learn.", "status.",
)


def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _domain_match(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _extra_official_domains() -> tuple[str, ...]:
    raw = os.getenv("OFFICIAL_SOURCE_EXTRA_DOMAINS", "") or ""
    return tuple(d.strip().lower() for d in raw.split(",") if d.strip())


def classify_source_url(url: str) -> str:
    """URL 을 official | community | other 로 분류한다."""
    host = _host(url)
    if not host:
        return "other"
    if host.startswith(_COMMUNITY_SUBDOMAIN_PREFIXES) or _domain_match(host, _COMMUNITY_DOMAINS):
        # docs.github.com 같은 공식 문서는 커뮤니티 루트보다 먼저 본다.
        if _domain_match(host, ("docs.github.com", "github.blog")):
            return "official"
        return "community"
    if _domain_match(host, _VENDOR_DOMAINS + _PAPER_DOMAINS + _extra_official_domains()):
        return "official"
    if host.endswith(".gov") or host.endswith(".edu"):
        return "official"
    if host.startswith(_OFFICIAL_SUBDOMAIN_PREFIXES):
        return "official"
    return "other"


_OWN_HOST_MARKERS = ("holyyomiai.blogspot.com", "blogger.com", "blogspot.com")


def _external_hrefs(html: str) -> list[str]:
    out: list[str] = []
    for href in re.findall(r"<a\b[^>]*\bhref=[\"'](https?://[^\"']+)[\"']", html or "", flags=re.I):
        host = _host(href)
        if not host or any(host == m or host.endswith("." + m) for m in _OWN_HOST_MARKERS):
            continue
        out.append(unescape(href))
    return out


def official_source_urls(html: str, citations: list[dict] | None = None) -> list[str]:
    """최종 HTML 의 외부 링크(+전달된 인용) 중 공식 출처 URL 목록(중복 제거)."""
    urls = _external_hrefs(html)
    for c in citations or []:
        if isinstance(c, dict) and str(c.get("url") or "").startswith(("http://", "https://")):
            # 인용 목록은 SOURCE_TRUST_BLOCK 에 실제로 렌더된 것만 의미가 있다 —
            # 렌더되지 않은 인용으로 통과시키지 않는다.
            if str(c.get("url")) in (html or ""):
                urls.append(str(c.get("url")))
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        if classify_source_url(u) == "official":
            out.append(u)
    return out


# ── (a) 문장 중복 ─────────────────────────────────────────────────────────────
def _visible_text_with_breaks(html: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    # 블록 경계마다 문장 끝을 넣어, 표 셀·목록 항목이 앞뒤 문장과 붙지 않게 한다.
    text = re.sub(r"</(?:p|li|h[1-6]|td|th|div|section|article|figcaption)>", ". ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", ". ", text, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def _normalized_sentences(html: str, *, min_chars: int = 40) -> list[str]:
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", _visible_text_with_breaks(html)):
        norm = re.sub(r"[^a-z0-9$%가-힣]+", " ", sentence.lower()).strip()
        if len(norm) >= min_chars:
            out.append(norm)
    return out


def duplicate_sentences(html: str, *, min_chars: int = 40, min_count: int = 2) -> dict[str, int]:
    """정규화 문장 → 등장 횟수 (min_count 이상만)."""
    counts = Counter(_normalized_sentences(html, min_chars=min_chars))
    return {s: n for s, n in counts.items() if n >= min_count}


# ── (c) 무출처 숫자 ───────────────────────────────────────────────────────────
def unsourced_numbers(html: str, source_text: str) -> list[str]:
    """본문 숫자 주장(가격·퍼센트·요청/메시지·용량) 중 출처 텍스트에 없는 것.

    판정 규칙(정규화·연도 면제)은 source_grounding_service 와 같다 — 생성 단계와
    발행 단계가 같은 기준을 봐야 "생성 땐 통과, 발행 땐 차단" 같은 엇갈림이 없다.
    출처 텍스트가 비어 있으면 숫자 주장 전부가 무출처다.
    """
    from blogspot_automation.services.source_grounding_service import (
        _NUMERIC_CLAIM_RE,
        _NUMERIC_SAFE_RE,
        _facts_number_pool,
        _normalize_number,
        _visible_text,
    )

    text = _visible_text(html)
    pool = _facts_number_pool(source_text or "")
    out: list[str] = []
    seen: set[str] = set()
    for match in _NUMERIC_CLAIM_RE.finditer(text):
        token = match.group(0).strip()
        norm = _normalize_number(token)
        bare = re.match(r"^\d+(?:\.\d+)?", norm)
        bare_value = bare.group(0) if bare else ""
        if not bare_value or _NUMERIC_SAFE_RE.match(bare_value):
            continue
        if norm in pool or bare_value in pool or norm in seen:
            continue
        seen.add(norm)
        out.append(token)
    return out


def audit_final_publish_html(
    html: str,
    *,
    source_text: str = "",
    citations: list[dict] | None = None,
) -> dict:
    """발행 직전 HTML 최종 게이트. 반환: {passed, mode, issues, details}.

    mode=observe 면 issues 를 기록만 하고 passed=True, off 면 검사하지 않는다.
    """
    mode = final_quality_gate_mode()
    if mode == "off":
        return {"passed": True, "mode": mode, "issues": [], "details": {}}

    issues: list[str] = []
    dups = duplicate_sentences(html)
    if dups:
        issues.append(f"duplicate_sentences:{len(dups)}")
    official = official_source_urls(html, citations)
    all_external = _external_hrefs(html)
    if not official:
        issues.append("no_official_source")
    numbers = unsourced_numbers(html, source_text)
    issues.extend(f"unsourced_number:{n}" for n in numbers[:8])

    details = {
        "duplicate_sentences": [
            {"count": n, "sentence": s[:160]} for s, n in sorted(dups.items(), key=lambda x: -x[1])[:8]
        ],
        "official_source_urls": official[:10],
        "external_source_hosts": sorted({_host(u) for u in all_external})[:20],
        "unsourced_numbers": numbers[:20],
        "source_text_chars": len(source_text or ""),
    }
    passed = not issues or mode == "observe"
    return {"passed": passed, "mode": mode, "issues": issues, "details": details}
