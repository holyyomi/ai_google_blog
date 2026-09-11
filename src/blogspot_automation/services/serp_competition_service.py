"""SERP 경쟁도 판정 — 이 주제에 우리가 낄 자리가 있나.

왜 만들었나 (2026-09-11 실측):
    holyyomiai 는 68편을 발행하는 동안 구글 색인 0 · 120일 검색 노출 0 · 클릭 0
    이었다. 같은 계정의 holyteminsight 는 색인된 글이 있고 노출도 나온다.
    두 블로그의 차이는 글솜씨가 아니라 겨냥한 자리였다:

        holyteminsight(색인됨) : "lazybee lashguard loosefit bodysuit"
                                 아무도 안 쓰는 제품명, 경쟁 사실상 0, 2위
        holyyomiai(색인 0)     : "chatgpt free version limits" / "grok pricing api"
                                 openai.com·x.ai 공식 문서가 이미 답한 질문

    기존 점수 체계(news_scoring_service)는 검색량을 본다. 검색량이 큰 주제는
    그만큼 경쟁도 세다. 도메인 신뢰도가 0인 신생 블로그에서 이 정렬은 정확히
    거꾸로다. 이 파일은 그 반대편 축, 이길 수 있는가를 잰다.

핵심 판정 원리 (한 줄):
    상위 결과에 작은 사이트·개인 블로그가 섞여 있으면 신생 블로그도 낄 수 있다.
    벤더 공식 문서와 대형 테크 매체로만 채워져 있으면 못 낀다.

네트워크는 선택이다:
    assess_from_domains() 는 순수 함수라 네트워크 없이 테스트된다.
    assess() 만 Exa 를 호출한다. 키가 없거나 실패하면 차단하지 않고
    확인 불가(winnable=None)를 돌려준다 — 측정 못 한 상태로 주제를 버리면
    조용히 아무것도 못 쓰게 된다(2026-08-06 이미지게이트 사고와 같은 함정).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

EXA_SEARCH_ENDPOINT = "https://api.exa.ai/search"
_TIMEOUT_SECONDS = 20
_DEFAULT_RESULTS = 10


# ── 도메인 등급 ────────────────────────────────────────────────────────────
# 완전한 목록이 아니다. 모르는 도메인은 TIER_UNKNOWN 으로 두고 개인 블로그로
# 낙관하지 않는다. 반복해서 보이는 도메인이 생기면 여기에 추가한다.

# 벤더 공식 — 자기 제품 질문에서 이들을 이길 방법은 없다. 가장 강한 상대.
_VENDOR = frozenset({
    "openai.com", "anthropic.com", "x.ai", "mistral.ai", "cohere.com",
    "deepmind.google", "ai.google", "ai.google.dev", "gemini.google.com",
    "developers.google.com", "cloud.google.com", "support.google.com",
    "huggingface.co", "nvidia.com", "microsoft.com", "azure.microsoft.com",
    "learn.microsoft.com", "aws.amazon.com", "meta.com", "ai.meta.com",
    "perplexity.ai", "midjourney.com", "stability.ai", "runwayml.com",
    "ollama.com", "ollama.ai", "langchain.com", "openrouter.ai",
    "groq.com", "together.ai", "replicate.com", "elevenlabs.io",
})

# 대형 테크 매체 — 신생 블로그가 정면으로 못 이긴다.
_BIG_MEDIA = frozenset({
    "theverge.com", "techcrunch.com", "arstechnica.com", "wired.com",
    "zdnet.com", "cnet.com", "tomshardware.com", "tomsguide.com",
    "venturebeat.com", "businessinsider.com", "forbes.com", "reuters.com",
    "bloomberg.com", "nytimes.com", "wsj.com", "ft.com", "cnbc.com",
    "engadget.com", "digitaltrends.com", "pcmag.com", "pcworld.com",
    "techradar.com", "howtogeek.com", "makeuseof.com", "lifehacker.com",
    "zapier.com", "androidauthority.com", "9to5google.com", "9to5mac.com",
    "theinformation.com", "axios.com", "semafor.com", "techmeme.com",
})

# 대형 플랫폼·커뮤니티 — 못 이기지만 벤더·대형매체보다는 약한 상대.
# 이들이 상위에 있다는 건 권위 있는 문서가 아직 없다는 신호이기도 하다.
_BIG_PLATFORM = frozenset({
    "reddit.com", "youtube.com", "wikipedia.org", "quora.com",
    "stackoverflow.com", "stackexchange.com", "superuser.com",
    "serverfault.com", "linkedin.com", "x.com", "twitter.com",
    "facebook.com", "discord.com", "community.openai.com",
    "discuss.huggingface.co", "news.ycombinator.com", "producthunt.com",
    "g2.com", "capterra.com", "trustpilot.com",
})

# 개인·소규모 퍼블리셔가 실제로 상위에 있는 자리 — 우리도 낄 수 있다는 신호.
_PERSONAL_BLOG_HOSTS = frozenset({
    "medium.com", "dev.to", "hashnode.com", "substack.com",
})
_PERSONAL_BLOG_SUFFIXES = (
    ".blogspot.com", ".wordpress.com", ".substack.com", ".medium.com",
    ".github.io", ".hashnode.dev", ".netlify.app", ".vercel.app",
    ".tistory.com", ".ghost.io", ".bearblog.dev",
)

TIER_VENDOR = "vendor_official"
TIER_MEDIA = "big_media"
TIER_PLATFORM = "big_platform"
TIER_BLOG = "small_publisher"
TIER_UNKNOWN = "unknown"

# 각 등급이 우리가 낄 자리에 주는 영향. 작은 퍼블리셔만 양수다.
#
# TIER_UNKNOWN 은 0(중립)이다. 2026-09-11 리허설 실측에서 후보 6개가 전부
# not winnable 로 걸려 전멸 방지가 발동했고, 그중에는 상위가 거의 전부
# unknown 인 자리(= 벤더도 대형매체도 없는, 우리가 낄 수 있는 자리)까지
# 섞여 있었다. unknown 에 음수를 주면 **대형 플레이어가 한 명도 없는 자리도
# 38점으로 탈락**한다(10개 전부 unknown 일 때). 모르는 도메인을 개인 블로그로
# 낙관하지도(+), 대형 사업자로 비관하지도(-) 않는 게 맞다.
_TIER_WEIGHT = {
    TIER_VENDOR: -12,
    TIER_MEDIA: -8,
    TIER_PLATFORM: -6,
    TIER_UNKNOWN: 0,
    TIER_BLOG: +14,
}

# 통과 기준. 근거 있는 값이 아니다 — 벤더·대형매체로만 채워진 자리는 확실히
# 막고, 작은 퍼블리셔가 둘 이상 보이는 자리는 통과시키는 출발점이다.
# 실제 색인·노출 데이터가 쌓이면 다시 정한다.
MIN_WINNABLE_SCORE = 40
MIN_RESULTS_TO_JUDGE = 5


def _matches(host: str, known: frozenset[str]) -> bool:
    """호스트가 목록의 도메인이거나 그 서브도메인이면 참.

    서브도메인은 같은 주체다 — help.openai.com·platform.openai.com 을 따로
    적지 않아도 openai.com 하나로 잡힌다.
    """
    return any(host == d or host.endswith("." + d) for d in known)


def classify_domain(host: str) -> str:
    """호스트 하나를 등급으로. 모르면 TIER_UNKNOWN — 개인 블로그로 낙관하지 않는다."""
    h = (host or "").strip().lower()
    if not h:
        return TIER_UNKNOWN
    if h.startswith("www."):
        h = h[4:]
    if h.endswith(_PERSONAL_BLOG_SUFFIXES) or _matches(h, _PERSONAL_BLOG_HOSTS):
        return TIER_BLOG
    if _matches(h, _VENDOR):
        return TIER_VENDOR
    if _matches(h, _BIG_MEDIA):
        return TIER_MEDIA
    if _matches(h, _BIG_PLATFORM):
        return TIER_PLATFORM
    # docs./help./support./developer. 서브도메인은 대개 벤더 공식 문서다.
    if re.match(r"^(docs|help|support|developer|developers|platform)\.", h):
        return TIER_VENDOR
    return TIER_UNKNOWN


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


@dataclass
class CompetitionVerdict:
    """판정 결과.

    winnable=None 은 확인 불가다. False(못 이긴다)와 절대 섞지 않는다.
    """

    topic: str
    winnable: bool | None
    score: int                      # 0~100. 높을수록 낄 자리가 있다
    reason: str
    tier_counts: dict[str, int] = field(default_factory=dict)
    blog_in_top5: int = 0
    checked_results: int = 0
    domains: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "winnable": self.winnable,
            "competition_score": self.score,
            "reason": self.reason,
            "tier_counts": dict(self.tier_counts),
            "blog_in_top5": self.blog_in_top5,
            "checked_results": self.checked_results,
            "domains": list(self.domains),
            "error": self.error,
        }


def assess_from_domains(topic: str, urls: list[str]) -> CompetitionVerdict:
    """순수 함수 — URL 목록만으로 판정한다. 네트워크를 쓰지 않아 테스트가 쉽다."""
    hosts = [h for h in (_host_of(u) for u in (urls or [])) if h]
    if len(hosts) < MIN_RESULTS_TO_JUDGE:
        return CompetitionVerdict(
            topic=topic, winnable=None, score=0,
            reason=f"results={len(hosts)} < {MIN_RESULTS_TO_JUDGE} - not judged",
            checked_results=len(hosts), domains=hosts,
        )

    tiers = [classify_domain(h) for h in hosts]
    counts: dict[str, int] = {}
    for tier in tiers:
        counts[tier] = counts.get(tier, 0) + 1

    # 50점에서 시작해 등급별 가중치를 더한다. 상위 5개는 1.5배 — 1페이지 위쪽이
    # 실제 클릭을 가져가는 자리라 더 무겁게 본다.
    score = 50.0
    for index, tier in enumerate(tiers):
        score += _TIER_WEIGHT.get(tier, -1) * (1.5 if index < 5 else 1.0)
    score_int = max(0, min(100, round(score)))

    blog_top5 = sum(1 for tier in tiers[:5] if tier == TIER_BLOG)
    blog_total = counts.get(TIER_BLOG, 0)

    if score_int >= MIN_WINNABLE_SCORE:
        winnable = True
        reason = (
            f"top{len(hosts)}: small publishers {blog_total}"
            + (f" (top5: {blog_top5})" if blog_top5 else "")
            + " - a new blog has room here"
        )
    else:
        occupied = " / ".join(
            f"{tier} {count}"
            for tier, count in sorted(counts.items(), key=lambda kv: -kv[1])
            if tier != TIER_BLOG and count
        )
        winnable = False
        reason = (
            f"top{len(hosts)} held by {occupied}; small publishers {blog_total}"
            " - a zero-authority site cannot win this query"
        )

    return CompetitionVerdict(
        topic=topic, winnable=winnable, score=score_int, reason=reason,
        tier_counts=counts, blog_in_top5=blog_top5,
        checked_results=len(hosts), domains=hosts,
    )


@dataclass
class SerpCompetitionConfig:
    exa_api_key: str = ""
    enabled: bool = True
    num_results: int = _DEFAULT_RESULTS
    timeout_seconds: int = _TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "SerpCompetitionConfig":
        flag = (os.getenv("ENABLE_SERP_COMPETITION", "true") or "").strip().lower()
        try:
            results = int(os.getenv("SERP_COMPETITION_RESULTS", "") or _DEFAULT_RESULTS)
        except ValueError:
            results = _DEFAULT_RESULTS
        return cls(
            exa_api_key=(os.getenv("EXA_API_KEY", "") or "").strip(),
            enabled=flag in {"1", "true", "yes", "on"},
            num_results=max(5, min(25, results)),
        )


class SerpCompetitionService:
    """Exa 로 상위 결과를 떠서 경쟁도를 판정한다.

    Exa 를 쓰는 이유: 이 워크스페이스에서 실제로 살아 있는 검색 API 가 Exa 뿐이다
    (Google Custom Search 는 403, 2026-09-11 재확인). Google SERP 직접 스크래핑은
    하지 않는다 — 약관 위반이고 잘 깨진다.
    Exa 결과는 구글 SERP 와 완전히 같지 않다. 그래서 이 판정은 정확한 순위가
    아니라 이 주제를 누가 점유하고 있나를 보는 용도로만 쓴다.
    """

    def __init__(
        self,
        config: SerpCompetitionConfig | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or SerpCompetitionConfig.from_env()
        self._session = session or requests.Session()
        self._cache: dict[str, CompetitionVerdict] = {}

    def assess(self, topic: str) -> CompetitionVerdict:
        key = (topic or "").strip()
        if not key:
            return CompetitionVerdict(topic=topic, winnable=None, score=0, reason="empty topic")
        if key in self._cache:
            return self._cache[key]

        if not self.config.enabled or not self.config.exa_api_key:
            verdict = CompetitionVerdict(
                topic=key, winnable=None, score=0,
                reason="EXA_API_KEY missing or disabled - competition unchecked, topic not blocked",
                error="exa_unavailable",
            )
            self._cache[key] = verdict
            return verdict

        try:
            response = self._session.post(
                EXA_SEARCH_ENDPOINT,
                headers={"Content-Type": "application/json", "x-api-key": self.config.exa_api_key},
                json={"query": key, "numResults": self.config.num_results, "type": "keyword"},
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            urls = [str(item.get("url") or "") for item in (payload.get("results") or [])]
            verdict = assess_from_domains(key, urls)
        except Exception as exc:  # noqa: BLE001 - 측정 실패로 발행을 멈추지 않는다.
            logger.warning("serp_competition: assess failed for %r (%s)", key[:60], exc)
            verdict = CompetitionVerdict(
                topic=key, winnable=None, score=0,
                reason=f"lookup failed ({type(exc).__name__}) - topic not blocked",
                error=type(exc).__name__,
            )
        self._cache[key] = verdict
        return verdict
