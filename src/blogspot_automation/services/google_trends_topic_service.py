"""GoogleTrendsTopicService — 한국 Google Trends 일일 트렌딩 키워드를 실제 토픽 후보로 시드.

기존 GoogleTrendsSignal은 트렌딩 키워드를 **스코어 부스트**로만 사용했다. 이 서비스는
같은 RSS 피드(키워드 + approx_traffic + related_news_titles)를 **NewsCandidate**로
변환해 후보 풀 자체를 넓힌다. 매일 같은 ~5개 에버그린 토픽이 반복되어 dedup에 막혀
슬롯을 못 채우던 문제(소싱 폭 부족)를 신선한 트렌딩 토픽으로 보완한다.

- 정치/대기업 거버넌스/사건사고 트렌드는 evaluate_news_focus로 사전 필터.
- raw 구조는 TrendingNewsService(naver_trending)와 동일 규약 → 동일 게이트/부스트 적용.
- ENABLE_GOOGLE_TRENDS_SIGNAL=false면 빈 리스트(시그널 비활성).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.google_trends_signal import GoogleTrendsSignal, TrendingKeyword
from blogspot_automation.services.news_focus_policy import evaluate_news_focus
from blogspot_automation.services.news_taxonomy import is_market_finance_text

logger = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")

# 증시·종목·코인 트렌드(검색량은 높지만 블로그 부적합 + 품질 게이트에서 반복 차단).
# is_market_finance_text가 못 잡는 구어/은어 보강.
_MARKET_NOISE_TERMS: tuple[str, ...] = (
    "급락", "급등", "폭락", "폭등", "상한가", "하한가", "피크아웃", "저가매수",
    "고점", "저점", "코스피", "코스닥", "증시", "주가", "시총", "시가총액",
    "공매도", "환율", "금리", "선물환", "어닝", "영업이익", "분기실적", "실적 발표",
    "배당", "공모주", "청약 경쟁률", "상장폐지", "비트코인", "이더리움", "가상자산",
    "코인", "삼전닉스", "sk하닉", "마이크론", "엔비디아 주가", "반도체株", "수혜주",
    "테마주", "매수세", "매도세", "차익실현", "저가 매수",
)


def _is_market_noise(text: str) -> bool:
    lowered = " ".join((text or "").split()).lower()
    return any(term.lower() in lowered for term in _MARKET_NOISE_TERMS)


def _approx_traffic_value(approx_traffic: str) -> int:
    digits = "".join(ch for ch in (approx_traffic or "") if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _buzz_score(value: int) -> int:
    if value >= 100_000:
        return 10
    if value >= 50_000:
        return 9
    if value >= 10_000:
        return 8
    if value >= 1_000:
        return 7
    return 6


def _click_potential(value: int) -> int:
    if value >= 50_000:
        return 10
    if value >= 10_000:
        return 9
    if value >= 1_000:
        return 8
    return 7


class GoogleTrendsTopicService:
    """Google Trends(KR) 트렌딩 키워드를 NewsCandidate 후보로 변환한다."""

    def collect_trending_candidates(self, *, max_candidates: int = 12) -> list[NewsCandidate]:
        try:
            keywords = GoogleTrendsSignal.get_trending_keywords()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GoogleTrendsTopicService: 트렌드 fetch 실패 — %s", exc)
            return []
        if not keywords:
            return []

        candidates: list[NewsCandidate] = []
        seen: set[str] = set()
        skipped_focus = 0
        skipped_noise = 0
        for kw in keywords:
            cand = self._keyword_to_candidate(kw)
            if cand is None:
                continue
            key = (cand.raw.get("google_trends_keyword") or cand.topic).strip()
            if key in seen:
                continue
            combined = f"{cand.topic} {cand.summary}"
            # 한국어 없는 트렌드(외국어 유입) + 금융/시장 노이즈는 블로그 부적합 → 제외.
            if (
                not _HANGUL_RE.search(combined)
                or is_market_finance_text(combined)
                or _is_market_noise(combined)
            ):
                skipped_noise += 1
                continue
            decision = evaluate_news_focus(
                topic=cand.topic,
                summary=cand.summary,
                raw=cand.raw,
            )
            if not decision.allowed:
                skipped_focus += 1
                continue
            seen.add(key)
            candidates.append(cand)
            if len(candidates) >= max_candidates:
                break

        logger.info(
            "GoogleTrendsTopicService: %d개 트렌딩 토픽 후보 생성 (focus 제외 %d, 노이즈 제외 %d)",
            len(candidates),
            skipped_focus,
            skipped_noise,
        )
        return candidates

    def _keyword_to_candidate(self, kw: TrendingKeyword) -> NewsCandidate | None:
        keyword = (kw.keyword or "").strip()
        if not keyword or len(keyword) < 2:
            return None
        related = [t.strip() for t in (kw.related_news_titles or ()) if t and t.strip()]
        # 실제 헤드라인이 있으면 토픽으로 사용(골든 매칭·제목 생성에 유리), 없으면 키워드.
        topic = related[0] if related else keyword
        summary = " | ".join(related[1:4])[:200]
        traffic_value = _approx_traffic_value(kw.approx_traffic)
        buzz = _buzz_score(traffic_value)
        click = _click_potential(traffic_value)
        token_count = len(re.findall(r"[가-힣A-Za-z0-9]{2,}", keyword))
        spec = min(10, max(6, token_count + 6))

        raw: dict[str, Any] = {
            "source_type": "google_trends_trending",
            "topic_group": "today_issue",
            "content_angle": {
                "content_type": "today_issue_explainer",
                "topic_group": "today_issue",
                "reader_question": "",
            },
            "is_stale": False,
            "trending_engine": True,
            # discovery_engine=True: 사전 분류된(today_issue_explainer) 후보로 취급해
            # 스코어링이 content_angle/topic_group을 재분류하지 않고 보존하게 한다.
            "discovery_engine": True,
            "today_buzz_score": buzz,
            "entity_specificity_score": spec,
            "safe_commentary_score": 8,
            "source_count": len(related) + 1,
            "primary_tokens": [keyword],
            "sample_titles": related[:5],
            "cluster_key": keyword,
            "reader_search_questions": [],
            "original_topic": topic,
            "search_demand_topic": keyword,
            "query": "google_trends",
            "query_group": "google_trends",
            "hook_signals": {"trending": True, "google_trends_signal": True},
            "trend_signals": {"google_trends_approx_traffic": kw.approx_traffic},
            "boring_signals": {"is_boring": False},
            "click_potential_score": click,
            "google_trends_keyword": keyword,
            "google_trends_approx_traffic": kw.approx_traffic,
        }
        return NewsCandidate(
            topic=topic,
            category="today_issue",
            summary=summary,
            source_hint="google_trends",
            published_at=None,
            url=None,
            raw=raw,
        )
