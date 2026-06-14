from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# patterns.json 기본 경로: 프로젝트 루트/golden_samples/patterns.json
_DEFAULT_PATTERNS_PATH = Path(__file__).parents[3] / "golden_samples" / "patterns.json"

# 매칭 점수 상수
_PER_KW_SCORE = 27       # 키워드 1개 히트당 점수 (3개 히트 → 81 → threshold 초과)
_MAX_KW_SCORE = 80       # 키워드 점수 상한
_CT_BONUS = 15           # content_type 정확 일치 보너스
_TG_BONUS = 10           # topic_group 정확 일치 보너스
_NEG_PENALTY = 25        # match_negative 히트당 페널티
_DEFAULT_THRESHOLD = 80  # 매칭 성공 최소 confidence


_PATTERN_BLOCKED_CONTENT_TYPES = {"general_life", "blogspot_growth", "evergreen_fallback"}

_DISABLED_PATTERN_IDS: frozenset[str] = frozenset(
    {
        "corporate_issue_decode",
    }
)


_NON_VIRAL_TOPIC_SIGNALS = (
    "지원금", "지원사업", "보조금", "환급금", "장려금",
    "신청방법", "신청 방법", "신청기간", "신청 기간", "신청마감",
    "공시", "공고", "고시", "법안", "조례", "예산", "정책",
    "민선", "도지사", "시장", "지방의원", "의원", "공무원",
    "기후보험", "경기패스", "경기 패스",
    "정부지원", "정부 지원", "정부 발표", "부처", "공공기관",
    "KT", "SKT", "SK텔레콤", "LG유플러스", "LGU+", "LG U+",
    "통신사", "이동통신", "통신요금", "통신비",
    "요금제", "데이터무제한", "무제한 요금",
    "5G", "LTE",
    "약정", "위약금", "번호이동", "알뜰폰", "결합할인", "결합 할인",
    "KT초이스", "올레", "지니", "U+", "유플러스", "유심", "eSIM",
    "멤버십 할인", "멤버십 적립", "통신 멤버십",
    "개인정보", "개인정보위", "개인정보위원회", "정보 유출",
    "본인확인", "본인 확인", "본인인증", "본인 인증",
    "보안 사고", "보안사고", "해킹", "피싱", "스미싱",
    "과징금", "매출 10%", "유출", "침해",
)

_POLICY_INDICATOR_KEYWORDS = _NON_VIRAL_TOPIC_SIGNALS

_VIRAL_PATTERN_IDS_REQUIRING_ENTERTAINMENT_FOCUS = {
    "viral_ott_reaction_decode",
}

_POLICY_SIGNAL_PENALTY = 60
_MIN_POLICY_SIGNALS_FOR_PENALTY = 2

_STRONG_NON_VIRAL_TOPIC_SIGNALS = (
    "기후보험", "경기패스", "경기 패스", "민선",
    "지원금", "지원사업", "보조금", "환급금",
    "개인정보", "개인정보위", "개인정보위원회", "정보 유출",
    "본인확인", "본인 확인", "보안 사고", "보안사고",
    "과징금", "피싱", "스미싱",
    "KT초이스", "요금제", "통신요금", "통신비",
)
_STRONG_NON_VIRAL_CAP_CONFIDENCE = 25


_CORPORATE_INDICATOR_KEYWORDS: tuple[str, ...] = ()
_PATTERNS_REJECTING_CORPORATE_SIGNALS: frozenset[str] = frozenset()
_CORPORATE_SIGNAL_PENALTY = 60
_MIN_CORPORATE_SIGNALS_FOR_PENALTY = 2


_MAX_TOPIC_TOKEN_COUNT = 14
_MAX_TOPIC_MIDDOT_COUNT = 3
_BROKEN_SURFACE_MARKERS = ("…", "...")
_VERB_ENDING_FOLLOWED_BY_NOUN_PATTERN = (
    "됐고 ", "했고 ", "되고 ", "였고 ",
)
_BROKEN_SURFACE_CAP_CONFIDENCE = 25


class GoldenPatternService:
    """golden_samples/patterns.json 기반 패턴 매칭 서비스.

    Phase 2 파이프라인에서 topic → 골든 패턴 매칭 → 슬롯 채우기로 이어지는
    첫 번째 단계를 담당한다. 매칭 실패(confidence < 80) 시 발행 보류.
    """

    def __init__(self, patterns_path: str | Path | None = None) -> None:
        self._path = Path(patterns_path) if patterns_path else _DEFAULT_PATTERNS_PATH
        self._patterns: list[dict[str, Any]] = []
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def load_patterns(self) -> list[dict[str, Any]]:
        """patterns.json을 로드해 패턴 목록을 반환한다. 한 번만 읽고 캐싱."""
        if self._loaded:
            return self._patterns
        self._patterns = self._read_patterns()
        self._loaded = True
        return self._patterns

    def list_patterns(self) -> list[dict[str, Any]]:
        """등록된 패턴의 요약 목록(pattern_id, title, content_type, topic_group)을 반환."""
        return [
            {
                "pattern_id": p.get("pattern_id"),
                "title": p.get("title"),
                "content_type": p.get("content_type"),
                "topic_group": p.get("topic_group"),
            }
            for p in self.load_patterns()
        ]

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """pattern_id로 단일 패턴 전체를 반환. 없으면 None."""
        return next(
            (p for p in self.load_patterns() if p.get("pattern_id") == pattern_id),
            None,
        )

    def match_pattern(
        self,
        topic: str,
        summary: str = "",
        content_type: str = "",
        topic_group: str = "",
    ) -> dict[str, Any]:
        """topic(+summary)을 모든 패턴과 비교해 가장 높은 confidence를 가진 결과를 반환.

        Args:
            topic:        후보 주제 문자열 (필수)
            summary:      추가 요약 텍스트 (선택, 없으면 빈 문자열)
            content_type: 스코어링 서비스에서 분류된 content_type (선택, 보너스 점수)
            topic_group:  스코어링 서비스에서 분류된 topic_group (선택, 보너스 점수)

        Returns:
            {
              "matched": bool,           # confidence >= threshold
              "pattern_id": str | None,
              "pattern_title": str | None,
              "confidence": int,         # 0~100
              "matched_keywords": list,
              "negative_hits": list,
              "content_type_match": bool,
              "topic_group_match": bool,
              "reason": str,
            }
        """
        patterns = self.load_patterns()
        if not patterns:
            return _no_match_result("no patterns loaded")
        if content_type in _PATTERN_BLOCKED_CONTENT_TYPES:
            return _no_match_result(f"content_type_not_pattern_eligible:{content_type}")

        combined = f"{topic} {summary}".strip()
        combined_lower = combined.lower()
        combined_words = combined.split()
        topic_only = (topic or "").strip()

        best: dict[str, Any] | None = None
        best_confidence = -1
        for pattern in patterns:
            result = self._score(
                pattern, combined, combined_lower, combined_words, content_type, topic_group,
                topic_only=topic_only,
            )
            if result["confidence"] > best_confidence:
                best_confidence = result["confidence"]
                best = result

        return best or _no_match_result("unexpected empty result")

    def list_required_slots(self, pattern_id: str) -> list[str]:
        """패턴의 required_slots 키 목록을 반환."""
        p = self.get_pattern(pattern_id)
        return list(p.get("required_slots", {}).keys()) if p else []

    def get_publish_policy(self, pattern_id: str) -> dict[str, Any]:
        """패턴의 publish_policy 딕셔너리를 반환."""
        p = self.get_pattern(pattern_id)
        return p.get("publish_policy", {}) if p else {}

    def get_quality_checks(self, pattern_id: str) -> dict[str, Any]:
        """패턴의 quality_checks 딕셔너리를 반환."""
        p = self.get_pattern(pattern_id)
        return p.get("quality_checks", {}) if p else {}

    def get_banned_default_phrases(self, pattern_id: str) -> list[str]:
        """패턴의 banned_default_phrases 목록을 반환."""
        p = self.get_pattern(pattern_id)
        return p.get("banned_default_phrases", []) if p else []

    def suggest_pattern_id_by_hint(
        self,
        text: str,
        content_type: str = "",
        topic_group: str = "",
    ) -> str | None:
        """content_type·topic_group·키워드 힌트로 pattern_id를 빠르게 추천한다.

        full match_pattern() 호출 없이 1차 필터링용으로 사용한다.
        """
        # content_type 기반 1:1 매핑
        if content_type in _PATTERN_BLOCKED_CONTENT_TYPES:
            return None

        _CT_MAP: dict[str, str] = {
            "tax_refund": "tax_refund_hometax_check",
            "viral_issue_decode": "viral_ott_reaction_decode",
            "ai_work_tip": "ai_work_time_savings",
            "ai_prompt_recipe": "ai_prompt_recipe",
            "ai_tool_review": "ai_tool_review",
            "ai_model_update": "ai_model_update",
            "ai_search_change": "ai_search_change",
            "ai_blog_growth": "ai_blog_growth",
            "ai_comparison": "ai_comparison",
            "ai_risk_security": "ai_risk_security",
            "ai_beginner_guide": "ai_beginner_guide",
            "money_checklist": "delivery_money_checklist",
            "platform_change": "platform_change_service_update",
            "consumer_warning": "consumer_warning_refund",
            "policy_deadline": "policy_deadline_support",
            "policy_benefit": "policy_deadline_support",
        }
        if content_type in _CT_MAP:
            return _CT_MAP[content_type]

        # topic_group 기반 힌트
        _TG_MAP: dict[str, str] = {
            "policy_benefit": "policy_deadline_support",
            "ott_platform": "viral_ott_reaction_decode",
            "fandom_consumer": "viral_ott_reaction_decode",
            "entertainment_sports": "viral_ott_reaction_decode",
            "ai_work": "ai_work_time_savings",
            "ai_prompt": "ai_prompt_recipe",
            "ai_tool": "ai_tool_review",
            "ai_model": "ai_model_update",
            "ai_search": "ai_search_change",
            "ai_blog": "ai_blog_growth",
            "ai_compare": "ai_comparison",
            "ai_risk": "ai_risk_security",
            "ai_beginner": "ai_beginner_guide",
            "delivery_money": "delivery_money_checklist",
            "consumer_life": "delivery_money_checklist",
            "platform_issue": "platform_change_service_update",
            "refund_consumer": "consumer_warning_refund",
        }
        if topic_group in _TG_MAP:
            return _TG_MAP[topic_group]

        # 키워드 기반 힌트
        lowered = text.lower().replace(" ", "")
        for pattern_id, keywords in _CANDIDATE_TO_PATTERN_HINTS.items():
            if pattern_id == "delivery_money_checklist" and not (content_type or topic_group):
                continue
            if any(kw.replace(" ", "") in lowered for kw in keywords):
                return pattern_id

        return None

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _read_patterns(self) -> list[dict[str, Any]]:
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            patterns: list[dict[str, Any]] = data.get("patterns", [])
            logger.info(
                "%s | loaded %d patterns from %s",
                __name__,
                len(patterns),
                self._path,
            )
            return patterns
        except FileNotFoundError:
            logger.warning("%s | patterns file not found: %s", __name__, self._path)
        except json.JSONDecodeError as exc:
            logger.error("%s | JSON parse error in %s: %s", __name__, self._path, exc)
        return []

    def _score(
        self,
        pattern: dict[str, Any],
        combined: str,
        combined_lower: str,
        words: list[str],
        content_type: str,
        topic_group: str,
        *,
        topic_only: str = "",
    ) -> dict[str, Any]:
        pid: str = pattern.get("pattern_id", "")
        if pid in _DISABLED_PATTERN_IDS:
            return {
                "matched": False,
                "near_match": False,
                "pattern_id": pid,
                "pattern_title": pattern.get("title", ""),
                "confidence": 0,
                "matched_keywords": [],
                "negative_hits": [],
                "content_type_match": False,
                "topic_group_match": False,
                "reason": f"pattern {pid} is disabled by user preference",
            }
        match_kws: list[str] = pattern.get("match_keywords", [])
        neg_kws: list[str] = pattern.get("match_negative", [])
        p_ct: str = pattern.get("content_type", "")
        p_tg: str = pattern.get("topic_group", "")
        threshold = int(pattern.get("minimum_pattern_confidence", _DEFAULT_THRESHOLD))

        matched_kws = [kw for kw in match_kws if _kw_in(kw, combined_lower, words)]
        neg_hits = [neg for neg in neg_kws if _kw_in(neg, combined_lower, words)]

        ct_match = bool(content_type) and content_type == p_ct
        tg_match = bool(topic_group) and topic_group == p_tg

        kw_score = min(len(matched_kws) * _PER_KW_SCORE, _MAX_KW_SCORE)
        bonus = (_CT_BONUS if ct_match else 0) + (_TG_BONUS if tg_match else 0)
        penalty = len(neg_hits) * _NEG_PENALTY

        policy_signal_hits: list[str] = []
        if pid in _VIRAL_PATTERN_IDS_REQUIRING_ENTERTAINMENT_FOCUS:
            policy_signal_hits = [
                kw for kw in _POLICY_INDICATOR_KEYWORDS
                if kw in combined or kw.replace(" ", "") in combined.replace(" ", "")
            ]
            if len(policy_signal_hits) >= _MIN_POLICY_SIGNALS_FOR_PENALTY:
                penalty += _POLICY_SIGNAL_PENALTY
        strong_non_viral_hits: list[str] = []
        if pid in _VIRAL_PATTERN_IDS_REQUIRING_ENTERTAINMENT_FOCUS:
            strong_non_viral_hits = [
                kw for kw in _STRONG_NON_VIRAL_TOPIC_SIGNALS
                if kw in combined or kw.replace(" ", "") in combined.replace(" ", "")
            ]

        corporate_signal_hits: list[str] = []
        if pid in _PATTERNS_REJECTING_CORPORATE_SIGNALS:
            corporate_signal_hits = [
                kw for kw in _CORPORATE_INDICATOR_KEYWORDS if kw in combined
            ]
            if len(corporate_signal_hits) >= _MIN_CORPORATE_SIGNALS_FOR_PENALTY:
                penalty += _CORPORATE_SIGNAL_PENALTY

        broken_surface_reason = _detect_broken_topic_surface(topic_only or combined)

        confidence = max(0, min(100, kw_score + bonus - penalty))
        if strong_non_viral_hits:
            confidence = min(confidence, _STRONG_NON_VIRAL_CAP_CONFIDENCE)
        if broken_surface_reason:
            confidence = min(confidence, _BROKEN_SURFACE_CAP_CONFIDENCE)
        matched = confidence >= threshold
        # near_match: confidence 75~79 + content_type_match + topic_group_match + no neg_hits
        near_match = (
            not matched
            and not neg_hits
            and confidence >= 75
            and ct_match
            and tg_match
        )

        if broken_surface_reason:
            reason = f"broken topic surface ({broken_surface_reason}) capped confidence at {confidence}"
        elif strong_non_viral_hits:
            reason = f"non-entertainment/privacy/policy signals hit on viral pattern: {strong_non_viral_hits[:5]} → confidence {confidence}"
        elif corporate_signal_hits and len(corporate_signal_hits) >= _MIN_CORPORATE_SIGNALS_FOR_PENALTY:
            reason = f"corporate signals hit on restricted pattern: {corporate_signal_hits[:5]} → confidence {confidence}"
        elif policy_signal_hits and len(policy_signal_hits) >= _MIN_POLICY_SIGNALS_FOR_PENALTY:
            reason = f"policy signals hit on viral pattern: {policy_signal_hits[:5]} → confidence {confidence}"
        elif neg_hits:
            reason = f"negative keywords hit: {neg_hits} → confidence {confidence}"
        elif matched:
            reason = f"{len(matched_kws)} keyword(s) matched → confidence {confidence}"
        elif near_match:
            reason = f"near_match confidence={confidence} (ct_match+tg_match, below threshold {threshold})"
        else:
            reason = f"confidence {confidence} below threshold {threshold}"

        logger.debug(
            "%s | pattern=%s kw_hits=%d neg_hits=%d confidence=%d matched=%s near_match=%s",
            __name__,
            pid,
            len(matched_kws),
            len(neg_hits),
            confidence,
            matched,
            near_match,
        )
        return {
            "matched": matched,
            "near_match": near_match,
            "pattern_id": pid,
            "pattern_title": pattern.get("title", ""),
            "confidence": confidence,
            "matched_keywords": matched_kws,
            "negative_hits": neg_hits,
            "content_type_match": ct_match,
            "topic_group_match": tg_match,
            "reason": reason,
        }


# ------------------------------------------------------------------ #
# Module-level helpers                                                #
# ------------------------------------------------------------------ #

def _detect_broken_topic_surface(text: str) -> str:
    if not text:
        return ""
    if text.count("·") >= _MAX_TOPIC_MIDDOT_COUNT:
        return "too_many_middots"
    for marker in _BROKEN_SURFACE_MARKERS:
        if marker in text:
            return f"truncate_marker:{marker}"
    if len(text.split()) > _MAX_TOPIC_TOKEN_COUNT:
        return "too_many_tokens"
    for ending in _VERB_ENDING_FOLLOWED_BY_NOUN_PATTERN:
        if ending in text:
            return f"verb_then_noun:{ending.strip()}"
    return ""


def _kw_in(kw: str, text_lower: str, text_words: list[str]) -> bool:
    """키워드가 텍스트에 포함되는지 3가지 방법으로 검사.

    1. 대소문자 무시 exact substring  (예: 홈택스 in 홈택스에서...)
    2. 공백 제거 후 substring         (예: 세금환급 in 세금환급금...)
    3. 단어 prefix 매칭               (예: [반응, 갈린] prefix → 반응이/갈린이유)
       한국어 조사 처리를 위해 각 단어가 키워드 파트로 시작하는지 확인한다.
    """
    kw_lower = kw.lower()

    # 1. exact substring (handles 홈택스에서 ← 홈택스, ChatGPT를 ← GPT, etc.)
    if kw_lower in text_lower:
        return True

    # 2. space-normalized (handles 세금환급 in 세금 환급금 / 세금환급금)
    kw_compact = kw_lower.replace(" ", "")
    text_compact = text_lower.replace(" ", "")
    if kw_compact in text_compact:
        return True

    # 3. word-prefix (handles 반응이/갈린 ← 반응/갈린, multi-word keyword)
    parts = kw_lower.split()
    n = len(parts)
    if n == 0:
        return False
    words_lower = [w.lower() for w in text_words]
    return any(
        all(words_lower[i + j].startswith(parts[j]) for j in range(n))
        for i in range(len(words_lower) - n + 1)
    )


_CANDIDATE_TO_PATTERN_HINTS: dict[str, list[str]] = {
    "tax_refund_hometax_check": [
        "환급금", "홈택스", "국세환급금", "세금환급", "손택스",
        "종합소득세환급", "연말정산환급", "미수령환급금", "환급계좌",
    ],
    "viral_ott_reaction_decode": [
        "넷플릭스", "OTT", "드라마", "반응갈린", "시청자반응",
        "예능", "팬덤", "팬반응", "콘텐츠반응", "OTT반응",
    ],
    "ai_work_time_savings": [
        "ChatGPT", "챗GPT", "직장인", "AI업무", "업무자동화",
        "생산성", "시간절약", "검수시간", "반복업무", "AI도구",
    ],
    "delivery_money_checklist": [
        "배달앱", "배달료", "배달비", "배달의민족", "배민", "쿠팡이츠", "요기요",
        "무료배달", "최소주문금액", "배달비절약", "결제금액비교",
    ],
    "platform_change_service_update": [
        "서비스변경", "약관변경", "요금제변경", "멤버십변경", "서비스종료",
        "앱개편", "플랫폼변경", "구독료인상", "쿠팡멤버십", "OTT요금",
    ],
    "consumer_warning_refund": [
        "환불논란", "소비자피해", "결제오류", "개인정보유출", "서비스장애",
        "약관논란", "환불지연", "피해대응", "환불거부",
    ],
    "policy_deadline_support": [
        "지원금신청", "신청마감", "지원마감", "대상조건", "신청기간",
        "지원금대상", "청년지원", "소상공인지원", "정부지원",
    ],
    "corporate_issue_decode": [
        "삼성", "현대", "LG", "SK", "포스코",
        "카카오", "네이버", "쿠팡", "노조", "노동조합",
        "대화", "교섭", "임직원", "사측",
        "공식입장", "공시", "DART", "이사회", "주주",
        "구조조정", "사업개편", "조직개편",
    ],
}


def _no_match_result(reason: str) -> dict[str, Any]:
    return {
        "matched": False,
        "near_match": False,
        "pattern_id": None,
        "pattern_title": None,
        "confidence": 0,
        "matched_keywords": [],
        "negative_hits": [],
        "content_type_match": False,
        "topic_group_match": False,
        "reason": reason,
    }
