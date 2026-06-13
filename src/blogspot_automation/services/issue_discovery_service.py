"""Real Today Issue Discovery Engine.

매일 자동으로 좋은 오늘의 이슈 후보를 발견하기 위한 서비스.
고정 query group에 의존하지 않고 broad scan + entity extraction + issue clustering으로
실제 오늘 여러 매체에서 반복 등장하는 이슈를 찾는다.

Output: list[DiscoveredIssue]
- topic, entities, source_count, today_buzz_score, entity_specificity_score,
  candidate_content_type, sample_titles, sample_sources
"""

from __future__ import annotations

import html
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree
import urllib.request

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.news_taxonomy import is_market_finance_text

logger = logging.getLogger(__name__)


GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"


# ─────────────────────────────────────────────────────────────────────────
# Broad seed queries — 고정 query group이 아니라 "오늘 무엇이든 이슈" 시드
# ─────────────────────────────────────────────────────────────────────────
BROAD_SEED_QUERIES: tuple[str, ...] = (
    "오늘 이슈",
    "오늘 논란",
    "오늘 발표",
    "오늘 변경",
    "오늘 발생",
    "긴급 공지",
    "속보",
    "오늘 화제",
    "오늘 반응",
    "오늘 인상",
    "오늘 종료",
    "오늘 출시",
    "오늘 신청",
    "오늘 마감",
)


# 한국 매체 source_hint 일부 (BLOCKED 외 한국 매체로 인정할 패턴 — 정확도보단 확장성)
KOREAN_MEDIA_HINTS: tuple[str, ...] = (
    "연합뉴스", "뉴스1", "뉴시스", "한국경제", "매일경제", "서울경제",
    "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문", "국민일보",
    "머니투데이", "이데일리", "아시아경제", "헤럴드경제", "오늘경제",
    "MBC", "KBS", "SBS", "JTBC", "YTN", "TV조선", "MBN", "채널A",
    "스포츠서울", "OSEN", "엑스포츠뉴스", "스타뉴스", "텐아시아",
    "다음", "네이버", "노컷뉴스", "한국일보", "세계일보", "파이낸셜뉴스",
    "이코노미스트", "보안뉴스", "비즈니스포스트", "서울신문", "대한민국 정책브리핑",
    "디지털타임스", "전자신문", "디지털데일리",
)

BLOCKED_SOURCE_HINTS: tuple[str, ...] = (
    "Vietnam.vn", "vietnam.vn", "vnexpress", "thanhnien", "tuoitre",
)


# 한국 고유명사/브랜드/플랫폼/기관 사전 — entity 추출용
ENTITY_LEXICON: dict[str, str] = {
    # 플랫폼/서비스 (platform_change 후보)
    "쿠팡": "platform", "네이버": "platform", "카카오": "platform",
    "유튜브": "platform", "넷플릭스": "platform", "티빙": "platform",
    "디즈니플러스": "platform", "왓챠": "platform", "웨이브": "platform",
    "쿠팡플레이": "platform", "라프텔": "platform", "삼성": "platform",
    "애플": "platform", "구글": "platform", "아마존": "platform",
    "메타": "platform", "인스타그램": "platform", "틱톡": "platform",
    "당근": "platform", "토스": "platform", "카카오톡": "platform",
    "카카오뱅크": "platform", "카카오페이": "platform", "네이버페이": "platform",
    "쿠팡이츠": "platform", "배달의민족": "platform", "배민": "platform",
    "요기요": "platform", "지마켓": "platform", "11번가": "platform",
    # 기관/정부 (policy 후보)
    "정부": "agency", "지자체": "agency", "공정위": "agency",
    "금감원": "agency", "국세청": "agency", "복지부": "agency",
    "고용부": "agency", "교육부": "agency", "기획재정부": "agency",
    "개인정보위": "agency", "개인정보보호위원회": "agency",
    "한국소비자원": "agency", "방통위": "agency", "한국인터넷진흥원": "agency",
    "경찰": "agency", "검찰": "agency", "법원": "agency",
    "보건복지부": "agency", "고용노동부": "agency",
    # 통신사/금융 (consumer_warning 후보)
    "KT": "telecom", "SKT": "telecom", "LGU+": "telecom", "LG유플러스": "telecom",
    "SK텔레콤": "telecom", "신한카드": "card", "삼성카드": "card",
    "현대카드": "card", "KB국민카드": "card", "롯데카드": "card",
    "BC카드": "card", "하나카드": "card", "농협카드": "card",
    # 이벤트/사건 키워드 (clustering 신호)
    "과징금": "event", "유출": "event", "장애": "event", "오류": "event",
    "환불": "event", "보상": "event", "지원금": "event", "마감": "event",
    "출시": "event", "공개": "event", "발표": "event", "변경": "event",
    "인상": "event", "종료": "event", "시작": "event", "개편": "event",
    "도입": "event",
}

# 위험/금지 키워드 — discovery 단계에서 미리 차단
# 부분 매칭 기준: 키워드가 title의 어느 부분에든 등장하면 차단
RISK_KEYWORDS: tuple[str, ...] = (
    # 사생활/루머/외모
    "열애설", "이혼설", "불륜", "사생활 폭로", "찌라시",
    "외모 비하", "피해자 신상", "신상공개", "악플 유도",
    "충격 근황", "결국 터졌다", "소름 돋는 이유",
    # 강력 범죄 — "살인/살해/사망/강간/성폭행/스토킹" 등 부분 매칭 가능
    "살인", "살해", "사망", "변사", "강간", "성폭행", "성추행",
    "스토킹", "흉기", "납치", "유괴", "방화", "묻지마",
    # 성/연령 보호
    "성인", "아동", "미성년자", "고어",
    # 혐오/선동
    "혐오", "정치 선동",
    # 정치/외교 — 정치적 의견 갈리는 이슈는 운영 리스크
    "정상회담", "대통령", "여당", "야당", "총리",
    "선거", "탄핵", "특검", "국정조사", "청문회",
    "의원", "내란", "쿠데타", "정쟁",
    # 종교/이념
    "종교 갈등", "이단",
)


# content_type → topic_group 기본 매핑 (allowed news 자동발행 카테고리)
_CT_TO_TG: dict[str, str] = {
    "today_issue_explainer": "today_issue",
    "viral_issue_decode": "ott_platform",
    "money_checklist": "delivery_money",
    "platform_change": "platform_issue",
    "consumer_warning": "refund_consumer",
    "policy_deadline": "policy_benefit",
    "policy_benefit": "policy_benefit",
}
NON_AUTO_DISCOVERY_CONTENT_TYPES = frozenset({"general_life"})


def _refine_topic_group_for_corporate(entities: list[str], entity_types: list[str], text: str) -> str | None:
    """corporate workplace issue는 ott_platform 대신 platform_issue topic_group으로 미세조정.

    그래야 corporate_issue_decode 패턴이 매칭됨.
    """
    text_lower = text.lower()
    has_platform = any(t == "platform" for t in entity_types)
    has_corp_signal = any(kw in text_lower for kw in (
        "노조", "노동조합", "교섭", "임직원", "사측", "노사",
        "이사회", "주주", "공시", "구조조정", "추가 대화", "공식 입장",
    ))
    if has_platform and has_corp_signal:
        return "platform_issue"  # corporate_issue_decode pattern은 ott_platform이라 양쪽 fit
    return None


def _build_reader_questions_for_issue(iss: "DiscoveredIssue") -> list[str]:
    """이슈 entity 기반으로 독자 질문 5개 생성."""
    ents = iss.entities[:2] if iss.entities else ["이 이슈"]
    primary = ents[0]
    ct = iss.candidate_content_type
    if ct == "platform_change":
        return [
            f"{primary} 변경 적용 시점은 언제인가요?",
            f"{primary} 기존 이용자는 그대로 사용할 수 있나요?",
            f"{primary} 변경 후 결제·약관은 어떻게 달라지나요?",
            "변경 전에 미리 점검해야 할 항목은 무엇인가요?",
            "공식 안내는 어디서 확인할 수 있나요?",
        ]
    if ct == "consumer_warning":
        return [
            f"{primary} 관련 피해가 의심될 때 먼저 무엇을 해야 하나요?",
            "공식 안내인지 어떻게 확인하나요?",
            "결제·계정 보호를 위해 즉시 할 일은 무엇인가요?",
            "신고는 어디로 해야 하나요?",
            "필요한 증거 자료는 무엇인가요?",
        ]
    if ct in ("policy_deadline", "policy_benefit"):
        return [
            f"{primary} 지원 대상은 누구인가요?",
            "소득 기준은 어떻게 적용되나요?",
            "필요 서류는 어디서 발급받나요?",
            "신청 마감일은 언제인가요?",
            "지급 방식과 사용처는 어떻게 되나요?",
        ]
    if ct == "viral_issue_decode":
        return [
            f"{primary} 반응이 갈리는 이유는 무엇인가요?",
            f"{primary}을 어떻게 봐야 할까요?",
            "확인된 사실과 추측은 어떻게 구분하나요?",
            "공식 발표·반응은 어디서 확인하나요?",
            "관련해서 사람들이 자주 묻는 질문은 무엇인가요?",
        ]
    if ct == "money_checklist":
        return [
            f"{primary} 관련 비용은 어떻게 바뀌나요?",
            "기존 이용자에게 미치는 실제 영향은 무엇인가요?",
            "비교할 때 무엇을 먼저 봐야 하나요?",
            "공식 안내와 다르게 적용되는 경우가 있나요?",
            "이용자가 즉시 확인할 항목은 무엇인가요?",
        ]
    return [
        f"{primary}의 핵심 내용은 무엇인가요?",
        "가장 중요한 확인 사항은 무엇인가요?",
        "나와 직접 관련이 있는지 어떻게 확인하나요?",
        "공식 안내는 어디서 확인하나요?",
        "자주 묻는 질문은 무엇인가요?",
    ]


@dataclass
class DiscoveredIssue:
    """클러스터링된 단일 이슈."""
    cluster_key: str
    primary_topic: str               # 대표 제목 (clean)
    entities: list[str]              # 추출된 고유명사 / 기관 / 사건어
    entity_types: list[str]          # 각 entity의 type (platform/agency/event 등)
    source_count: int                # 다른 매체 수
    sample_titles: list[str]         # 묶인 원본 제목들
    sample_sources: list[str]        # 매체 hint들
    earliest_pub: str | None
    latest_pub: str | None
    today_buzz_score: int            # 0-10
    entity_specificity_score: int    # 0-10
    safe_commentary_score: int       # 0-10
    candidate_content_type: str      # allowed ct or non-auto ct such as market_finance
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_key": self.cluster_key,
            "primary_topic": self.primary_topic,
            "entities": self.entities,
            "entity_types": self.entity_types,
            "source_count": self.source_count,
            "sample_titles": self.sample_titles[:5],
            "sample_sources": self.sample_sources[:5],
            "earliest_pub": self.earliest_pub,
            "latest_pub": self.latest_pub,
            "today_buzz_score": self.today_buzz_score,
            "entity_specificity_score": self.entity_specificity_score,
            "safe_commentary_score": self.safe_commentary_score,
            "candidate_content_type": self.candidate_content_type,
            "risk_flags": self.risk_flags,
        }


class IssueDiscoveryService:
    """Real Today Issue Discovery Engine.

    broad scan으로 24-48h 이슈 수집 → entity 추출 → 같은 entity 공유 기사 클러스터링
    → today_buzz_score(source count) 계산 → content_type 분류 → 안전 필터링
    """

    def __init__(
        self,
        *,
        seed_queries: tuple[str, ...] = BROAD_SEED_QUERIES,
        max_items_per_query: int = 20,
        recency_hours: int = 48,
    ) -> None:
        self.seed_queries = seed_queries
        self.max_items_per_query = max_items_per_query
        self.recency_hours = recency_hours

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def discover_today_issues(self) -> list[DiscoveredIssue]:
        """오늘의 이슈를 broad scan + entity + cluster로 발견.

        실패하면 빈 리스트 반환 (호출자가 기존 파이프라인으로 폴백).
        """
        try:
            raw_items = self._broad_scan()
        except Exception as exc:  # noqa: BLE001
            logger.warning("broad_scan failed: %s", exc)
            return []
        if not raw_items:
            return []
        filtered = self._filter_safe_and_korean(raw_items)
        if not filtered:
            return []
        # 각 기사에 entity 추출
        for item in filtered:
            item["entities"], item["entity_types"] = self._extract_entities(item.get("title", ""))
        clusters = self._cluster_issues(filtered)
        issues = [self._build_discovered_issue(c) for c in clusters]
        # source_count 0~1 짜리 단발성 + entity 없는 cluster는 제외
        issues = [iss for iss in issues if iss.entities and iss.source_count >= 1]
        # 점수 내림차순 정렬
        issues.sort(
            key=lambda x: (x.today_buzz_score, x.entity_specificity_score, x.source_count),
            reverse=True,
        )
        return issues[:30]  # 상위 30개

    def to_news_candidates(
        self,
        issues: list[DiscoveredIssue],
        *,
        min_buzz: int = 6,
        min_specificity: int = 6,
        min_safe: int = 6,
        require_strong_entity: bool = True,
    ) -> list[NewsCandidate]:
        """발견된 이슈를 기존 파이프라인이 사용하는 NewsCandidate로 변환.

        엄격 필터: 발행 가능 수준의 quality만 후보화.

        - high buzz (>= 8) + strong entity면 specificity 6이어도 통과
        - 그 외는 specificity >= 7 요구
        """
        strong_types = {"platform", "agency", "telecom", "card", "acronym"}
        candidates: list[NewsCandidate] = []
        for iss in issues:
            if iss.today_buzz_score < min_buzz:
                continue
            has_strong = any(t in strong_types for t in iss.entity_types)
            # buzz 8+ + strong entity면 spec 6 허용. 아니면 spec 7+ 요구
            effective_spec_min = min_specificity if (iss.today_buzz_score >= 8 and has_strong) else max(min_specificity + 1, 7)
            if iss.entity_specificity_score < effective_spec_min:
                continue
            if iss.safe_commentary_score < min_safe:
                continue
            if iss.risk_flags:
                continue
            if require_strong_entity and not has_strong:
                continue
            original_ct = iss.candidate_content_type
            ct = self._normalize_candidate_content_type(original_ct)
            if ct in NON_AUTO_DISCOVERY_CONTENT_TYPES or ct not in _CT_TO_TG:
                continue
            # topic_group은 content_type 기반으로 매핑
            tg = _CT_TO_TG.get(ct, "general_life")
            # corporate workplace issue (노조/공시 등) → platform_issue로 보내
            # corporate_issue_decode 패턴이 매칭되도록
            _corp_tg = _refine_topic_group_for_corporate(
                iss.entities, iss.entity_types,
                iss.primary_topic + " " + " ".join(iss.sample_titles),
            )
            if _corp_tg:
                tg = _corp_tg
            # reader_search_questions 미리 생성
            reader_questions = _build_reader_questions_for_issue(iss)
            raw: dict[str, Any] = {
                "source_type": "google_news_rss",
                "topic_group": tg,
                "content_angle": {
                    "content_type": ct,
                    "topic_group": tg,
                    "reader_question": reader_questions[0] if reader_questions else "",
                },
                "original_content_type": original_ct,
                "is_stale": False,
                "discovery_engine": True,
                "today_buzz_score": iss.today_buzz_score,
                "entity_specificity_score": iss.entity_specificity_score,
                "safe_commentary_score": iss.safe_commentary_score,
                "source_count": iss.source_count,
                "entities": iss.entities,
                "entity_types": iss.entity_types,
                "sample_sources": iss.sample_sources,
                "sample_titles": iss.sample_titles,
                "cluster_key": iss.cluster_key,
                "reader_search_questions": reader_questions,
                "original_topic": iss.primary_topic,
                "query": "discovery_engine",
                "query_group": "discovery_engine",
                "hook_signals": {"famous_entity": True},
                "trend_signals": {},
                "boring_signals": {"is_boring": False},
            }
            candidates.append(NewsCandidate(
                topic=iss.primary_topic,
                category=tg,
                summary=" ".join(iss.sample_titles[:3])[:200],
                source_hint=iss.sample_sources[0] if iss.sample_sources else None,
                published_at=iss.latest_pub,
                url=None,
                raw=raw,
            ))
        return candidates

    # ------------------------------------------------------------------ #
    # Step 1: broad scan                                                   #
    # ------------------------------------------------------------------ #

    def _broad_scan(self) -> list[dict[str, Any]]:
        """broad seed queries로 Google News RSS 수집. 한국어/한국 매체 위주."""
        all_items: list[dict[str, Any]] = []
        for q in self.seed_queries:
            params = {"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
            url = f"{GOOGLE_NEWS_RSS_ENDPOINT}?{urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=9) as resp:
                    payload = resp.read()
                root = ElementTree.fromstring(payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("broad_scan rss fail (q=%s): %s", q, exc)
                continue
            for item in root.iter():
                if self._tag_name(item) != "item":
                    continue
                title_raw = self._child_text(item, "title")
                link = self._child_text(item, "link")
                pub_date = self._child_text(item, "pubDate")
                source = self._child_text(item, "source")
                clean_title = self._clean_title(title_raw)
                if not clean_title:
                    continue
                pub_dt = self._parse_pub(pub_date)
                if pub_dt and (datetime.now(UTC) - pub_dt) > timedelta(hours=self.recency_hours):
                    continue
                all_items.append({
                    "title": clean_title,
                    "title_raw": title_raw,
                    "link": link,
                    "pub_date": pub_date,
                    "pub_dt": pub_dt.isoformat() if pub_dt else None,
                    "source": source,
                    "seed_query": q,
                })
                if len(all_items) >= self.max_items_per_query * len(self.seed_queries):
                    break
        # 중복 제거 (title 정규화 기준)
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in all_items:
            key = re.sub(r"\s+", "", item["title"]).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    # ------------------------------------------------------------------ #
    # Step 2: safety + Korean filter                                       #
    # ------------------------------------------------------------------ #

    def _filter_safe_and_korean(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in items:
            source = str(item.get("source") or "")
            if source and any(blocked.lower() in source.lower() for blocked in BLOCKED_SOURCE_HINTS):
                continue
            title = item.get("title", "")
            if any(kw in title for kw in RISK_KEYWORDS):
                continue
            filtered.append(item)
        return filtered

    # ------------------------------------------------------------------ #
    # Step 3: entity extraction                                            #
    # ------------------------------------------------------------------ #

    def _extract_entities(self, title: str) -> tuple[list[str], list[str]]:
        """한국어 휴리스틱 entity 추출.

        - ENTITY_LEXICON 사전 매칭 우선
        - 추가로 '회사명' 대문자 영문 약어, 카드사·통신사 등
        - 단순 일반어는 제외
        """
        entities: list[str] = []
        types: list[str] = []
        title_lower = title.lower()
        for key, etype in ENTITY_LEXICON.items():
            if key.lower() in title_lower and key not in entities:
                entities.append(key)
                types.append(etype)
        # 영문 약어 (KT, SKT, LGU+ 등은 lexicon에 있음; 그 외 대문자 2-5자)
        for m in re.finditer(r"\b([A-Z][A-Z0-9+]{1,5})\b", title):
            tok = m.group(1)
            if tok in entities or len(tok) < 2 or tok.lower() in {"the", "and", "for"}:
                continue
            entities.append(tok)
            types.append("acronym")
        return entities, types

    # ------------------------------------------------------------------ #
    # Step 4: clustering (shared entity sets)                              #
    # ------------------------------------------------------------------ #

    def _cluster_issues(
        self, items: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """entity 공유 기반 클러스터링.

        - 공유 strong entity(platform/agency/telecom/card/acronym)가 1개 이상이면 cluster로 묶음
        - 또는 같은 entity 2개 이상 공유 시 묶음
        - event-only entity(발표/공개/마감 등)는 너무 generic해서 단독 묶지 않음
        """
        strong_types = {"platform", "agency", "telecom", "card", "acronym"}
        clusters: list[list[dict[str, Any]]] = []
        for item in items:
            ents = set(item.get("entities") or [])
            ent_types_map = dict(zip(item.get("entities", []), item.get("entity_types", [])))
            if not ents:
                continue
            strong_ents = {e for e in ents if ent_types_map.get(e) in strong_types}
            attached = False
            for cluster in clusters:
                cluster_ents = set()
                cluster_strong = set()
                for c in cluster:
                    c_ents = c.get("entities") or []
                    c_types = c.get("entity_types") or []
                    cluster_ents.update(c_ents)
                    for e, t in zip(c_ents, c_types):
                        if t in strong_types:
                            cluster_strong.add(e)
                # 우선: strong entity가 1개 이상 공유되면 동일 cluster
                if strong_ents & cluster_strong:
                    cluster.append(item)
                    attached = True
                    break
                # fallback: event 포함 일반 entity가 2개 이상 공유되면 동일 cluster
                shared = ents & cluster_ents
                if len(shared) >= 2:
                    cluster.append(item)
                    attached = True
                    break
            if not attached:
                clusters.append([item])
        return clusters

    # ------------------------------------------------------------------ #
    # Step 5: build DiscoveredIssue                                        #
    # ------------------------------------------------------------------ #

    def _build_discovered_issue(self, cluster: list[dict[str, Any]]) -> DiscoveredIssue:
        # entity 통합
        ent_count: dict[str, int] = defaultdict(int)
        ent_type: dict[str, str] = {}
        sources: list[str] = []
        titles: list[str] = []
        pub_dts: list[datetime] = []
        for item in cluster:
            for e, t in zip(item.get("entities", []), item.get("entity_types", [])):
                ent_count[e] += 1
                ent_type[e] = t
            src = str(item.get("source") or "").strip()
            if src and src not in sources:
                sources.append(src)
            t = item.get("title", "")
            if t and t not in titles:
                titles.append(t)
            pd = item.get("pub_dt")
            if pd:
                try:
                    pub_dts.append(datetime.fromisoformat(pd))
                except Exception:
                    pass
        # 대표 topic = 가장 짧고 명확한 title 또는 cluster 중 첫 번째
        primary = min(titles, key=lambda t: len(t)) if titles else "(no topic)"
        sorted_ents = sorted(ent_count.items(), key=lambda x: (-x[1], x[0]))
        entities = [e for e, _ in sorted_ents[:6]]
        entity_types = [ent_type.get(e, "other") for e in entities]
        source_count = len(sources)
        # cluster_key = 정규화 entity set
        cluster_key = "|".join(sorted(entities))

        today_buzz_score = self._compute_buzz_score(source_count)
        entity_specificity_score = self._compute_specificity_score(entities, entity_types)
        safe_commentary_score = self._compute_safe_commentary_score(titles)
        ct = self._classify_content_type(entities, entity_types, " ".join(titles))
        risk_flags = self._detect_risk_flags(" ".join(titles))

        return DiscoveredIssue(
            cluster_key=cluster_key,
            primary_topic=primary,
            entities=entities,
            entity_types=entity_types,
            source_count=source_count,
            sample_titles=titles[:5],
            sample_sources=sources[:5],
            earliest_pub=min(pub_dts).isoformat() if pub_dts else None,
            latest_pub=max(pub_dts).isoformat() if pub_dts else None,
            today_buzz_score=today_buzz_score,
            entity_specificity_score=entity_specificity_score,
            safe_commentary_score=safe_commentary_score,
            candidate_content_type=ct,
            risk_flags=risk_flags,
        )

    # ------------------------------------------------------------------ #
    # Scoring                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_buzz_score(source_count: int) -> int:
        """source 수 기반 buzz score (0-10).

        - 1매체: 3
        - 2매체: 6
        - 3매체: 8
        - 4+매체: 10
        """
        if source_count >= 4:
            return 10
        if source_count == 3:
            return 8
        if source_count == 2:
            return 6
        if source_count == 1:
            return 3
        return 0

    @staticmethod
    def _compute_specificity_score(entities: list[str], types: list[str]) -> int:
        if not entities:
            return 0
        score = 3  # 기본 낮춤 — event-only는 specific하지 않음
        # 고유 entity가 많을수록 specific
        score += min(3, len(entities))
        # platform/agency/telecom/card/acronym 같은 구체적인 type이 있으면 가점
        strong_types = {"platform", "agency", "telecom", "card", "acronym"}
        strong_hits = sum(1 for t in types if t in strong_types)
        if strong_hits >= 2:
            score += 4
        elif strong_hits == 1:
            score += 2
        # 모든 entity가 event-only이면 (발표/공개/시작/마감 등만) specificity 매우 약함
        if all(t == "event" for t in types):
            score -= 4
        return max(0, min(10, score))

    @staticmethod
    def _compute_safe_commentary_score(titles: list[str]) -> int:
        joined = " ".join(titles).lower()
        # 사실형 vs 자극형
        sensational = ("충격", "경악", "소름", "역대급", "난리", "결국 터졌")
        analytic = ("발표", "공지", "변경", "인상", "출시", "환불", "장애", "유출")
        sensational_hits = sum(1 for kw in sensational if kw in joined)
        analytic_hits = sum(1 for kw in analytic if kw in joined)
        score = 7
        score += min(3, analytic_hits)
        score -= 2 * sensational_hits
        return max(0, min(10, score))

    @staticmethod
    def _detect_risk_flags(text: str) -> list[str]:
        return [kw for kw in RISK_KEYWORDS if kw in text]

    @staticmethod
    def _classify_content_type(
        entities: list[str], types: list[str], text: str
    ) -> str:
        """이슈 내용 기반 content_type 분류."""
        lower = text.lower()
        if is_market_finance_text(text):
            return "today_issue_explainer"
        # 1. policy 관련
        if any(kw in lower for kw in ("지원금", "신청 마감", "신청마감", "지급")):
            if any(kw in lower for kw in ("마감", "시행일", "접수")):
                return "policy_deadline"
            return "policy_benefit"
        # 2. consumer_warning (개인정보/환불/장애/피싱)
        if any(kw in lower for kw in (
            "유출", "개인정보", "피싱", "스미싱", "환불", "장애", "오류",
            "결제 오류", "예약 취소", "보상", "피해",
        )):
            return "consumer_warning"
        # 3. platform_change (요금/멤버십/약관/서비스 종료/개편)
        if any(kw in lower for kw in (
            "요금제", "멤버십", "구독료", "약관 변경", "서비스 종료",
            "개편", "정책 변경", "지원 종료",
        )):
            return "platform_change"
        # 4. viral_issue_decode (연예/OTT/스포츠/팬덤/공개 반응 OR 기업 노사/공시 이슈)
        if any(kw in lower for kw in (
            "드라마", "예능", "OTT", "넷플릭스", "티빙", "디즈니",
            "방송", "공개", "반응", "팬", "굿즈", "콘서트", "티켓팅",
            "경기", "야구", "축구", "스포츠", "선수", "아이돌",
        )):
            return "viral_issue_decode"
        # 4-b. corporate workplace issue — 노조/임직원/사업/공시/이사회 등 → viral_issue_decode
        # platform entity가 있을 때만 (대기업/플랫폼 기업 이슈)
        if any(t == "platform" for t in types) and any(kw in lower for kw in (
            "노조", "노동조합", "교섭", "임직원", "사측", "노사",
            "이사회", "주주", "공시", "구조조정", "사업 부진",
            "추가 대화", "공식 입장", "공식 안내", "대화 제안",
        )):
            return "viral_issue_decode"
        # 5. money_checklist (가격/수수료/생활비)
        if any(kw in lower for kw in (
            "가격", "수수료", "구독료", "배달비", "통신비", "보험료",
            "전기요금", "교통비", "월급",
        )):
            return "money_checklist"
        # 6. 기본 — entity가 platform/telecom/card면 platform_change, agency면 policy_benefit
        if any(t in ("platform", "telecom") for t in types):
            return "platform_change"
        if "agency" in types:
            return "policy_benefit"
        return "today_issue_explainer"

    @staticmethod
    def _normalize_candidate_content_type(content_type: str) -> str:
        if content_type == "market_finance":
            return "today_issue_explainer"
        return content_type

    # ------------------------------------------------------------------ #
    # Utilities                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tag_name(item: ElementTree.Element) -> str:
        return item.tag.rsplit("}", 1)[-1] if isinstance(item.tag, str) else ""

    def _child_text(self, item: ElementTree.Element, child_name: str) -> str:
        for child in list(item):
            if self._tag_name(child) == child_name:
                return (child.text or "").strip()
        return ""

    @staticmethod
    def _clean_title(title: str) -> str:
        cleaned = html.unescape(title or "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # 매체명 접미사 제거 (- 매체명)
        cleaned = re.sub(r"\s*-\s*[가-힣A-Za-z][가-힣A-Za-z0-9 .]*$", "", cleaned)
        return cleaned.strip(" \"'“”‘’[]()")

    @staticmethod
    def _parse_pub(pub_date: str) -> datetime | None:
        if not pub_date:
            return None
        try:
            parsed = parsedate_to_datetime(pub_date)
        except Exception:  # noqa: BLE001
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
