from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueContentProfile:
    profile_id: str
    profile_name: str
    intent_mode: str
    title_mode: str
    primary_goal: str
    lead_rule: str
    required_sections: tuple[str, ...]
    avoid_sections: tuple[str, ...]
    answer_engine_mode: str
    reader_question_style: str
    cta_style: str
    recommended_content_type: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_sections"] = list(self.required_sections)
        data["avoid_sections"] = list(self.avoid_sections)
        return data


class IssueContentProfileService:
    """Selects the writing frame that best fits each news issue."""

    PROBLEM_CONTENT_TYPES = frozenset(
        {
            "policy_deadline",
            "tax_refund",
            "money_checklist",
            "consumer_warning",
            "platform_change",
            "ai_work_tip",
        }
    )
    REACTION_CONTENT_TYPES = frozenset({"viral_issue_decode"})
    TREND_CONTENT_TYPES = frozenset({"trend_decode"})
    WEAK_CONTENT_TYPES = frozenset({"", "general_life", "today_issue", "today_issue_explainer"})

    REACTION_TOPIC_GROUPS = frozenset({"entertainment_sports", "ott_platform", "fandom_consumer"})
    TREND_TOPIC_GROUPS = frozenset({"trend_meme"})
    PROBLEM_TOPIC_GROUPS = frozenset(
        {
            "delivery_money",
            "refund_consumer",
            "privacy_security",
            "policy_benefit",
            "platform_issue",
            "ai_work",
        }
    )

    PROBLEM_KEYWORDS = (
        "신청",
        "마감",
        "대상",
        "조건",
        "지원금",
        "환급",
        "환불",
        "반품",
        "배송",
        "택배",
        "회수",
        "결제",
        "요금",
        "인상",
        "종료",
        "오류",
        "장애",
        "피해",
        "개인정보",
        "유출",
        "보상",
        "쿠폰",
        "세금",
        "보험",
        "계좌",
    )
    REACTION_KEYWORDS = (
        "배우",
        "가수",
        "아이돌",
        "드라마",
        "영화",
        "예능",
        "방송",
        "시청률",
        "넷플릭스",
        "디즈니",
        "티빙",
        "쿠팡플레이",
        "팬",
        "팬덤",
        "콘서트",
        "컴백",
        "프로야구",
        "kbo",
        "축구",
        "야구",
        "농구",
        "배구",
        "득점",
        "우승",
        "순위",
        "대표팀",
        "월드컵",
        "챔피언스리그",
        "손흥민",
        "이강인",
        "김민재",
        "류현진",
    )
    TREND_KEYWORDS = ("밈", "챌린지", "유행", "릴스", "쇼츠", "틱톡", "인스타", "커뮤니티", "화제")

    _PROFILES: dict[str, IssueContentProfile] = {
        "problem_solution": IssueContentProfile(
            profile_id="problem_solution",
            profile_name="문제해결형",
            intent_mode="actionable_solution",
            title_mode="손실, 마감, 조건, 확인 순서 중심",
            primary_goal="독자가 지금 무엇을 확인하고 어떤 순서로 움직여야 하는지 바로 알게 한다.",
            lead_rule="첫 문단에서 대상, 핵심 변화, 지금 확인할 순서를 바로 답한다.",
            required_sections=("핵심 답변", "대상과 조건", "지금 확인할 순서", "예외와 주의점", "FAQ"),
            avoid_sections=("반응만 나열", "근거 없는 전망", "문제 없는 이슈에 억지 해결법 붙이기"),
            answer_engine_mode="direct_answer_checklist",
            reader_question_style="어떻게 확인하나, 누가 대상인가, 무엇을 먼저 해야 하나",
            cta_style="다음 확인은 블로그 내부 관련 글로 이어지게 한다.",
            recommended_content_type="consumer_warning",
        ),
        "reaction_decode": IssueContentProfile(
            profile_id="reaction_decode",
            profile_name="반응·관전포인트형",
            intent_mode="reaction_context",
            title_mode="반응이 갈린 지점, 맥락, 다음 관전 포인트 중심",
            primary_goal="연예, 스포츠, OTT 이슈에서 왜 사람들이 반응했는지와 다음에 볼 포인트를 정리한다.",
            lead_rule="첫 문단에서 사건보다 반응이 생긴 이유와 관전 포인트를 먼저 제시한다.",
            required_sections=("무슨 일이 있었나", "반응이 갈린 이유", "맥락과 이해관계", "다음 관전 포인트", "FAQ"),
            avoid_sections=("억지 해결법", "지금 해야 할 3단계", "신청·환급·대응 같은 생활문제 프레임"),
            answer_engine_mode="reaction_watchpoints",
            reader_question_style="왜 반응이 갈렸나, 무엇을 보면 되나, 다음 변수는 무엇인가",
            cta_style="관련 해석형 내부 글로 체류를 이어가게 한다.",
            recommended_content_type="viral_issue_decode",
        ),
        "trend_meaning": IssueContentProfile(
            profile_id="trend_meaning",
            profile_name="트렌드해석형",
            intent_mode="trend_meaning",
            title_mode="왜 퍼졌나, 무엇을 의미하나, 어디까지 갈까 중심",
            primary_goal="밈과 유행의 확산 구조, 참여 심리, 소비·플랫폼 의미를 해석한다.",
            lead_rule="첫 문단에서 유행의 표면보다 사람들이 붙는 이유를 먼저 말한다.",
            required_sections=("어디서 퍼졌나", "사람들이 붙는 이유", "확산 구조", "식는 신호와 남는 의미", "FAQ"),
            avoid_sections=("구매 강요", "도덕적 훈계", "문제해결 체크리스트로 억지 전환"),
            answer_engine_mode="trend_explainer",
            reader_question_style="왜 갑자기 떴나, 누가 쓰나, 계속 갈까",
            cta_style="비슷한 트렌드 해석 내부 글로 이어가게 한다.",
            recommended_content_type="trend_decode",
        ),
        "timeline_context": IssueContentProfile(
            profile_id="timeline_context",
            profile_name="맥락·타임라인형",
            intent_mode="context_timeline",
            title_mode="확인된 것, 아직 모르는 것, 왜 지금인가 중심",
            primary_goal="문제해결보다 사건의 흐름, 확정 사실, 남은 쟁점을 빠르게 이해시킨다.",
            lead_rule="첫 문단에서 지금 확인된 사실과 아직 단정하면 안 되는 지점을 나눠 제시한다.",
            required_sections=("지금 확인된 내용", "왜 지금 이슈가 됐나", "타임라인", "아직 확인할 부분", "FAQ"),
            avoid_sections=("억지 행동 지침", "확인 안 된 수치 단정", "자극적 전망"),
            answer_engine_mode="confirmed_unknown_context",
            reader_question_style="무슨 일이 있었나, 왜 지금인가, 무엇이 아직 미확정인가",
            cta_style="배경 설명형 내부 글로 이어가게 한다.",
            recommended_content_type="today_issue_explainer",
        ),
    }

    def build_profile(
        self,
        *,
        topic: str,
        summary: str = "",
        content_type: str = "",
        topic_group: str = "",
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = (raw or {}).get("issue_content_profile")
        if isinstance(existing, dict) and str(existing.get("profile_id") or "").strip():
            profile = self._profile_by_id(str(existing.get("profile_id") or ""))
            data = profile.to_dict()
            data.update({k: v for k, v in existing.items() if v not in (None, "", [], {})})
            return data

        text = " ".join(
            str(value or "")
            for value in (
                topic,
                summary,
                (raw or {}).get("original_topic"),
                " ".join((raw or {}).get("sample_titles") or []),
                " ".join((raw or {}).get("primary_tokens") or []),
            )
        ).lower()
        profile_id = self._profile_id_for(
            text=text,
            content_type=(content_type or "").strip(),
            topic_group=(topic_group or "").strip(),
        )
        profile = self._profile_by_id(profile_id).to_dict()
        if profile_id == "problem_solution":
            profile["recommended_content_type"] = self._problem_content_type_for(text, content_type)
        return profile

    def apply_to_raw(
        self,
        raw: dict[str, Any],
        *,
        topic: str,
        summary: str = "",
    ) -> dict[str, Any]:
        content_angle = raw.get("content_angle")
        if not isinstance(content_angle, dict):
            content_angle = {}
            raw["content_angle"] = content_angle

        current_content_type = str(content_angle.get("content_type") or raw.get("content_type") or "").strip()
        topic_group = str(content_angle.get("topic_group") or raw.get("topic_group") or "").strip()
        profile = self.build_profile(
            topic=topic,
            summary=summary,
            content_type=current_content_type,
            topic_group=topic_group,
            raw=raw,
        )
        recommended_type = str(profile.get("recommended_content_type") or "").strip()

        raw["issue_content_profile"] = profile
        raw["issue_intent_mode"] = profile.get("intent_mode", "")
        raw["issue_profile_id"] = profile.get("profile_id", "")
        content_angle["issue_content_profile"] = profile.get("profile_id", "")
        content_angle["intent_mode"] = profile.get("intent_mode", "")
        content_angle["title_mode"] = profile.get("title_mode", "")
        content_angle["answer_engine_mode"] = profile.get("answer_engine_mode", "")
        content_angle["reader_question_style"] = profile.get("reader_question_style", "")
        content_angle["required_sections"] = list(profile.get("required_sections") or [])
        content_angle["avoid_sections"] = list(profile.get("avoid_sections") or [])

        if self.should_replace_content_type(current_content_type, recommended_type):
            if current_content_type:
                content_angle["original_content_type"] = current_content_type
            content_angle["content_type"] = recommended_type
        elif current_content_type:
            content_angle["content_type"] = current_content_type
        return profile

    @classmethod
    def prompt_block(cls, profile: dict[str, Any] | IssueContentProfile | None) -> str:
        if isinstance(profile, IssueContentProfile):
            data = profile.to_dict()
        elif isinstance(profile, dict):
            data = profile
        else:
            data = cls._PROFILES["timeline_context"].to_dict()

        required = ", ".join(str(item) for item in data.get("required_sections") or [])
        avoid = ", ".join(str(item) for item in data.get("avoid_sections") or [])
        return (
            "\n[이슈 맞춤 작성 프로필]\n"
            f"- 프로필: {data.get('profile_name')} ({data.get('profile_id')})\n"
            f"- 검색 의도: {data.get('intent_mode')}\n"
            f"- 제목 방향: {data.get('title_mode')}\n"
            f"- 첫 문단 규칙: {data.get('lead_rule')}\n"
            f"- 본문 목표: {data.get('primary_goal')}\n"
            f"- 필수 섹션: {required}\n"
            f"- 피해야 할 구성: {avoid}\n"
            f"- FAQ/PAA 방향: {data.get('reader_question_style')}\n"
            "- 레이아웃은 63-cj 글의 가독성만 참고하고 구조를 복제하지 마세요. "
            "같은 class 체계(yomi-clean-post, yomi-lede, yomi-risk, yomi-list, yomi-lens, yomi-faq)는 쓰되 "
            "섹션 제목, 표 열 이름, 모듈 순서는 이슈 성격에 맞게 바꾸세요.\n"
            "- 문제해결형은 위험도 표와 확인 순서를, 반응해석형은 반응이 갈린 이유와 관전 포인트를, "
            "타임라인형은 확인된 것과 아직 모르는 것을 우선하세요.\n"
            "- 문제해결형이 아닌 이슈에는 체크리스트, 신청 방법, 대응 절차를 억지로 만들지 마세요.\n"
            "- 외부 사이트로 나가는 링크는 본문에 넣지 말고, 필요하면 출처명은 텍스트로만 언급하세요.\n"
        )

    @classmethod
    def should_replace_content_type(cls, current_content_type: str, recommended_content_type: str) -> bool:
        current = (current_content_type or "").strip()
        recommended = (recommended_content_type or "").strip()
        return bool(recommended and recommended != current and current in cls.WEAK_CONTENT_TYPES)

    @classmethod
    def _profile_by_id(cls, profile_id: str) -> IssueContentProfile:
        return cls._PROFILES.get(profile_id, cls._PROFILES["timeline_context"])

    @classmethod
    def _profile_id_for(cls, *, text: str, content_type: str, topic_group: str) -> str:
        if content_type in cls.PROBLEM_CONTENT_TYPES or topic_group in cls.PROBLEM_TOPIC_GROUPS:
            return "problem_solution"
        if content_type in cls.REACTION_CONTENT_TYPES or topic_group in cls.REACTION_TOPIC_GROUPS:
            return "reaction_decode"
        if content_type in cls.TREND_CONTENT_TYPES or topic_group in cls.TREND_TOPIC_GROUPS:
            return "trend_meaning"
        if cls._contains_any(text, cls.REACTION_KEYWORDS):
            return "reaction_decode"
        if cls._contains_any(text, cls.PROBLEM_KEYWORDS):
            return "problem_solution"
        if cls._contains_any(text, cls.TREND_KEYWORDS):
            return "trend_meaning"
        return "timeline_context"

    @classmethod
    def _problem_content_type_for(cls, text: str, current_content_type: str) -> str:
        if current_content_type in cls.PROBLEM_CONTENT_TYPES:
            return current_content_type
        if cls._contains_any(text, ("세금", "환급", "환급금", "홈택스", "연말정산")):
            return "tax_refund"
        if cls._contains_any(text, ("지원금", "신청", "마감", "대상", "조건", "복지", "보조금")):
            return "policy_deadline"
        if cls._contains_any(text, ("배달비", "쿠폰", "할인", "최종 결제", "최소주문", "구독료")):
            return "money_checklist"
        if cls._contains_any(text, ("요금", "인상", "종료", "변경", "멤버십", "플랫폼")):
            return "platform_change"
        return "consumer_warning"

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        lowered = (text or "").lower()
        return any(keyword.lower() in lowered for keyword in keywords)
