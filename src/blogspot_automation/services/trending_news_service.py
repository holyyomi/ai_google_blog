"""TrendingNewsService — 네이버 뉴스 인기 기사 페이지에서 실제 클릭 트렌딩 수집.

기존 IssueDiscoveryService(Google News RSS broad scan + entity 추출)와 보완 관계.
- IssueDiscoveryService: 추정 buzz(source_count). 한국 뉴스 broad scan
- TrendingNewsService: **실제 클릭 데이터**. 네이버 뉴스 popularDay 페이지

페이지: https://news.naver.com/main/ranking/popularDay.naver
- 약 84개 언론사 × 5개 기사 = ~420 기사 (분야 통합 일일 인기 랭킹)
- 동일 사건이 여러 언론사에서 등장 = 진짜 트렌딩 신호
- 각 기사 = 네이버에서 실제로 가장 많이 클릭된 글

이 서비스는 NewsCandidate 리스트만 반환. 본문 크롤링은 안 함 (LLM이 자체 생성).
news_pipeline.py가 결과를 candidates 앞에 prepend해서 우선 후보화한다.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from collections import Counter
from typing import Any
from urllib.error import HTTPError, URLError

from blogspot_automation.models.news_models import NewsCandidate

logger = logging.getLogger(__name__)

_RANKING_URL = "https://news.naver.com/main/ranking/popularDay.naver"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_TIMEOUT = 20

# 사용자가 명시적으로 싫어하는 주제(대기업 노사·공시·실적·총수) → 후순위.
# memory: feedback_blogspot_content_preferences 참고.
_DEPRIORITIZED_CORPORATE_TOKENS = frozenset({
    # 대기업명 (substring 매칭)
    "삼성", "현대차", "현대자동차", "기아", "LG에너지", "LG화학", "SK하이닉스",
    "SK텔레콤", "SKT", "LG유플", "포스코", "한화", "롯데", "신세계", "이마트",
    "쿠팡", "카카오", "네이버", "넷마블", "엔씨소프트", "엔씨", "KT",
    # 기업 총수·경영진
    "이재용", "정의선", "최태원", "구광모", "신동빈", "정용진", "정몽구",
    "이부진", "이서현", "허창수", "조원태",
    # 기업 운영·노사 키워드
    "노조", "노사", "임금협상", "임단협", "교섭", "성과급", "총파업", "주주총회",
    "공시", "실적", "분기실적", "영업이익", "분사", "합병", "인수", "M&A",
    "사측", "이사회", "대표이사", "주주", "투자자",
})


def _is_corporate_issue(title: str, tokens: list[str]) -> bool:
    """제목/토큰에 대기업 노사·공시 관련 키워드가 있으면 corporate로 분류."""
    text = title + " " + " ".join(tokens)
    return any(kw in text for kw in _DEPRIORITIZED_CORPORATE_TOKENS)

# 한국어 stop words / 의미 약한 토큰 (cluster 키 추출 시 제외)
_STOP_TOKENS = frozenset({
    "있다", "없다", "한다", "했다", "된다", "됐다", "위해", "통해", "대해",
    "오늘", "어제", "내일", "올해", "내년", "지금", "현재", "이번",
    "관련", "정도", "정말", "역시", "결국", "그리고", "그러나", "하지만",
    "또한", "이미", "처음", "최근", "다시", "또", "그", "이", "저", "것",
})


def _extract_significant_tokens(title: str) -> list[str]:
    """제목에서 명사/고유명사 후보 토큰 추출 (3자 이상 한글/영문 단어)."""
    tokens = re.findall(r"[가-힣A-Za-z0-9]{3,}", title)
    return [t for t in tokens if t not in _STOP_TOKENS]


class TrendingNewsService:
    """네이버 뉴스 인기 기사 페이지에서 트렌딩 후보를 수집해 NewsCandidate로 변환한다."""

    def __init__(self, ranking_url: str = _RANKING_URL, timeout: int = _TIMEOUT) -> None:
        self.ranking_url = ranking_url
        self.timeout = timeout

    def collect_trending_candidates(
        self,
        *,
        max_candidates: int = 30,
        min_cluster_size: int = 2,
    ) -> list[NewsCandidate]:
        """페이지 fetch + 파싱 + 클러스터링 + NewsCandidate 변환.

        max_candidates: 반환할 최대 후보 수 (실제 클릭 신호 강한 순)
        min_cluster_size: 동일 사건으로 묶인 최소 기사 수 (낮을수록 후보 다양, 높을수록 진짜 트렌딩만)
        """
        try:
            html = self._fetch_page()
        except Exception as exc:
            logger.warning("TrendingNewsService: fetch 실패 — %s", exc)
            return []

        articles = self._parse_articles(html)
        logger.info("TrendingNewsService: %d개 기사 파싱됨", len(articles))
        if not articles:
            return []

        clusters = self._cluster_by_shared_tokens(articles)
        # cluster size 큰 순 = 여러 언론사가 같이 보도 = 진짜 트렌딩
        # 단 corporate 이슈는 후순위(사용자 선호 반영) — 같은 cluster size면 non-corporate 우선
        for cl in clusters:
            primary = min(cl["articles"], key=lambda a: a["rank"])
            cl["_is_corporate"] = _is_corporate_issue(primary["title"], cl["primary_tokens"])
        clusters.sort(key=lambda c: (
            c["_is_corporate"],  # False=0 우선
            -len(c["articles"]),
            -c["max_rank_score"],
        ))

        candidates: list[NewsCandidate] = []
        for cl in clusters:
            if len(cl["articles"]) < min_cluster_size and len(candidates) >= 5:
                # min_cluster_size 미만 cluster는 후순위 (singleton은 일부만 허용)
                continue
            cand = self._cluster_to_candidate(cl)
            if cand is not None:
                candidates.append(cand)
            if len(candidates) >= max_candidates:
                break

        logger.info(
            "TrendingNewsService: %d개 트렌딩 후보 생성 (cluster ≥%d 기준)",
            len(candidates), min_cluster_size,
        )
        return candidates

    # ── 내부 ─────────────────────────────────────────────────────────────

    def _fetch_page(self) -> str:
        req = urllib.request.Request(
            self.ranking_url,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        # 네이버는 UTF-8이지만 일부 페이지가 EUC-KR 가능성 있어 fallback
        for enc in ("utf-8", "euc-kr"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def _parse_articles(self, html: str) -> list[dict[str, Any]]:
        """페이지에서 (제목, URL, 언론사) 리스트 추출."""
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # noqa: BLE001
            logger.warning("TrendingNewsService: BeautifulSoup import 실패 — %s", exc)
            return []

        soup = BeautifulSoup(html, "lxml")
        boxes = soup.select("div.rankingnews_box")
        articles: list[dict[str, Any]] = []
        for box in boxes:
            press_el = box.select_one("h4, h3, h2, .rankingnews_name, strong")
            press = press_el.get_text(strip=True) if press_el else ""
            items = box.select("ul.rankingnews_list > li")
            for rank_idx, it in enumerate(items, start=1):
                title_el = it.select_one(".list_title")
                link_el = it.select_one('a[href*="n.news.naver.com"]') or it.select_one("a")
                if not title_el or not link_el:
                    continue
                title = title_el.get_text(strip=True)
                url = link_el.get("href", "").strip()
                if not title or not url:
                    continue
                articles.append({
                    "title": title,
                    "url": url,
                    "press": press,
                    "rank": rank_idx,  # 1~5 (낮을수록 인기)
                })
        return articles

    def _cluster_by_shared_tokens(
        self, articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """동일 사건 클러스터링 — 공유 토큰 ≥ 2개 또는 동일 entity 1개."""
        # 각 기사의 significant tokens 추출
        for art in articles:
            art["tokens"] = set(_extract_significant_tokens(art["title"]))

        clusters: list[dict[str, Any]] = []
        used: set[int] = set()

        for i, art_a in enumerate(articles):
            if i in used:
                continue
            cluster_articles = [art_a]
            cluster_tokens = Counter(art_a["tokens"])
            used.add(i)
            for j in range(i + 1, len(articles)):
                if j in used:
                    continue
                art_b = articles[j]
                shared = art_a["tokens"] & art_b["tokens"]
                # 공유 토큰 2개 이상 → 같은 사건
                if len(shared) >= 2:
                    cluster_articles.append(art_b)
                    cluster_tokens.update(art_b["tokens"])
                    used.add(j)
            # 가장 빈도 높은 토큰 = cluster의 핵심 키워드
            primary_tokens = [t for t, _ in cluster_tokens.most_common(5)]
            # max_rank_score: 가장 인기 있는 기사의 (6 - rank) 합산 — 클수록 인기
            max_rank_score = sum(max(0, 6 - a["rank"]) for a in cluster_articles)
            clusters.append({
                "articles": cluster_articles,
                "primary_tokens": primary_tokens,
                "max_rank_score": max_rank_score,
            })
        return clusters

    def _cluster_to_candidate(self, cluster: dict[str, Any]) -> NewsCandidate | None:
        articles = cluster["articles"]
        if not articles:
            return None
        # 대표 기사 = rank 가장 낮은(가장 인기) 기사
        primary = min(articles, key=lambda a: a["rank"])
        topic = primary["title"]
        # summary = 다른 기사 제목 2~3개
        other_titles = [a["title"] for a in articles if a is not primary][:3]
        summary = " | ".join(other_titles)[:200]
        sample_sources = list({a["press"] for a in articles if a["press"]})
        source_count = len(articles)

        # buzz_score: cluster size + rank_score 종합 (0~10)
        buzz = min(10, max(3, source_count + (cluster["max_rank_score"] // 3)))
        # entity_specificity_score: primary_tokens 수 기반 (3개 이상이면 7+, 5개 이상이면 9)
        spec = min(10, max(5, len(cluster["primary_tokens"]) + 4))

        raw: dict[str, Any] = {
            "source_type": "naver_trending",
            "topic_group": "today_issue",  # 게이트가 활용 — 골든 패턴은 별도 매칭
            "content_angle": {
                "content_type": "today_issue_explainer",
                "topic_group": "today_issue",
                "reader_question": "",
            },
            "is_stale": False,
            "trending_engine": True,
            "discovery_engine": False,
            "today_buzz_score": buzz,
            "entity_specificity_score": spec,
            "safe_commentary_score": 8,
            "source_count": source_count,
            "primary_tokens": cluster["primary_tokens"],
            "sample_sources": sample_sources,
            "sample_titles": [a["title"] for a in articles[:5]],
            "cluster_key": "_".join(cluster["primary_tokens"][:3]),
            "reader_search_questions": [],
            "original_topic": topic,
            "query": "naver_trending",
            "query_group": "naver_trending",
            "hook_signals": {"trending": True, "real_click_signal": True},
            "trend_signals": {"naver_ranking_cluster_size": source_count},
            "boring_signals": {"is_boring": False},
            "click_potential_score": min(10, max(7, source_count + 4)),
        }
        return NewsCandidate(
            topic=topic,
            category="today_issue",
            summary=summary,
            source_hint=primary["press"] or None,
            published_at=None,  # 페이지에 정확 시각 없음
            url=primary["url"],
            raw=raw,
        )
