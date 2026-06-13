from __future__ import annotations

import re
from typing import Any


_SEARCH_TERMS = (
    "방법", "대상", "조건", "확인", "비교", "체크", "조회", "신청", "마감",
    "환불", "보상", "설정", "변경", "인상", "종료", "이유", "왜",
)
_CURIOSITY_TERMS = (
    "왜", "이유", "반응", "갈린", "논란", "화제", "갑자기", "알고보니",
    "숨은", "놓친", "헷갈", "달라지는", "끝일까", "진짜",
)
_UTILITY_TERMS = (
    "손해", "비용", "돈", "시간", "위험", "피해", "보안", "개인정보",
    "환급", "지원금", "결제", "계정", "비밀번호", "증거", "체크리스트",
    "기준", "순서", "비교", "저장",
)
_GENERIC_TITLE_TERMS = (
    "사람들이 본 핵심 포인트",
    "평점보다 먼저 볼 포인트",
    "화제 된 이유",
    "핵심 포인트",
    "반응 뜨거운 이유",
)


class ReaderInterestBriefService:
    """Build the pre-writing brief needed to create publishable daily posts.

    The point is not only to block weak posts. This brief gives the downstream
    title/content generators an explicit answer to: why click, why read, and
    what should be saved from the article.
    """

    @classmethod
    def build(
        cls,
        *,
        topic: str,
        summary: str = "",
        raw: dict[str, Any] | None = None,
        topic_group: str = "",
        content_type: str = "",
    ) -> dict[str, Any]:
        raw = raw or {}
        search_angle = raw.get("search_angle") if isinstance(raw.get("search_angle"), dict) else {}
        content_angle = raw.get("content_angle") if isinstance(raw.get("content_angle"), dict) else {}
        content_type = content_type or str(content_angle.get("content_type") or "")
        topic_group = topic_group or str(raw.get("topic_group") or "")
        search_demand_topic = str(
            search_angle.get("search_demand_topic")
            or raw.get("search_demand_topic")
            or topic
            or ""
        ).strip()
        questions = [
            str(q).strip()
            for q in (
                raw.get("reader_search_questions")
                or search_angle.get("reader_search_questions")
                or []
            )
            if str(q).strip()
        ]
        text = " ".join(
            str(value or "")
            for value in (
                topic,
                summary,
                raw.get("original_topic"),
                search_demand_topic,
                raw.get("click_reason"),
                raw.get("reader_benefit"),
                raw.get("content_promise"),
                " ".join(questions[:5]),
                " ".join(raw.get("sample_titles") or []),
            )
        )
        click_potential = cls._to_int(raw.get("click_potential_score"), 0)
        buzz = cls._to_int(raw.get("today_buzz_score"), 0)
        source_count = cls._to_int(raw.get("source_count"), 0)
        practical_value = cls._to_int(raw.get("practical_value_score"), 0)
        safety = cls._to_int(raw.get("viral_safety_score"), 80)
        risk_flags = list(raw.get("viral_risk_flags") or raw.get("risk_flags") or [])
        is_stale = bool(raw.get("is_stale"))

        search_score = cls._search_score(
            text=text,
            search_demand_topic=search_demand_topic,
            questions=questions,
            is_stale=is_stale,
        )
        curiosity_score = cls._curiosity_score(
            text=text,
            click_potential=click_potential,
            buzz=buzz,
            source_count=source_count,
            content_type=content_type,
            topic_group=topic_group,
        )
        save_value_score = cls._save_value_score(
            text=text,
            practical_value=practical_value,
            content_type=content_type,
            topic_group=topic_group,
        )
        fit_score = cls._fit_score(
            text=text,
            topic=topic,
            search_demand_topic=search_demand_topic,
            safety=safety,
            risk_flags=risk_flags,
        )
        penalty = cls._generic_penalty(text)
        total = max(0, min(100, search_score + curiosity_score + save_value_score + fit_score - penalty))
        strategy = cls._strategy(
            content_type=content_type,
            topic_group=topic_group,
            curiosity_score=curiosity_score,
            save_value_score=save_value_score,
        )
        weak_reasons = cls._weak_reasons(
            search_score=search_score,
            curiosity_score=curiosity_score,
            save_value_score=save_value_score,
            fit_score=fit_score,
            penalty=penalty,
            questions=questions,
        )
        primary_question = cls._primary_question(
            topic=search_demand_topic or topic,
            questions=questions,
            content_type=content_type,
            topic_group=topic_group,
        )
        click_hook = cls._click_hook(
            topic=search_demand_topic or topic,
            content_type=content_type,
            topic_group=topic_group,
            text=text,
        )
        reader_payoff = cls._reader_payoff(
            topic=search_demand_topic or topic,
            content_type=content_type,
            topic_group=topic_group,
            text=text,
        )
        save_asset = cls._save_asset(content_type=content_type, topic_group=topic_group, text=text)

        return {
            "reader_interest_score": total,
            "search_question_score": search_score,
            "curiosity_score": curiosity_score,
            "save_value_score": save_value_score,
            "specificity_fit_score": fit_score,
            "generic_penalty": penalty,
            "strategy": strategy,
            "primary_reader_question": primary_question,
            "click_hook": click_hook,
            "reader_payoff": reader_payoff,
            "save_asset": save_asset,
            "recommended_structure": cls._recommended_structure(content_type, topic_group, strategy),
            "avoid_in_article": cls._avoid_phrases(content_type, topic_group),
            "weak_reasons": weak_reasons,
            "publish_intent": "publishable" if total >= 70 else "click_first" if curiosity_score >= 20 else "needs_stronger_angle",
        }

    @staticmethod
    def prompt_block(brief: dict[str, Any] | None) -> str:
        if not isinstance(brief, dict) or not brief:
            return ""
        avoid = ", ".join(str(item) for item in brief.get("avoid_in_article") or [])
        structure = " → ".join(str(item) for item in brief.get("recommended_structure") or [])
        return (
            "\n[독자 관심 브리프]\n"
            f"- 첫 문단에서 바로 답할 질문: {brief.get('primary_reader_question', '')}\n"
            f"- 클릭 이유: {brief.get('click_hook', '')}\n"
            f"- 읽고 얻어야 할 것: {brief.get('reader_payoff', '')}\n"
            f"- 저장할 자산: {brief.get('save_asset', '')}\n"
            f"- 권장 구성: {structure}\n"
            f"- 쓰면 안 되는 표현/구성: {avoid}\n"
            "- 제목과 첫 문단은 위 클릭 이유와 질문에 직접 답해야 합니다. "
            "섹션을 채우기 위해 같은 말을 반복하지 말고, 표나 체크리스트는 저장 가치가 있을 때만 넣으세요.\n"
        )

    @staticmethod
    def _search_score(*, text: str, search_demand_topic: str, questions: list[str], is_stale: bool) -> int:
        score = 0
        if search_demand_topic and len(search_demand_topic) >= 8:
            score += 8
        if len(questions) >= 3:
            score += 7
        elif len(questions) >= 2:
            score += 5
        elif len(questions) == 1:
            score += 3
        hits = sum(1 for term in _SEARCH_TERMS if term in text)
        score += min(8, hits * 2)
        if "?" in text or "까" in text:
            score += 2
        if not is_stale:
            score += 3
        return max(0, min(25, score))

    @staticmethod
    def _curiosity_score(
        *,
        text: str,
        click_potential: int,
        buzz: int,
        source_count: int,
        content_type: str,
        topic_group: str,
    ) -> int:
        score = min(12, click_potential * 2)
        score += min(5, buzz)
        score += min(4, source_count)
        hits = sum(1 for term in _CURIOSITY_TERMS if term in text)
        score += min(6, hits * 2)
        if content_type in {"viral_issue_decode", "trend_decode", "today_issue_explainer"}:
            score += 3
        if topic_group in {"ott_platform", "fandom_consumer", "entertainment_sports", "today_issue"}:
            score += 2
        return max(0, min(25, score))

    @staticmethod
    def _save_value_score(*, text: str, practical_value: int, content_type: str, topic_group: str) -> int:
        score = min(8, max(0, practical_value // 2))
        hits = sum(1 for term in _UTILITY_TERMS if term in text)
        score += min(10, hits * 2)
        if content_type in {"consumer_warning", "money_checklist", "tax_refund", "policy_deadline", "platform_change", "ai_work_tip"}:
            score += 6
        elif content_type == "viral_issue_decode":
            score += 2
        if topic_group in {"privacy_security", "delivery_money", "policy_benefit", "ai_work", "platform_issue"}:
            score += 4
        return max(0, min(25, score))

    @staticmethod
    def _fit_score(*, text: str, topic: str, search_demand_topic: str, safety: int, risk_flags: list[Any]) -> int:
        score = 8
        if _has_specific_entity(f"{topic} {search_demand_topic}"):
            score += 8
        if len((search_demand_topic or topic).strip()) >= 12:
            score += 4
        if safety >= 70 and not risk_flags:
            score += 5
        elif safety < 50 or risk_flags:
            score -= 6
        if len(set(re.findall(r"[가-힣A-Za-z0-9]+", text))) >= 8:
            score += 3
        return max(0, min(25, score))

    @staticmethod
    def _generic_penalty(text: str) -> int:
        penalty = 0
        for phrase in _GENERIC_TITLE_TERMS:
            if phrase in text:
                penalty += 4
        if text.count("핵심 포인트") >= 2:
            penalty += 4
        if text.count("사람들이") >= 3:
            penalty += 3
        return min(15, penalty)

    @staticmethod
    def _strategy(*, content_type: str, topic_group: str, curiosity_score: int, save_value_score: int) -> str:
        if save_value_score >= 18:
            return "save_value_first"
        if curiosity_score >= 20 and content_type in {"viral_issue_decode", "trend_decode", "today_issue_explainer"}:
            return "click_first_context"
        if topic_group == "privacy_security" or content_type == "consumer_warning":
            return "risk_checklist"
        if content_type in {"money_checklist", "tax_refund", "policy_deadline", "platform_change", "ai_work_tip"}:
            return "problem_solution"
        return "context_then_payoff"

    @staticmethod
    def _weak_reasons(
        *,
        search_score: int,
        curiosity_score: int,
        save_value_score: int,
        fit_score: int,
        penalty: int,
        questions: list[str],
    ) -> list[str]:
        reasons: list[str] = []
        if search_score < 12 or len(questions) < 2:
            reasons.append("search_question_weak")
        if curiosity_score < 12:
            reasons.append("click_curiosity_weak")
        if save_value_score < 10:
            reasons.append("save_value_weak")
        if fit_score < 12:
            reasons.append("specificity_or_safety_weak")
        if penalty >= 6:
            reasons.append("generic_template_smell")
        return reasons

    @staticmethod
    def _primary_question(*, topic: str, questions: list[str], content_type: str, topic_group: str) -> str:
        for question in questions:
            if len(question) >= 8 and any(term in question for term in _SEARCH_TERMS + _CURIOSITY_TERMS):
                return question
        if topic_group == "privacy_security":
            return f"{topic} 이후 내 계정은 무엇부터 확인해야 하나요?"
        if content_type == "consumer_warning":
            return f"{topic} 관련 피해를 줄이려면 무엇부터 해야 하나요?"
        if content_type == "money_checklist":
            return f"{topic}에서 실제로 돈이 더 나가는 지점은 무엇인가요?"
        if content_type in {"policy_deadline", "tax_refund"}:
            return f"{topic} 대상과 신청 조건은 어떻게 확인하나요?"
        if content_type == "ai_work_tip":
            return f"{topic}이 실제 업무 시간을 줄이려면 무엇이 먼저인가요?"
        if content_type == "viral_issue_decode":
            return f"{topic}에서 사람들이 가장 궁금해한 지점은 무엇인가요?"
        return f"{topic}에서 지금 확인할 핵심은 무엇인가요?"

    @staticmethod
    def _click_hook(*, topic: str, content_type: str, topic_group: str, text: str) -> str:
        if topic_group == "privacy_security" or "개인정보" in text or "유출" in text:
            return "내 계정과 같은 비밀번호를 쓴 다른 서비스까지 위험해질 수 있다."
        if content_type == "money_checklist" or any(term in text for term in ("결제", "배달비", "쿠폰", "최종금액")):
            return "할인처럼 보여도 최종 결제금액에서는 더 낼 수 있다."
        if content_type in {"policy_deadline", "tax_refund"}:
            return "대상 조건이나 계좌 확인을 놓치면 받을 수 있는 돈 확인이 늦어진다."
        if content_type == "ai_work_tip":
            return "AI를 써도 검수 기준이 없으면 오히려 시간이 늘 수 있다."
        if content_type == "viral_issue_decode":
            return "댓글 반응보다 사람들이 실제로 갈린 지점을 보면 볼지 말지가 빨리 정리된다."
        return f"{topic}을 단순 소식이 아니라 내 선택 기준으로 바꿔 읽을 수 있다."

    @staticmethod
    def _reader_payoff(*, topic: str, content_type: str, topic_group: str, text: str) -> str:
        if topic_group == "privacy_security":
            return "비밀번호 변경, 2차 인증, 피싱 문자 확인 순서를 얻는다."
        if content_type == "consumer_warning":
            return "증거 기록, 고객센터 대응, 보상 여부 확인 순서를 얻는다."
        if content_type == "money_checklist":
            return "최종금액, 조건, 예외를 비교하는 기준을 얻는다."
        if content_type in {"policy_deadline", "tax_refund"}:
            return "대상, 신청 경로, 마감, 필요 정보를 한 번에 확인한다."
        if content_type == "ai_work_tip":
            return "AI에 맡길 일과 사람이 검수할 일을 나누는 기준을 얻는다."
        if content_type == "viral_issue_decode":
            return "확인된 사실, 반응이 갈린 이유, 다음 관전 포인트를 분리해서 본다."
        return "확인된 내용과 아직 모르는 내용을 나눠 판단 기준을 얻는다."

    @staticmethod
    def _save_asset(*, content_type: str, topic_group: str, text: str) -> str:
        if topic_group == "privacy_security":
            return "계정 보안 체크리스트"
        if content_type == "consumer_warning":
            return "피해 대응 기록표"
        if content_type == "money_checklist":
            return "최종 결제금액 비교표"
        if content_type in {"policy_deadline", "tax_refund"}:
            return "대상·마감·신청 경로 체크리스트"
        if content_type == "ai_work_tip":
            return "업무 자동화 적용 기준표"
        if content_type == "viral_issue_decode":
            return "보기 전 판단 기준표"
        return "확인된 것과 아직 모르는 것 표"

    @staticmethod
    def _recommended_structure(content_type: str, topic_group: str, strategy: str) -> list[str]:
        if topic_group == "privacy_security":
            return ["내 계정 해당 여부", "유출 항목", "지금 할 일", "피싱·2차 피해", "FAQ"]
        if content_type == "consumer_warning":
            return ["피해 가능성", "증거 기록", "문의·보상 순서", "예외", "FAQ"]
        if content_type == "money_checklist":
            return ["돈이 새는 지점", "비교표", "계산 예시", "손해 줄이는 순서", "FAQ"]
        if content_type in {"policy_deadline", "tax_refund"}:
            return ["대상", "금액·마감", "신청 경로", "제외 조건", "FAQ"]
        if content_type == "ai_work_tip":
            return ["실패 원인", "적용 가능한 업무", "검수 기준", "워크플로우", "FAQ"]
        if content_type == "viral_issue_decode" or strategy == "click_first_context":
            return ["무슨 일이 있었나", "반응이 갈린 이유", "확인된 것", "다음 관전 포인트", "FAQ"]
        return ["지금 확인된 것", "왜 관심이 커졌나", "독자 영향", "확인할 기준", "FAQ"]

    @staticmethod
    def _avoid_phrases(content_type: str, topic_group: str) -> list[str]:
        avoid = ["화제 된 이유만 반복", "사람들이 본 핵심 포인트", "같은 Q&A 반복"]
        if content_type not in {"policy_deadline", "tax_refund"}:
            avoid.extend(["신청 전 많이 묻는 질문", "대상 조건 억지 삽입"])
        if content_type != "viral_issue_decode":
            avoid.append("평점보다 먼저 볼 포인트")
        if topic_group != "privacy_security":
            avoid.append("보안 대응 억지 삽입")
        return avoid

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def _has_specific_entity(text: str) -> bool:
    tokens = re.findall(r"[가-힣A-Za-z0-9+·]{2,}", text or "")
    generic = {
        "오늘", "이슈", "논란", "반응", "화제", "사람들", "핵심", "포인트",
        "확인", "방법", "조건", "기준", "정리", "이유", "먼저",
    }
    for token in tokens[:12]:
        if token in generic:
            continue
        if re.search(r"[A-Z][A-Za-z0-9+]*", token):
            return True
        if any(ch.isdigit() for ch in token):
            return True
        if token not in generic and len(token) >= 3:
            return True
    return False
