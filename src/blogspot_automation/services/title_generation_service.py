from __future__ import annotations

import re

from blogspot_automation.models.news_models import ScoredNewsCandidate, TitleCandidate
from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.news_taxonomy import (
    extract_public_benefit_keyword,
    is_delivery_money_text,
    is_policy_benefit_text,
    is_privacy_security_text,
    is_tax_refund_text,
)


HONORIFIC_BANNED = ("했습니다", "됩니다", "됐습니다", "합니다", "입니다")
CLICKBAIT_BANNED = ("충격", "경악", "발칵", "소름", "역대급", "난리났다", "무조건", "절대")
STRATEGY_BANNED_TITLE_PATTERNS = (
    "사람들이 놓친",
    "진짜 변수",
    "유행 뒤에 숨은 돈의 흐름",
    "결국 누가 더 내나",
    "충격 근황",
    "결국 터졌다",
    "소름 돋는 이유",
    "사생활 논란 총정리",
    "루머 진짜일까",
)

VIRAL_ISSUE_TEMPLATES: list[tuple[str, str]] = [
    ("반응분석", "{keyword} 반응이 갈린 이유, 사람들이 본 핵심 포인트"),
    ("화제분석", "{keyword}, 화제 된 이유보다 먼저 볼 반응 포인트"),
    ("팬덤구조", "{keyword} 반복 반응, 팬덤 소비 구조로 보면"),
    ("반응분석", "{keyword} 이후 댓글이 갈린 이유, 단순 결과보다 중요한 것"),
    ("커뮤니티분석", "{keyword} 논의가 커진 이유, 사람들이 불편해한 지점"),
    ("플랫폼분석", "{keyword} 변화, 시청자에게 미치는 실질 영향"),
    ("반응분석", "{keyword} 반응, 팬들이 본 핵심 장면"),
]
GOOD_TITLE_SIGNALS = (
    "확인하세요",
    "먼저 볼",
    "내 폰도 해당될까",
    "해당될까",
    "증거",
    "조건",
    "체크",
    "이유",
    "방법",
    "줄이는 법",
)

# 강한 이슈 키워드 뒤에 '화제'가 오면 중복 → 제거 대상
_REDUNDANT_HWAJAE_RE = re.compile(
    r"(논란|수수료|환불|연봉|이슈|변화|품절|피해|지연|AI)\s+화제"
)
# '화제' 조합 시 감점 대상 키워드 (delivery/refund/salary/AI 계열)
_HWAJAE_PENALTY_KW = ("논란", "수수료", "환불", "연봉", "피해", "지연")
_VIRAL_CORE_SUFFIXES = (
    "반응이 갈린 이유와 핵심 포인트",
    "반응이 갈린 이유",
    "사람들이 본 핵심 포인트",
    "핵심 포인트",
    "먼저 볼 3가지",
)
REFUND_KEYWORDS = (
    "환불", "피해", "결제", "카드", "고객센터", "소비자", "지연", "취소", "환급",
    "영업종료", "배송 중단", "연락 두절", "쇼핑몰", "이용 중단", "서비스 중단", "환불 가능", "피해 대응",
)
REFUND_TREND_BANNED = ("유행 뒤", "유행", "오픈런", "품절", "인증샷", "팬덤", "트렌드", "열풍")
REFUND_TEMPLATES: list[tuple[str, str]] = [
    ("생활체감", "{keyword}, 소비자가 먼저 볼 것"),
    ("손해회피", "{keyword}, 기다리면 손해인 이유"),
    ("소비자피해", "{keyword}, 소비자가 먼저 남길 증거"),
    ("손해회피", "{keyword}, 환불 전에 확인할 것"),
    ("소비자피해", "{keyword}, 결제 신뢰가 문제다"),
]
DELIVERY_TREND_BANNED = ("유행", "트렌드", "오픈런", "품절", "인증샷", "팬덤", "열풍")
DELIVERY_TEMPLATES: list[tuple[str, str]] = [
    ("돈문제", "{keyword}, 결제금액부터 확인할 이유"),
    ("생활체감", "{keyword}, 쿠폰보다 먼저 볼 것"),
    ("계산법", "{keyword}, 최종 결제금액 체크 방법"),
    ("생활체감", "{keyword}, 라이더와 소비자가 보는 기준"),
    ("역발상", "{keyword}, 가격표보다 중요한 것"),
]
POLICY_TREND_BANNED = ("유행", "트렌드", "오픈런", "품절", "인증샷", "팬덤", "열풍")
POLICY_BENEFIT_TEMPLATES: list[tuple[str, str]] = [
    ("신청정보", "{keyword}, 놓치기 전 확인할 것"),
    ("대상조건", "{keyword}, 대상 조건에서 갈리는 이유"),
    ("신청정보", "{keyword}, 신청 전 먼저 볼 것"),
    ("AI활용", "{keyword}, 놓치기 전 확인할 것"),
    ("마감체크", "{keyword}, 마감 전에 체크할 조건"),
]
CONTENT_ANGLE_TITLES: dict[str, list[tuple[str, str, int]]] = {
    "money_checklist": [
        ("실전절약", "무료배달이라더니 왜 더 비싸졌나", 170),
        ("실전절약", "쿠폰 받았는데 결제금액이 오른 이유", 168),
        ("체크리스트", "배달앱에서 싸게 시키는 사람들은 이것부터 본다", 166),
        ("손해방지", "배달비 아끼려다 더 쓰는 사람들이 놓치는 것", 164),
        ("체크리스트", "배달료 논란보다 먼저 봐야 할 결제창", 162),
    ],
    "consumer_warning": [
        ("손해방지", "환불 기다리기 전에 먼저 확인할 것", 160),
        ("소비자대응", "배송 중단 때 소비자가 놓치면 안 되는 것", 158),
        ("손해방지", "결제 취소가 늦어질 때 손해 줄이는 법", 156),
        ("소비자대응", "환불 논란에서 사람들이 가장 늦게 보는 것", 154),
    ],
    "policy_deadline": [
        ("신청정보", "지원금 신청 전 이것부터 확인하세요", 160),
        ("대상조건", "청년 지원금, 못 받기 전에 볼 조건", 158),
        ("마감체크", "신청 마감 전에 확인할 3가지", 156),
        ("대상조건", "대상 조건 하나로 갈리는 지원금", 154),
    ],
    "tax_refund": [
        ("홈택스조회", "세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", 178),
        ("지연대응", "세금 환급금이 늦어질 때 먼저 확인할 것", 174),
        ("계좌오류", "국세환급금 조회 전 계좌 오류부터 확인하세요", 172),
        ("조회경로", "홈택스 세금 환급금 조회, 대상보다 먼저 볼 항목", 170),
    ],
    "ai_work_tip": [
        ("업무팁", "AI 도구 바뀌면 직장인이 먼저 볼 것", 158),
        ("업무팁", "업무 줄여준다는 AI가 일을 늘릴 수도 있다", 156),
        ("업무기준", "AI 기능보다 중요한 건 사용 기준이다", 154),
        ("도구비교", "ChatGPT와 Claude, 내 업무에는 무엇이 맞을까", 153),
        ("프롬프트", "AI 프롬프트 쓰기 전 먼저 정할 3가지", 152),
        ("보안체크", "회사 자료를 AI에 넣기 전 지워야 할 정보", 151),
        ("자동화", "AI 자동화 시작 전 사람이 남겨야 할 검수 단계", 150),
    ],
    "trend_decode": [
        ("소비해석", "오픈런이 맛보다 먼저 파는 것", 156),
        ("소비해석", "품절 유행에 사람들이 몰리는 진짜 이유", 154),
        ("가격착시", "인증샷 때문에 더 비싸지는 소비", 152),
    ],
    "platform_change": [
        ("변경대응", "내 폰에서 갑자기 안 될 수 있는 서비스", 158),
        ("변경대응", "서비스 종료 공지, 사용자가 늦게 아는 이유", 156),
        ("체크리스트", "플랫폼 변경 전에 먼저 확인할 것", 154),
    ],
    "viral_issue_decode": [
        ("반응분석", "반응이 갈린 이유, 사람들이 본 핵심 포인트", 175),
        ("화제분석", "화제 된 이유, 시청자가 먼저 본 3가지", 173),
        ("팬덤구조", "반복되는 이유, 팬덤 소비 구조로 보면", 171),
        ("커뮤니티분석", "댓글이 갈린 이유, 단순 결과보다 중요한 것", 169),
        ("플랫폼분석", "변화가 시청자에게 미치는 실질 영향", 167),
    ],
}
LONG_TEMPLATES: list[tuple[str, str]] = [
    ("손해회피", "{keyword}, 지금 웃으면 안 되는 이유"),
    ("이면폭로", "모두가 {keyword} 말할 때 봐야 할 이면"),
    ("생활비", "{keyword}, 결제 전 확인할 이유"),
    ("돈문제", "{keyword}, 비용부터 확인할 이유"),
    ("체크리스트", "{keyword}, 먼저 체크할 한 가지"),
    ("논란반전", "{keyword} 논란, 문제는 다른 곳에 있다"),
    ("돈문제", "{keyword} 열풍, 누가 진짜 이득 보나"),
    ("트렌드", "{keyword} 반응 뜨거운 이유와 함정"),
]
SHORT_TEMPLATES: list[tuple[str, str]] = [
    ("확인형", "{keyword}, 먼저 확인할 것"),
    ("돈문제", "{keyword}, 비용부터 볼 이유"),
    ("체크리스트", "{keyword}, 체크할 조건"),
    ("역발상", "{keyword}, 왜 지금 커졌나"),
    ("손해회피", "{keyword}, 웃을 일이 아닌 이유"),
]
KEYWORD_CLEANUP_PHRASES = (
    "소비자와 사장님 모두 불만",
    "왜 커졌나",
    "진짜 이유",
    "관심 증가",
    "반응 폭발",
    "모두 불만",
    "대응법",
    "유행의",
)


class TitleGenerationService:
    def __init__(self, *, title_candidate_count: int = 7) -> None:
        self.title_candidate_count = max(1, title_candidate_count)

    def generate_titles(self, candidate: ScoredNewsCandidate) -> list[TitleCandidate]:
        raw = candidate.candidate.raw if isinstance(candidate.candidate.raw, dict) else {}
        # 영어 모드(2026-07-17): 이 서비스의 한국어 후킹 템플릿은 전부 우회하고
        # 영어 제목 빌더([키워드]+[각도]+[연도])를 쓴다.
        if is_english_mode():
            from blogspot_automation.services.title_candidate_service import _build_english_titles

            created_en: list[TitleCandidate] = []
            seen_en: set[str] = set()
            for idx, (title, title_type) in enumerate(
                _build_english_titles(topic=candidate.candidate.topic or "", raw=raw)
            ):
                if title in seen_en:
                    continue
                seen_en.add(title)
                created_en.append(
                    TitleCandidate(
                        title=title,
                        hook_type=title_type,
                        # 빌더 순서 = 각도 적합도 순 — 앞 후보에 가산점
                        ctr_score=max(40, 72 - idx * 4),
                        reason="English title formula: [keyword] + [angle] + [year].",
                    )
                )
            if created_en:
                return created_en
        hook_angle = raw.get("hook_angle", {}) if isinstance(raw.get("hook_angle"), dict) else {}
        content_angle = raw.get("content_angle", {}) if isinstance(raw.get("content_angle"), dict) else {}
        search_angle = raw.get("search_angle", {}) if isinstance(raw.get("search_angle"), dict) else {}
        content_type = str(content_angle.get("content_type") or "")
        search_demand_topic = str(search_angle.get("search_demand_topic") or "").strip()
        commercial_support_signal = bool(raw.get("commercial_support_signal") or search_angle.get("commercial_support_signal"))
        public_benefit_keyword = str(raw.get("public_benefit_keyword") or "").strip()
        if not public_benefit_keyword and not commercial_support_signal:
            public_benefit_keyword = extract_public_benefit_keyword(
                f"{candidate.candidate.topic} {candidate.candidate.summary}"
            )
        topic = self._extract_core_keyword(candidate.candidate.topic)
        safe_title_keyword = str(hook_angle.get("safe_title_keyword", "")).strip()
        if public_benefit_keyword:
            topic = public_benefit_keyword
        elif search_demand_topic and bool(search_angle.get("should_transform_title")) and not commercial_support_signal:
            topic = search_demand_topic
        if safe_title_keyword:
            topic = self._truncate_by_tokens(safe_title_keyword, 18)
        hook_signals = raw.get("hook_signals", {}) if isinstance(raw.get("hook_signals"), dict) else {}
        trend_signals = raw.get("trend_signals", {}) if isinstance(raw.get("trend_signals"), dict) else {}
        is_refund_issue = self._is_refund_issue(topic)
        is_delivery_issue = self._is_delivery_issue(topic)
        is_policy_benefit_issue = (
            str(raw.get("topic_group") or "") == "policy_benefit"
            or bool(public_benefit_keyword)
            or self._is_policy_benefit_issue(candidate.candidate.topic)
            or self._is_policy_benefit_issue(topic)
        )
        if public_benefit_keyword:
            topic = public_benefit_keyword
        elif is_policy_benefit_issue:
            topic = self._extract_policy_benefit_core_keyword(candidate.candidate.topic) or topic

        templates = self._hook_angle_templates(hook_angle) + self._select_templates(topic, hook_signals, trend_signals)

        created: list[TitleCandidate] = []
        seen: set[str] = set()
        for hook_type, title, ctr_score in self._contextual_news_title_candidates(
            original_topic=candidate.candidate.topic,
            working_topic=topic,
            content_type=content_type,
            topic_group=str(raw.get("topic_group") or ""),
            search_angle=search_angle,
            hook_angle=hook_angle,
            raw=raw,
        ):
            normalized = self._normalize_title(title)
            if not normalized or normalized in seen or self._has_banned_strategy_pattern(normalized):
                continue
            seen.add(normalized)
            created.append(
                TitleCandidate(
                    title=normalized,
                    hook_type=hook_type,
                    ctr_score=ctr_score,
                    reason="오늘 뉴스 주제 기반 후킹 제목입니다. 원문 제목보다 독자의 손해, 궁금증, 확인 이득을 우선합니다.",
                )
            )
        for hook_type, title, ctr_score in self._search_angle_title_candidates(search_angle):
            normalized = self._normalize_title(title)
            if not normalized or normalized in seen or self._has_banned_strategy_pattern(normalized):
                continue
            seen.add(normalized)
            created.append(
                TitleCandidate(
                    title=normalized,
                    hook_type=hook_type,
                    ctr_score=ctr_score,
                    reason="search_angle 기반 제목입니다. 기사 제목보다 독자의 검색 질문과 클릭 이유를 우선합니다.",
                )
            )
        for hook_type, title, ctr_score in self._content_angle_title_candidates(content_type):
            normalized = self._normalize_title(title)
            if not normalized or normalized in seen or self._has_banned_strategy_pattern(normalized):
                continue
            seen.add(normalized)
            created.append(
                TitleCandidate(
                    title=normalized,
                    hook_type=hook_type,
                    ctr_score=ctr_score,
                    reason="content_angle 기반 독자 질문형 제목입니다. 뉴스 원문보다 손해, 궁금증, 실전 이득을 우선합니다.",
                )
            )
        if is_policy_benefit_issue:
            policy_titles = (
                self._public_benefit_title_candidates(public_benefit_keyword)
                if public_benefit_keyword
                else self._policy_benefit_title_candidates(topic)
            )
            for hook_type, title, ctr_score in policy_titles:
                normalized = self._normalize_title(title)
                if not normalized or normalized in seen or self._has_banned_strategy_pattern(normalized):
                    continue
                seen.add(normalized)
                created.append(
                    TitleCandidate(
                        title=normalized,
                        hook_type=hook_type,
                        ctr_score=ctr_score,
                        reason="policy_benefit 전용 제목입니다. 신청, 마감, 대상 조건을 명확히 드러내고 trend 표현을 피합니다.",
                    )
                )
        if is_delivery_issue:
            for hook_type, title, ctr_score in self._delivery_money_title_candidates(topic):
                normalized = self._normalize_title(title)
                if not normalized or normalized in seen or self._has_banned_strategy_pattern(normalized):
                    continue
                seen.add(normalized)
                created.append(
                    TitleCandidate(
                        title=normalized,
                        hook_type=hook_type,
                        ctr_score=ctr_score,
                        reason="배달료, 쿠폰, 최종 결제금액 중 하나를 분명하게 짚는 delivery_money 전용 제목입니다.",
                    )
                )
        if content_type == "viral_issue_decode":
            for hook_type, title, ctr_score in self._viral_issue_decode_title_candidates(topic):
                normalized = self._normalize_title(title)
                if not normalized or normalized in seen or self._has_banned_strategy_pattern(normalized):
                    continue
                seen.add(normalized)
                created.append(
                    TitleCandidate(
                        title=normalized,
                        hook_type=hook_type,
                        ctr_score=ctr_score,
                        reason="viral_issue_decode 전용 제목입니다. 반응 구조와 핵심 포인트를 드러내고 루머·과장 표현을 피합니다.",
                    )
                )
        for hook_type, template in templates:
            title = self._compose_title(topic, template)
            if not title:
                continue
            if self._has_banned_strategy_pattern(title):
                continue
            if title in seen:
                continue
            seen.add(title)
            ctr_score = self._score_ctr(title, topic)
            reason = self._build_reason(title, ctr_score, hook_type)
            created.append(
                TitleCandidate(
                    title=title,
                    hook_type=hook_type,
                    ctr_score=ctr_score,
                    reason=reason,
                )
            )

        # 후보가 부족하면 기본 템플릿으로 채운다.
        fallback_templates = POLICY_BENEFIT_TEMPLATES if is_policy_benefit_issue else REFUND_TEMPLATES if is_refund_issue else DELIVERY_TEMPLATES if is_delivery_issue else [
            ("확인형", "{keyword}, 먼저 확인할 것"),
            ("이면폭로", "모두가 {keyword} 말할 때 봐야 할 이면"),
            ("체크리스트", "{keyword}, 체크할 조건"),
            ("손해회피", "{keyword}, 웃을 일이 아닌 이유"),
            ("트렌드", "{keyword}, 왜 지금 커졌나"),
        ]
        for hook_type, template in fallback_templates:
            if len(created) >= self.title_candidate_count:
                break
            title = self._compose_title(topic, template)
            if not title or title in seen or self._has_banned_strategy_pattern(title):
                continue
            seen.add(title)
            ctr_score = self._score_ctr(title, topic)
            reason = self._build_reason(title, ctr_score, hook_type)
            created.append(
                TitleCandidate(
                    title=title,
                    hook_type=hook_type,
                    ctr_score=ctr_score,
                    reason=reason,
                )
            )

        created.sort(key=lambda item: item.ctr_score, reverse=True)
        return created[: self.title_candidate_count]

    def select_best_title(self, titles: list[TitleCandidate]) -> TitleCandidate:
        if not titles:
            if is_english_mode():
                return TitleCandidate(
                    title="Today's AI Update: What Actually Changed",
                    hook_type="search",
                    ctr_score=40,
                    reason="No candidates — safe English default title.",
                )
            return TitleCandidate(
                title="지금 먼저 확인할 것",
                hook_type="확인형",
                ctr_score=40,
                reason="후보가 없어 안전한 기본 제목을 선택했다.",
            )
        return max(titles, key=lambda item: item.ctr_score)

    def _contextual_news_title_candidates(
        self,
        *,
        original_topic: str,
        working_topic: str,
        content_type: str,
        topic_group: str,
        search_angle: dict,
        hook_angle: dict,
        raw: dict,
    ) -> list[tuple[str, str, int]]:
        seed = self._contextual_news_seed(
            original_topic=original_topic,
            working_topic=working_topic,
            search_angle=search_angle,
            hook_angle=hook_angle,
            raw=raw,
        )
        core = self._contextual_news_core(seed)
        if content_type == "viral_issue_decode" or topic_group in {"ott_platform", "entertainment_sports", "fandom_consumer"}:
            core = self._clean_viral_issue_core(core)
        if not core:
            return []

        issue_profile = raw.get("issue_content_profile") if isinstance(raw.get("issue_content_profile"), dict) else {}
        profile_id = str(issue_profile.get("profile_id") or content_type or "").strip()
        templates = self._issue_profile_title_templates(profile_id=profile_id)
        templates += self._contextual_news_templates(
            content_type=content_type,
            topic_group=topic_group,
            angle_type=str(search_angle.get("angle_type") or raw.get("angle_type") or ""),
            core=core,
        )
        candidates: list[tuple[str, str, int]] = []
        seen: set[str] = set()
        for idx, (hook_type, template) in enumerate(templates):
            title = self._normalize_title(template.format(core=core))
            if not title or title in seen or not self._looks_natural(title):
                continue
            seen.add(title)
            candidates.append((hook_type, title, 210 - idx * 4))
        return candidates[:4]

    @staticmethod
    def _issue_profile_title_templates(*, profile_id: str) -> list[tuple[str, str]]:
        if profile_id == "reaction_decode":
            return [
                ("반응해석", "{core}, 반응이 갈린 진짜 지점"),
                ("관전포인트", "{core}, 장면보다 중요한 다음 포인트"),
                ("맥락해석", "{core}, 왜 지금 크게 번졌나"),
                ("팬덤맥락", "{core}, 팬들이 먼저 본 신호"),
            ]
        if profile_id == "timeline_context":
            return [
                ("맥락정리", "{core}, 지금 확인된 것과 아직 모르는 것"),
                ("타임라인", "{core}, 왜 오늘 이슈가 됐나"),
                ("쟁점정리", "{core}, 흐름을 바꾼 한 가지"),
            ]
        if profile_id == "trend_meaning":
            return [
                ("트렌드해석", "{core}, 왜 갑자기 퍼졌나"),
                ("밈분석", "{core}, 밈이 된 진짜 이유"),
                ("확산구조", "{core}, 사람들이 따라붙는 구조"),
            ]
        return []

    @staticmethod
    def _contextual_news_seed(
        *,
        original_topic: str,
        working_topic: str,
        search_angle: dict,
        hook_angle: dict,
        raw: dict,
    ) -> str:
        values = (
            search_angle.get("search_demand_topic"),
            raw.get("search_demand_topic"),
            raw.get("transformed_topic"),
            original_topic,
            raw.get("original_topic"),
            hook_angle.get("safe_title_keyword"),
            working_topic,
        )
        for value in values:
            text = " ".join(str(value or "").split()).strip(" ,.-:;!?\"'")
            if text:
                return text
        return ""

    def _contextual_news_core(self, seed: str) -> str:
        core = " ".join((seed or "").split()).strip(" ,.-:;!?\"'")
        if not core:
            return ""
        core = re.split(r"\s+[|\-]\s+", core)[0].strip(" ,.-:;!?\"'")
        cleanup_patterns = (
            (r"^(.*지원 종료).*$", r"\1"),
            (r"^(.*수수료 인상).*$", r"\1"),
            (r"\s*(신청하기|확인하기|조회하기)?\s*전(?:에)?\s*(먼저\s*)?(확인할|볼)\s*(설정|조건|항목|것|체크리스트)?$", ""),
            (r"\s*대상과\s*신청\s*방법$", " 대상"),
            (r"\s*대상과\s*사용기한\s*확인$", " 사용기한"),
            (r"\s*왜\s*관심이\s*커졌는지\s*확인$", ""),
            (r"\s*(소비자|이용자|시청자|직장인)?\s*(부담|영향|논쟁|반응)$", ""),
            (r"\s*(방법|기준|정리|가이드|확인|조회)$", ""),
        )
        for pattern, replacement in cleanup_patterns:
            core = re.sub(pattern, replacement, core).strip(" ,.-:;!?\"'")
        core = re.sub(r"\s+", " ", core).strip(" ,.-")
        if not core:
            return ""
        return self._trim_contextual_core_tail(self._truncate_by_tokens(core, 16))

    @staticmethod
    def _trim_contextual_core_tail(core: str) -> str:
        parts = core.split()
        weak_tail = {"소비자", "이용자", "시청자", "직장인", "구형", "스마트폰", "부담", "영향", "논쟁", "반응"}
        while len(parts) > 2 and parts[-1].strip(" ,.-") in weak_tail:
            parts.pop()
        return " ".join(parts).strip(" ,.-")

    @staticmethod
    def _contextual_news_templates(
        *,
        content_type: str,
        topic_group: str,
        angle_type: str,
        core: str,
    ) -> list[tuple[str, str]]:
        if topic_group == "privacy_security" or (
            angle_type == "consumer_warning" and is_privacy_security_text(core)
        ):
            return [
                ("보안체크", "{core}, 비밀번호부터 확인할 것"),
                ("계정점검", "{core}, 같은 비밀번호 쓴 계정도 봐야 할까"),
                ("피싱주의", "{core}, 피싱 문자 전에 확인할 3가지"),
            ]
        if content_type in {"consumer_warning"} or topic_group == "refund_consumer" or angle_type == "refund_action":
            return [
                ("소비자대응", "{core}, 소비자가 먼저 남길 증거"),
                ("손해회피", "{core}, 기다리기 전 확인할 기록"),
                ("체크리스트", "{core}, 대응 전에 볼 3가지"),
            ]
        if content_type in {"money_checklist"} or topic_group == "delivery_money" or angle_type == "money_compare":
            return [
                ("돈문제", "{core}, 결제금액부터 확인할 이유"),
                ("체크리스트", "{core}, 결제 전 먼저 볼 3가지"),
                ("손해회피", "{core}, 놓치면 더 내는 조건"),
            ]
        if content_type in {"policy_deadline", "policy_benefit"} or topic_group == "policy_benefit":
            return [
                ("대상조건", "{core}, 대상 조건에서 갈리는 이유"),
                ("마감체크", "{core}, 마감 전에 확인할 조건"),
                ("신청정보", "{core}, 신청 전 먼저 볼 3가지"),
            ]
        if content_type == "platform_change" or topic_group == "platform_issue" or angle_type == "platform_check":
            return [
                ("변경대응", "{core}, 기존 이용자가 먼저 볼 3가지"),
                ("체크리스트", "{core}, 변경 전 확인할 조건"),
                ("영향분석", "{core}, 뭐가 달라지는지 보는 기준"),
            ]
        if content_type == "viral_issue_decode" or topic_group in {"ott_platform", "entertainment_sports", "fandom_consumer"}:
            return [
                ("반응분석", "{core} 반응이 갈린 이유, 먼저 볼 3가지"),
                ("화제분석", "{core}, 사람들이 먼저 본 포인트"),
                ("구조분석", "{core}, 반응보다 중요한 구조"),
            ]
        return [
            ("확인형", "{core}, 먼저 확인할 3가지"),
            ("손해회피", "{core}, 놓치면 손해인 이유"),
            ("체크리스트", "{core}, 지금 볼 기준"),
        ]

    def _select_templates(
        self,
        keyword: str,
        hook_signals: dict,
        trend_signals: dict,
    ) -> list[tuple[str, str]]:
        templates: list[tuple[str, str]] = list(LONG_TEMPLATES)

        prioritized: list[tuple[str, str]] = []
        if self._is_policy_benefit_issue(keyword):
            non_trend_templates = [
                item for item in templates + SHORT_TEMPLATES
                if not self._contains_policy_banned_trend(item[1])
            ]
            return POLICY_BENEFIT_TEMPLATES + non_trend_templates
        if self._is_refund_issue(keyword):
            non_trend_templates = [
                item for item in templates + SHORT_TEMPLATES
                if item[0] != "트렌드" and not self._contains_refund_banned_trend(item[1])
            ]
            return REFUND_TEMPLATES + non_trend_templates
        if self._is_delivery_issue(keyword):
            non_trend_templates = [
                item for item in templates + SHORT_TEMPLATES
                if item[0] != "트렌드" and not self._contains_delivery_banned_trend(item[1])
            ]
            return DELIVERY_TEMPLATES + non_trend_templates

        if bool(hook_signals.get("money")):
            prioritized.extend([
                ("돈문제", "{keyword}, 비용부터 확인할 이유"),
                ("손해회피", "{keyword}, 지금 웃으면 안 되는 이유"),
            ])
        if bool(hook_signals.get("life")):
            prioritized.extend([
                ("생활체감", "{keyword}, 먼저 체크할 한 가지"),
                ("생활체감", "{keyword} 반응 뜨거운 이유와 함정"),
            ])
        if any(bool(value) for value in trend_signals.values()):
            prioritized.extend([
                ("트렌드", "{keyword} 열풍, 누가 진짜 이득 보나"),
                ("트렌드", "{keyword}, 비용부터 확인할 이유"),
            ])
        if bool(hook_signals.get("controversy")):
            prioritized.extend([
                ("논란반전", "{keyword} 논란, 문제는 다른 곳에 있다"),
                ("이면폭로", "모두가 {keyword} 말할 때 봐야 할 이면"),
            ])
        if bool(hook_signals.get("famous_entity")):
            prioritized.insert(0, ("확인형", "{keyword}, 먼저 확인할 것"))

        # 우선순위 템플릿 + 기본 템플릿
        return prioritized + templates + SHORT_TEMPLATES

    def _hook_angle_templates(self, hook_angle: dict) -> list[tuple[str, str]]:
        if not hook_angle:
            return []
        gap = str(hook_angle.get("curiosity_gap", ""))
        impact = str(hook_angle.get("money_or_life_impact", ""))
        templates: list[tuple[str, str]] = []
        if "누가 비용" in gap or "최종 결제" in impact:
            templates.extend([
                ("돈문제", "{keyword}, 결제금액부터 확인할 이유"),
                ("계산법", "{keyword}, 최종 결제금액 체크 방법"),
                ("생활체감", "{keyword}, 쿠폰보다 먼저 볼 것"),
            ])
        elif "기다리면 손해" in gap or "환불" in impact:
            templates.extend([
                ("생활체감", "{keyword}, 소비자가 먼저 볼 것"),
                ("손해회피", "{keyword}, 기다리면 손해인 이유"),
                ("소비자대응", "{keyword}, 소비자가 먼저 남길 증거"),
            ])
        elif "업무 기준" in gap or "생산성" in impact:
            templates.extend([
                ("역발상", "{keyword}, 기능보다 중요한 기준"),
                ("업무팁", "{keyword}, 직장인이 먼저 볼 설정"),
                ("손해회피", "{keyword}, 지금 확인할 것"),
            ])
        elif "인증 욕구" in gap or "인증 소비" in impact:
            templates.extend([
                ("트렌드", "{keyword}, 사람들이 몰리는 진짜 이유"),
                ("이면폭로", "{keyword}, 인증샷 뒤의 소비 심리"),
                ("손해회피", "{keyword}, 따라가기 전 볼 것"),
            ])
        elif "평가가 갈린" in gap or "팬 반응" in impact:
            templates.extend([
                ("논란반전", "{keyword}, 팬들 평가가 갈린 이유"),
                ("확인형", "{keyword}, 보기 전에 확인할 것"),
                ("역발상", "{keyword}, 반응이 엇갈린 포인트"),
            ])
        return templates

    def _score_ctr(self, title: str, keyword: str) -> int:
        score = 50
        lowered = title.lower()
        if keyword and keyword.lower() in lowered:
            score += 10

        if any(token in title for token in ("손해", "비용", "돈", "가격", "수수료", "지원금")):
            score += 8
        if any(token in title for token in ("이유", "함정", "확인", "체크", "조건", "증거", "방법")):
            score += 8
        if any(token in title for token in GOOD_TITLE_SIGNALS):
            score += 12
        if any(token in title for token in ("유행", "품절", "오픈런", "밈")):
            score += 8
        if "화제" in title:
            if any(kw in title for kw in _HWAJAE_PENALTY_KW):
                score -= 5
            else:
                score += 4
        if "왜" in title:
            score += 6
        if any(token in title for token in ("논란", "이슈")) and not any(token in title for token in GOOD_TITLE_SIGNALS):
            score -= 12
        if len(title) <= 35:
            score += 5

        if self._is_refund_issue(f"{keyword} {title}"):
            if "소비자가 먼저 볼 것" in title:
                score += 34
            elif any(token in title for token in ("소비자가 먼저 남길 증거", "기다리면 손해", "결제 신뢰", "환불 전에 확인", "대응 전에 확인")):
                score += 12
            if any(token in title for token in REFUND_TREND_BANNED):
                score -= 25
        if self._is_delivery_issue(f"{keyword} {title}"):
            if any(token in title for token in ("결제금액부터 확인할 이유", "최종 결제금액 체크 방법")):
                score += 24
            elif any(token in title for token in ("쿠폰보다 먼저 볼 것", "라이더와 소비자가 보는 기준", "가격표보다 중요한 것")):
                score += 16
            if any(token in title for token in DELIVERY_TREND_BANNED):
                score -= 35

        if self._is_policy_benefit_issue(f"{keyword} {title}"):
            if any(token in title for token in ("놓치기 전 확인할 것", "신청 전 먼저 볼 것", "마감 전에 체크할 조건", "대상 조건")):
                score += 35
            if any(token in title for token in POLICY_TREND_BANNED):
                score -= 45
            if "대상 조" in title:
                score -= 35

        if any(token in title for token in CLICKBAIT_BANNED):
            score -= 30
        if self._has_banned_strategy_pattern(title):
            score -= 90
        if re.search(r"(논란|이슈)\s*,\s*(결국|진짜)", title):
            score -= 45
        if any(token in title for token in HONORIFIC_BANNED):
            score -= 20

        if self._is_too_generic(title):
            score -= 60 if "세금 환급" in title or "지원금 신청 전" in title else 10
        return max(0, score)

    def _is_too_generic(self, title: str) -> bool:
        too_generic_titles = {
            "지원금 신청 전 이것부터 확인하세요",
            "세금 환급 신청 전 이것부터 확인하세요",
            "세금 환급 대상과 조회 방법 먼저 확인하세요",
            "세금 환급 대상인지 먼저 확인할 것",
        }
        if title in too_generic_titles:
            return True
        concrete_terms = (
            "고유가", "청년", "홈택스", "손택스", "카카오톡", "크롬", "쿠팡", "환불",
            "대상 조건", "사용기한", "지급일", "사용처", "증거", "설정", "국세환급금", "환급금",
        )
        if any(term in title for term in concrete_terms):
            return False
        generic_patterns = ("최신 소식", "정리", "요약", "알아보기", "체크")
        return any(pattern in title for pattern in generic_patterns)

    @staticmethod
    def _tax_refund_title_keyword(text: str) -> str:
        compact = " ".join((text or "").split())
        if "국세환급금" in compact:
            return "국세환급금"
        if "미수령" in compact and "환급" in compact:
            return "미수령 환급금"
        if "종합소득세" in compact:
            return "종합소득세 환급금"
        if "연말정산" in compact:
            return "연말정산 환급금"
        return "세금 환급금"

    def _build_reason(self, title: str, ctr_score: int, hook_type: str) -> str:
        if ctr_score >= 78:
            return f"{hook_type} 후킹이 강하고 핵심 단어가 살아 있어 클릭 유도가 좋다."
        if ctr_score >= 65:
            return f"{hook_type} 관점은 유효하지만 후킹 단어 밀도는 중간 수준이다."
        return f"{hook_type} 방향은 맞지만 표현이 다소 일반적이라 개선 여지가 있다."

    def _extract_core_keyword(self, topic: str) -> str:
        compact = " ".join((topic or "").split()).strip()
        if not compact:
            return "이슈"
        policy_keyword = self._extract_policy_benefit_core_keyword(compact)
        if policy_keyword:
            return policy_keyword
        refund_keyword = self._extract_refund_core_keyword(compact)
        if refund_keyword:
            return refund_keyword
        delivery_keyword = self._extract_delivery_core_keyword(compact)
        if delivery_keyword:
            return delivery_keyword
        compact = re.split(r"[,:;!?]", compact)[0].strip()
        for phrase in KEYWORD_CLEANUP_PHRASES:
            compact = compact.replace(phrase, "")
        compact = re.sub(r"\s+화제\s*$", "", compact)
        compact = re.sub(r"\s+", " ", compact).strip(" ,.-")
        if not compact:
            compact = "이슈"
        return self._truncate_by_tokens(compact, 18)

    def _extract_refund_core_keyword(self, topic: str) -> str:
        compact = " ".join((topic or "").split()).strip(" ,.-")
        if not self._is_refund_issue(compact):
            return ""
        lead = re.split(r"[,:;!?]", compact)[0].strip(" ,.-")
        brand_match = re.search(r"(쇼핑몰\s+[^\s,]+|[가-힣A-Za-z0-9]+)", lead)
        brand = brand_match.group(1).strip() if brand_match else lead
        if "영업종료" in compact:
            return self._truncate_by_tokens(f"{brand} 영업종료", 18)
        if "환불" in compact:
            return self._truncate_by_tokens(f"{brand} 환불 논란", 18)
        if "배송 중단" in compact or "이용 중단" in compact or "서비스 중단" in compact:
            return self._truncate_by_tokens(f"{brand} 이용 중단", 18)
        return ""

    def _is_refund_issue(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(keyword in lowered for keyword in REFUND_KEYWORDS)

    def _contains_refund_banned_trend(self, text: str) -> bool:
        return any(keyword in text for keyword in REFUND_TREND_BANNED)

    def _content_angle_title_candidates(self, content_type: str) -> list[tuple[str, str, int]]:
        return list(CONTENT_ANGLE_TITLES.get(content_type, []))

    def _search_angle_title_candidates(self, search_angle: dict) -> list[tuple[str, str, int]]:
        if not search_angle:
            return []
        if bool(search_angle.get("commercial_support_signal")) and not str(search_angle.get("public_benefit_keyword") or "").strip():
            return []
        demand_topic = str(search_angle.get("search_demand_topic") or "").strip()
        original_topic = str(search_angle.get("original_topic") or "").strip()
        angle_type = str(search_angle.get("angle_type") or "")
        questions = [str(item) for item in search_angle.get("reader_search_questions") or []]
        if not demand_topic:
            return []
        if angle_type == "tax_refund":
            keyword = self._tax_refund_title_keyword(demand_topic)
            return [
                ("홈택스조회", f"{keyword} 조회 전 홈택스에서 먼저 볼 3가지", 198),
                ("지연대응", f"{keyword}이 늦어질 때 먼저 확인할 것", 192),
                ("계좌오류", "국세환급금 조회 전 계좌 오류부터 확인하세요", 188),
                ("조회경로", "홈택스 세금 환급금 조회, 대상보다 먼저 볼 항목", 186),
            ]
        if angle_type in {"benefit_howto", "deadline_check"}:
            keyword = self._extract_policy_benefit_core_keyword(demand_topic) or demand_topic
            if "이용권" in demand_topic:
                benefit_name = (
                    demand_topic
                    .replace(" 대상과 사용기한 확인", "")
                    .replace(" 대상 먼저 확인", "")
                    .strip(" ,.-")
                )
                return [
                    ("기한체크", f"{benefit_name}, 사용기한 전에 볼 조건", 188),
                    ("대상조건", f"{benefit_name}, 대상 먼저 확인하세요", 182),
                ]
            return [
                ("신청정보", f"{keyword} 신청 전 이것부터 확인하세요", 188),
                ("대상조건", f"{keyword} 대상 조건, 놓치기 전 확인할 것", 182),
            ]
        if angle_type == "platform_check":
            if "카카오톡" in demand_topic:
                return [
                    ("기기확인", "카카오톡 지원 종료, 내 폰도 해당될까", 188),
                    ("백업체크", "카카오톡 지원 종료 전 백업부터 확인하세요", 176),
                ]
            return [
                ("변경확인", f"{demand_topic}", 180),
                ("체크리스트", f"{demand_topic}, 먼저 볼 체크리스트", 172),
            ]
        if angle_type == "refund_action":
            return [
                ("증거확보", "환불 지연 때 소비자가 먼저 남겨야 할 증거", 188),
                ("피해대응", "환불 지연, 기다리기 전 확인할 기록", 174),
            ]
        if angle_type == "consumer_warning" and is_privacy_security_text(f"{demand_topic} {original_topic}"):
            return [
                ("보안체크", f"{demand_topic}", 188),
                ("비밀번호", "개인정보 안내 뒤 비밀번호부터 확인할 것", 178),
            ]
        if angle_type == "ai_setting":
            return [
                ("설정확인", f"{demand_topic}", 184),
                ("업무설정", "크롬 AI 기능 켜기 전에 확인할 설정", 182),
            ]
        if angle_type == "money_compare":
            return [
                ("비교체크", f"{demand_topic}", 178),
                ("결제확인", "결제 전 최종금액부터 확인하세요", 168),
            ]
        if questions:
            return [("검색질문", questions[0].rstrip("?") + " 확인", 150)]
        return []

    def _public_benefit_title_candidates(self, keyword: str) -> list[tuple[str, str, int]]:
        core = (keyword or "").strip()
        if not core:
            return []
        if is_tax_refund_text(core):
            tax_keyword = self._tax_refund_title_keyword(core)
            return [
                ("홈택스조회", f"{tax_keyword} 조회 전 홈택스에서 먼저 볼 3가지", 198),
                ("지연대응", f"{tax_keyword}이 늦어질 때 먼저 확인할 것", 192),
                ("계좌오류", "국세환급금 조회 전 계좌 오류부터 확인하세요", 188),
                ("조회경로", "홈택스 세금 환급금 조회, 대상보다 먼저 볼 항목", 186),
                ("공식확인", f"{tax_keyword} 공식 안내에서 먼저 볼 항목", 176),
            ]
        return [
            ("신청정보", f"{core} 신청 전 이것부터 확인하세요", 190),
            ("대상조건", f"{core} 대상 조건, 놓치기 전 확인할 것", 184),
            ("마감주의", f"{core} 신청 마감 전 확인할 조건", 182),
            ("지급방식", f"{core} 지급일과 신청방법 정리", 180),
            ("사용처확인", f"{core} 사용처, 결제 전 확인할 것", 178),
            ("손해방지", f"{core} 못 받기 전 체크할 서류와 조건", 176),
            ("공식확인", f"{core} 공식 공고에서 먼저 볼 항목", 170),
        ]

    def _policy_benefit_title_candidates(self, keyword: str) -> list[tuple[str, str, int]]:
        core = self._extract_policy_benefit_core_keyword(keyword) or keyword
        if is_tax_refund_text(core):
            tax_keyword = self._tax_refund_title_keyword(core)
            return [
                ("홈택스조회", f"{tax_keyword} 조회 전 홈택스에서 먼저 볼 3가지", 156),
                ("지연대응", f"{tax_keyword}이 늦어질 때 먼저 확인할 것", 152),
                ("계좌오류", "국세환급금 조회 전 계좌 오류부터 확인하세요", 150),
                ("조회경로", "홈택스 세금 환급금 조회, 대상보다 먼저 볼 항목", 148),
                ("공식확인", f"{tax_keyword} 공식 안내에서 먼저 볼 항목", 142),
            ]
        return [
            ("신청정보", f"{core} 신청 전 먼저 볼 것", 146),
            ("대상조건", f"{core} 대상 조건에서 갈리는 이유", 142),
            ("마감주의", f"{core} 마감 전에 체크할 조건", 140),
            ("지급방식", f"{core} 지급 방식과 사용처 확인", 138),
            ("손해방지", f"{core} 못 받기 전에 확인할 것", 136),
            ("공식확인", f"{core} 공식 공고에서 먼저 볼 항목", 132),
        ]

    def _extract_policy_benefit_core_keyword(self, topic: str) -> str:
        compact = " ".join((topic or "").split()).strip(" ,.-")
        public_benefit_keyword = extract_public_benefit_keyword(compact)
        if public_benefit_keyword:
            return public_benefit_keyword
        if not self._is_policy_benefit_issue(compact):
            return ""
        lead = re.split(r"[,:;!?]", compact)[0].strip(" ,.-")
        text = compact.replace(" ", "")
        if "청년" in text and "지원금" in text and ("신청" in text or "마감" in text):
            return "청년 지원금 신청 마감"
        if "청년" in text and "지원금" in text and ("대상" in text or "조건" in text):
            return "청년 지원금 대상 조건"
        if "청년" in text and "지원" in text:
            return "청년 지원금 대상 조건"
        if "교통비" in text and "지원" in text:
            return "교통비 지원 신청"
        if "세금" in text and "환급" in text:
            return "세금 환급 신청"
        if "소상공인" in text and "지원" in text:
            return "소상공인 지원금 신청"
        if "자영업자" in text and "지원" in text:
            return "자영업자 지원금 신청"
        if "부모" in text and "지원" in text:
            return "부모 지원금 대상 조건"
        if "정부" in text and "지원" in text:
            return "정부 지원금 신청 조건"
        if "환급" in text:
            return "환급 신청 조건"
        if "지원금" in text and "마감" in text:
            return "지원금 신청 마감"
        if "지원금" in text:
            return "지원금 대상 조건"
        return self._truncate_by_tokens(lead, 18)

    def _is_policy_benefit_issue(self, text: str) -> bool:
        return is_policy_benefit_text(text)

    def _contains_policy_banned_trend(self, text: str) -> bool:
        return any(keyword in text for keyword in POLICY_TREND_BANNED)

    def _viral_issue_decode_title_candidates(self, keyword: str) -> list[tuple[str, str, int]]:
        core = self._clean_viral_issue_core(self._truncate_by_tokens(keyword, 16) or "이슈")
        particle = _subject_particle(core)
        return [
            ("반응분석", f"{core} 반응이 갈린 이유, 사람들이 본 핵심 포인트", 175),
            ("화제분석", f"{core}{particle} 화제 된 이유, 시청자가 먼저 본 3가지", 173),
            ("팬덤구조", f"{core} 반복 반응, 팬덤 소비 구조로 보면", 170),
            ("플랫폼분석", f"{core} 반응, 플랫폼·소비 구조 해석", 168),
            ("커뮤니티분석", f"{core} 이후 댓글이 갈린 이유", 165),
        ]

    @staticmethod
    def _clean_viral_issue_core(value: str) -> str:
        core = " ".join((value or "").split()).strip(" ,.-:;!?\"'")
        core = re.sub(r"\s*반응이\s*갈린\s*이유.*$", "", core).strip()
        core = re.sub(r"\s*사람들이\s*본.*$", "", core).strip()
        core = re.sub(r"\s*핵심\s*포인트.*$", "", core).strip()
        core = re.sub(r"\s*먼저\s*볼\s*3가지.*$", "", core).strip()
        for suffix in _VIRAL_CORE_SUFFIXES:
            if core.endswith(suffix):
                core = core[: -len(suffix)]
        core = re.sub(r"\s+", " ", core).strip(" ,.-:;!?\"'")
        return core or "이슈"

    def _delivery_money_title_candidates(self, keyword: str) -> list[tuple[str, str, int]]:
        core = self._extract_delivery_core_keyword(keyword) or keyword
        if "배달료" not in core and "배달비" not in core and "배달앱" not in core:
            core = "배달료 논란"
        return [
            ("생활비", f"{core}, 결제금액부터 확인할 이유", 130),
            ("생활비", f"{core}, 무료배달보다 먼저 볼 것", 126),
            ("이면폭로", f"{core}, 쿠폰 뒤에 숨은 결제 구조", 124),
            ("소비자피해", f"{core}, 소비자가 놓치기 쉬운 한 가지", 120),
            ("계산법", f"{core}, 라이더와 소비자의 계산법", 118),
        ]

    def _extract_delivery_core_keyword(self, topic: str) -> str:
        compact = " ".join((topic or "").split()).strip(" ,.-")
        if not self._is_delivery_issue(compact):
            return ""
        if "실시간" in compact and "배달료" in compact and "논란" in compact:
            return "실시간 배달료 논란"
        if "배달료" in compact and "논란" in compact:
            return "배달료 논란"
        if "배달비" in compact and "논란" in compact:
            return "배달비 논란"
        if "배달앱" in compact and "수수료" in compact:
            return "배달앱 수수료 논란"
        if "배달의민족" in compact:
            return "배달의민족 수수료 논란" if "수수료" in compact else "배달의민족 논란"
        if "무료배달" in compact or "쿠폰" in compact:
            return "배달앱 쿠폰 조건"
        return ""

    def _is_delivery_issue(self, text: str) -> bool:
        return is_delivery_money_text(text)

    def _contains_delivery_banned_trend(self, text: str) -> bool:
        return any(keyword in text for keyword in DELIVERY_TREND_BANNED)

    @staticmethod
    def _has_banned_strategy_pattern(title: str) -> bool:
        compact = " ".join((title or "").split())
        if any(pattern in compact for pattern in STRATEGY_BANNED_TITLE_PATTERNS):
            return True
        if any(pattern in compact for pattern in CLICKBAIT_BANNED):
            return True
        if re.search(r"(논란|이슈)\s*,\s*(결국|진짜)", compact):
            return True
        return False

    def _compose_title(self, keyword: str, template: str) -> str:
        title = self._normalize_title(template.format(keyword=keyword))
        if len(title) <= 35 and self._looks_natural(title) and not self._has_banned_strategy_pattern(title):
            return title

        for short_template in SHORT_TEMPLATES:
            short_title = self._normalize_title(short_template[1].format(keyword=keyword))
            if (
                len(short_title) <= 35
                and self._looks_natural(short_title)
                and not self._has_banned_strategy_pattern(short_title)
            ):
                return short_title

        trimmed_keyword = self._truncate_by_tokens(keyword, 14)
        fallback_title = self._normalize_title(f"{trimmed_keyword}, 먼저 확인할 것")
        if len(fallback_title) <= 35 and self._looks_natural(fallback_title):
            return fallback_title
        return self._truncate_by_tokens(fallback_title, 35)

    def _normalize_title(self, title: str) -> str:
        compact = " ".join(title.split()).strip()
        compact = re.sub(r"\s+,", ",", compact)
        compact = re.sub(r"\s{2,}", " ", compact)
        compact = re.sub(r"대상 조(?!건)", "대상 조건", compact)

        # 금지 표현 완화
        for bad in HONORIFIC_BANNED:
            compact = compact.replace(bad, "")
        for bad in CLICKBAIT_BANNED:
            compact = compact.replace(bad, "")
        compact = _REDUNDANT_HWAJAE_RE.sub(r"\1", compact)
        compact = " ".join(compact.split()).strip(" ,.-")

        # 35자 이내 우선: 자연스럽게 컷
        if len(compact) > 35:
            compact = self._truncate_by_tokens(compact, 35)

        return compact

    def _truncate_by_tokens(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        tokens = text.split()
        if not tokens:
            return text[:max_len].rstrip(" ,.-")
        output: list[str] = []
        for token in tokens:
            candidate = " ".join(output + [token]).strip()
            if len(candidate) > max_len:
                break
            output.append(token)
        if output:
            return " ".join(output).strip(" ,.-")
        # 단어 하나가 너무 긴 경우만 최소 절단
        return text[:max_len].rstrip(" ,.-")

    def _looks_natural(self, title: str) -> bool:
        # "소비자와 사" 같은 단편 방지
        bad_ending_tokens = ("와", "과", "및", "의", "이", "가", "은", "는")
        parts = title.split()
        if not parts:
            return False
        last = parts[-1].strip(" ,.-")
        if last == "것":
            return True
        if len(last) <= 1:
            return False
        return last not in bad_ending_tokens


def _subject_particle(word: str) -> str:
    last = (word or "").strip()[-1:] or ""
    code = ord(last) if last else 0
    if 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0:
        return "이"
    return "가"
