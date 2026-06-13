from __future__ import annotations

from typing import Any

from blogspot_automation.models.news_models import NewsCandidate, ScoredNewsCandidate
from blogspot_automation.services.google_trends_signal import GoogleTrendsSignal
from blogspot_automation.services.news_taxonomy import (
    build_search_angle,
    classify_public_benefit,
    classify_topic_group as classify_taxonomy_topic_group,
    content_type_for_topic_group,
    is_privacy_security_text,
    is_tax_refund_text,
    is_promotion_like_title,
    is_viral_safe,
    transformed_public_benefit_topic,
    viral_safety_score,
    VIRAL_RISK_KEYWORDS,
    VIRAL_SAFE_SIGNALS,
)
from blogspot_automation.services.reader_interest_brief_service import ReaderInterestBriefService

MONEY_KEYWORDS = (
    "배달료", "배달비", "수수료", "가격", "요금", "생활비", "지원금",
    "환급", "세금", "대출", "금리", "보험료", "구독료", "쿠폰", "무료배달",
    "통신비", "결제", "환불", "위약금", "손해", "이득", "비용",
    "주식", "투자", "성과급", "연봉", "임금", "마일리지", "포인트", "적립",
    "할인", "인상", "인하", "가격 변동",
)
AUDIENCE_KEYWORDS = (
    "소비자", "자영업자", "사장님", "라이더", "직장인", "부모", "학생", "청년",
    "운전자", "이용자", "팬",
    "투자자", "주주", "노동자", "시청자", "구독자", "납세자",
)
URGENCY_KEYWORDS = (
    "오늘", "지금", "실시간", "갑자기", "중단", "종료", "변경", "논란", "마감", "지연",
    "혼란", "인상", "신청 기간", "지원 종료",
    "파업", "총파업", "긴급", "화제", "급등", "급증", "폭발", "최고", "역대",
    "합병", "인수", "폐지", "시행", "개정", "발효", "확정",
    "휴무", "집화", "배송조회", "청약", "사전투표", "선거일",
)
CURIOSITY_KEYWORDS = (
    "이유", "이면", "숨은", "놓친", "결국", "왜", "논란", "반응", "갈린",
    "진짜", "실제로", "따져보면", "알고보면", "사실은", "정말",
)
SEARCH_INTENT_KEYWORDS = (
    "신청", "방법", "대상", "조건", "확인", "환불", "증거", "설정", "해지",
    "비교", "체크", "계산", "기간", "마감", "종료", "변경", "지원",
)
PRACTICAL_VALUE_KEYWORDS = (
    "체크리스트", "계산", "비교", "신청 전", "환불 증거", "증거", "설정 방법",
    "대상 조건", "공식 페이지", "오늘 바로", "확인", "방법", "조건",
)
BRAND_FIT_KEYWORDS = (
    "돈", "시간", "불안", "선택", "생활", "의사결정", "AI", "자동화",
    "소비자", "행동 기준", "실전", "체크", "확인",
)
RISK_KEYWORDS = (
    "정치 선동", "선동", "정쟁", "국회 공방", "범죄", "사건사고", "사망",
    "선거", "표심", "민심", "한강벨트", "정치권", "오세훈",
    "압수수색", "수사 착수",
    "살해", "폭행", "혐오", "성인", "19금", "미성년자", "루머", "출처 불명",
    "가짜뉴스", "기업 실적", "실적 발표", "보도자료", "정례회의", "외교 회의",
    "외교 회담", "부동산 시세", "아파트 시세", "의료", "법률", "소송 확정",
    "무조건", "절대", "충격", "경악", "소름", "난리났다",
)


class NewsScoringService:
    # 후보 생성 진입 기준 (article_candidate.html 생성 가능 여부 판단용)
    # auto-publish는 별도 게이트(publish_ready/geo_ready/sge_ready)로 차단됨
    DEFAULT_CANDIDATE_GENERATION_MIN_SCORE = 65

    def __init__(
        self,
        *,
        min_topic_score: int = 75,
        candidate_generation_min_score: int | None = None,
    ) -> None:
        self.min_topic_score = min_topic_score
        self.candidate_generation_min_score = (
            candidate_generation_min_score
            if candidate_generation_min_score is not None
            else self.DEFAULT_CANDIDATE_GENERATION_MIN_SCORE
        )

    def score_candidates(self, candidates: list[NewsCandidate]) -> list[ScoredNewsCandidate]:
        scored_items: list[ScoredNewsCandidate] = []
        for candidate in candidates:
            raw = candidate.raw if isinstance(candidate.raw, dict) else {}
            candidate.raw = raw
            title = (candidate.topic or "").strip()
            summary = (candidate.summary or "").strip()
            category = (candidate.category or "").strip().lower()
            query_group = str(raw.get("query_group", ""))
            text = f"{title} {summary} category:{category} query_group:{query_group}"
            lowered = text.lower()
            source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
            is_evergreen_fallback = source_type == "evergreen_fallback"
            is_discovery_candidate = bool(raw.get("discovery_engine"))
            if is_evergreen_fallback and isinstance(raw.get("search_angle"), dict):
                search_angle = dict(raw.get("search_angle") or {})
            else:
                search_angle = build_search_angle(title, summary=summary, category=category, raw=raw)
            search_demand_topic = str(search_angle.get("search_demand_topic") or "").strip()
            # discovery_engine 후보는 이미 entity-specific하므로 transformation skip
            # (transformation이 "삼성 노조 대화" → "확인 전에 볼 주의점" 같은 generic으로 변질시키는 것 방지)
            if (
                search_demand_topic
                and bool(search_angle.get("should_transform_title"))
                and not is_discovery_candidate
            ):
                raw.setdefault("original_topic", title)
                candidate.topic = search_demand_topic
                title = search_demand_topic
                text = f"{title} {summary} original_topic:{raw.get('original_topic')} category:{category} query_group:{query_group}"
                lowered = text.lower()
            raw["search_angle"] = search_angle
            raw["search_demand_topic"] = search_demand_topic
            raw["reader_search_questions"] = list(search_angle.get("reader_search_questions") or [])
            raw["click_reason"] = str(search_angle.get("click_reason") or "")
            raw["reader_benefit"] = str(search_angle.get("reader_benefit") or "")
            raw["urgency_reason"] = str(search_angle.get("urgency_reason") or "")
            raw["content_promise"] = str(search_angle.get("content_promise") or "")
            raw["angle_type"] = str(search_angle.get("angle_type") or "")

            benefit_info = classify_public_benefit(f"{text} {search_demand_topic}")
            public_benefit_keyword = str(benefit_info.get("public_benefit_keyword") or "")
            commercial_support_signal = bool(benefit_info.get("commercial_support_signal") or search_angle.get("commercial_support_signal"))
            generic_support_keyword = str(benefit_info.get("generic_support_keyword") or search_angle.get("generic_support_keyword") or "")
            public_benefit_confidence = str(benefit_info.get("public_benefit_confidence") or "none")
            public_benefit_promotion_blocked = bool(
                benefit_info.get("public_benefit_promotion_blocked")
                or search_angle.get("public_benefit_promotion_blocked")
            )
            is_stale = bool(raw.get("is_stale")) and not is_evergreen_fallback
            promotion_like_title = is_promotion_like_title(str(search_angle.get("original_topic") or title))
            promoted_from_brand_article = bool(public_benefit_keyword and promotion_like_title)
            raw["commercial_support_signal"] = commercial_support_signal
            raw["generic_support_keyword"] = generic_support_keyword
            raw["public_benefit_confidence"] = public_benefit_confidence
            raw["public_benefit_promotion_blocked"] = public_benefit_promotion_blocked
            raw["stale_penalty_applied"] = False
            if public_benefit_keyword:
                original_topic = raw.setdefault("original_topic", str(search_angle.get("original_topic") or title))
                transformed_topic = search_demand_topic or transformed_public_benefit_topic(public_benefit_keyword, text)
                if transformed_topic:
                    candidate.topic = transformed_topic
                    title = transformed_topic
                raw["public_benefit_keyword"] = public_benefit_keyword
                raw["core_public_benefit_keyword"] = public_benefit_keyword
                raw["transformed_topic"] = transformed_topic or title
                raw["promotion_like_title"] = promotion_like_title
                raw["promoted_from_brand_article"] = promoted_from_brand_article
                raw["public_benefit_original_topic"] = original_topic
                text = (
                    f"{title} {summary} original_topic:{original_topic} "
                    f"public_benefit_keyword:{public_benefit_keyword} category:{category} query_group:{query_group}"
                )
                lowered = text.lower()

            topic_group = self._topic_group_from_search_angle(
                search_angle=search_angle,
                text=text,
                public_benefit_keyword=public_benefit_keyword,
                commercial_support_signal=commercial_support_signal,
            )
            if is_evergreen_fallback and str(raw.get("topic_group") or "").strip():
                topic_group = str(raw.get("topic_group") or "").strip()
            # discovery_engine 후보는 entity 기반으로 분류 완료된 상태 — raw 그대로 보존
            if is_discovery_candidate and str(raw.get("topic_group") or "").strip():
                topic_group = str(raw.get("topic_group") or "").strip()
            content_angle = self._build_content_angle(
                text=text,
                topic_group=topic_group,
                public_benefit_keyword=public_benefit_keyword,
                search_angle=search_angle,
            )
            if is_evergreen_fallback and isinstance(raw.get("content_angle"), dict):
                content_angle = dict(raw.get("content_angle") or {})
            if is_discovery_candidate and isinstance(raw.get("content_angle"), dict):
                # discovery candidate의 content_angle을 보존하되 기본 필드는 build 결과로 채움
                discovery_ca = dict(raw.get("content_angle") or {})
                content_angle = {**content_angle, **discovery_ca}
            strategy_score_breakdown = self._build_strategy_score_breakdown(
                candidate=candidate,
                text=lowered,
                query_group=query_group,
                topic_group=topic_group,
                content_angle=content_angle,
                public_benefit_keyword=public_benefit_keyword,
                search_angle=search_angle,
                commercial_support_signal=commercial_support_signal,
                is_stale=is_stale,
                is_evergreen_fallback=is_evergreen_fallback,
            )
            freshness_score = int(strategy_score_breakdown["freshness_score"])
            search_demand_score = int(strategy_score_breakdown["search_intent_score"])
            contrarian_gap_score = self._contrarian_gap_score(lowered, topic_group)
            mass_impact_score = int(strategy_score_breakdown["mass_relevance_score"])
            adsense_value_score = int(strategy_score_breakdown["brand_fit_score"])
            hook_score = self._hook_score(lowered, topic_group)
            risk_penalty = int(strategy_score_breakdown["risk_penalty_abs"])
            click_potential_score = self._score_click_potential(lowered, topic_group)
            if is_evergreen_fallback:
                click_potential_score = max(click_potential_score, 9)
            # discovery/trending 시드(naver_trending·google_trends)는 실제 검색량·클릭
            # 신호를 raw.click_potential_score에 담아온다 — 텍스트 기반 점수가 이를
            # 깎지 않도록 보존(가장 강한 클릭 신호). 하류 품질 게이트는 그대로 적용된다.
            if is_discovery_candidate or raw.get("trending_engine"):
                seeded_click = int(raw.get("click_potential_score") or 0)
                if seeded_click:
                    click_potential_score = max(click_potential_score, seeded_click)
            content_type = str(content_angle.get("content_type") or "")
            hook_category_priority = self._hook_category_priority(
                raw,
                lowered,
                topic_group,
                content_type,
            )
            hook_category_bonus = self._hook_category_bonus(
                raw,
                lowered,
                topic_group,
                content_type,
            )
            hook_category_reason = self._hook_category_reason(
                raw,
                lowered,
                topic_group,
                content_type,
            )
            front_page_signal_score = self._front_page_signal_score(raw, lowered, topic_group)
            raw["click_potential_score"] = click_potential_score
            raw["topic_group"] = topic_group
            raw["content_angle"] = content_angle
            reader_interest_brief = ReaderInterestBriefService.build(
                topic=title,
                summary=summary,
                raw=raw,
                topic_group=topic_group,
                content_type=content_type,
            )
            reader_interest_score = int(reader_interest_brief.get("reader_interest_score") or 0)
            reader_interest_bonus = self._reader_interest_selection_bonus(reader_interest_score)

            raw_total_score = int(strategy_score_breakdown["raw_total_score"])
            raw_total_score_before_selection_bonus = raw_total_score
            click_potential_bonus = 0
            # click_potential bonus — 조회수 폭발 주제 우선 선정
            # click >= 9: +8, >= 8: +5, >= 7: +2, < 7: 0 (패널티 없음, 게이트는 auto_publish에서 차단)
            if click_potential_score >= 9:
                click_potential_bonus = 8
            elif click_potential_score >= 8:
                click_potential_bonus = 5
            elif click_potential_score >= 7:
                click_potential_bonus = 2
            raw_total_score += click_potential_bonus + hook_category_bonus + reader_interest_bonus
            strategy_score_breakdown["raw_total_score_before_selection_bonus"] = raw_total_score_before_selection_bonus
            strategy_score_breakdown["click_potential_bonus"] = click_potential_bonus
            strategy_score_breakdown["hook_category_priority"] = hook_category_priority
            strategy_score_breakdown["hook_category_bonus"] = hook_category_bonus
            strategy_score_breakdown["hook_category_reason"] = hook_category_reason
            strategy_score_breakdown["front_page_signal_score"] = front_page_signal_score
            strategy_score_breakdown["reader_interest_bonus"] = reader_interest_bonus
            strategy_score_breakdown["raw_total_score"] = raw_total_score
            strategy_score_breakdown["total_before_clamp"] = raw_total_score
            total_score = self._clamp(raw_total_score, 0, 100)
            hook_angle = self._build_hook_angle(
                title=title,
                topic_group=topic_group,
                public_benefit_keyword=public_benefit_keyword,
            )

            scoring_breakdown = raw.setdefault("scoring_breakdown", {})
            if isinstance(scoring_breakdown, dict):
                scoring_breakdown.update(strategy_score_breakdown)
                scoring_breakdown["click_potential_score"] = click_potential_score
                scoring_breakdown["raw_total_score"] = raw_total_score
                scoring_breakdown["topic_group"] = topic_group
                scoring_breakdown["content_angle"] = content_angle
                scoring_breakdown["cooldown_penalty"] = 0
            raw["search_intent_score"] = strategy_score_breakdown["search_intent_score"]
            raw["money_loss_score"] = strategy_score_breakdown["money_loss_score"]
            raw["mass_relevance_score"] = strategy_score_breakdown["mass_relevance_score"]
            raw["practical_value_score"] = strategy_score_breakdown["practical_value_score"]
            raw["brand_fit_score"] = strategy_score_breakdown["brand_fit_score"]
            raw["strategy_score_breakdown"] = strategy_score_breakdown
            raw["click_potential_score"] = click_potential_score
            raw["raw_total_score"] = raw_total_score
            raw["reader_interest_brief"] = reader_interest_brief
            raw["reader_interest_score"] = reader_interest_score
            raw["reader_interest_strategy"] = str(reader_interest_brief.get("strategy") or "")
            raw["reader_interest_publish_intent"] = str(reader_interest_brief.get("publish_intent") or "")
            raw["save_value_score"] = int(reader_interest_brief.get("save_value_score") or 0)
            raw["curiosity_score"] = int(reader_interest_brief.get("curiosity_score") or 0)
            raw["hook_category_priority"] = hook_category_priority
            raw["hook_category_bonus"] = hook_category_bonus
            raw["hook_category_reason"] = hook_category_reason
            raw["front_page_signal_score"] = front_page_signal_score
            raw["topic_group"] = topic_group
            raw["content_angle"] = content_angle
            raw["cooldown_penalty"] = 0
            raw["hook_angle"] = hook_angle
            raw.setdefault("promotion_like_title", promotion_like_title)
            raw.setdefault("promoted_from_brand_article", promoted_from_brand_article)
            raw["stale_penalty_applied"] = bool(strategy_score_breakdown.get("stale_penalty_applied"))
            raw["evergreen_fallback"] = is_evergreen_fallback
            if topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"} or str(content_angle.get("content_type") or "") == "viral_issue_decode":
                raw["viral_issue_category"] = str(content_angle.get("viral_issue_category") or self._classify_viral_category(lowered))
                raw["viral_safety_score"] = int(content_angle.get("viral_safety_score") or viral_safety_score(f"{title} {text}"))
                raw["viral_risk_flags"] = list(content_angle.get("viral_risk_flags") or [kw for kw in VIRAL_RISK_KEYWORDS if kw.lower() in lowered])
                raw["reaction_points_count"] = int(content_angle.get("reaction_points_count") or 3)
                raw["structure_analysis_present"] = bool(content_angle.get("structure_analysis_present") or True)
                raw["evergreen_link_suggestions"] = list(content_angle.get("evergreen_link_suggestions") or self._viral_evergreen_suggestions(lowered))

            # --- Topic Engine v2 scoring ---
            v2_bucket = self._classify_topic_bucket(raw, topic_group)
            v2_scores = self._compute_topic_engine_v2_scores(raw, text, lowered, topic_group)
            v2_grade = self._compute_topic_candidate_grade(v2_scores)
            raw["topic_candidate_bucket"] = v2_bucket
            raw["topic_candidate_grade"] = v2_grade
            raw["topic_engine_score"] = v2_scores["topic_engine_score"]
            raw["topic_traffic_potential_score"] = v2_scores["topic_traffic_potential_score"]
            raw["topic_search_intent_score"] = v2_scores["topic_search_intent_score"]
            raw["topic_usefulness_score"] = v2_scores["topic_usefulness_score"]
            raw["topic_safety_score"] = v2_scores["topic_safety_score"]
            raw["topic_monetization_score"] = v2_scores["topic_monetization_score"]
            raw["topic_hook_category_priority"] = v2_scores["topic_hook_category_priority"]
            raw["topic_hook_category_bonus"] = v2_scores["topic_hook_category_bonus"]
            raw["topic_hook_category_reason"] = v2_scores["topic_hook_category_reason"]
            # --------------------------------

            try:
                trends_boost, trends_matched = GoogleTrendsSignal.score_topic_boost(
                    f"{title} {search_demand_topic}", max_boost=20
                )
            except Exception:  # noqa: BLE001
                trends_boost, trends_matched = 0, []
            if trends_boost > 0:
                raw["google_trends_boost"] = trends_boost
                raw["google_trends_matched"] = trends_matched
                total_score = int(total_score) + trends_boost

            scored_items.append(
                ScoredNewsCandidate(
                    candidate=candidate,
                    freshness_score=freshness_score,
                    search_demand_score=search_demand_score,
                    contrarian_gap_score=contrarian_gap_score,
                    mass_impact_score=mass_impact_score,
                    adsense_value_score=adsense_value_score,
                    hook_score=hook_score,
                    risk_penalty=risk_penalty,
                    total_score=total_score,
                    reason=(
                        f"{public_benefit_keyword}은 환급 대상, 조회 방법, 신청 경로 검색 수요가 있는 세금 환급 주제입니다. 공식 안내 확인이 필요합니다."
                        if public_benefit_keyword and is_tax_refund_text(f"{public_benefit_keyword} {text}")
                        else f"{public_benefit_keyword}은 신청방법, 대상 조건, 지급일, 사용처 검색 수요가 있는 정책 지원금 주제입니다. 공식 안내 확인이 필요합니다."
                        if public_benefit_keyword
                        else self._build_reason(topic_group)
                    ),
                )
            )
        return sorted(scored_items, key=lambda item: item.total_score, reverse=True)

    def get_publishable_candidates(self, scored: list[ScoredNewsCandidate]) -> list[ScoredNewsCandidate]:
        return [item for item in scored if item.total_score >= self.min_topic_score]

    def get_candidate_generation_eligible(
        self, scored: list[ScoredNewsCandidate]
    ) -> list[ScoredNewsCandidate]:
        """article_candidate.html 생성 진입 기준(score >= 65) 통과 후보.

        후보 생성 진입은 raw_total_score(쿨다운 차감 전)를 기준으로 한다.
        쿨다운은 발행 다양성을 위한 장치이므로 후보 생성 자체에는 적용하지 않는다.
        실제 자동 발행은 별도 게이트(publish_ready/geo_ready/sge_ready,
        content_type allowlist 등)에서 검증된다.
        """
        eligible: list[ScoredNewsCandidate] = []
        for item in scored:
            raw_total = self._effective_candidate_generation_score(item)
            if raw_total >= self.candidate_generation_min_score:
                eligible.append(item)
        return eligible

    @staticmethod
    def _effective_candidate_generation_score(item: ScoredNewsCandidate) -> int:
        """쿨다운 차감 전 raw_total_score를 반환. 없으면 total_score로 폴백."""
        raw = item.candidate.raw if isinstance(item.candidate.raw, dict) else {}
        sb = raw.get("strategy_score_breakdown") or {}
        raw_total = sb.get("raw_total_score")
        if raw_total is None:
            raw_total = raw.get("raw_total_score")
        try:
            return int(raw_total) if raw_total is not None else int(item.total_score)
        except (TypeError, ValueError):
            return int(item.total_score)

    # ------------------------------------------------------------------ #
    # Topic Engine v2                                                      #
    # ------------------------------------------------------------------ #

    _VIRAL_TOPIC_GROUPS = frozenset({
        "entertainment_sports", "ott_platform", "fandom_consumer",
        "entertainment_reaction", "ott_drama_reaction", "sports_reaction",
        "fandom_consumption", "community_hot_issue", "trend_meme",
        "ticketing_goods_issue", "youtube_creator_issue",
    })
    _EVERGREEN_TOPIC_GROUPS = frozenset({"ai_work", "platform_issue"})
    _HIGH_CPC_CONTENT_TYPES = frozenset({
        "ai_work_tip", "platform_change", "trend_decode",
        "viral_issue_decode", "today_issue_explainer",
    })
    _HOOK_FIRST_TOPIC_GROUPS = _VIRAL_TOPIC_GROUPS
    _FRONT_PAGE_TOPIC_GROUPS = frozenset({
        "privacy_security", "refund_consumer", "delivery_money",
        "platform_issue", "policy_benefit", "trend_meme",
        "today_issue",
    })
    _FRONT_PAGE_QUERY_GROUPS = frozenset({
        "breaking_issue", "consumer_warning_issue", "consumer_warning_secondary",
        "platform_consumer", "platform_change_secondary", "money_life",
        "money_secondary", "policy_benefit", "policy_secondary",
        "naver_trending", "discovery_engine",
    })
    _FRONT_PAGE_SIGNAL_KEYWORDS = (
        "속보", "단독", "긴급", "헤드라인", "1면", "주요 뉴스",
    "발표", "공개", "중단", "종료", "인상", "장애", "오류",
    "환불", "보상", "논란", "반응", "화제", "휴무", "집화",
    "배송조회", "청약", "신청", "마감", "조건", "대상",
)

    @classmethod
    def _classify_topic_bucket(cls, raw: dict, topic_group: str) -> str:
        content_type = ""
        ca = raw.get("content_angle")
        if isinstance(ca, dict):
            content_type = str(ca.get("content_type") or "")
        if topic_group in cls._VIRAL_TOPIC_GROUPS or content_type == "viral_issue_decode":
            return "viral_traffic_candidate"
        if topic_group in cls._EVERGREEN_TOPIC_GROUPS:
            return "evergreen_useful_candidate"
        if content_type in cls._HIGH_CPC_CONTENT_TYPES:
            return "high_cpc_guide_candidate"
        return "general"

    @classmethod
    def _hook_category_priority(
        cls,
        raw: dict,
        text: str,
        topic_group: str,
        content_type: str = "",
    ) -> int:
        if content_type == "viral_issue_decode" or topic_group in cls._HOOK_FIRST_TOPIC_GROUPS:
            return 0
        if cls._front_page_signal_score(raw, text, topic_group) >= 2:
            return 1
        if topic_group in cls._FRONT_PAGE_TOPIC_GROUPS:
            return 2
        return 3

    @classmethod
    def _hook_category_bonus(
        cls,
        raw: dict,
        text: str,
        topic_group: str,
        content_type: str = "",
    ) -> int:
        priority = cls._hook_category_priority(raw, text, topic_group, content_type)
        if priority == 0:
            viral_safety = cls._safe_int(raw.get("viral_safety_score"), 80)
            viral_risk_flags = list(raw.get("viral_risk_flags") or [])
            if viral_safety < 60 or viral_risk_flags:
                return 0
            return 12
        if priority == 1:
            return 9
        if priority == 2:
            return 4
        return 0

    @classmethod
    def _hook_category_reason(
        cls,
        raw: dict,
        text: str,
        topic_group: str,
        content_type: str = "",
    ) -> str:
        priority = cls._hook_category_priority(raw, text, topic_group, content_type)
        if priority == 0:
            return "hook_first_entertainment_sports_or_viral"
        if priority == 1:
            return "front_page_or_multi_source_headline"
        if priority == 2:
            return "broad_public_impact_news"
        return "standard_news_priority"

    @staticmethod
    def _reader_interest_selection_bonus(score: int) -> int:
        if score >= 85:
            return 8
        if score >= 75:
            return 5
        if score >= 65:
            return 2
        return 0

    @classmethod
    def _front_page_signal_score(cls, raw: dict, text: str, topic_group: str) -> int:
        score = 0
        source_type = str(raw.get("source_type") or raw.get("source") or "").strip().lower()
        query_group = str(raw.get("query_group") or "").strip()
        if raw.get("trending_engine") or source_type == "naver_trending":
            score += 2
        if raw.get("discovery_engine"):
            buzz = cls._safe_int(raw.get("today_buzz_score"), 0)
            source_count = cls._safe_int(raw.get("source_count"), 0)
            if buzz >= 8 or source_count >= 3:
                score += 2
            elif buzz >= 6 or source_count >= 2:
                score += 1
        if query_group in cls._FRONT_PAGE_QUERY_GROUPS:
            score += 1
        lowered = (text or "").lower()
        if any(keyword.lower() in lowered for keyword in cls._FRONT_PAGE_SIGNAL_KEYWORDS):
            score += 1
        if topic_group in cls._FRONT_PAGE_TOPIC_GROUPS:
            score += 1
        return score

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _compute_topic_engine_v2_scores(
        cls, raw: dict, text: str, lowered: str, topic_group: str
    ) -> dict:
        content_type = ""
        ca = raw.get("content_angle")
        if isinstance(ca, dict):
            content_type = str(ca.get("content_type") or "")
        click_score = int(raw.get("click_potential_score") or 0)
        viral_safety = int(raw.get("viral_safety_score") or 80)
        viral_risk_flags = list(raw.get("viral_risk_flags") or [])
        is_viral_ct = content_type == "viral_issue_decode"
        is_today_issue_ct = content_type == "today_issue_explainer" or topic_group == "today_issue"
        is_evergreen = str(raw.get("source_type") or "").lower() == "evergreen_fallback"
        is_stale = bool(raw.get("is_stale"))
        angle_type = str(raw.get("angle_type") or "")
        query_group = str(raw.get("query_group") or "")
        search_demand_topic = str(raw.get("search_demand_topic") or "")
        reader_questions = list(raw.get("reader_search_questions") or [])
        practical_value = int(raw.get("practical_value_score") or 0)
        hook_category_priority = cls._hook_category_priority(raw, text, topic_group, content_type)
        hook_category_bonus = cls._hook_category_bonus(raw, text, topic_group, content_type)
        hook_category_reason = cls._hook_category_reason(raw, text, topic_group, content_type)
        reader_interest = cls._safe_int(raw.get("reader_interest_score"), 0)
        save_value = cls._safe_int(raw.get("save_value_score"), 0)
        curiosity = cls._safe_int(raw.get("curiosity_score"), 0)

        # ── traffic_potential_score (0-30) ──
        tp = min(15, click_score)
        if is_viral_ct or topic_group in cls._VIRAL_TOPIC_GROUPS:
            tp += 8
        elif is_today_issue_ct:
            tp += 6
        if viral_safety >= 70:
            tp += 3
        if not viral_risk_flags:
            tp += 2
        if not is_stale:
            tp += 2
        if hook_category_bonus:
            tp += min(8, hook_category_bonus)
        tp += min(5, curiosity // 5)
        traffic_potential_score = max(0, min(30, tp))

        # ── search_intent_score (0-20) ──
        si = 0
        if query_group in cls._VIRAL_TOPIC_GROUPS:
            si += 6
        if search_demand_topic:
            si += 5
        if len(reader_questions) >= 2:
            si += 4
        if angle_type in ("viral_issue_decode", "benefit_howto", "tax_refund", "ai_setting") or is_today_issue_ct:
            si += 3
        if not is_stale:
            si += 2
        if hook_category_priority <= 1:
            si += 3
        elif hook_category_priority == 2:
            si += 1
        si += min(4, reader_interest // 25)
        search_intent_score = max(0, min(20, si))

        # ── usefulness_score (0-20) ──
        us = 0
        if content_type not in ("", "general_life"):
            us += 8
        us += min(6, int(practical_value / 3))
        if any(kw in (search_demand_topic + text) for kw in ("방법", "이유", "체크", "확인", "비교")):
            us += 3
        if is_evergreen:
            us += 3
        us += min(4, save_value // 6)
        usefulness_score = max(0, min(20, us))

        # ── safety_score (0-15) ──
        ss = 10
        if not viral_risk_flags:
            ss += 5
        if viral_safety < 40:
            ss -= 10
        elif viral_safety < 60:
            ss -= 3
        _HARD_BANNED = ("열애설", "이혼설", "불륜", "사생활 폭로", "루머", "외모 비하",
                        "미성년자", "피해자 신상", "악플 유도")
        if any(kw in lowered for kw in _HARD_BANNED):
            ss = 0
        safety_score = max(0, min(15, ss))

        # ── monetization_score (0-15) ──
        ms = 0
        if is_evergreen:
            ms += 5
        if content_type in ("ai_work_tip", "platform_change", "viral_issue_decode", "today_issue_explainer"):
            ms += 4
        if topic_group == "policy_benefit":
            ms += 3
        if click_score >= 8:
            ms += 3
        if hook_category_bonus:
            ms += 2
        if reader_interest >= 75:
            ms += 2
        monetization_score = max(0, min(15, ms))

        topic_engine_score = max(0, min(100,
            traffic_potential_score + search_intent_score + usefulness_score + safety_score + monetization_score
        ))

        return {
            "topic_traffic_potential_score": traffic_potential_score,
            "topic_search_intent_score": search_intent_score,
            "topic_usefulness_score": usefulness_score,
            "topic_safety_score": safety_score,
            "topic_monetization_score": monetization_score,
            "topic_hook_category_priority": hook_category_priority,
            "topic_hook_category_bonus": hook_category_bonus,
            "topic_hook_category_reason": hook_category_reason,
            "topic_engine_score": topic_engine_score,
        }

    @staticmethod
    def _compute_topic_candidate_grade(v2_scores: dict) -> str:
        score = v2_scores.get("topic_engine_score", 0)
        safety = v2_scores.get("topic_safety_score", 0)
        usefulness = v2_scores.get("topic_usefulness_score", 0)
        traffic = v2_scores.get("topic_traffic_potential_score", 0)
        if safety <= 0:
            return "D"
        if score >= 80 and safety >= 10 and (traffic >= 20 or usefulness >= 14):
            return "A"
        if score >= 70 and safety >= 10:
            return "B"
        if score >= 50 and safety >= 5:
            return "C"
        return "D"

    def _topic_group_from_search_angle(
        self,
        *,
        search_angle: dict[str, Any],
        text: str,
        public_benefit_keyword: str,
        commercial_support_signal: bool = False,
    ) -> str:
        if commercial_support_signal and not public_benefit_keyword:
            return "general_life"
        if public_benefit_keyword:
            return "policy_benefit"
        angle_type = str(search_angle.get("angle_type") or "")
        if angle_type == "tax_refund":
            return "policy_benefit"
        if angle_type in {"benefit_howto", "deadline_check"}:
            return "policy_benefit"
        if angle_type in {"refund_action", "consumer_warning"}:
            if is_privacy_security_text(f"{text} {search_angle.get('search_demand_topic') or ''}"):
                return "privacy_security"
            return "refund_consumer"
        if angle_type == "platform_check":
            return "platform_issue"
        if angle_type == "ai_setting":
            return "ai_work"
        if angle_type == "money_compare":
            return "delivery_money"
        if angle_type == "viral_issue_decode":
            text_lower = text.lower()
            if any(kw in text_lower for kw in ("넷플릭스", "ott", "티빙", "왓챠", "드라마", "예능", "시즌")):
                return "ott_platform"
            if any(kw in text_lower for kw in ("굿즈", "티켓팅", "팬덤 소비", "콘서트", "팬미팅", "아이돌")):
                return "fandom_consumer"
            return "entertainment_sports"
        if angle_type == "trend_reason":
            return "trend_meme"
        return self.classify_topic_group(text)

    def _build_strategy_score_breakdown(
        self,
        *,
        candidate: NewsCandidate,
        text: str,
        query_group: str,
        topic_group: str,
        content_angle: dict[str, Any],
        public_benefit_keyword: str = "",
        search_angle: dict[str, Any] | None = None,
        commercial_support_signal: bool = False,
        is_stale: bool = False,
        is_evergreen_fallback: bool = False,
    ) -> dict[str, Any]:
        search_intent_score = self._strategy_search_intent_score(text, topic_group)
        money_loss_score = self._strategy_money_loss_score(text, topic_group)
        mass_relevance_score = self._strategy_mass_relevance_score(text, topic_group)
        freshness_score = self._strategy_freshness_score(candidate, text, query_group)
        if topic_group == "policy_benefit" and any(token in text for token in ("마감", "신청 기간", "지원 종료")):
            freshness_score = self._clamp(freshness_score + 3, 0, 15)
        practical_value_score = self._strategy_practical_value_score(text, topic_group, content_angle)
        brand_fit_score = self._strategy_brand_fit_score(text, topic_group)
        risk_penalty_abs = self._risk_penalty(text)
        if public_benefit_keyword:
            search_intent_score = max(search_intent_score, 22)
            money_loss_score = max(money_loss_score, 20)
            mass_relevance_score = max(mass_relevance_score, 12)
            practical_value_score = max(practical_value_score, 13)
            brand_fit_score = max(brand_fit_score, 9)
            if any(token in text for token in ("신청", "마감", "지급", "지급일", "오늘", "이번주")):
                freshness_score = max(freshness_score, 12)
        if search_angle:
            questions = [str(item) for item in search_angle.get("reader_search_questions") or [] if str(item).strip()]
            click_reason = str(search_angle.get("click_reason") or "")
            should_transform = bool(search_angle.get("should_transform_title"))
            angle_type = str(search_angle.get("angle_type") or "")
            if len(questions) >= 3 and all(len(item) >= 12 for item in questions[:3]):
                search_intent_score = self._clamp(search_intent_score + 3, 0, 25)
            if any(token in click_reason for token in ("돈", "기한", "대상", "환불", "지원 종료", "설정", "손해", "지원금")):
                money_loss_score = self._clamp(money_loss_score + 2, 0, 20)
                practical_value_score = self._clamp(practical_value_score + 2, 0, 15)
            if should_transform:
                brand_fit_score = self._clamp(brand_fit_score + 1, 0, 10)
            if not should_transform and angle_type == "trend_reason":
                search_intent_score = self._clamp(search_intent_score - 2, 0, 25)
                brand_fit_score = self._clamp(brand_fit_score - 2, 0, 10)
        if is_evergreen_fallback:
            evergreen_axis = str(candidate.raw.get("evergreen_axis") or "")
            search_intent_score = max(search_intent_score, 22)
            mass_relevance_score = max(mass_relevance_score, 12)
            practical_value_score = max(practical_value_score, 13)
            brand_fit_score = max(brand_fit_score, 9)
            freshness_score = max(freshness_score, 8)
            if evergreen_axis in {"adsense_revenue", "blogspot_growth", "tax_refund_support", "money_life"}:
                money_loss_score = max(money_loss_score, 16)
            if evergreen_axis in {"ai_automation", "digital_survival"}:
                money_loss_score = max(money_loss_score, 10)
            if any(token in text for token in ("알아보기", "정리", "팁", "정보")) and not any(
                token in text for token in ("체크", "비교", "조회", "방법", "수익", "환급", "자동화", "구독", "검색")
            ):
                search_intent_score = min(search_intent_score, 18)
                brand_fit_score = min(brand_fit_score, 7)
        stale_penalty_applied = False
        if is_stale:
            freshness_score = min(freshness_score, 3)
            stale_penalty_applied = True
        if commercial_support_signal and not public_benefit_keyword:
            search_intent_score = min(search_intent_score, 8)
            money_loss_score = min(money_loss_score, 4)
            mass_relevance_score = min(mass_relevance_score, 4)
            practical_value_score = min(practical_value_score, 5)
            brand_fit_score = min(brand_fit_score, 2)
            risk_penalty_abs = max(risk_penalty_abs, 20)
            if is_stale:
                risk_penalty_abs = 30

        # fresh allowed real news + risk=0 후보 candidate generation boost
        # 후보 생성 진입(>=65)을 돕기 위함. 자동 발행은 publish_ready/geo_ready/sge_ready로 별도 차단.
        fresh_news_candidate_boost = self._fresh_news_candidate_boost(
            candidate=candidate,
            content_angle=content_angle,
            is_stale=is_stale,
            risk_penalty_abs=risk_penalty_abs,
            commercial_support_signal=commercial_support_signal,
            is_evergreen_fallback=is_evergreen_fallback,
            search_angle=search_angle or {},
        )
        external_evidence_bonus = self._external_evidence_bonus(
            candidate.raw if isinstance(candidate.raw, dict) else {},
            is_stale=is_stale,
            risk_penalty_abs=risk_penalty_abs,
            is_evergreen_fallback=is_evergreen_fallback,
        )

        raw_total_score = (
            search_intent_score
            + money_loss_score
            + mass_relevance_score
            + freshness_score
            + practical_value_score
            + brand_fit_score
            - risk_penalty_abs
            + fresh_news_candidate_boost
            + external_evidence_bonus
        )

        # discovery_engine 후보 score floor — broad scan은 일반 scoring keyword와 적게 매칭되지만
        # entity_specificity / today_buzz / safe_commentary 같은 meta signal로 quality는 이미 검증됨.
        # floor를 적용해 entity-specific 이슈가 publishable threshold(75)에 도달 가능하게 함.
        candidate_raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        if bool(candidate_raw.get("discovery_engine")):
            buzz = int(candidate_raw.get("today_buzz_score") or 0)
            specificity = int(candidate_raw.get("entity_specificity_score") or 0)
            safe = int(candidate_raw.get("safe_commentary_score") or 0)
            # buzz가 매우 높으면(>=10) spec 6도 publishable 진입 가능 (다매체 보도 + strong entity)
            if buzz >= 10 and specificity >= 6 and safe >= 7 and risk_penalty_abs == 0:
                raw_total_score = max(raw_total_score, 80)
            elif buzz >= 8 and specificity >= 7 and safe >= 7 and risk_penalty_abs == 0:
                raw_total_score = max(raw_total_score, 80)
            elif buzz >= 6 and specificity >= 7 and safe >= 6 and risk_penalty_abs == 0:
                raw_total_score = max(raw_total_score, 70)
            elif buzz >= 6 and specificity >= 6 and risk_penalty_abs == 0:
                raw_total_score = max(raw_total_score, 65)
        return {
            "search_intent_score": search_intent_score,
            "money_loss_score": money_loss_score,
            "mass_relevance_score": mass_relevance_score,
            "freshness_score": freshness_score,
            "practical_value_score": practical_value_score,
            "brand_fit_score": brand_fit_score,
            "risk_penalty": -risk_penalty_abs,
            "risk_penalty_abs": risk_penalty_abs,
            "fresh_news_candidate_boost": fresh_news_candidate_boost,
            "external_evidence_bonus": external_evidence_bonus,
            "raw_total_score": raw_total_score,
            "total_before_clamp": raw_total_score,
            "score_model": "content_strategy_lock_v1",
            "public_benefit_keyword": public_benefit_keyword,
            "official_source_check_needed": bool(public_benefit_keyword),
            "search_angle_type": str((search_angle or {}).get("angle_type") or ""),
            "search_angle_applied": bool(search_angle),
            "commercial_support_signal": commercial_support_signal,
            "stale_penalty_applied": stale_penalty_applied,
            "evergreen_fallback": is_evergreen_fallback,
            "evergreen_axis": str(candidate.raw.get("evergreen_axis") or ""),
        }

    # tuple of content_types eligible for the candidate generation boost
    _NEWS_AUTO_PUBLISH_CONTENT_TYPES = frozenset({
        "today_issue_explainer",
        "viral_issue_decode",
        "money_checklist",
        "platform_change",
        "consumer_warning",
        "policy_deadline",
        "policy_benefit",
        "tax_refund",  # tax_refund는 policy_benefit으로 정규화될 수 있어 포함
    })

    def _fresh_news_candidate_boost(
        self,
        *,
        candidate: NewsCandidate,
        content_angle: dict[str, Any],
        is_stale: bool,
        risk_penalty_abs: int,
        commercial_support_signal: bool,
        is_evergreen_fallback: bool,
        search_angle: dict[str, Any],
    ) -> int:
        """fresh allowed real news + risk=0 후보에 candidate generation boost (+5~+8).

        조건:
        - source_type이 실제 뉴스 소스 (google_news_rss 또는 google_custom_search)
        - content_type이 뉴스 자동발행 허용 카테고리
        - is_stale=False, risk_penalty=0
        - evergreen_fallback/commercial_support_signal 아님

        boost 크기:
        - 기본 +5
        - reader_search_questions가 3개 이상이면 +2
        - click_reason이 손해/대상/마감/환불/지원 관련이면 +1
        - content_type이 consumer_warning/viral_issue_decode면 +1 (점수가 낮은 경향)

        목적:
        65~74 범위에 머무는 좋은 fresh news가 article_candidate 생성 진입을 통과하도록.
        자동 발행은 publish_ready/geo_ready/sge_ready로 별도 차단되므로 안전.
        """
        if is_stale or risk_penalty_abs > 0:
            return 0
        if commercial_support_signal or is_evergreen_fallback:
            return 0
        raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        source_type = str(raw.get("source_type") or raw.get("source") or "").lower()
        if source_type not in {
            "google_news_rss",
            "google_custom_search",
            "naver_news_search",
            "naver_webkr_search",
            "naver_blog_search",
        }:
            return 0
        content_type = str((content_angle or {}).get("content_type") or "")
        if content_type not in self._NEWS_AUTO_PUBLISH_CONTENT_TYPES:
            return 0
        boost = 5
        questions = list(search_angle.get("reader_search_questions") or [])
        if len([q for q in questions if str(q).strip()]) >= 3:
            boost += 2
        elif len([q for q in questions if str(q).strip()]) >= 2:
            # 2개 질문이라도 검색 의도가 명확한 fresh news는 +1
            boost += 1
        click_reason = str(search_angle.get("click_reason") or "")
        if any(token in click_reason for token in ("손해", "기한", "대상", "환불", "마감", "지원금", "설정", "지원 종료")):
            boost += 1
        reader_benefit = str(search_angle.get("reader_benefit") or "")
        if any(token in reader_benefit for token in ("체크", "비교", "확인", "방법", "기준")):
            boost += 1
        # content_type별 미세 조정 (체감 점수가 낮은 카테고리에 가산)
        if content_type == "consumer_warning":
            boost += 3
        elif content_type == "viral_issue_decode":
            boost += 1
        # discovery_engine 후보 — 실제 오늘 여러 매체에서 buzz 있는 이슈
        # entity-specific하고 안전 필터 이미 통과했으므로 우선 발행 가능 후보
        if bool(raw.get("discovery_engine")):
            buzz = int(raw.get("today_buzz_score") or 0)
            specificity = int(raw.get("entity_specificity_score") or 0)
            if buzz >= 8 and specificity >= 7:
                boost += 5
            elif buzz >= 6:
                boost += 3
        return boost

    def _external_evidence_bonus(
        self,
        raw: dict[str, Any],
        *,
        is_stale: bool,
        risk_penalty_abs: int,
        is_evergreen_fallback: bool,
    ) -> int:
        if is_stale or risk_penalty_abs > 0 or is_evergreen_fallback:
            return 0
        source_type = str(raw.get("source_type") or raw.get("source") or "").lower()
        if source_type in {"fallback", "viral_fallback", "evergreen_fallback"}:
            return 0
        try:
            datalab_score = int(raw.get("naver_datalab_score") or 0)
        except (TypeError, ValueError):
            datalab_score = 0
        try:
            verified_count = int(raw.get("verified_source_count") or 0)
        except (TypeError, ValueError):
            verified_count = 0
        try:
            diversity_score = int(raw.get("source_diversity_score") or 0)
        except (TypeError, ValueError):
            diversity_score = 0

        bonus = 0
        if datalab_score >= 8:
            bonus += 4
        elif datalab_score >= 5:
            bonus += 3
        elif datalab_score >= 3:
            bonus += 1
        if verified_count >= 4:
            bonus += 3
        elif verified_count >= 2:
            bonus += 2
        elif verified_count >= 1:
            bonus += 1
        if diversity_score >= 4:
            bonus += 2
        elif diversity_score >= 2:
            bonus += 1
        if bool(raw.get("official_source_found")):
            bonus += 2
        return min(8, bonus)

    def _build_content_angle(
        self,
        *,
        text: str,
        topic_group: str,
        public_benefit_keyword: str = "",
        search_angle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content_type = content_type_for_topic_group(topic_group)
        if public_benefit_keyword and is_tax_refund_text(f"{public_benefit_keyword} {text}"):
            return {
                "content_type": "tax_refund",
                "content_subtype": "refund_tax",
                "reader_question": f"{public_benefit_keyword}은 누가, 어디서, 어떻게 조회해야 할까?",
                "reader_loss": "환급 대상 여부, 조회 경로, 환급 계좌를 놓치면 돌려받을 수 있는 금액 확인이 늦어질 수 있다.",
                "practical_value": "환급 대상, 홈택스·손택스 조회 경로, 필요 서류와 계좌 확인 체크리스트를 제공한다.",
                "example_needed": False,
            }
        if public_benefit_keyword:
            return {
                "content_type": "policy_deadline",
                "reader_question": f"{public_benefit_keyword}은 누가, 언제, 어떻게 신청해야 할까?",
                "reader_loss": "대상 조건, 신청 기간, 지급 방식, 사용처를 놓치면 받을 수 있는 지원금을 놓칠 수 있다.",
                "practical_value": "신청 기간, 대상 조건, 지급 방식, 사용처 확인 체크리스트를 제공한다.",
                "example_needed": False,
            }
        if search_angle:
            angle_type = str(search_angle.get("angle_type") or "")
            if angle_type == "viral_issue_decode":
                vscore = viral_safety_score(f"{text} {str(search_angle.get('search_demand_topic') or '')}")
                vrisk_flags = [kw for kw in VIRAL_RISK_KEYWORDS if kw.lower() in text.lower()]
                return {
                    "content_type": "viral_issue_decode",
                    "reader_question": str(search_angle.get("reader_search_questions", [""])[0] or "이 이슈가 왜 반응을 만들었을까?"),
                    "reader_loss": str(search_angle.get("click_reason") or "공개 콘텐츠·경기·방송 이슈가 왜 반응을 만들었는지 구조적으로 보면 다음 포인트가 보인다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "이슈 해석, 반응 포인트, 팬덤·플랫폼·소비 구조를 정리한다."),
                    "example_needed": False,
                    "viral_safety_score": vscore,
                    "viral_risk_flags": vrisk_flags,
                    "viral_issue_category": self._classify_viral_category(text),
                    "reaction_points_count": 3,
                    "structure_analysis_present": True,
                    "evergreen_link_suggestions": self._viral_evergreen_suggestions(text),
                }
            if angle_type == "refund_action":
                return {
                    "content_type": "consumer_warning",
                    "reader_question": "환불이나 결제 문제가 생기면 무엇부터 남겨야 할까?",
                    "reader_loss": str(search_angle.get("click_reason") or "증거를 늦게 남기면 환불 지연 때 손해를 줄이기 어렵다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "결제내역, 주문번호, 상담 기록을 남기는 순서를 정리한다."),
                    "example_needed": False,
                }
            if angle_type == "consumer_warning" and is_privacy_security_text(f"{text} {search_angle.get('search_demand_topic') or ''}"):
                return {
                    "content_type": "consumer_warning",
                    "reader_question": "개인정보 안내를 받았다면 계정 보안에서 무엇부터 확인해야 할까?",
                    "reader_loss": str(search_angle.get("click_reason") or "비밀번호 재사용과 피싱 문자를 놓치면 추가 도용 대응이 늦어질 수 있다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "유출 항목, 비밀번호 변경, 2차 인증, 공식 신고 채널 확인 순서를 정리한다."),
                    "example_needed": False,
                }
            if angle_type == "tax_refund":
                return {
                    "content_type": "tax_refund",
                    "content_subtype": "refund_tax",
                    "reader_question": "세금 환급 대상과 조회 경로를 어디서 확인해야 할까?",
                    "reader_loss": str(search_angle.get("click_reason") or "환급 대상 여부와 계좌 정보를 놓치면 환급 확인이 늦어질 수 있다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "홈택스·손택스 조회 경로와 필요 서류를 확인할 수 있다."),
                    "example_needed": False,
                }
            if angle_type == "platform_check":
                return {
                    "content_type": "platform_change",
                    "reader_question": "내 계정이나 기기가 이번 변경 대상인지 어떻게 확인할까?",
                    "reader_loss": str(search_angle.get("click_reason") or "지원 종료 대상인지 모르면 갑자기 서비스 이용이 막힐 수 있다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "계정, 백업, 업데이트 확인 순서를 알 수 있다."),
                    "example_needed": False,
                }
            if angle_type == "ai_setting":
                return {
                    "content_type": "ai_work_tip",
                    "reader_question": "AI 기능을 켜기 전에 어떤 설정을 먼저 확인해야 할까?",
                    "reader_loss": str(search_angle.get("click_reason") or "설정을 모르고 켜면 업무 흐름이 꼬일 수 있다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "AI 기능 사용 전 확인할 설정과 검수 기준을 알 수 있다."),
                    "example_needed": False,
                }
            if angle_type == "money_compare":
                return {
                    "content_type": "money_checklist",
                    "reader_question": "결제 전 어떤 조건을 비교해야 실제로 더 저렴할까?",
                    "reader_loss": str(search_angle.get("click_reason") or "쿠폰, 수수료, 최소 조건을 놓치면 할인받고도 더 낼 수 있다."),
                    "practical_value": str(search_angle.get("reader_benefit") or "최종 결제금액을 비교하는 기준을 얻는다."),
                    "example_needed": True,
                }
        angles = {
            "money_checklist": {
                "reader_question": "무료배달이나 쿠폰을 써도 왜 결제금액이 더 비싸질까?",
                "reader_loss": "최소주문금액, 메뉴 가격 차이, 쿠폰 조건을 놓치면 할인받고도 더 낼 수 있다.",
                "practical_value": "같은 메뉴를 앱별 최종 결제금액으로 비교하는 체크리스트를 제공한다.",
                "example_needed": True,
            },
            "consumer_warning": {
                "reader_question": "환불이나 배송 문제가 생기면 무엇부터 남겨야 할까?",
                "reader_loss": "증빙과 결제내역을 늦게 챙기면 환불 지연 때 손해를 줄이기 어렵다.",
                "practical_value": "캡처, 결제내역, 고객센터 기록을 남기는 순서를 정리한다.",
                "example_needed": False,
            },
            "policy_deadline": {
                "reader_question": "지원금 신청 전에 어떤 조건을 먼저 확인해야 할까?",
                "reader_loss": "마감, 대상 조건, 소득 기준, 필요 서류를 놓치면 받을 수 있는 지원을 놓친다.",
                "practical_value": "신청 전 확인할 대상 조건과 서류 체크리스트를 제공한다.",
                "example_needed": False,
            },
            "ai_work_tip": {
                "reader_question": "AI 도구가 바뀌면 업무에서 무엇을 먼저 바꿔야 할까?",
                "reader_loss": "기능만 따라가면 검토, 보안, 재작업이 늘어 생산성이 떨어질 수 있다.",
                "practical_value": "자동화할 일과 사람이 검토할 일을 나누는 기준을 제공한다.",
                "example_needed": False,
            },
            "trend_decode": {
                "reader_question": "왜 사람들이 이 유행에 돈과 시간을 쓰게 될까?",
                "reader_loss": "희소성과 인증샷에 끌리면 실제 가치보다 비싸게 소비할 수 있다.",
                "practical_value": "따라가기 전 가격, 지속성, 대체재를 보는 기준을 제공한다.",
                "example_needed": False,
            },
            "platform_change": {
                "reader_question": "서비스 변경 전에 내 계정과 결제에서 무엇을 확인해야 할까?",
                "reader_loss": "종료나 정책 변경을 늦게 알면 백업, 결제, 기기 호환성에서 불편이 생긴다.",
                "practical_value": "계정, 기기, 결제, 백업 체크리스트를 제공한다.",
                "example_needed": False,
            },
        }
        angles["today_issue_explainer"] = {
            "reader_question": "What is confirmed now, what is still unclear, and why is this issue leading today?",
            "reader_loss": "If readers mix confirmed facts with reactions, they can misread the real impact of today's issue.",
            "practical_value": "Summarize the confirmed facts, timeline, open questions, and next watch points.",
            "example_needed": False,
        }
        content_angle = dict(angles.get(content_type, angles["consumer_warning"]))
        content_angle["content_type"] = content_type
        return content_angle

    @staticmethod
    def _content_angle_bonus(content_angle: dict[str, Any]) -> int:
        content_type = str(content_angle.get("content_type") or "")
        if content_type in {
            "money_checklist",
            "consumer_warning",
            "policy_deadline",
            "tax_refund",
            "ai_work_tip",
            "trend_decode",
            "platform_change",
            "today_issue_explainer",
        }:
            return 4
        return 0

    @staticmethod
    def classify_topic_group(text: str) -> str:
        return classify_taxonomy_topic_group(text)

    def _strategy_search_intent_score(self, text: str, topic_group: str) -> int:
        score = 4
        score += min(15, self._keyword_hits(text, SEARCH_INTENT_KEYWORDS) * 3)
        if any(token in text for token in ("어떻게", "어디서", "언제", "내가", "해당", "신청 전")):
            score += 4
        if topic_group == "policy_benefit":
            score += 3
        elif topic_group in {"privacy_security", "refund_consumer", "platform_issue"}:
            score += 6
        elif topic_group in {"delivery_money", "ai_work"}:
            score += 5
        elif topic_group == "trend_meme":
            score += 2
        elif topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"}:
            score += 4
        elif topic_group == "today_issue":
            score += 5
        if topic_group == "entertainment_sports" and self._keyword_hits(text, SEARCH_INTENT_KEYWORDS) < 2:
            score -= 3
        if "보도자료" in text or "정례회의" in text:
            score -= 6
        return self._clamp(score, 0, 25)

    def _strategy_money_loss_score(self, text: str, topic_group: str) -> int:
        score = min(15, self._keyword_hits(text, MONEY_KEYWORDS) * 3)
        if topic_group in {"delivery_money", "privacy_security", "refund_consumer", "policy_benefit"}:
            score += 8 if topic_group == "policy_benefit" else 6
        elif topic_group == "platform_issue":
            score += 4
        elif topic_group == "ai_work":
            score += 2
        if any(token in text for token in ("손해", "더 내", "아끼", "받을 수", "놓치면")):
            score += 3
        return self._clamp(score, 0, 20)

    def _strategy_mass_relevance_score(self, text: str, topic_group: str) -> int:
        score = min(10, self._keyword_hits(text, AUDIENCE_KEYWORDS) * 2)
        if topic_group == "policy_benefit":
            score += 7
        elif topic_group in {"delivery_money", "privacy_security", "refund_consumer", "platform_issue"}:
            score += 5
        elif topic_group in {"ai_work", "trend_meme"}:
            score += 4
        elif topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"}:
            score += 6
        elif topic_group == "today_issue":
            score += 7
        return self._clamp(score, 0, 15)

    def _strategy_freshness_score(self, candidate: NewsCandidate, text: str, query_group: str) -> int:
        score = 6 if candidate.published_at else 5
        score += min(8, self._keyword_hits(text, URGENCY_KEYWORDS) * 2)
        if query_group in {"policy_benefit", "platform_consumer"}:
            score += 2
        elif query_group == "breaking_issue":
            score += 1
        if any(token in text for token in ("마감", "종료", "변경", "인상", "지원 종료", "신청 기간")):
            score += 3
        if any(token in text for token in ("실시간", "논란")) and self._keyword_hits(text, PRACTICAL_VALUE_KEYWORDS) == 0:
            score = min(score, 8)
        return self._clamp(score, 0, 15)

    def _strategy_practical_value_score(
        self,
        text: str,
        topic_group: str,
        content_angle: dict[str, Any],
    ) -> int:
        score = min(12, self._keyword_hits(text, PRACTICAL_VALUE_KEYWORDS) * 3)
        content_type = str(content_angle.get("content_type") or "")
        if content_type in {
            "money_checklist",
            "consumer_warning",
            "policy_deadline",
            "tax_refund",
            "platform_change",
            "ai_work_tip",
            "today_issue_explainer",
        }:
            score += 5
        elif content_type == "trend_decode":
            score += 3
        if topic_group in {"policy_benefit", "privacy_security", "refund_consumer", "delivery_money"}:
            score += 3
        if any(token in text for token in ("의견", "논평", "반응", "평가가 갈린")) and self._keyword_hits(text, PRACTICAL_VALUE_KEYWORDS) < 2:
            score = min(score, 7)
        return self._clamp(score, 0, 15)

    def _strategy_brand_fit_score(self, text: str, topic_group: str) -> int:
        score = min(4, self._keyword_hits(text, BRAND_FIT_KEYWORDS))
        if topic_group in {"delivery_money", "privacy_security", "refund_consumer", "policy_benefit", "platform_issue"}:
            score += 5 if topic_group == "policy_benefit" else 6
        elif topic_group == "ai_work":
            score += 5
        elif topic_group == "trend_meme":
            score += 3
        elif topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"}:
            score += 3
        elif topic_group == "today_issue":
            score += 2
        if any(token in text for token in ("기업 실적", "정치", "외교", "부동산 시세")):
            score -= 6
        return self._clamp(score, 0, 10)

    def _freshness_score(self, candidate: NewsCandidate, text: str, query_group: str) -> int:
        score = 17 if candidate.published_at else 15
        if any(token in text for token in URGENCY_KEYWORDS):
            score += 5
        if query_group in {"trend_meme", "breaking_issue"}:
            score += 2
        return self._clamp(score, 0, 25)

    def _search_demand_score(self, text: str, topic_group: str) -> int:
        score = 4
        score += min(8, self._keyword_hits(text, MONEY_KEYWORDS) * 2)
        score += min(6, self._keyword_hits(text, AUDIENCE_KEYWORDS) * 2)
        if topic_group in {"delivery_money", "privacy_security", "refund_consumer", "platform_issue"}:
            score += 8
        elif topic_group == "policy_benefit":
            score += 7
        elif topic_group in {"ai_work", "entertainment_sports"}:
            score += 6
        elif topic_group == "today_issue":
            score += 6
        elif topic_group == "trend_meme":
            score += 5
        return self._clamp(score, 0, 20)

    def _contrarian_gap_score(self, text: str, topic_group: str) -> int:
        score = 6 + min(8, self._keyword_hits(text, CURIOSITY_KEYWORDS) * 2)
        if topic_group in {"delivery_money", "privacy_security", "refund_consumer"}:
            score += 6
        elif topic_group in {"platform_issue", "policy_benefit"}:
            score += 4
        elif topic_group == "trend_meme":
            score += 3
        elif topic_group == "today_issue":
            score += 4
        return self._clamp(score, 0, 20)

    def _mass_impact_score(self, text: str, topic_group: str) -> int:
        score = min(8, self._keyword_hits(text, AUDIENCE_KEYWORDS) * 2)
        if topic_group == "policy_benefit":
            score += 7
        elif topic_group in {"delivery_money", "privacy_security", "refund_consumer", "platform_issue"}:
            score += 7
        elif topic_group in {"ai_work", "entertainment_sports"}:
            score += 5
        elif topic_group == "trend_meme":
            score += 3
        elif topic_group == "today_issue":
            score += 7
        return self._clamp(score, 0, 15)

    def _adsense_value_score(self, text: str, topic_group: str) -> int:
        score = min(5, self._keyword_hits(text, MONEY_KEYWORDS))
        if topic_group == "policy_benefit":
            score += 4
        elif topic_group in {"delivery_money", "privacy_security", "refund_consumer"}:
            score += 5
        elif topic_group in {"ai_work", "platform_issue"}:
            score += 4
        elif topic_group == "entertainment_sports":
            score += 2
        elif topic_group == "today_issue":
            score += 2
        return self._clamp(score, 0, 10)

    def _hook_score(self, text: str, topic_group: str) -> int:
        score = min(7, self._keyword_hits(text, URGENCY_KEYWORDS + CURIOSITY_KEYWORDS))
        if topic_group == "policy_benefit":
            score += 4
        elif topic_group in {"delivery_money", "privacy_security", "refund_consumer", "trend_meme", "entertainment_sports", "ott_platform", "fandom_consumer"}:
            score += 3
        elif topic_group == "today_issue":
            score += 6
        return self._clamp(score, 0, 10)

    def _risk_penalty(self, text: str) -> int:
        penalty = 0
        high_risk_keywords = (
            "정치 선동", "선동", "범죄", "사망", "살해", "폭행", "혐오",
            "성인", "19금", "미성년자", "의료", "법률", "소송 확정",
            "선거", "표심", "한강벨트", "정치권", "오세훈",
            "압수수색", "수사 착수",
        )
        viral_high_risk_keywords = (
            "열애설", "이혼설", "불륜", "사생활 폭로", "찌라시",
            "외모 비하", "피해자 신상", "악플 유도",
        )
        medium_risk_keywords = (
            "루머", "출처 불명", "가짜뉴스", "사건사고", "기업 실적",
            "실적 발표", "보도자료", "정례회의", "외교 회의", "외교 회담",
            "부동산 시세", "아파트 시세",
        )
        clickbait_keywords = ("충격", "경악", "소름", "난리났다", "무조건", "절대", "결국 터졌다")
        if any(keyword in text for keyword in high_risk_keywords):
            penalty += 30
        if any(keyword in text for keyword in viral_high_risk_keywords):
            penalty += 30
        if any(keyword in text for keyword in medium_risk_keywords):
            penalty += 20
        elif any(keyword in text for keyword in RISK_KEYWORDS):
            penalty += 12
        if any(keyword in text for keyword in clickbait_keywords):
            penalty += 10
        if any(keyword in text for keyword in ("실시간 논란", "논란 확산", "반응 폭발")) and self._keyword_hits(text, PRACTICAL_VALUE_KEYWORDS) == 0:
            penalty += 12
        return self._clamp(penalty, 0, 30)

    def _score_click_potential(self, text: str, topic_group: str) -> int:
        score = 0
        score += min(4, self._keyword_hits(text, MONEY_KEYWORDS) * 2)
        score += min(3, self._keyword_hits(text, AUDIENCE_KEYWORDS))
        score += min(3, self._keyword_hits(text, URGENCY_KEYWORDS))
        score += min(3, self._keyword_hits(text, CURIOSITY_KEYWORDS))
        if topic_group in {"delivery_money", "privacy_security", "refund_consumer"}:
            score += 3
        elif topic_group == "policy_benefit":
            score += 3
        elif topic_group == "platform_issue":
            score += 4
        elif topic_group in self._HOOK_FIRST_TOPIC_GROUPS:
            score += 4
        elif topic_group in self._FRONT_PAGE_TOPIC_GROUPS:
            score += 2
        return self._clamp(score, 0, 15)

    def _build_hook_angle(
        self,
        *,
        title: str,
        topic_group: str,
        public_benefit_keyword: str = "",
    ) -> dict[str, str]:
        if public_benefit_keyword:
            return {
                "reader_target": f"{public_benefit_keyword} 신청 대상자",
                "money_or_life_impact": f"{public_benefit_keyword} 대상 조건, 지급 방식, 사용처",
                "why_now": f"{public_benefit_keyword} 신청 정보",
                "curiosity_gap": "브랜드 소식보다 먼저 확인해야 하는 신청 조건과 사용처",
                "safe_title_keyword": public_benefit_keyword,
            }
        if topic_group == "delivery_money":
            keyword = "실시간 배달료 논란" if "실시간" in title and "배달료" in title else "배달료 논란"
            return {
                "reader_target": "소비자, 라이더, 자영업자",
                "money_or_life_impact": "배달료와 최종 결제 금액",
                "why_now": keyword,
                "curiosity_gap": "누가 비용을 더 부담하게 되는가",
                "safe_title_keyword": keyword,
            }
        if topic_group == "refund_consumer":
            return {
                "reader_target": "소비자와 결제 이용자",
                "money_or_life_impact": "환불 지연과 결제 신뢰",
                "why_now": "환불 피해 대응 관심 증가",
                "curiosity_gap": "기다리면 손해가 커질 수 있는 이유",
                "safe_title_keyword": "환불 지연 논란",
            }
        if topic_group == "privacy_security":
            return {
                "reader_target": "서비스 이용자와 계정 보안이 걱정되는 독자",
                "money_or_life_impact": "개인정보, 계정 도용, 피싱 피해 예방",
                "why_now": "개인정보 안내와 비밀번호 변경 권고",
                "curiosity_gap": "안내를 본 뒤 바로 바꿔야 하는 계정의 범위",
                "safe_title_keyword": "개인정보 보안 안내",
            }
        if topic_group == "ai_work":
            return {
                "reader_target": "직장인과 AI 도구 사용자",
                "money_or_life_impact": "업무 생산성과 도구 의존도",
                "why_now": "AI 서비스 변화",
                "curiosity_gap": "기능 변화보다 중요한 업무 기준 변화",
                "safe_title_keyword": "AI 업무 도구 변화",
            }
        if topic_group == "trend_meme":
            return {
                "reader_target": "SNS 이용자와 트렌드 소비자",
                "money_or_life_impact": "인증 소비와 과소비 가능성",
                "why_now": "오픈런과 품절 확산",
                "curiosity_gap": "맛보다 인증 욕구가 먼저 움직이는 이유",
                "safe_title_keyword": "오픈런 품절",
            }
        if topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"}:
            compact = (title or "").replace(" ", "")
            if "굿즈" in compact or "티켓팅" in compact or "팬덤" in compact:
                safe_kw = "팬덤 소비 구조"
            elif "ott" in compact.lower() or "넷플릭스" in compact or "드라마" in compact:
                safe_kw = "OTT 반응 분석"
            elif "경기" in compact or "손흥민" in compact or "야구" in compact:
                safe_kw = "경기 반응 포인트"
            else:
                safe_kw = title[:18].strip() or "이슈 반응 분석"
            return {
                "reader_target": "팬·시청자·대중 이슈 소비자",
                "money_or_life_impact": "팬덤 소비·플랫폼 전략·반응 구조",
                "why_now": "반응이 갈린 직후 검색 수요 집중",
                "curiosity_gap": "반응이 갈린 이유와 플랫폼·팬덤·소비 구조 해석",
                "safe_title_keyword": safe_kw,
            }
        if topic_group == "policy_benefit":
            compact = (title or "").replace(" ", "")
            if "청년" in compact and "지원금" in compact and ("신청" in compact or "마감" in compact):
                keyword = "청년 지원금 신청 마감"
            elif "청년" in compact and "지원금" in compact:
                keyword = "청년 지원금 대상 조건"
            elif "환급" in compact:
                keyword = "환급 신청 조건"
            elif "지원금" in compact and "마감" in compact:
                keyword = "지원금 신청 마감"
            else:
                keyword = "지원금 대상 조건"
            return {
                "reader_target": "지원금 신청 대상자",
                "money_or_life_impact": "신청 마감과 대상 조건에 따라 받을 수 있는 지원금",
                "why_now": keyword,
                "curiosity_gap": "금액보다 먼저 확인해야 하는 신청 조건",
                "safe_title_keyword": keyword,
            }
        return {
            "reader_target": "일반 독자",
            "money_or_life_impact": "생활 선택과 비용 판단",
            "why_now": "오늘 관심이 커진 이슈",
            "curiosity_gap": "사람들이 놓치기 쉬운 이면",
            "safe_title_keyword": title[:18].strip() or "오늘 이슈",
        }

    @staticmethod
    def _build_reason(topic_group: str) -> str:
        reasons = {
            "delivery_money": "배달료와 수수료는 소비자, 라이더, 자영업자 모두에게 연결되는 생활비 이슈라 대중 관심도가 높습니다.",
            "privacy_security": "개인정보와 계정 보안 이슈는 비밀번호 변경, 피싱 예방, 공식 신고 확인으로 바로 이어집니다.",
            "refund_consumer": "환불과 소비자 피해 이슈는 결제 신뢰와 직접 연결돼 생활 밀착성이 큽니다.",
            "ai_work": "AI 서비스 변화는 직장인 생산성과 연결돼 후킹 가능성이 있습니다.",
            "trend_meme": "오픈런과 품절은 SNS 확산 신호가 있어 트렌드형 소재로 활용 가능합니다.",
            "entertainment_sports": "스포츠와 팬 반응 이슈는 대중 관심과 댓글 참여를 만들 수 있어 화제성 소재로 활용 가능합니다.",
            "ott_platform": "OTT/방송 반응 이슈는 조회수 폭발 구조와 내부링크 유입 경로로 활용 가능합니다.",
            "fandom_consumer": "팬덤 소비·굿즈·티켓팅 이슈는 높은 반복 검색 수요와 클릭 욕구를 가집니다.",
            "policy_benefit": "지원금과 신청 마감 이슈는 독자 행동으로 이어질 가능성이 있습니다.",
            "platform_issue": "플랫폼 정책과 오류 이슈는 이용자 영향이 커서 관심도가 높습니다.",
        }
        return reasons.get(topic_group, "생활 밀착성이 있는 오늘 이슈입니다.")

    @staticmethod
    def _classify_viral_category(text: str) -> str:
        t = text.lower()
        if any(kw in t for kw in ("넷플릭스", "ott", "티빙", "드라마", "예능", "시즌")):
            return "ott_drama"
        if any(kw in t for kw in ("손흥민", "야구", "축구", "경기", "스포츠")):
            return "sports"
        if any(kw in t for kw in ("굿즈", "티켓팅", "팬덤 소비", "콘서트", "아이돌")):
            return "fandom_consumption"
        if any(kw in t for kw in ("유튜버", "커뮤니티", "인플루언서", "숏폼")):
            return "influencer_community"
        return "entertainment_general"

    @staticmethod
    def _viral_evergreen_suggestions(text: str) -> list[str]:
        t = text.lower()
        suggestions: list[str] = []
        if any(kw in t for kw in ("ott", "넷플릭스", "요금제")):
            suggestions.append("OTT 요금제 비교 가이드")
        if any(kw in t for kw in ("티켓팅", "콘서트")):
            suggestions.append("콘서트 티켓팅 방법 가이드")
        if any(kw in t for kw in ("굿즈", "팬덤 소비")):
            suggestions.append("팬덤 소비 합리화 가이드")
        if any(kw in t for kw in ("스포츠", "야구", "축구")):
            suggestions.append("스포츠 중계 플랫폼 비교")
        if not suggestions:
            suggestions.append("오늘 이슈 관련 생활 선택 기준 가이드")
        return suggestions[:3]

    @staticmethod
    def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
        return sum(1 for keyword in keywords if keyword.lower() in text)

    @staticmethod
    def _clamp(value: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(max_value, value))
