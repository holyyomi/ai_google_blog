from __future__ import annotations

from html import unescape
import logging
import re
from typing import Any

from blogspot_automation.services.golden_pattern_service import GoldenPatternService

logger = logging.getLogger(__name__)

_GLOBAL_BANNED_PHRASES = [
    "이 이슈는 나와 직접 관련이 없다",
    "정보가 너무 많음",
    "공식 안내를 확인한다",
    "오늘 내 선택 기준",
]


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return bool(value)


_POLICY_REGION_TERMS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
_POLICY_PAYMENT_TERMS = (
    "울산페이", "지역화폐", "지역사랑상품권", "상품권", "바우처",
    "카드 포인트", "포인트", "현금", "계좌 입금",
)
_POLICY_TARGET_TERMS = (
    "근로자", "재직자", "청년", "소상공인", "자영업자", "사업자",
    "구직자", "가구", "시민", "주민", "노동자",
)


def _policy_fact_pack(topic: str, raw: dict[str, Any]) -> dict[str, Any]:
    source_text = _policy_source_text(topic, raw)
    subject = _policy_subject(topic=topic, raw=raw, source_text=source_text)
    return {
        "source_text": source_text,
        "subject": subject,
        "regions": _unique_terms(_POLICY_REGION_TERMS, source_text),
        "amounts": _unique_regex(r"(?:1인(?:당)?\s*)?(?:최대\s*)?\d+(?:,\d{3})*\s*(?:만\s*)?원", source_text),
        "targets": _extract_policy_targets(source_text),
        "payments": _unique_terms(_POLICY_PAYMENT_TERMS, source_text),
        "deadlines": _unique_regex(r"(?:20\d{2}년\s*)?\d{1,2}월\s*\d{1,2}일(?:\s*\([^)]+\))?", source_text),
        "contacts": _unique_regex(r"\b0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}\b", source_text),
        "source_names": _extract_policy_source_names(source_text),
    }


def _policy_source_text(topic: str, raw: dict[str, Any]) -> str:
    values: list[str] = [topic]
    for key in (
        "original_topic", "source_title", "source_summary", "cleaned_title",
        "original_title", "search_demand_topic", "reader_benefit",
        "content_promise", "public_benefit_original_topic",
    ):
        values.append(str(raw.get(key) or ""))
    for key in ("source_titles", "sample_titles", "reader_search_questions", "source_excerpts"):
        items = raw.get(key)
        if isinstance(items, list):
            values.extend(str(item or "") for item in items)
    verification = raw.get("web_verification")
    if isinstance(verification, dict):
        for docs in verification.values():
            if isinstance(docs, list):
                for item in docs[:3]:
                    if isinstance(item, dict):
                        values.extend([str(item.get("title") or ""), str(item.get("snippet") or "")])
    naver_item = raw.get("naver_item")
    if isinstance(naver_item, dict):
        values.extend([str(naver_item.get("title") or ""), str(naver_item.get("description") or "")])
    return _clean_policy_text(" ".join(values))


def _clean_policy_text(text: str) -> str:
    clean = unescape(str(text or ""))
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\[[^\]]{1,18}\]", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _policy_subject(*, topic: str, raw: dict[str, Any], source_text: str) -> str:
    candidates: list[str] = []
    for key in ("source_title", "original_topic", "cleaned_title", "original_title"):
        value = str(raw.get(key) or "").strip()
        if value:
            candidates.append(value)
    source_titles = raw.get("source_titles")
    if isinstance(source_titles, list):
        candidates.extend(str(item or "") for item in source_titles[:3])
    candidates.extend([topic, source_text])

    for value in candidates:
        text = _clean_policy_text(value)
        text = re.split(r"\s+[|｜]\s+|\s+-\s+", text)[0].strip(" ,.-:;!?\"'")
        text = re.sub(r"\s*(연합뉴스|뉴시스|뉴스1|이데일리|매일경제|한국경제)$", "", text).strip()
        if not text:
            continue
        match = re.search(
            r"([가-힣A-Za-z0-9·\s]{2,42}(?:지원금|지원사업|장려금|보조금|수당|안심페이|울산페이))",
            text,
        )
        subject = (match.group(1) if match else text).strip()
        subject = re.split(
            r"\s*(?:신청방법|신청 방법|대상 조건|대상은|어떻게|참여자 모집|공고|,|—)",
            subject,
        )[0].strip(" ,.-:;!?\"'")
        if len(subject) >= 3:
            return subject[:36].strip()
    return "지원금 공고"


def _unique_terms(terms: tuple[str, ...], text: str) -> list[str]:
    found: list[str] = []
    for term in terms:
        if term in text and term not in found:
            found.append(term)
    return found


def _unique_regex(pattern: str, text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(pattern, text or ""):
        value = " ".join(match.group(0).split()).strip()
        if value and value not in found:
            found.append(value)
    return found


def _extract_policy_targets(text: str) -> list[str]:
    found: list[str] = []
    for term in _POLICY_TARGET_TERMS:
        for match in re.finditer(rf"[가-힣A-Za-z0-9·\s]{{0,18}}{re.escape(term)}", text or ""):
            value = " ".join(match.group(0).split()).strip(" ,.-")
            if len(value) >= 2 and value not in found:
                found.append(value[:32])
    return found[:4]


def _extract_policy_source_names(text: str) -> list[str]:
    names: list[str] = []
    for term in ("고용노동부", "보건복지부", "국세청", "정부24", "복지로", "대한민국 정책브리핑"):
        if term in text and term not in names:
            names.append(term)
    for region in _POLICY_REGION_TERMS:
        for suffix in ("시", "광역시", "도", "시청", "도청"):
            name = f"{region}{suffix}"
            if name in text and name not in names:
                names.append(name)
    return names[:4]


def _fact_text(values: list[str], fallback: str) -> str:
    return ", ".join(values[:3]) if values else fallback


_REACTION_SUBJECT_STOP_PHRASES = (
    "반응이 갈린 이유와 핵심 포인트",
    "반응이 갈린 이유",
    "사람들이 본 핵심 포인트",
    "사람들이 본 핵",
    "먼저 볼 3가지",
    "먼저 볼 것",
)


def _reaction_subject(topic: str, raw: dict[str, Any]) -> str:
    values = [
        str(raw.get("source_title") or ""),
        str(raw.get("original_topic") or ""),
        str(raw.get("cleaned_title") or ""),
        str(raw.get("search_demand_topic") or ""),
        topic,
    ]
    for value in values:
        text = _clean_policy_text(value)
        if not text:
            continue
        text = re.split(r"\s+[|｜]\s+|\s+-\s+", text)[0].strip()
        for phrase in _REACTION_SUBJECT_STOP_PHRASES:
            text = text.replace(phrase, " ")
        text = re.sub(r"\s+", " ", text).strip(" ,.-:;!?\"'")
        if len(text) >= 2:
            return text[:42].strip()
    return "이 이슈"


def _policy_hashtags(facts: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    subject = re.sub(r"\s+", "", str(facts.get("subject") or ""))[:12]
    if subject:
        tags.append(f"#{subject}")
    for value in [*(facts.get("regions") or []), *(facts.get("payments") or [])]:
        clean = re.sub(r"\s+", "", str(value or ""))[:12]
        if clean:
            tags.append(f"#{clean}")
    tags.append("#지원금신청")
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
        if len(deduped) >= 3:
            break
    return deduped


class SlotFillerService:
    """골든 패턴의 required_slots를 topic/candidate_raw 기반으로 채우는 서비스.

    Phase 2-2: AI 생성 없이 lookup(slot_filling_strategy 기반) 또는
    derived(topic·메타데이터 기반) 방식만 사용한다.
    """

    def __init__(self, pattern_service: GoldenPatternService | None = None) -> None:
        self._ps = pattern_service or GoldenPatternService()
        self._builders: dict[str, Any] = {
            "tax_refund_hometax_check": self._build_tax_refund,
            "viral_ott_reaction_decode": self._build_viral_ott,
            "ai_work_time_savings": self._build_ai_work,
            "ai_tool_comparison": self._build_ai_tool_comparison,
            "ai_automation_workflow": self._build_ai_automation_workflow,
            "ai_prompt_recipe": self._build_ai_prompt_recipe,
            "ai_tool_review": self._build_ai_tool_review,
            "ai_model_update": self._build_ai_model_update,
            "ai_search_change": self._build_ai_search_change,
            "ai_blog_growth": self._build_ai_blog_growth,
            "ai_comparison": self._build_ai_comparison,
            "ai_risk_security": self._build_ai_risk_security,
            "ai_beginner_guide": self._build_ai_beginner_guide,
            "delivery_money_checklist": self._build_delivery_money_checklist,
            "platform_change_service_update": self._build_platform_change,
            "consumer_warning_refund": self._build_consumer_warning,
            "policy_deadline_support": self._build_policy_deadline,
            "corporate_issue_decode": self._build_corporate_issue,
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def fill_slots(
        self,
        pattern_id: str,
        topic: str,
        candidate_raw: dict | None = None,
    ) -> dict[str, Any]:
        """pattern_id와 topic을 받아 슬롯을 채우고 payload를 반환한다.

        Returns:
            {
              pattern_id, topic, slots, required_slots,
              filled_required_slots, missing_required_slots,
              slot_fill_rate, fill_strategy[, error]
            }
        """
        pattern = self._ps.get_pattern(pattern_id)
        required_slots = self._ps.list_required_slots(pattern_id)
        raw = candidate_raw or {}

        if not pattern:
            logger.warning("%s | pattern not found: %s", __name__, pattern_id)
            return {
                "pattern_id": pattern_id,
                "topic": topic,
                "slots": {},
                "required_slots": [],
                "filled_required_slots": [],
                "missing_required_slots": [],
                "slot_fill_rate": 0.0,
                "fill_strategy": {},
                "error": f"pattern not found: {pattern_id}",
            }

        builder = self._builders.get(pattern_id)
        if builder:
            slots, fill_strategy = builder(topic, raw)
        else:
            slots, fill_strategy = self._build_generic(pattern, topic, raw)

        fill_rate = self.calculate_slot_fill_rate(slots, required_slots)
        missing = self.get_missing_required_slots(slots, required_slots)
        filled_list = [s for s in required_slots if s not in missing]

        logger.info(
            "%s | pattern=%s fill_rate=%.2f missing=%s",
            __name__, pattern_id, fill_rate, missing,
        )

        return {
            "pattern_id": pattern_id,
            "topic": topic,
            "slots": slots,
            "required_slots": required_slots,
            "filled_required_slots": filled_list,
            "missing_required_slots": missing,
            "slot_fill_rate": fill_rate,
            "fill_strategy": fill_strategy,
        }

    def calculate_slot_fill_rate(
        self, slots: dict, required_slots: list[str]
    ) -> float:
        """required_slots 중 채워진 비율(0.0~1.0)을 반환한다."""
        if not required_slots:
            return 1.0
        filled_count = sum(1 for s in required_slots if _is_filled(slots.get(s)))
        return filled_count / len(required_slots)

    def get_missing_required_slots(
        self, slots: dict, required_slots: list[str]
    ) -> list[str]:
        """required_slots 중 비어 있는 슬롯 이름 목록을 반환한다."""
        return [s for s in required_slots if not _is_filled(slots.get(s))]

    # ------------------------------------------------------------------ #
    # Pattern-specific builders                                            #
    # ------------------------------------------------------------------ #

    def _build_tax_refund(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "환급금이 있다는 안내 문자를 받았는데 통장에는 아무것도 들어오지 않은 경험이 있다면, "
                "그 이유는 환급 유형을 구분하지 않은 채로 조회를 시작했기 때문일 가능성이 높다. "
                "홈택스에 로그인했는데 어느 메뉴를 열어야 할지 몰라 그냥 닫은 적이 있는가? "
                "국세환급금·종합소득세·연말정산·지방세는 각기 다른 메뉴에서 확인해야 하며, "
                "유형을 구분하지 않으면 내 환급금이 어디 있는지 찾지 못한 채 소멸시효가 지날 수 있다."
            ),
            "yomi_judgment": (
                "요미 판단: 환급금 조회는 절차 자체가 복잡하지 않다. "
                "국세환급금·종합소득세·연말정산·지방세 중 어느 유형인지 먼저 구분한 뒤 해당 메뉴로 들어가면 된다. "
                "확인을 미루면 5년 소멸시효가 지나 환급금을 영원히 받을 수 없게 된다. "
                "지금 홈택스에 로그인해서 환급 유형부터 구분하라."
            ),
            "misconceptions": [
                {
                    "착각": "환급금은 별도 신청 없이 자동으로 통장에 입금된다",
                    "실제": "계좌를 홈택스에 등록하거나 직접 신청해야 입금된다. 계좌 미등록 시 환급금이 발생해도 통장에 들어오지 않는다",
                },
                {
                    "착각": "종합소득세 신고를 한 사람만 환급 대상이다",
                    "실제": "연말정산 과납자, 경정청구 대상자, 국세환급금 발생자 등 유형마다 대상이 다르다. 직장인도 환급 대상이 될 수 있다",
                },
                {
                    "착각": "홈택스 환급금 조회 메뉴 하나에서 모든 환급을 한 번에 확인할 수 있다",
                    "실제": "국세환급금·종합소득세·연말정산·지방세는 각기 다른 메뉴에서 따로 확인해야 한다",
                },
                {
                    "착각": "안내 문자나 우편이 오면 이미 입금된 것이다",
                    "실제": "안내는 환급 발생 사실을 알리는 것이며, 계좌 등록 후 별도로 입금 처리가 이루어진다",
                },
            ],
            "real_criterion": (
                "1단계: 환급 유형 확인 — 홈택스 로그인 후 마이홈택스 > 환급금 통합 조회에서 전체 내역 먼저 확인. "
                "국세환급금(체납 공제 후 잔액 환급)·종합소득세 환급·연말정산 환급·지방세(위택스) 중 해당 유형 파악.\n"
                "2단계: 계좌 등록 확인 — 홈택스 환급계좌 신청/해지 메뉴에서 등록 여부 확인. "
                "미등록 상태라면 즉시 본인 계좌 등록. 손택스(모바일 앱)에서도 동일하게 처리 가능.\n"
                "3단계: 미수령 원인 진단 — 환급 예정 금액이 있으나 입금이 안 된 경우, "
                "주소 불일치·계좌 오류·처리 중 대기 상태 여부를 홈택스 내 환급 상태 메시지로 확인."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "홈택스 환급금 조회를 한 번도 안 해봤다",
                    "할 일": "홈택스 로그인 → 마이홈택스 → 환급금 통합 조회 먼저 실행",
                },
                {
                    "내 상황": "조회했는데 환급금 금액이 0원이다",
                    "할 일": "환급 유형 재확인 — 종합소득세·연말정산·지방세(위택스)를 각각 별도 메뉴에서 조회",
                },
                {
                    "내 상황": "환급 예정 금액은 보이는데 입금이 안 됐다",
                    "할 일": "홈택스 환급계좌 신청/해지 확인 → 계좌 미등록이면 즉시 등록",
                },
                {
                    "내 상황": "환급금 안내 문자를 받았다",
                    "할 일": "문자의 유형(국세환급금/지방세) 확인 → 해당 서비스(홈택스/위택스)에 직접 접속해 조회",
                },
                {
                    "내 상황": "5년이 지난 환급금이 있을 것 같다",
                    "할 일": "소멸시효 확인 후 경정청구 가능 여부를 세무사에게 상담",
                },
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "홈택스 환급금 통합 조회 실행",
                    "설명": "홈택스 로그인 → 마이홈택스 → 세금신고납부 → 국세환급금 통합조회 순으로 접속",
                },
                {
                    "번호": 2,
                    "행동": "손택스(모바일)에서 환급 유형별 확인",
                    "설명": "손택스 앱 로그인 → 조회/발급 → 환급 관련 메뉴 선택 → 유형별 금액 확인",
                },
                {
                    "번호": 3,
                    "행동": "홈택스 환급계좌 등록 또는 확인",
                    "설명": "홈택스 → 마이홈택스 → 환급계좌 신청/해지 → 현재 등록 계좌 확인 및 수정",
                },
            ],
            "faq": [
                {
                    "Q": "홈택스에 환급계좌를 등록하는 방법은?",
                    "A": (
                        "홈택스 로그인 → 마이홈택스 → 환급계좌 신청/해지 메뉴에서 본인 계좌를 입력하고 저장한다. "
                        "손택스 앱에서도 동일하게 등록 가능하다."
                    ),
                },
                {
                    "Q": "환급 예정금액이 있는데 왜 입금이 안 되나?",
                    "A": (
                        "계좌 미등록, 등록 계좌 오류, 주소 불일치, 환급 처리 중 대기 상태 중 하나일 가능성이 높다. "
                        "홈택스 내 환급 상태 메시지를 먼저 확인하라."
                    ),
                },
                {
                    "Q": "환급금에도 소멸시효가 있나?",
                    "A": (
                        "국세환급금 소멸시효는 5년이다. "
                        "발생한 환급금도 5년 내 청구하지 않으면 소멸한다. "
                        "경정청구도 법정신고기한으로부터 5년 이내에만 가능하므로 해당 연도를 반드시 확인해야 한다."
                    ),
                },
            ],
            "hashtags": [
                "#세금환급",
                "#홈택스",
                "#국세환급금",
                "#환급계좌등록",
                "#종합소득세환급",
                "#연말정산환급",
                "#손택스",
                "#AI활용",
            ],
            "internal_links": [
                {
                    "주제": "종합소득세 신고 방법과 환급 시점 완전 정리",
                    "content_type": "tax_refund",
                },
                {
                    "주제": "연말정산과 종합소득세 환급 차이 — 직장인이 알아야 할 구분",
                    "content_type": "tax_refund",
                },
                {
                    "주제": "홈택스 처음 쓰는 직장인을 위한 기초 가이드",
                    "content_type": "policy_benefit",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_viral_ott(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        subject = _reaction_subject(topic, raw)
        slots: dict[str, Any] = {
            "hook_opening": (
                f"{subject} 이슈는 제목만 보고 좋다거나 나쁘다고 단정하기 어렵다. "
                "공개 반응은 이용자 기대, 플랫폼 맥락, 실제 확인 가능한 정보가 섞여 움직인다. "
                "그래서 먼저 볼 것은 댓글의 온도가 아니라 무엇이 확인됐고 무엇이 아직 주장인지다. "
                "반응이 갈린 지점을 나누어 보면 이 이슈를 계속 지켜볼지, 내 선택에 영향을 주는지 더 빠르게 판단할 수 있다."
            ),
            "yomi_judgment": (
                f"요미 판단: {subject}의 반응 갈림은 한쪽 반응만 확대해서 볼 일이 아니다. "
                "공식 확인 내용, 실제 이용자에게 생기는 영향, 커뮤니티에서 과장된 해석을 분리해야 한다. "
                "확인되지 않은 주장까지 사실처럼 받아들이면 판단이 흐려진다. "
                "먼저 원문 공지와 신뢰할 수 있는 보도, 당사자 안내를 나눠 확인하라."
            ),
            "misconceptions": [
                {
                    "착각": "반응이 많으면 사실관계가 이미 정리됐다는 뜻이다",
                    "실제": "화제성과 사실 확인은 다르다. 공유량이 많아도 공식 확인 전 정보는 주장으로 봐야 한다",
                },
                {
                    "착각": "긍정 반응과 부정 반응 중 하나만 맞다",
                    "실제": "이슈의 이해관계, 이용자 상황, 기대값에 따라 양쪽 반응이 동시에 존재할 수 있다",
                },
                {
                    "착각": "커뮤니티 요약만 보면 핵심을 파악할 수 있다",
                    "실제": "요약 글은 맥락이 빠지기 쉽다. 원문 안내와 보도에서 확인된 범위를 먼저 봐야 한다",
                },
                {
                    "착각": "반응이 갈리면 내 선택과 무관하다",
                    "실제": "구독, 결제, 시청, 참여, 팬덤 소비처럼 내 행동과 연결되는 지점이 있는지 따로 봐야 한다",
                },
            ],
            "real_criterion": (
                f"관점 1: 확인된 사실 — {subject}에 대해 실제로 공개된 공지, 보도, 플랫폼 안내가 무엇인지 먼저 구분한다.\n"
                "관점 2: 이용자 영향 — 구독료, 이용 조건, 시청 선택, 팬덤 소비, 일정 변화처럼 독자 행동에 연결되는 부분만 따로 본다.\n"
                "관점 3: 반응의 출처 — 공식 안내, 언론 보도, 커뮤니티 반응, 추측성 댓글을 한데 섞지 않는다. "
                "출처가 다른 반응은 같은 무게로 비교하면 안 된다."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "제목만 보고 판단하려는 중이다",
                    "먼저 할 것": f"{subject} 관련 공식 안내나 원문 보도에서 확인된 사실을 먼저 본다",
                },
                {
                    "내 상황": "커뮤니티 반응이 크게 갈린다",
                    "먼저 할 것": "반응의 출처가 이용자 후기인지, 추측인지, 공식 발표인지 나눈다",
                },
                {
                    "내 상황": "내 구독이나 소비 결정에 영향이 있을 수 있다",
                    "먼저 할 것": "요금, 이용 조건, 환불, 일정, 참여 방식처럼 직접 영향 항목만 확인한다",
                },
                {
                    "내 상황": "루머성 주장이 같이 돌고 있다",
                    "먼저 할 것": "확인되지 않은 사생활·추측성 정보는 판단 근거에서 제외한다",
                },
                {
                    "내 상황": "계속 지켜볼지 결정해야 한다",
                    "먼저 할 것": "공식 추가 공지, 후속 보도, 실제 이용자 변화가 생기는지 확인한다",
                },
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "공식 확인 범위 분리",
                    "설명": f"{subject} 관련 공식 안내, 보도, 커뮤니티 반응을 따로 적어 사실과 해석을 구분한다",
                },
                {
                    "번호": 2,
                    "행동": "내 영향 항목만 확인",
                    "설명": "구독, 결제, 이용 조건, 일정, 소비 결정처럼 나에게 직접 영향을 주는 항목이 있는지 확인한다",
                },
                {
                    "번호": 3,
                    "행동": "추측성 반응 제외",
                    "설명": "루머, 사생활, 출처 없는 단정은 공유하거나 판단 근거로 쓰지 않는다",
                },
            ],
            "faq": [
                {
                    "Q": f"{subject}에 대해 반응이 갈리는 이유는 무엇인가요?",
                    "A": (
                        "확인된 사실, 이용자 기대, 커뮤니티 해석이 서로 다른 층위에서 움직이기 때문이다. "
                        "먼저 공식 확인 내용과 반응 해석을 분리해야 맥락이 선명해진다."
                    ),
                },
                {
                    "Q": f"{subject}의 화제성과 실제 영향은 어떻게 구분하나요?",
                    "A": (
                        "댓글 수나 공유량은 화제성이고, 요금·일정·이용 조건·공식 조치 변화는 실제 영향이다. "
                        "내 선택에 필요한 것은 실제 영향 항목이다."
                    ),
                },
                {
                    "Q": f"{subject} 관련 루머와 사실은 어떻게 구분하나요?",
                    "A": (
                        "출처가 공식 공지, 언론 보도, 이용자 주장 중 어디인지 확인한다. "
                        "출처가 없거나 사생활·추측 중심이면 사실 판단에서 제외하는 편이 안전하다."
                    ),
                },
            ],
            "hashtags": [
                "#이슈해석",
                "#반응분석",
                "#AI트렌드",
            ],
            "internal_links": [
                {
                    "주제": "공식 안내와 커뮤니티 반응을 구분하는 법",
                    "content_type": "viral_issue_decode",
                },
                {
                    "주제": "플랫폼 공지 변경 때 먼저 확인할 항목",
                    "content_type": "viral_issue_decode",
                },
                {
                    "주제": "이슈성 기사에서 루머와 사실을 나누는 기준",
                    "content_type": "viral_issue_decode",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_work(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "ChatGPT를 쓰기 시작했는데 오히려 시간이 더 걸리는 경험을 한 적 있다면 나만 그런 게 아니다. "
                "초안을 받았는데 그대로 쓸 수 없어 전부 다시 쓰거나, 프롬프트를 고치느라 30분이 사라진 날이 있다. "
                "문제는 AI를 어디에 쓰느냐다. "
                "작성 시간은 줄지만 검수 시간이 늘어나면 총 업무 시간은 오히려 늘어날 수 있다. "
                "시간이 줄어드는 업무와 오히려 늘어나는 업무는 구분된다."
            ),
            "yomi_judgment": (
                "요미 판단: AI는 완성본을 만들어주는 도구가 아니라 80점짜리 초안을 3분 안에 만들어주는 도구다. "
                "AI는 시간을 없애는 도구가 아니라 일의 형태를 바꾸는 도구다. "
                "판단·검토·맥락 설정은 여전히 내 몫이다. "
                "검수 비용이 작은 업무(반복 텍스트, 이메일 초안, 요약)부터 적용하면 실질적인 시간 절감이 생긴다. "
                "지금 내 업무 목록에서 반복되는 텍스트 업무를 먼저 찾아라."
            ),
            "misconceptions": [
                {
                    "착각": "AI가 완성본을 만들어주면 그대로 제출하면 된다",
                    "실제": "AI 결과물은 80점 초안이다. 팩트 확인·맥락 수정·문체 조정은 여전히 사람 몫이다",
                },
                {
                    "착각": "1시간 걸리던 일이 AI로 5분이면 55분을 절약한 것이다",
                    "실제": "검수와 수정에 30~40분이 걸리면 실질 절약은 15~20분이다. 검수 비용을 포함해 계산해야 한다",
                },
                {
                    "착각": "ChatGPT를 많이 쓸수록 업무 효율이 올라간다",
                    "실제": "맞지 않는 업무에 쓰면 오히려 시간이 더 걸린다. 업무 유형 구분이 먼저다",
                },
                {
                    "착각": "유료 버전(ChatGPT Plus)이 아니면 효과가 없다",
                    "실제": "무료 버전으로도 반복 텍스트 초안 생성·요약·번역은 충분히 활용 가능하다",
                },
            ],
            "real_criterion": (
                "패턴 1: 반복 텍스트 업무에 우선 적용 — 매주 작성하는 보고서 형식, 이메일 템플릿, 회의록 요약처럼 "
                "구조가 고정된 업무에 AI를 먼저 적용하라. 검수 부담이 낮고 시간 절감 효과가 즉각적이다.\n"
                "패턴 2: 80점 초안 기준 채택 — AI 결과물에 100점을 기대하지 않는다. "
                "80점 초안을 받아 20점을 채우는 방식으로 사용하면 검수 시간이 일정하게 유지된다.\n"
                "패턴 3: 프롬프트 템플릿 고정 — 잘 작동한 프롬프트는 저장하고 재사용한다. "
                "매번 프롬프트를 새로 작성하면 AI 사용 자체에 시간이 더 들어가므로 고정 템플릿이 핵심이다."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "AI를 써도 시간이 더 걸린다",
                    "할 일": "현재 쓰는 업무 유형 확인 — 검수 비용이 낮은 반복 텍스트 업무로 먼저 전환",
                },
                {
                    "내 상황": "AI 결과물을 계속 다시 쓰게 된다",
                    "할 일": "완성본 기대가 문제 — 80점 초안 기준으로 목표를 낮추고 수정 범위를 좁혀라",
                },
                {
                    "내 상황": "프롬프트를 매번 새로 짠다",
                    "할 일": "잘 작동한 프롬프트 1개를 메모앱이나 문서에 저장 → 다음 번 재사용",
                },
                {
                    "내 상황": "어떤 업무에 써야 할지 모른다",
                    "할 일": "반복적으로 비슷한 형식을 쓰는 업무(이메일/보고서/요약) 목록화 → 하나씩 적용 테스트",
                },
                {
                    "내 상황": "유료 버전이 없어서 못 쓴다",
                    "할 일": "무료 버전으로 반복 텍스트 초안 생성 먼저 시도 — 기능 차이보다 사용 패턴이 더 중요하다",
                },
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "반복 텍스트 업무 목록화",
                    "설명": "이번 주 작성한 텍스트 중 비슷한 형식이 반복된 것 3가지를 적어라. 그게 AI 우선 적용 대상이다",
                },
                {
                    "번호": 2,
                    "행동": "잘 된 프롬프트 저장",
                    "설명": "AI 결과물이 만족스러웠던 프롬프트를 메모앱이나 Notion에 저장하고 동일 업무에 재사용하라",
                },
                {
                    "번호": 3,
                    "행동": "5분 수정 룰 적용",
                    "설명": "AI 결과물을 받은 뒤 5분 이상 수정하게 된다면 프롬프트가 부정확한 것이다. 5분 내 수정 완료 기준으로 프롬프트를 개선하라",
                },
            ],
            "faq": [
                {
                    "Q": "ChatGPT 무료 버전으로도 효과가 있나?",
                    "A": (
                        "무료 버전으로도 이메일 초안·보고서 요약·반복 텍스트 생성은 충분히 활용 가능하다. "
                        "복잡한 분석보다 구조화된 텍스트 생성에서는 유료와 차이가 크지 않다."
                    ),
                },
                {
                    "Q": "좋은 프롬프트는 어떻게 짜나?",
                    "A": (
                        "역할 지정(당신은 ~입니다) + 목적(~을 작성해주세요) + 조건(~형식으로, ~분량으로) "
                        "3가지를 포함하면 결과물 품질이 올라간다. 간단하게 시작해서 결과 보고 조건을 추가하라."
                    ),
                },
                {
                    "Q": "AI 결과물을 그대로 제출해도 되나?",
                    "A": (
                        "팩트 확인 없이 AI 결과물을 그대로 제출하는 것은 위험하다. "
                        "AI는 그럴듯한 오류를 생성하는 경향이 있다. "
                        "핵심 사실 2~3가지는 직접 확인한 뒤 제출하라."
                    ),
                },
            ],
            "hashtags": [
                "#AI활용",
                "#업무자동화",
                "#ChatGPT활용",
                "#직장인AI",
                "#생산성향상",
                "#프롬프트작성",
                "#업무효율",
            ],
            "internal_links": [
                {
                    "주제": "ChatGPT 유료 vs 무료 기능 비교 — 직장인이 알아야 할 차이",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "업무자동화 입문 가이드 — 반복 업무 3가지 줄이는 방법",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "AI 사용 시 회사 보안 주의사항",
                    "content_type": "ai_work_tip",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_tool_comparison(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "AI 도구를 골랐는데 실제 업무에서 쓰기 어려웠던 경험이 있다면 선택 기준이 잘못된 것일 수 있다. "
                "기능 수와 가격만 보고 결정했다가 정작 필요한 기능이 없거나, 익히는 데 시간이 더 든 경우가 많다. "
                "ChatGPT, Claude, Copilot 모두 잘 만든 도구지만 업무 유형에 따라 적합한 도구가 다르다. "
                "내 반복 업무와 출력 형식을 기준으로 도구를 고르면 시행착오를 줄일 수 있다."
            ),
            "yomi_judgment": (
                "요미 판단: AI 도구 선택의 기준은 기능 목록이 아니라 내 실제 업무 워크플로우와의 적합성이다. "
                "같은 프롬프트에도 도구마다 출력 형식과 길이가 달라 검수 시간이 달라진다. "
                "무료 플랜의 제한 항목과 유료 전환 기준을 먼저 파악해야 불필요한 비용을 줄일 수 있다. "
                "지금 자신이 가장 자주 반복하는 업무 1가지를 기준으로 도구를 먼저 테스트하라."
            ),
            "misconceptions": [
                {
                    "착각": "기능이 많은 AI 도구가 무조건 더 유용하다",
                    "실제": "실제 업무에 맞는 출력 형식과 응답 정확도가 더 중요하다. 기능 수보다 적합성이 우선이다",
                },
                {
                    "착각": "유료 버전은 무조건 무료보다 낫다",
                    "실제": "반복 텍스트 초안 생성은 무료 버전으로도 충분한 경우가 많다. 유료 전환은 한계에 부딪힌 뒤에 판단하라",
                },
                {
                    "착각": "가장 유명한 AI 도구가 내 업무에도 최적이다",
                    "실제": "업무 유형(텍스트 작성, 코딩, 이미지 생성)에 따라 적합한 도구가 다르다",
                },
                {
                    "착각": "AI 도구는 한 번 익히면 평생 쓸 수 있다",
                    "실제": "업데이트 주기가 빠르고 새 도구가 계속 출시되므로 6개월마다 재평가가 권장된다",
                },
            ],
            "real_criterion": (
                "관점 1: 텍스트 생성 업무 — 보고서·이메일·요약처럼 텍스트가 주인 업무라면 ChatGPT 또는 Claude가 적합하다. "
                "Claude는 긴 문서 분석과 요약에 강점이 있고, ChatGPT는 구조화된 초안 생성에 빠르다.\n"
                "관점 2: 코딩·기술 업무 — GitHub Copilot이나 GPT-4는 코드 생성·디버깅에서 강점을 보인다. "
                "반복 코드 패턴이 많은 업무라면 코딩 특화 도구부터 테스트하라.\n"
                "관점 3: 비용 대비 효율 — 무료 플랜의 실제 한계(메시지 수·파일 업로드 여부)를 먼저 확인하라. "
                "한계에 자주 부딪히는 업무에만 유료 전환을 적용하면 비용을 줄일 수 있다."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "보고서·이메일 초안을 자주 쓴다",
                    "할 일": "ChatGPT 또는 Claude 무료 버전으로 동일 프롬프트 테스트 후 결과 비교",
                },
                {
                    "내 상황": "코드 작성·디버깅이 주 업무다",
                    "할 일": "GitHub Copilot 또는 GPT-4 코딩 특화 기능 먼저 테스트",
                },
                {
                    "내 상황": "긴 문서를 요약해야 한다",
                    "할 일": "Claude 무료 버전으로 긴 문서 입력 후 요약 품질 확인",
                },
                {
                    "내 상황": "이미 쓰는 도구가 있는데 한계를 느낀다",
                    "할 일": "한계 지점(메시지 수·파일 크기·정확도) 확인 후 유료 전환 여부 판단",
                },
                {
                    "내 상황": "어떤 AI 도구를 먼저 써야 할지 모른다",
                    "할 일": "가장 자주 반복하는 업무 1가지 선택 → ChatGPT 무료 버전으로 일주일 테스트",
                },
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "대표 업무 1개로 도구 비교 테스트",
                    "설명": "동일한 프롬프트를 ChatGPT와 Claude에 각각 입력해 출력 품질·형식·길이를 비교하라",
                },
                {
                    "번호": 2,
                    "행동": "무료 플랜 한계 먼저 확인",
                    "설명": "각 도구의 무료 플랜 메시지 수·파일 업로드 가능 여부·모델 버전을 공식 페이지에서 확인하라",
                },
                {
                    "번호": 3,
                    "행동": "프롬프트 결과 기록 후 비교",
                    "설명": "같은 업무에 다른 도구를 써본 결과를 메모앱에 기록해 일주일 뒤 비교하라. 체감 차이가 선택 기준이 된다",
                },
            ],
            "faq": [
                {
                    "Q": "ChatGPT와 Claude 중 어떤 게 더 낫나?",
                    "A": (
                        "업무 유형에 따라 다르다. "
                        "ChatGPT는 구조화된 텍스트 초안 생성에 빠르고, Claude는 긴 문서 분석과 논리적 요약에 강하다. "
                        "같은 프롬프트로 둘 다 테스트해보고 내 업무에 맞는 쪽을 선택하라."
                    ),
                },
                {
                    "Q": "무료 버전으로 업무에 쓸 수 있나?",
                    "A": (
                        "반복 텍스트 초안 생성, 요약, 번역은 무료 버전으로 충분히 가능하다. "
                        "파일 업로드나 긴 대화 이력이 필요한 작업에서 한계가 생기면 그때 유료를 고려하라."
                    ),
                },
                {
                    "Q": "AI 도구를 쓸 때 회사 보안은 어떻게 하나?",
                    "A": (
                        "고객 정보, 내부 기밀 데이터, 개인식별정보는 AI에 입력하지 말아야 한다. "
                        "회사 AI 사용 정책을 먼저 확인하고, 민감 정보는 가공하거나 익명화한 뒤 입력하라."
                    ),
                },
            ],
            "hashtags": [
                "#AI도구비교",
                "#ChatGPT",
                "#Claude",
                "#AI활용",
                "#업무생산성",
                "#직장인AI",
                "#생산성도구",
            ],
            "internal_links": [
                {
                    "주제": "ChatGPT 무료 vs 유료 기능 비교 — 직장인이 알아야 할 차이",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "AI 업무 활용 전 회사 보안 주의사항",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "업무자동화 입문 — 반복 업무 줄이는 3가지 패턴",
                    "content_type": "ai_work_tip",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_automation_workflow(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "반복 업무를 자동화하려고 도구를 설치했는데 처음 설정부터 막힌 경험이 있다면 순서가 잘못된 것일 수 있다. "
                "도구를 먼저 고르면 도구에 맞춰 업무를 바꾸게 된다. "
                "자동화에 적합한 업무는 규칙이 명확하고 입력과 출력이 고정된 반복 작업이다. "
                "도구 설치 전에 자동화할 업무 프로세스를 먼저 정의하면 시행착오를 줄일 수 있다."
            ),
            "yomi_judgment": (
                "요미 판단: 자동화 도구를 고르기 전에 자동화할 업무 프로세스부터 정의해야 한다. "
                "입력 자료, 처리 규칙, 출력 형식이 명확한 업무만 자동화 효과가 난다. "
                "검수 루프 없이 자동화하면 오류가 누적되어 수동 수정 비용이 증가한다. "
                "지금 내 업무 중 매주 동일한 형식으로 반복되는 것 1가지를 찾아 자동화 대상을 정하라."
            ),
            "misconceptions": [
                {
                    "착각": "자동화 도구를 설치하면 업무가 바로 자동화된다",
                    "실제": "도구 설치보다 자동화할 프로세스 정의와 검수 기준 설정이 먼저다. 정의 없이 도구를 쓰면 오히려 복잡도가 늘어난다",
                },
                {
                    "착각": "n8n, Zapier 같은 노코드 도구면 코딩 없이 뭐든 자동화된다",
                    "실제": "규칙이 단순하고 입출력이 명확한 업무만 노코드 자동화가 효과적이다. 예외가 많은 업무는 자동화 비용이 크다",
                },
                {
                    "착각": "자동화하면 검수가 필요 없다",
                    "실제": "자동화 초기에는 반드시 검수 루프가 필요하다. 예외 케이스를 발견하지 못하면 오류가 축적된다",
                },
                {
                    "착각": "복잡한 업무일수록 자동화 효과가 크다",
                    "실제": "규칙이 단순한 반복 업무가 자동화 적합도가 높다. 복잡한 판단이 필요한 업무는 AI 보조 + 사람 검수 구조가 더 효과적이다",
                },
            ],
            "real_criterion": (
                "단계 1: 자동화 대상 업무 선정 — 매주 동일 형식으로 반복되는 업무를 목록화한다. "
                "입력 자료와 출력 형식이 고정된 업무(보고서 정리, 데이터 정렬, 알림 발송 등)가 자동화에 적합하다.\n"
                "단계 2: 프로세스 단순화 — 자동화 전에 해당 업무의 단계를 3~5개로 줄인다. "
                "예외 케이스를 제거하거나 별도 처리로 분리해서 메인 흐름을 단순하게 만든다.\n"
                "단계 3: 파일럿 테스트와 검수 루프 설정 — 도구 적용 후 1~2주간 결과물을 직접 확인한다. "
                "예외가 발생하면 프로세스를 보완하고, 검수 없이 자동화 범위를 확대하지 않는다."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "자동화 도구를 설치했는데 어디서부터 시작해야 할지 모른다",
                    "할 일": "자동화할 업무 1가지 선정 → 입력·처리·출력 3단계로 정리 → 도구 연결",
                },
                {
                    "내 상황": "자동화를 했는데 오류가 자꾸 생긴다",
                    "할 일": "예외 케이스 확인 → 프로세스 단순화 → 검수 루프 추가",
                },
                {
                    "내 상황": "어떤 업무를 자동화해야 할지 모른다",
                    "할 일": "지난 한 달 동안 동일 형식으로 반복한 업무 3가지 목록화 → 가장 단순한 것부터 적용",
                },
                {
                    "내 상황": "노코드 도구가 너무 복잡하다",
                    "할 일": "Google Sheets 자동화(앱스스크립트)나 이메일 필터 규칙부터 먼저 적용",
                },
                {
                    "내 상황": "자동화 후 결과물 품질이 걱정된다",
                    "할 일": "처음 2주는 자동화 결과를 직접 검수 → 오류율이 낮으면 점진적으로 검수 빈도 줄이기",
                },
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "자동화 대상 업무 1가지 선정",
                    "설명": "이번 주 반복한 업무 중 입력과 출력이 고정된 것을 1가지 선택해 자동화 대상으로 지정하라",
                },
                {
                    "번호": 2,
                    "행동": "프로세스 3단계로 단순화",
                    "설명": "선정한 업무의 단계를 입력→처리→출력 3단계로 정리하고 예외 케이스를 별도 분리하라",
                },
                {
                    "번호": 3,
                    "행동": "파일럿 테스트 1주 실행",
                    "설명": "자동화 도구 적용 후 1주간 결과물을 직접 확인하라. 오류 패턴을 발견하면 프로세스를 먼저 보완하라",
                },
            ],
            "faq": [
                {
                    "Q": "n8n과 Zapier 중 어떤 걸 써야 하나?",
                    "A": (
                        "Zapier는 설정이 간단하고 주요 앱 연동이 쉬워 처음 자동화에 적합하다. "
                        "n8n은 무료 오픈소스로 복잡한 로직 구현이 가능하지만 초기 설정이 더 어렵다. "
                        "처음이라면 Zapier 무료 플랜으로 시작하는 것이 권장된다."
                    ),
                },
                {
                    "Q": "자동화하면 안 되는 업무가 있나?",
                    "A": (
                        "판단이 필요한 업무, 예외가 많은 업무, 실시간 대응이 필요한 업무는 자동화 적합도가 낮다. "
                        "이런 업무는 AI 보조 + 사람 검수 구조가 더 효과적이다."
                    ),
                },
                {
                    "Q": "자동화 후 오류가 생기면 어떻게 하나?",
                    "A": (
                        "오류 원인을 입력 자료 문제인지 처리 규칙 문제인지 먼저 분류하라. "
                        "입력 자료 문제라면 전처리 단계를 추가하고, 처리 규칙 문제라면 예외 케이스를 별도 분기로 처리하라."
                    ),
                },
            ],
            "hashtags": [
                "#업무자동화",
                "#AI자동화",
                "#워크플로우",
                "#반복업무",
                "#생산성향상",
                "#직장인AI",
                "#자동화도구",
            ],
            "internal_links": [
                {
                    "주제": "AI 도구 비교 — ChatGPT vs Claude 업무용 선택 기준",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "직장인 ChatGPT 활용 패턴 — 시간이 줄어드는 업무 3가지",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "업무자동화 도구 입문 가이드 — n8n·Zapier 비교",
                    "content_type": "ai_work_tip",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_prompt_recipe(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_prompt_recipe 플래그십 빌더.

        프롬프트 레시피형 — 복사 가능한 prompt_block과 결과물 품질 checklist를
        핵심 모듈로 갖는다. geo_score 게이트 유지를 위해 표준 슬롯도 함께 채운다.
        """
        slots: dict[str, Any] = {
            "hook_opening": (
                "프롬프트를 매번 새로 쓰느라 정작 일보다 프롬프트 고치는 데 시간이 더 들어간 적 있다면 그건 흔한 일이다. "
                "같은 업무인데도 그날그날 결과 품질이 들쭉날쭉한 이유는 프롬프트가 매번 달라서다. "
                "좋은 프롬프트는 영감이 아니라 고정된 양식에서 나온다. "
                "역할·목적·입력·출력 형식을 한 번 정해 템플릿으로 굳히면 결과가 안정된다. "
                "아래 레시피는 복사해서 값만 바꿔 바로 쓸 수 있게 구성했다."
            ),
            "yomi_judgment": (
                "프롬프트의 핵심은 길이가 아니라 구조다. 역할 지정, 작업 목적, 입력 자료, 출력 형식, 제약 조건 다섯 가지를 "
                "고정하면 짧아도 결과가 안정적이다. 매번 새로 쓰지 말고 잘 나온 프롬프트를 템플릿으로 저장해 값만 교체하라. "
                "AI 출력은 80점 초안이라는 전제는 프롬프트가 좋아져도 변하지 않으므로, 결과물 품질 체크리스트로 검수하는 단계를 함께 두어야 한다. "
                "지금 가장 자주 하는 업무 하나를 골라 아래 템플릿에 대입하는 것부터 시작하라."
            ),
            "prompt_block": [
                {
                    "label": "기본 템플릿 (역할·목적·입력·형식·제약)",
                    "prompt": (
                        "당신은 [직무/전문 역할]입니다.\n"
                        "다음 자료를 바탕으로 [작업 목적]을 작성해 주세요.\n\n"
                        "[입력 자료 또는 핵심 정보를 여기에 붙여넣기]\n\n"
                        "출력 형식: [예: 제목 + 3개 단락 + 불릿 5개]\n"
                        "조건: [분량, 어조, 대상 독자, 금지 표현 등]\n"
                        "확실하지 않은 사실은 추측하지 말고 '확인 필요'로 표시해 주세요."
                    ),
                },
                {
                    "label": "변형 1 — 보고서 초안",
                    "prompt": (
                        "당신은 [부서] 보고서를 쓰는 실무자입니다.\n"
                        "아래 메모를 바탕으로 경영진 보고용 요약 보고서 초안을 작성해 주세요.\n\n"
                        "[회의 메모/데이터 붙여넣기]\n\n"
                        "출력 형식: 핵심 결론 3줄 → 배경 → 다음 액션 표\n"
                        "조건: A4 1장 분량, 군더더기 없는 문어체, 숫자는 원문 그대로 인용."
                    ),
                },
                {
                    "label": "변형 2 — 긴 글 요약",
                    "prompt": (
                        "당신은 핵심만 뽑아내는 편집자입니다.\n"
                        "아래 글을 읽고 의사결정에 필요한 정보만 요약해 주세요.\n\n"
                        "[원문 붙여넣기]\n\n"
                        "출력 형식: 한 줄 요약 → 핵심 포인트 5개 → 주의할 점 2개\n"
                        "조건: 원문에 없는 내용은 추가하지 말 것."
                    ),
                },
            ],
            "real_criterion": (
                "1단계: 역할과 목적부터 한 줄로 — '당신은 ~입니다 / ~을 작성해 주세요'를 먼저 고정한다. "
                "이 한 줄이 결과 품질의 절반을 결정한다.\n"
                "2단계: 입력과 출력 형식을 분리 — 붙여넣는 자료(입력)와 받고 싶은 형태(출력 형식)를 명시적으로 나눠 적는다. "
                "'표로', '불릿 5개로'처럼 형태를 지정할수록 재작업이 줄어든다.\n"
                "3단계: 제약과 안전장치 추가 — 분량·어조·대상 독자를 적고, '확실하지 않으면 추측하지 말 것'을 넣어 환각을 줄인다. "
                "잘 나온 프롬프트는 그 자리에서 템플릿으로 저장해 다음에 값만 바꿔 재사용한다."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "결과가 매번 달라 불안정하다",
                    "할 일": "출력 형식 줄을 고정 — '제목+3단락+불릿5개'처럼 형태를 명시하면 일관성이 올라간다",
                },
                {
                    "내 상황": "프롬프트가 너무 길어진다",
                    "할 일": "역할·목적·형식 3줄로 축약 — 설명보다 형식 지정이 품질을 좌우한다",
                },
                {
                    "내 상황": "AI가 사실을 지어낸다",
                    "할 일": "'확실하지 않으면 확인 필요로 표시' 제약을 추가하고 핵심 사실은 직접 검증",
                },
                {
                    "내 상황": "매번 처음부터 다시 쓴다",
                    "할 일": "잘 나온 프롬프트를 메모앱·문서에 저장 → 다음엔 값만 교체",
                },
                {
                    "내 상황": "어떤 업무에 쓸지 모르겠다",
                    "할 일": "반복되는 텍스트 업무(보고서·이메일·요약) 하나를 골라 기본 템플릿에 대입",
                },
            ],
            "checklist": [
                "요청한 출력 형식(제목·단락·표 등)을 그대로 지켰는가",
                "핵심 사실 2~3개를 원문·공식 자료로 직접 확인했는가",
                "원문에 없는 내용을 임의로 지어내지 않았는가",
                "대상 독자와 어조(문어체/구어체)가 맞는가",
                "민감 정보(개인정보·사내 기밀)를 입력에 넣지 않았는가",
                "5분 안에 수정이 끝나는가 — 더 걸리면 프롬프트를 손봐야 한다",
            ],
            "risk_note": [
                "사내 기밀·고객 개인정보·계약서 원문을 프롬프트 입력에 그대로 붙여넣지 말 것. 회사 AI 사용 정책을 먼저 확인한다.",
                "AI는 그럴듯한 거짓을 만들어낼 수 있다(환각). 숫자·인용·출처는 반드시 원문으로 직접 검증한다.",
                "생성 결과를 그대로 게시·제출할 때 저작권·표절 문제가 생길 수 있으므로 사실과 표현을 손본 뒤 사용한다.",
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "기본 템플릿 복사해 1개 업무에 대입",
                    "설명": "가장 자주 하는 텍스트 업무를 골라 위 기본 템플릿의 대괄호 값만 바꿔 실행해 보라",
                },
                {
                    "번호": 2,
                    "행동": "잘 나온 프롬프트를 템플릿으로 저장",
                    "설명": "결과가 만족스러웠던 프롬프트를 메모앱·Notion에 라벨을 붙여 저장하고 동일 업무에 재사용하라",
                },
                {
                    "번호": 3,
                    "행동": "결과물 품질 체크리스트로 검수",
                    "설명": "출력을 받은 뒤 위 체크리스트 6개 항목을 통과시키고, 통과 못 하면 프롬프트의 형식·제약 줄을 수정하라",
                },
            ],
            "faq": [
                {
                    "Q": "프롬프트는 길수록 좋은가?",
                    "A": (
                        "아니다. 길이보다 구조가 중요하다. 역할·목적·입력·출력 형식·제약 다섯 가지가 들어가면 "
                        "짧아도 결과가 안정적이다. 불필요한 설명을 늘리는 것보다 출력 형식을 명확히 지정하는 편이 품질에 더 효과적이다."
                    ),
                },
                {
                    "Q": "무료 버전으로도 이 템플릿이 통하나?",
                    "A": (
                        "보고서 초안·요약·이메일 같은 구조화된 텍스트 작업은 무료 버전으로도 충분히 활용 가능하다. "
                        "모델별로 표현 차이는 있지만 템플릿 구조 자체는 동일하게 적용된다."
                    ),
                },
                {
                    "Q": "AI가 사실을 지어내는 건 프롬프트로 막을 수 있나?",
                    "A": (
                        "완전히 막을 수는 없다. '확실하지 않으면 추측하지 말고 확인 필요로 표시'라는 제약으로 줄일 수는 있지만, "
                        "핵심 사실 2~3개는 사람이 직접 확인하는 검수 단계가 반드시 필요하다."
                    ),
                },
            ],
            "hashtags": [
                "#프롬프트",
                "#프롬프트템플릿",
                "#ChatGPT활용",
                "#AI활용",
                "#업무자동화",
                "#프롬프트작성법",
                "#생산성향상",
            ],
            "internal_links": [
                {
                    "주제": "ChatGPT로 업무 시간 줄이는 법 — 반복 업무 먼저 맡기기",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "AI 도구 비교 — 업무용으로 무엇을 고를까",
                    "content_type": "ai_work_tip",
                },
                {
                    "주제": "AI 결과물 검수 기준 — 그대로 쓰면 안 되는 이유",
                    "content_type": "ai_work_tip",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["prompt_block"] = "lookup"
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["checklist"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_tool_review(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_tool_review 플래그십 빌더 (master_guide Category A 구조).

        1줄 요약 → 누구에게 맞나(추천/비추) → 직접 써본 결과 → 무료/유료 경계 →
        최종 판정(별점). who_for / pricing_table / verdict / tool_summary 모듈을 갖는다.
        """
        slots: dict[str, Any] = {
            "hook_opening": (
                "새 AI 도구가 나올 때마다 '이거 진짜 쓸 만한가' 검색부터 하게 된다면 당연한 일이다. "
                "기능 목록만 봐서는 내 업무에 맞는지 알 수 없고, 광고성 후기는 단점을 가린다. "
                "도구는 기능 수가 아니라 내 반복 업무에 실제로 시간을 줄여주는지로 판단해야 한다. "
                "무료로 어디까지 되는지, 유료는 어디서부터 필요한지의 경계도 미리 알아야 한다. "
                "아래는 직접 써보고 판단하는 기준과 추천·비추 대상을 정리한 것이다."
            ),
            "tool_summary": (
                "한 줄 요약: 반복적인 텍스트·정리 업무를 빠르게 처리하는 데 강하고, "
                "사실 검증이 필요한 작업에는 사람의 확인이 반드시 필요한 보조 도구다."
            ),
            "yomi_judgment": (
                "도구는 기능 개수가 아니라 내 반복 업무에서 검수 시간을 줄여주는지로 판단한다. "
                "무료 범위에서 내 실제 업무 한 가지를 직접 시켜 보고, 결과물을 5분 안에 다듬을 수 있으면 그 업무엔 합격이다. "
                "유료는 무료 한계(횟수·고급 모델·파일 처리)에 실제로 막힐 때 전환하면 된다. "
                "지금 내 반복 업무 하나를 골라 무료로 테스트하는 것부터 시작하라."
            ),
            "who_for": {
                "추천": [
                    "보고서·이메일·요약처럼 형식이 반복되는 텍스트 업무가 많은 사람",
                    "초안을 빠르게 받아 직접 다듬는 작업 방식을 선호하는 사람",
                    "무료 범위 안에서 먼저 충분히 테스트해 보려는 사람",
                ],
                "비추": [
                    "검증 없이 결과물을 그대로 제출·게시하려는 사람",
                    "민감한 사내 기밀·개인정보를 입력해야 하는 업무",
                    "완성도 100%를 기대하고 검수 시간을 들이지 않으려는 사람",
                ],
            },
            "real_criterion": (
                "1단계: 무료 범위에서 내 반복 업무 1개를 그대로 시켜본다 — 광고가 아니라 내 실제 작업으로 검증한다.\n"
                "2단계: 결과물의 검수 시간을 잰다 — 5분 안에 다듬어지면 합격, 매번 전부 다시 써야 하면 그 업무엔 맞지 않는다.\n"
                "3단계: 무료 한계에 부딪히는 지점을 확인한다 — 횟수 제한·고급 모델·파일 업로드 등 어디서 막히는지가 유료 전환 판단 기준이다."
            ),
            "pricing_table": [
                {"플랜": "무료", "가격": "0원", "핵심 기능": "기본 모델, 일반 텍스트 생성·요약", "한계": "사용량/횟수 제한, 고급 모델 제외"},
                {"플랜": "유료(개인)", "가격": "월 2만~3만원대", "핵심 기능": "고급 모델, 더 긴 입력, 파일 처리", "한계": "팀 협업·관리 기능 부족"},
                {"플랜": "팀/기업", "가격": "1인당 추가 과금", "핵심 기능": "관리·보안·데이터 정책 옵션", "한계": "도입 절차·비용 부담"},
            ],
            "quick_decision_table": [
                {"내 상황": "처음 써본다", "할 일": "무료 플랜에서 내 반복 업무 1개로 먼저 테스트"},
                {"내 상황": "무료로 자주 막힌다", "할 일": "막히는 지점(횟수·모델·파일)이 유료 핵심 기능과 맞는지 확인 후 결정"},
                {"내 상황": "사내 자료를 다룬다", "할 일": "회사 AI 사용 정책·데이터 처리 옵션부터 확인, 기밀은 입력 금지"},
                {"내 상황": "비슷한 도구와 고민된다", "할 일": "같은 업무를 두 도구에 시켜 검수 시간을 직접 비교"},
                {"내 상황": "결과 품질이 들쭉날쭉", "할 일": "도구 문제가 아니라 입력·요청 방식 문제일 수 있으니 요청 형식부터 고정"},
            ],
            "verdict": {
                "결론": (
                    "반복 텍스트 업무가 많고 직접 검수할 의향이 있다면 무료 플랜부터 도입할 가치가 충분하다. "
                    "다만 사실 검증과 민감정보 관리는 도구가 대신해 주지 않으므로, 검수 루프를 함께 두는 조건에서 추천한다."
                ),
                "별점": 4,
            },
            "actions": [
                {"번호": 1, "행동": "무료로 실제 업무 1개 테스트", "설명": "광고 후기 대신 내 반복 업무를 직접 시켜 검수 시간을 측정한다"},
                {"번호": 2, "행동": "무료 한계 지점 기록", "설명": "어디서 막히는지(횟수·모델·파일)를 적어 유료 전환 필요 여부를 판단한다"},
                {"번호": 3, "행동": "검수 체크 기준 정하기", "설명": "사실 2~3개 확인·민감정보 미입력을 고정 규칙으로 두고 사용한다"},
            ],
            "faq": [
                {
                    "Q": "무료로 어디까지 쓸 수 있나요?",
                    "A": (
                        "기본 모델로 텍스트 생성·요약·번역은 무료로 충분히 가능합니다. "
                        "사용 횟수 제한, 고급 모델, 긴 문서·파일 처리에서 무료 한계에 부딪히며, 그 지점이 유료 전환 판단 기준이 됩니다."
                    ),
                },
                {
                    "Q": "비슷한 도구 중 무엇을 골라야 하나요?",
                    "A": (
                        "기능 목록이 아니라 같은 업무를 두 도구에 시켜 검수 시간을 비교해 고르는 것이 정확합니다. "
                        "내 반복 업무에서 다듬는 시간이 더 짧은 쪽이 나에게 맞는 도구입니다."
                    ),
                },
                {
                    "Q": "결과물을 그대로 업무에 써도 되나요?",
                    "A": (
                        "그대로 쓰는 것은 위험합니다. AI는 그럴듯한 오류를 만들 수 있어 핵심 사실 2~3개는 직접 확인해야 하고, "
                        "사내 기밀·개인정보는 입력하지 않는 것이 원칙입니다."
                    ),
                },
            ],
            "hashtags": [
                "#AI도구",
                "#AI리뷰",
                "#AI툴추천",
                "#ChatGPT활용",
                "#업무자동화",
                "#생산성도구",
                "#무료AI",
            ],
            "internal_links": [
                {"주제": "AI 도구 비교 — 업무 유형별로 고르는 기준", "content_type": "ai_work_tip"},
                {"주제": "복사해서 쓰는 업무용 프롬프트 템플릿", "content_type": "ai_prompt_recipe"},
                {"주제": "AI 결과물 검수 기준 — 그대로 쓰면 안 되는 이유", "content_type": "ai_work_tip"},
            ],
            "risk_note": [
                "요금·기능·무료 한도는 서비스 정책에 따라 수시로 바뀌므로 도입 전 공식 가격 페이지를 직접 확인할 것.",
                "사내 기밀·고객 개인정보를 입력에 넣지 말고, 회사 AI 사용 정책을 먼저 확인한다.",
                "AI 결과물은 사실 오류(환각)가 있을 수 있으므로 숫자·인용·출처는 원문으로 검증한다.",
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        for k in ("tool_summary", "who_for", "real_criterion", "pricing_table", "verdict", "actions"):
            fill_strategy[k] = "lookup"
        return slots, fill_strategy

    def _build_ai_model_update(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_model_update — 모델 업데이트 해설. 확인된 변경 vs 과장 기대를 구분."""
        slots: dict[str, Any] = {
            "hook_opening": (
                "새 AI 모델이 공개되면 남들보다 먼저 써보고 활용법을 아는 사람이 가장 크게 이득을 본다. "
                "문제는 발표 첫날엔 정보가 과장과 추측으로 뒤섞여 '지금 당장 뭘 할 수 있는지'가 잘 안 보인다는 점이다. "
                "그래서 이 글은 무엇이 새로 가능해졌고, 오늘 바로 해볼 수 있는 활용법이 무엇인지에 집중한다. "
                "왜 지금 화제인지, 그리고 이걸로 지금 무엇을 할 수 있는지부터 빠르게 정리한다."
            ),
            "yomi_judgment": (
                "이번 업데이트가 주목받는 이유는 그동안 한계였던 작업(긴 문서 처리·추론·코드·이미지 등)이 새로 풀렸기 때문이다. "
                "핵심은 버전 숫자가 아니라 '전에는 안 되던 게 지금 되는가'다. 거기서 새로운 활용법이 나온다. "
                "남들보다 먼저 내 반복 업무 한 가지에 적용해 보면 어떤 작업에서 이득인지 바로 감이 온다. "
                "다만 첫날 정보엔 과장이 섞이므로, 활용은 빠르게 하되 사실·요금은 공식 발표로 확인하라."
            ),
            "misconceptions": [
                {"착각": "새 모델이면 모든 작업이 다 좋아진다", "실제": "이미 잘 되던 작업은 차이가 작고, 전에 한계였던 영역에서 새 활용법이 열린다"},
                {"착각": "벤치마크 1위면 내 업무에도 최고다", "실제": "벤치마크는 시험 점수다. 내 실제 업무로 직접 써봐야 활용 가치를 안다"},
                {"착각": "출시 첫날 정보는 다 사실이다", "실제": "첫날엔 과장·추측이 섞인다. 요금·기능은 공식 발표 기준으로 확인해야 한다"},
            ],
            "real_criterion": (
                "활용법 1: 전에 막히던 작업부터 다시 시도 — 길어서 못 넣던 문서, 복잡한 추론, 코드 디버깅처럼 한계였던 일을 새 모델로 먼저 돌려본다.\n"
                "활용법 2: 내 반복 업무에 그대로 얹기 — 자주 쓰는 보고서·요약·번역 프롬프트를 새 모델에 넣어 품질과 시간이 어떻게 달라지는지 본다.\n"
                "활용법 3: 새로 생긴 기능을 한 번씩 써보기 — 이미지·파일·음성·긴 컨텍스트 등 추가된 기능을 실제 업무 예시로 한 번씩 테스트해 쓸 곳을 찾는다."
            ),
            "quick_decision_table": [
                {"내 상황": "전에 길이·복잡도로 막혔다", "할 일": "가장 효과 큰 영역 — 막히던 작업을 새 모델로 먼저 재시도"},
                {"내 상황": "글쓰기·요약 위주다", "할 일": "체감 차이는 작을 수 있으니 무료 범위에서 같은 프롬프트로 비교"},
                {"내 상황": "새 기능(이미지·파일)이 궁금하다", "할 일": "실제 업무 예시 하나로 한 번씩 테스트해 쓸 곳 발굴"},
                {"내 상황": "유료 전환을 고민 중", "할 일": "달라진 요금·사용량 한도를 공식 페이지에서 확인 후 결정"},
            ],
            "actions": [
                {"번호": 1, "행동": "막히던 작업부터 재시도", "설명": "전에 한계였던 일(긴 문서·추론·코드)을 새 모델로 먼저 돌려 새 활용처를 찾는다"},
                {"번호": 2, "행동": "내 프롬프트로 직접 비교", "설명": "자주 쓰는 프롬프트를 이전/신규에 넣어 품질·시간 차이를 확인한다"},
                {"번호": 3, "행동": "공식 발표로 사실 확인", "설명": "요금·무료 제공 범위·기능은 첫날 소문 대신 공식 채널로 검증한다"},
            ],
            "faq": [
                {"Q": "지금 새 모델로 뭘 먼저 해보면 좋나요?", "A": "전에 막히던 작업부터 시도하세요. 너무 길어 못 넣던 문서 요약, 복잡한 추론, 코드 디버깅처럼 한계였던 일에서 가장 큰 차이를 체감할 수 있습니다."},
                {"Q": "벤치마크 점수를 믿어도 되나요?", "A": "참고치로만 보세요. 벤치마크는 시험 점수라 내 실제 업무 성능과 다를 수 있습니다. 자주 쓰는 프롬프트로 직접 비교가 가장 정확합니다."},
                {"Q": "무료로도 새 모델을 쓸 수 있나요?", "A": "초기에는 유료·사용량 제한이 있는 경우가 많습니다. 무료 제공 범위와 요금은 공식 발표에서 확인해야 합니다."},
            ],
            "hashtags": ["#AI모델", "#AI업데이트", "#ChatGPT", "#AI뉴스", "#생성형AI", "#AI활용", "#AI트렌드"],
            "internal_links": [
                {"주제": "AI 도구 직접 써보고 판단하는 기준", "content_type": "ai_tool_review"},
                {"주제": "AI 도구·모델 요금제 비교", "content_type": "ai_comparison"},
                {"주제": "AI 결과물 검수 기준", "content_type": "ai_work_tip"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_search_change(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_search_change — AI 검색(AEO/GEO/SGE) 변화 해설."""
        slots: dict[str, Any] = {
            "hook_opening": (
                "검색창에 질문을 넣으면 파란 링크 대신 AI가 정리한 답변이 먼저 뜨는 일이 잦아졌다. "
                "이 변화에 블로그·콘텐츠 운영자는 '클릭이 줄어드는 것 아닌가' 걱정부터 든다. "
                "검색은 사라지는 게 아니라 'AI가 인용할 소스가 되는 경쟁'으로 형태가 바뀌고 있다. "
                "용어부터 정리하고, 내 글이 인용되려면 무엇을 바꿔야 하는지 보자."
            ),
            "yomi_judgment": (
                "AEO·GEO·SGE는 모두 'AI 답변에 내 글이 소스로 쓰이게 하는 최적화'를 가리킨다. "
                "기존 SEO가 끝난 게 아니라, 명확한 사실·구조화된 정보·신뢰 신호가 더 중요해진 것이다. "
                "질문형 제목, 첫 문장 직접 답변, 표·정의 박스, 최신 날짜·출처가 인용 확률을 높인다. "
                "지금 내 글에서 핵심 답변이 한 문단으로 추출 가능한지부터 점검하라."
            ),
            "misconceptions": [
                {"착각": "AI 검색이 뜨면 SEO는 끝이다", "실제": "AI가 인용할 소스를 고르는 기준이 추가됐을 뿐, 명확성·신뢰도는 더 중요해졌다"},
                {"착각": "키워드만 많이 넣으면 인용된다", "실제": "AI는 명확한 사실·구조화된 답변을 인용한다. 키워드 반복은 오히려 역효과다"},
                {"착각": "AI 검색은 트래픽을 다 가져간다", "실제": "출처 링크가 함께 노출돼, 인용되는 글은 오히려 신뢰·유입을 얻을 수 있다"},
            ],
            "real_criterion": (
                "1단계: 핵심 질문에 첫 문장으로 직접 답한다 — 'X는 ~입니다'로 시작해 AI가 추출하기 쉽게 만든다.\n"
                "2단계: 구조화한다 — 정의는 정의 박스, 순서는 번호 목록, 비교는 표로 제시한다.\n"
                "3단계: 신뢰 신호를 더한다 — 최신 업데이트 날짜, 작성자 정보, 외부 공식 출처 링크를 넣는다."
            ),
            "quick_decision_table": [
                {"내 상황": "글이 길고 결론이 흩어져 있다", "할 일": "각 섹션 첫 문장에 핵심 답을 배치해 추출 가능하게 정리"},
                {"내 상황": "표·목록 없이 줄글만 있다", "할 일": "비교는 표, 순서는 번호 목록으로 구조화"},
                {"내 상황": "날짜·출처가 없다", "할 일": "업데이트 날짜와 공식 출처 링크를 추가해 신뢰 신호 보강"},
                {"내 상황": "FAQ가 없다", "할 일": "독자 질문 3개를 질문형 제목+직접 답변으로 추가"},
            ],
            "actions": [
                {"번호": 1, "행동": "핵심 답변 한 문단화", "설명": "글 맨 앞에 질문에 대한 직접 답변을 3~5문장으로 정리한다"},
                {"번호": 2, "행동": "구조화 요소 추가", "설명": "정의 박스·비교표·번호 목록으로 AI가 추출하기 쉽게 만든다"},
                {"번호": 3, "행동": "신뢰 신호 보강", "설명": "업데이트 날짜·작성자·공식 출처 링크를 추가한다"},
            ],
            "faq": [
                {"Q": "AEO와 GEO는 무엇이 다른가요?", "A": "AEO는 구글 추천 스니펫·답변 박스 점유에, GEO는 ChatGPT·Perplexity 같은 생성형 엔진의 인용에 초점이 있습니다. 실무에서는 '명확·구조화·신뢰'라는 공통 원칙으로 함께 대응합니다."},
                {"Q": "AI 검색 때문에 블로그 트래픽이 줄어드나요?", "A": "단순 정보성 클릭은 줄 수 있지만, 인용되는 글은 출처 링크로 노출돼 신뢰와 유입을 얻습니다. 깊이 있는 글일수록 유리합니다."},
                {"Q": "지금 당장 무엇부터 해야 하나요?", "A": "각 글의 핵심 답변을 맨 앞 한 문단으로 정리하고, 표·날짜·출처를 더하는 것부터 시작하세요."},
            ],
            "hashtags": ["#AI검색", "#GEO", "#AEO", "#SGE", "#블로그SEO", "#AI인용", "#콘텐츠전략"],
            "internal_links": [
                {"주제": "AI 블로그 운영·수익화·자동화", "content_type": "ai_blog_growth"},
                {"주제": "복사해서 쓰는 업무용 프롬프트 템플릿", "content_type": "ai_prompt_recipe"},
                {"주제": "AI 도구 직접 써보고 판단하는 기준", "content_type": "ai_tool_review"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_blog_growth(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_blog_growth — AI 블로그 운영/수익화/자동화."""
        slots: dict[str, Any] = {
            "hook_opening": (
                "AI로 글을 빠르게 쓸 수 있게 되면서 '발행량만 늘리면 조회수가 오르겠지' 기대하기 쉽다. "
                "하지만 검수 없이 찍어낸 글은 검색에서 밀리고 오히려 블로그 신뢰도를 깎는다. "
                "AI는 발행 속도를 높이는 도구이지, 품질과 검색 노출을 보장하는 도구가 아니다. "
                "조회수를 망치는 구조를 먼저 피하고, 검수 루프를 갖춘 자동화를 설계해야 한다."
            ),
            "yomi_judgment": (
                "AI 블로그의 성패는 '양'이 아니라 '검색 의도를 충족하는 깊이'에서 갈린다. "
                "AI 초안을 그대로 올리면 비슷한 글이 양산돼 차별화가 사라진다. "
                "내 경험·데이터·관점을 더하고, 발행 전 품질 체크리스트로 거르는 루프가 핵심이다. "
                "지금 가장 조회수가 낮은 글의 구조부터 점검해 보라."
            ),
            "real_criterion": (
                "1단계: 검색 의도가 명확한 주제 선정 — 'X 하는 법', 'A vs B'처럼 답을 찾는 검색어를 고른다.\n"
                "2단계: AI 초안 + 사람 가치 추가 — 초안을 받되 내 경험·수치·관점을 더해 차별화한다.\n"
                "3단계: 발행 전 품질 검수 — 체크리스트로 사실·구조·중복을 거른 뒤 발행하고, 내부 링크로 글을 연결한다."
            ),
            "quick_decision_table": [
                {"내 상황": "발행량은 많은데 조회수가 안 는다", "할 일": "양 대신 검색 의도 충족도 점검 — 깊이 있는 글 위주로 전환"},
                {"내 상황": "비슷한 글이 많아 묻힌다", "할 일": "내 경험·데이터·관점을 더해 AI 초안과 차별화"},
                {"내 상황": "글끼리 연결이 없다", "할 일": "관련 글을 내부 링크로 묶어 허브 구조 구성"},
                {"내 상황": "수익이 안 난다", "할 일": "구매·비교 의도 키워드(도구 비교·요금) 글 비중을 늘려 RPM 개선"},
            ],
            "checklist": [
                "검색 의도가 명확한 제목인가 (답을 찾는 검색어인가)",
                "AI 초안에 내 경험·수치·관점이 더해졌는가",
                "다른 글과 중복되는 내용이 아닌가",
                "핵심 사실을 출처로 확인했는가",
                "관련 글로 가는 내부 링크가 2개 이상인가",
                "제목·첫 문단에 핵심 답이 들어 있는가",
            ],
            "actions": [
                {"번호": 1, "행동": "저조한 글 구조 점검", "설명": "조회수 낮은 글의 제목·첫 문단·검색 의도 충족도를 먼저 점검한다"},
                {"번호": 2, "행동": "품질 체크리스트 적용", "설명": "발행 전 체크리스트 6개 항목을 통과시키는 루프를 고정한다"},
                {"번호": 3, "행동": "내부 링크 허브 구성", "설명": "관련 글을 묶어 허브-서브 구조로 연결해 체류·인덱싱을 개선한다"},
            ],
            "faq": [
                {"Q": "AI로 쓴 글도 검색에 노출되나요?", "A": "노출됩니다. 다만 검수 없이 양산한 글은 밀립니다. 사람의 경험·검증이 더해진 글이 유리합니다."},
                {"Q": "하루에 몇 개를 올려야 하나요?", "A": "개수보다 검색 의도를 충족하는 깊이가 중요합니다. 적게 올리더라도 깊이 있는 글이 장기적으로 트래픽을 모읍니다."},
                {"Q": "수익을 높이려면 어떤 글을 써야 하나요?", "A": "도구 비교·요금제·구매 결정에 도움이 되는 키워드 글이 광고 단가(RPM)가 높은 편입니다."},
            ],
            "hashtags": ["#AI블로그", "#블로그수익화", "#애드센스", "#블로그자동화", "#콘텐츠SEO", "#블로그운영", "#트래픽"],
            "internal_links": [
                {"주제": "AI 검색 변화 — 인용되는 글 구조", "content_type": "ai_search_change"},
                {"주제": "복사해서 쓰는 업무용 프롬프트 템플릿", "content_type": "ai_prompt_recipe"},
                {"주제": "AI 도구 직접 써보고 판단하는 기준", "content_type": "ai_tool_review"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["checklist"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_comparison(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_comparison — AI 도구/모델/요금제 비교 (pricing_table+who_for+verdict)."""
        slots: dict[str, Any] = {
            "hook_opening": (
                "AI 도구가 많아지면서 'A랑 B 중 뭐가 나아?'라는 질문이 가장 흔해졌다. "
                "기능 목록만 비교하면 다 비슷해 보이고, 정작 내 업무에 맞는지는 알 수 없다. "
                "비교의 기준은 기능 수가 아니라 내 반복 업무에서의 결과 품질과 검수 시간이다. "
                "아래에 무료/유료 경계와 상황별 추천, 최종 판단 기준을 정리했다."
            ),
            "yomi_judgment": (
                "도구·모델 비교에 '절대 승자'는 없다. 글쓰기에 강한 도구와 코딩·분석에 강한 도구가 다르다. "
                "무료로 어디까지 되는지, 유료 전환 시 무엇이 풀리는지의 경계가 실제 선택 기준이다. "
                "같은 업무를 두 도구에 시켜 검수 시간을 비교하면 내게 맞는 쪽이 분명해진다. "
                "지금 가장 자주 하는 업무 하나로 직접 비교해 보라."
            ),
            "real_criterion": (
                "1단계: 비교 기준 정하기 — 기능 개수가 아니라 내 핵심 업무(글쓰기·코딩·요약 등)를 기준 작업으로 정한다.\n"
                "2단계: 같은 입력으로 동시 비교 — 동일한 요청을 양쪽에 넣어 결과 품질과 다듬는 시간을 나란히 본다.\n"
                "3단계: 무료/유료 경계 확인 — 무료로 어디까지 되는지, 어디서 막혀 유료가 필요한지를 공식 가격으로 확인해 최종 선택한다."
            ),
            "pricing_table": [
                {"플랜": "무료", "가격": "0원", "핵심 기능": "기본 모델, 일반 텍스트·요약", "한계": "사용량 제한, 고급 모델 제외"},
                {"플랜": "유료(개인)", "가격": "월 2만~3만원대", "핵심 기능": "고급 모델, 긴 입력, 파일 처리", "한계": "팀 관리·보안 기능 부족"},
                {"플랜": "팀/기업", "가격": "1인당 추가 과금", "핵심 기능": "관리·보안·데이터 정책", "한계": "도입 절차·비용 부담"},
            ],
            "who_for": {
                "추천": [
                    "글쓰기·요약 중심이면 자연스러운 문장 품질이 강한 쪽",
                    "코딩·분석·긴 문서 처리면 추론·컨텍스트가 강한 쪽",
                    "무료로 충분한지 먼저 확인하려는 사람",
                ],
                "비추": [
                    "기능 목록만 보고 '더 많은 쪽'을 고르려는 경우",
                    "내 실제 업무로 검증하지 않고 후기만 보는 경우",
                ],
            },
            "quick_decision_table": [
                {"내 상황": "글쓰기·요약 위주", "할 일": "문장 자연스러움·한국어 품질이 좋은 도구를 무료로 비교"},
                {"내 상황": "코딩·분석 위주", "할 일": "추론·긴 컨텍스트에 강한 도구 우선 테스트"},
                {"내 상황": "비용을 아끼고 싶다", "할 일": "무료 한계에 실제로 막힐 때만 유료 전환"},
                {"내 상황": "둘 다 비슷해 보인다", "할 일": "같은 업무를 양쪽에 시켜 검수 시간으로 결정"},
            ],
            "verdict": {
                "결론": "절대 강자는 없다. 글쓰기 중심이면 문장 품질이 좋은 쪽, 코딩·분석 중심이면 추론이 강한 쪽이 유리하다. 무료로 내 업무를 비교한 뒤, 무료 한계에 막힐 때 유료로 넘어가는 순서를 추천한다.",
                "별점": 4,
            },
            "actions": [
                {"번호": 1, "행동": "내 핵심 업무 1개 선정", "설명": "가장 자주 하는 업무를 비교 기준 작업으로 정한다"},
                {"번호": 2, "행동": "두 도구에 같은 입력", "설명": "동일 입력을 넣어 결과 품질과 다듬는 시간을 비교한다"},
                {"번호": 3, "행동": "무료 한계 확인 후 결정", "설명": "어디서 막히는지 확인하고 필요할 때만 유료로 전환한다"},
            ],
            "faq": [
                {"Q": "결국 어떤 걸 써야 하나요?", "A": "업무 유형에 따라 다릅니다. 글쓰기는 문장 품질, 코딩·분석은 추론이 강한 쪽이 유리합니다. 내 업무로 비교하는 것이 가장 정확합니다."},
                {"Q": "무료 플랜만으로 충분한가요?", "A": "텍스트 생성·요약 위주라면 충분한 경우가 많습니다. 사용량·고급 모델·파일 처리에서 막힐 때 유료를 고려하세요."},
                {"Q": "가격 비교는 어디서 확인하나요?", "A": "요금은 자주 바뀌므로 각 서비스 공식 가격 페이지에서 직접 확인해야 합니다."},
            ],
            "hashtags": ["#AI비교", "#AI도구", "#ChatGPTvsClaude", "#AI요금제", "#AI추천", "#생산성도구", "#AI선택"],
            "internal_links": [
                {"주제": "AI 도구 직접 써보고 판단하는 기준", "content_type": "ai_tool_review"},
                {"주제": "AI 모델 업데이트 — 무엇이 바뀌었나", "content_type": "ai_model_update"},
                {"주제": "ChatGPT로 업무 시간 줄이는 법", "content_type": "ai_work_tip"},
            ],
            "risk_note": [
                "요금·무료 한도·기능은 수시로 바뀌므로 도입 전 공식 가격 페이지를 직접 확인할 것.",
                "벤치마크·후기는 참고치이며, 내 실제 업무 결과로 검증해야 한다.",
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        for k in ("pricing_table", "who_for", "verdict", "quick_decision_table", "actions"):
            fill_strategy[k] = "lookup"
        return slots, fill_strategy

    def _build_ai_risk_security(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_risk_security — 개인정보/보안/저작권/환각 리스크와 대응."""
        slots: dict[str, Any] = {
            "hook_opening": (
                "업무에 AI를 쓰다 보면 '이 자료를 넣어도 되나' 잠깐 망설인 적이 있을 것이다. "
                "편의만 보고 사내 기밀이나 고객 정보를 그대로 입력하면 돌이키기 어려운 사고로 이어진다. "
                "AI 리스크는 막연한 공포가 아니라, 입력 단계에서 지킬 규칙으로 대부분 예방된다. "
                "무엇이 진짜 위험이고 어떻게 막는지, 구체적인 안전장치를 정리했다."
            ),
            "yomi_judgment": (
                "AI 리스크는 '쓰지 말기'가 아니라 '안전하게 쓰는 규칙'으로 관리하는 것이 현실적이다. "
                "핵심은 세 가지다. 민감정보는 입력하지 않기, 결과의 사실은 직접 검증하기, 저작권·정책을 확인하기. "
                "특히 환각(그럴듯한 거짓)은 기술로 완전히 못 막으므로 사람의 검수 단계가 필수다. "
                "지금 내가 AI에 넣는 자료에 기밀·개인정보가 섞여 있지 않은지부터 점검하라."
            ),
            "misconceptions": [
                {"착각": "입력한 자료는 어차피 사라진다", "실제": "서비스·설정에 따라 학습·보관될 수 있다. 민감정보는 처음부터 넣지 않는 게 원칙이다"},
                {"착각": "AI 결과는 출처가 있으니 사실이다", "실제": "AI는 그럴듯한 거짓(환각)을 만든다. 인용·수치는 원문으로 직접 확인해야 한다"},
                {"착각": "AI가 만든 건 저작권 문제가 없다", "실제": "학습 데이터·생성물에 따라 표절·저작권 이슈가 생길 수 있어 표현을 손봐야 한다"},
            ],
            "real_criterion": (
                "1단계: 입력 전 분류 — 기밀·개인정보·계약 정보는 입력 금지, 일반·공개 정보만 넣는다.\n"
                "2단계: 결과 검증 — 핵심 사실 2~3개는 원문·공식 자료로 직접 확인한다.\n"
                "3단계: 정책 확인 — 회사 AI 사용 정책과 도구의 데이터 처리 옵션(학습 제외 설정 등)을 확인한다."
            ),
            "risk_note": [
                "사내 기밀·고객 개인정보·계약서 원문을 프롬프트에 붙여넣지 말 것. 회사 AI 사용 정책을 먼저 확인한다.",
                "AI 결과의 숫자·인용·출처는 그럴듯해도 틀릴 수 있으므로 원문으로 직접 검증한다.",
                "생성물을 그대로 게시·제출하면 저작권·표절 문제가 생길 수 있어 사실과 표현을 손본다.",
                "가능하면 대화 학습 제외 설정을 켜고, 민감 업무는 기업용 보안 옵션을 사용한다.",
            ],
            "quick_decision_table": [
                {"내 상황": "사내 자료를 요약하고 싶다", "할 일": "기밀·개인정보 제거 후 일반화한 내용만 입력, 또는 기업용 보안 옵션 사용"},
                {"내 상황": "결과를 바로 제출하려 한다", "할 일": "핵심 사실 2~3개 직접 검증 후 사용"},
                {"내 상황": "이미지·문구를 생성했다", "할 일": "저작권·상표 충돌 여부 확인하고 표현을 수정"},
                {"내 상황": "회사 정책을 모른다", "할 일": "AI 사용 가능 범위·금지 데이터를 먼저 확인"},
            ],
            "actions": [
                {"번호": 1, "행동": "입력 금지 목록 정하기", "설명": "기밀·개인정보·계약 정보는 입력하지 않는다는 규칙을 명문화한다"},
                {"번호": 2, "행동": "검증 루프 고정", "설명": "결과의 핵심 사실은 원문으로 확인한 뒤 사용하는 단계를 둔다"},
                {"번호": 3, "행동": "보안 설정 켜기", "설명": "학습 제외 설정·기업용 보안 옵션을 확인하고 적용한다"},
            ],
            "faq": [
                {"Q": "회사 자료를 AI에 넣어도 되나요?", "A": "기밀·개인정보가 포함되면 안 됩니다. 일반화·익명화한 내용만 넣거나, 데이터 보호가 되는 기업용 옵션을 사용하세요. 회사 정책 확인이 우선입니다."},
                {"Q": "환각은 어떻게 막나요?", "A": "완전히 막을 수는 없습니다. '확실하지 않으면 추측하지 말 것' 같은 제약을 더하고, 핵심 사실은 사람이 직접 검증해야 합니다."},
                {"Q": "AI 생성물의 저작권은 누구에게 있나요?", "A": "서비스 약관과 국가별 기준에 따라 다르고 모호한 영역입니다. 표절·상표 충돌이 없는지 확인하고 표현을 손본 뒤 사용하는 것이 안전합니다."},
            ],
            "hashtags": ["#AI보안", "#개인정보", "#AI저작권", "#AI리스크", "#데이터보호", "#AI윤리", "#환각"],
            "internal_links": [
                {"주제": "ChatGPT로 업무 시간 줄이는 법", "content_type": "ai_work_tip"},
                {"주제": "AI 도구 직접 써보고 판단하는 기준", "content_type": "ai_tool_review"},
                {"주제": "복사해서 쓰는 업무용 프롬프트 템플릿", "content_type": "ai_prompt_recipe"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["risk_note"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_ai_beginner_guide(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """ai_beginner_guide — 초보자용 AI 활용 가이드."""
        slots: dict[str, Any] = {
            "hook_opening": (
                "AI를 처음 써보려는데 어디서부터 시작해야 할지 막막했던 적이 있을 것이다. "
                "용어는 어렵고, 어떤 도구를 골라야 할지, 무료로 뭘 할 수 있는지도 헷갈린다. "
                "처음엔 거창한 활용법보다 '내가 자주 하는 작은 일 하나'를 맡겨 보는 게 빠르다. "
                "용어를 쉽게 풀고, 처음 시작하는 순서와 점검표를 정리했다."
            ),
            "yomi_judgment": (
                "초보자가 가장 빨리 느는 길은 '내 실제 업무 하나'로 바로 써보는 것이다. "
                "AI는 완성본을 주는 마법이 아니라 80점 초안을 빠르게 주는 도구라는 점만 기억하면 된다. "
                "무료 버전으로도 요약·번역·초안 작성은 충분히 시작할 수 있다. "
                "지금 자주 쓰는 이메일이나 요약 한 가지를 골라 첫 시도를 해보라."
            ),
            "real_criterion": (
                "1단계: 무료 도구 하나를 정한다 — 처음엔 도구를 늘리지 말고 하나로 익숙해진다.\n"
                "2단계: 내 작은 업무를 맡긴다 — '이 메일을 정중하게 다듬어줘'처럼 구체적으로 요청한다.\n"
                "3단계: 결과를 다듬는다 — 그대로 쓰지 말고 사실을 확인하고 내 말투로 고친다. 잘 된 요청은 저장해 둔다."
            ),
            "quick_decision_table": [
                {"내 상황": "뭐부터 시작할지 모른다", "할 일": "자주 하는 작은 업무 1개(이메일·요약)를 골라 맡겨 보기"},
                {"내 상황": "결과가 이상하게 나온다", "할 일": "요청을 더 구체적으로 — 역할·목적·형식을 한 줄씩 적기"},
                {"내 상황": "유료를 써야 하나 고민", "할 일": "무료로 충분한 경우가 많으니 막힐 때까지는 무료로 시작"},
                {"내 상황": "용어가 어렵다", "할 일": "모르는 용어는 AI에게 '초등학생도 알게 설명해줘'로 물어보기"},
            ],
            "checklist": [
                "도구를 하나만 정해 익숙해지고 있는가",
                "요청에 역할·목적·형식이 들어갔는가",
                "결과를 그대로 쓰지 않고 사실을 확인했는가",
                "민감 정보(개인정보)를 넣지 않았는가",
                "잘 된 요청을 저장해 재사용하는가",
            ],
            "actions": [
                {"번호": 1, "행동": "무료 도구 1개 정하기", "설명": "처음엔 하나만 골라 익숙해지는 데 집중한다"},
                {"번호": 2, "행동": "작은 업무 맡겨 보기", "설명": "이메일 다듬기·짧은 글 요약처럼 부담 없는 일부터 시작한다"},
                {"번호": 3, "행동": "결과 다듬고 저장", "설명": "사실을 확인해 내 말투로 고치고, 잘 된 요청은 저장해 재사용한다"},
            ],
            "faq": [
                {"Q": "완전 초보도 무료로 시작할 수 있나요?", "A": "네. 요약·번역·이메일 초안 같은 작업은 무료 버전으로 충분히 시작할 수 있습니다. 익숙해진 뒤 필요하면 유료를 고려하세요."},
                {"Q": "프롬프트라는 게 뭔가요?", "A": "AI에게 주는 '요청문'입니다. 역할(누구처럼), 목적(무엇을), 형식(어떤 모양으로)을 적으면 결과가 좋아집니다."},
                {"Q": "AI가 틀린 답을 주면 어떡하나요?", "A": "AI는 그럴듯한 오류를 만들 수 있습니다. 중요한 사실은 검색이나 공식 자료로 직접 확인한 뒤 사용하세요."},
            ],
            "hashtags": ["#AI입문", "#AI초보", "#ChatGPT사용법", "#AI활용", "#왕초보AI", "#AI기초", "#생산성"],
            "internal_links": [
                {"주제": "복사해서 쓰는 업무용 프롬프트 템플릿", "content_type": "ai_prompt_recipe"},
                {"주제": "ChatGPT로 업무 시간 줄이는 법", "content_type": "ai_work_tip"},
                {"주제": "AI 쓸 때 보안·개인정보 주의점", "content_type": "ai_risk_security"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["checklist"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    def _build_delivery_money_checklist(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "배달앱으로 주문 버튼을 누르기 전까지 최종 금액이 얼마인지 정확히 모르는 경우가 많다. "
                "화면에 보이는 음식 가격에 배달비가 더해지고, 쿠폰 적용 후 최소주문금액 조건이 바뀌어 "
                "예상보다 비싸게 결제된 경험이 있다면 확인 순서가 잘못된 것이다. "
                "배달앱마다 배달비 무료 조건, 쿠폰 적용 기준, 최소주문금액이 다르기 때문에 "
                "주문 전에 3가지 항목을 순서대로 확인하면 결제 후 후회를 줄일 수 있다."
            ),
            "yomi_judgment": (
                "요미 판단: 배달앱 결제금액 비교는 어렵지 않다. "
                "배달비 조건, 쿠폰 적용 여부, 최소주문금액을 순서대로 확인하면 최종금액이 정해진다. "
                "비교 없이 주문하면 같은 음식을 더 비싸게 결제하는 상황이 반복될 수 있다. "
                "지금 주문 전에 배달비 조건부터 먼저 확인하라."
            ),
            "misconceptions": [
                {
                    "착각": "배달비 0원이면 추가 비용이 없다",
                    "실제": "배달비 무료는 최소주문금액 충족 시 적용된다. 조건 미달 시 배달비가 추가된다",
                },
                {
                    "착각": "쿠폰이 있으면 항상 결제금액에서 차감된다",
                    "실제": "쿠폰마다 적용 가능한 최소주문금액·메뉴 카테고리·앱 조건이 다르다. 주문 전 쿠폰 조건을 확인해야 한다",
                },
                {
                    "착각": "배달앱마다 같은 가게 음식 가격은 동일하다",
                    "실제": "앱별로 입점 수수료 구조와 프로모션이 달라 최종 결제금액이 다를 수 있다. 동일 가게라도 앱별 비교가 필요하다",
                },
                {
                    "착각": "무료배달 구독권이 있으면 언제나 배달비가 무료다",
                    "실제": "구독권 적용 제외 가게가 있으며, 최소주문금액 조건이 별도로 있는 경우도 있다",
                },
            ],
            "real_criterion": (
                "1단계: 배달비 조건 확인 — 주문 전 해당 가게의 배달비와 무료 배달 조건(최소주문금액)을 확인한다. "
                "구독권 보유 시 해당 가게에 구독권이 적용되는지 먼저 체크한다.\n"
                "2단계: 쿠폰 적용 기준 확인 — 보유 쿠폰의 적용 조건(최소주문금액·카테고리·유효기간)을 확인한다. "
                "쿠폰 적용 후 달라지는 최소주문금액 충족 여부를 재확인한다.\n"
                "3단계: 최종 결제금액 확인 후 주문 — 가상의 계산 예시로 음식 12,000원 + 배달비 3,000원 − 쿠폰 2,000원 = 최종 결제금액 13,000원처럼 "
                "최종금액을 확인한다. 다른 앱에서 동일 가게를 검색해 최종 결제금액을 비교한 뒤 주문을 확정한다."
            ),
            "quick_decision_table": [
                {
                    "내 상황": "주문 금액이 예상보다 많이 나왔다",
                    "할 일": "배달비 조건 재확인 — 최소주문금액 미달로 배달비가 붙었는지 체크",
                },
                {
                    "내 상황": "쿠폰이 있는데 적용이 안 된다",
                    "할 일": "쿠폰 적용 조건 확인 — 최소주문금액·카테고리·유효기간 중 어떤 조건을 충족 못했는지 확인",
                },
                {
                    "내 상황": "배달앱 구독권이 있다",
                    "할 일": "주문할 가게가 구독권 적용 대상인지 먼저 확인 후 주문",
                },
                {
                    "내 상황": "어떤 배달앱이 더 저렴한지 모른다",
                    "할 일": "동일 가게를 배달의민족·쿠팡이츠·요기요에서 각각 검색해 최종금액 비교",
                },
                {
                    "내 상황": "배달비가 너무 비싸게 느껴진다",
                    "할 일": "최소주문금액 추가 주문으로 무료배달 조건 충족 여부 확인 또는 포장 주문 비교",
                },
            ],
            "actions": [
                {
                    "번호": 1,
                    "행동": "주문 전 배달비 조건 먼저 확인",
                    "설명": "앱에서 가게 선택 후 배달비와 무료배달 최소주문금액을 주문 전에 반드시 확인하라",
                },
                {
                    "번호": 2,
                    "행동": "쿠폰 적용 조건 체크 후 사용",
                    "설명": "쿠폰함에서 사용 가능한 쿠폰의 적용 조건을 확인하고 조건 충족 여부를 먼저 파악하라",
                },
                {
                    "번호": 3,
                    "행동": "앱별 최종금액 비교 후 주문",
                    "설명": "같은 가게를 2개 이상 앱에서 검색해 최종 결제금액을 비교한 뒤 더 저렴한 쪽으로 주문하라",
                },
            ],
            "faq": [
                {
                    "Q": "배달비 무료 조건은 어떻게 확인하나?",
                    "A": (
                        "앱에서 가게를 선택한 뒤 배달비 항목을 탭하면 무료배달 최소주문금액을 확인할 수 있다. "
                        "구독권 보유 시에도 해당 가게에 적용 여부가 별도로 표시된다."
                    ),
                },
                {
                    "Q": "쿠폰을 중복으로 적용할 수 있나?",
                    "A": (
                        "대부분의 배달앱은 1회 주문 시 쿠폰 1개만 적용된다. "
                        "쿠폰과 구독 할인은 중복 적용되는 경우가 있지만, 앱별·쿠폰 종류별로 다르므로 결제 화면에서 확인해야 한다."
                    ),
                },
                {
                    "Q": "같은 가게인데 앱마다 가격이 다른 이유는?",
                    "A": (
                        "앱별로 입점 수수료 구조, 자체 프로모션, 최소주문금액 설정이 다를 수 있다. "
                        "가게가 앱마다 가격을 다르게 설정하는 경우도 있으므로 주문 전 2개 앱 이상 비교가 도움된다."
                    ),
                },
            ],
            "hashtags": [
                "#배달앱",
                "#배달비절약",
                "#생활비절약",
                "#배달의민족",
                "#쿠팡이츠",
                "#배달비비교",
                "#소비절약",
                "#AI활용",
            ],
            "internal_links": [
                {
                    "주제": "OTT 구독료 비교 — 넷플릭스·티빙·쿠팡플레이 월정액 따져보기",
                    "content_type": "money_checklist",
                },
                {
                    "주제": "생활비 줄이는 소비 패턴 정리 — 고정비 점검 체크리스트",
                    "content_type": "money_checklist",
                },
                {
                    "주제": "배달앱 구독권 실제 이득 되는 조건과 안 되는 조건",
                    "content_type": "money_checklist",
                },
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    # ------------------------------------------------------------------ #
    # platform_change_service_update                                       #
    # ------------------------------------------------------------------ #

    def _build_platform_change(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "플랫폼 서비스 변경 공지가 떴는데 정작 내 계정·결제·기기가 변경 대상에 포함되는지 확인이 늦으면 "
                "갑자기 서비스 이용이 막히거나 자동결제가 그대로 빠져나가 손해가 생길 수 있다. "
                "변경 공지에는 적용 일자, 영향 범위, 기존 사용자 처리 기준이 함께 안내되는데 "
                "이용자가 직접 확인해야 하는 항목이 의외로 많다. "
                "변경 일자 전에 내 계정·결제·기기 상태를 순서대로 점검하면 갑작스러운 불편을 줄일 수 있다."
            ),
            "yomi_judgment": (
                "요미 판단: 플랫폼 변경 공지가 떴다면 알림을 기다리지 말고 지금 직접 확인하라. "
                "내 계정이 적용 대상인지, 결제 수단이 변경되는지, 사용 중인 기기가 호환되는지 "
                "공식 안내에서 확인하면 변경 일자 이후 당황할 일을 피할 수 있다. "
                "공식 페이지 안내 외 출처는 사실 확인이 필요하다."
            ),
            "misconceptions": [
                {"착각": "알림이 안 왔으니 내 계정은 대상이 아니다",
                 "실제": "알림이 모든 이용자에게 동일하게 가지 않는 경우가 있다. 변경 공지 페이지에서 직접 확인해야 한다"},
                {"착각": "기존 사용자는 자동으로 예외 처리된다",
                 "실제": "기존 사용자 처리 기준은 변경마다 다르다. 공식 공지에서 적용 대상과 예외 조건을 확인해야 한다"},
                {"착각": "변경 일자 이후 천천히 대응해도 된다",
                 "실제": "결제·자동결제·로그인 등이 변경 일자에 즉시 적용되는 경우가 많다. 변경 전에 확인하고 조치해야 한다"},
                {"착각": "취소·환불 정책은 변경 전후 동일하다",
                 "실제": "약관 변경에 따라 취소·환불 기준이 함께 바뀔 수 있다. 변경 공지에 함께 안내된 정책을 확인해야 한다"},
            ],
            "real_criterion": (
                "1단계: 변경 공지 원문 확인 — 적용 일자·영향 범위·기존 사용자 처리 기준을 공식 안내에서 직접 확인한다. "
                "캡처 또는 URL을 저장해 둔다.\n"
                "2단계: 내 계정·결제·기기 점검 — 변경 대상에 내 계정 유형이 포함되는지, "
                "등록된 결제 수단이 변경 영향권에 있는지, 사용 중인 기기·앱 버전이 변경 후에도 호환되는지 확인한다.\n"
                "3단계: 변경 전 조치 — 자동결제 해지 또는 유지 여부 결정, 백업 필요 데이터 추출, "
                "필요 시 대체 서비스나 새 결제 수단 등록을 변경 일자 전에 마친다."
            ),
            "quick_decision_table": [
                {"내 상황": "변경 공지를 받았는데 내가 대상인지 모르겠다",
                 "확인할 것": "공식 공지에서 '적용 대상' 섹션 확인 — 내 계정 유형·요금제·가입일이 해당되는지 체크"},
                {"내 상황": "자동결제가 등록되어 있다",
                 "확인할 것": "결제 수단·요금이 변경 후에도 그대로 빠져나가는지 확인. 원치 않으면 변경 전 해지"},
                {"내 상황": "사용 중인 기기가 오래되었다",
                 "확인할 것": "지원 종료 기기 목록 확인. 필요 시 변경 전 데이터 백업 또는 기기 교체 일정 검토"},
                {"내 상황": "약관·이용 조건이 함께 바뀐다",
                 "확인할 것": "취소·환불·해지 기준이 어떻게 바뀌는지 확인. 불리하면 변경 전 정리"},
                {"내 상황": "기존 사용자 예외가 있다는 안내를 봤다",
                 "확인할 것": "예외 적용 조건과 기한 확인. 신청이 필요한 예외인지, 자동 적용인지 구분"},
            ],
            "actions": [
                {"번호": 1, "행동": "공식 공지 원문 확인",
                 "설명": "변경 일자·적용 대상·예외 조건을 운영사 공식 안내에서 직접 확인하고 캡처를 남긴다"},
                {"번호": 2, "행동": "내 계정·결제·기기 점검",
                 "설명": "변경 대상 여부, 등록된 결제 수단, 사용 기기 호환성을 변경 일자 전에 확인한다"},
                {"번호": 3, "행동": "변경 전 조치 완료",
                 "설명": "자동결제 정리, 데이터 백업, 대체 수단 마련 등 필요한 조치를 변경 일자 전에 마친다"},
            ],
            "faq": [
                {"Q": "공식 공지는 어디서 확인하나?",
                 "A": "운영사 공식 홈페이지의 공지사항 또는 앱 내 공지 배너에서 확인할 수 있다. "
                      "검색엔진 결과나 SNS 게시물만으로 단정하지 말고 운영사 안내를 직접 확인하라."},
                {"Q": "기존 사용자도 변경이 적용되나?",
                 "A": "변경마다 기준이 다르다. 공식 안내의 '기존 사용자 처리' 또는 '경과 조치' 섹션을 확인해야 한다. "
                      "예외가 있는 경우 적용 조건과 기한이 별도로 표시된다."},
                {"Q": "변경 후 취소·환불은 어떻게 하나?",
                 "A": "약관 변경과 함께 취소·환불 기준이 바뀔 수 있다. 변경 공지에 함께 안내된 정책을 확인하고, "
                      "불리한 변경이라면 변경 일자 전에 해지하거나 환불 신청을 마치는 것이 안전하다."},
            ],
            "hashtags": [
                "#플랫폼변경", "#서비스변경", "#약관변경", "#멤버십변경",
                "#서비스종료", "#디지털생존", "#앱업데이트", "#계정관리",
            ],
            "internal_links": [
                {"주제": "OTT 구독료 비교 — 변경 전 점검할 항목", "content_type": "money_checklist"},
                {"주제": "환불·결제 피해 대응 체크리스트", "content_type": "consumer_warning"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    # ------------------------------------------------------------------ #
    # consumer_warning_refund                                              #
    # ------------------------------------------------------------------ #

    def _build_consumer_warning(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        slots: dict[str, Any] = {
            "hook_opening": (
                "환불·결제 오류·개인정보 유출 같은 소비자 피해 상황에서 가장 먼저 해야 할 일은 "
                "고객센터 전화가 아니라 증거를 남기는 것이다. "
                "결제내역·주문번호·상담 기록·캡처를 늦게 챙기면 환불 지연이 길어지거나 "
                "분쟁이 생겼을 때 손해를 줄이기 어렵다. "
                "피해 발생 직후 30분 안에 무엇을 어떤 순서로 남기느냐가 이후 대응 속도와 결과를 좌우한다."
            ),
            "yomi_judgment": (
                "요미 판단: 소비자 피해는 기다리면 자동 해결되지 않는다. "
                "결제내역·상담 기록·캡처를 먼저 확보하고, 운영사 공식 고객센터 → 소비자원 순으로 단계별 대응하라. "
                "지금 결제 화면, 주문번호, 챗·전화 기록부터 캡처해 두라. "
                "공식 확인이 필요한 단정은 피하고, 객관적 기록 중심으로 정리한다."
            ),
            "misconceptions": [
                {"착각": "기다리면 자동으로 해결된다",
                 "실제": "환불·보상은 신청·증빙이 필요한 경우가 대부분이다. 증거 확보가 늦으면 처리 속도와 결과가 달라진다"},
                {"착각": "고객센터에 전화만 하면 충분하다",
                 "실제": "전화 통화 내용은 별도로 남지 않을 수 있다. 채팅·이메일 등 기록이 남는 채널 사용을 권장한다"},
                {"착각": "결제 취소를 누르면 환불이 끝난 것이다",
                 "실제": "결제 취소 요청과 실제 환불 처리는 다르다. 환불 완료 안내·입금 확인까지 추적해야 한다"},
                {"착각": "개인정보 유출 안내를 받아도 별로 할 일이 없다",
                 "실제": "유출 종류에 따라 비밀번호 변경·2차 인증 설정·금융 거래 점검 등 즉시 조치가 필요할 수 있다"},
            ],
            "real_criterion": (
                "1단계: 즉시 캡처 — 결제 화면, 주문번호, 결제 시각, 상품/서비스명, "
                "오류 메시지나 상태 표시를 화면 캡처로 남긴다. 스크린샷 파일명에 날짜를 포함한다.\n"
                "2단계: 기록이 남는 채널로 문의 — 운영사 앱·웹 고객센터 채팅, 이메일 등 텍스트 기록이 남는 경로로 "
                "피해 내용·요청 사항·접수 일시를 명확히 전달한다. 통화는 통화 후 메모로 보완한다.\n"
                "3단계: 공식 기관 단계 진행 — 운영사 1차 대응이 미흡하면 한국소비자원(1372), "
                "개인정보침해 신고센터(118), 금융 분쟁 시 금융감독원 등 공식 기관에 증빙과 함께 신고한다."
            ),
            "quick_decision_table": [
                {"내 상황": "결제 오류로 이중 결제되었다",
                 "즉시 할 일": "결제 화면·결제내역·시간 캡처 → 운영사 채널로 환불 요청 접수 → 영업일 처리 기한 확인"},
                {"내 상황": "환불 신청했는데 처리가 늦다",
                 "즉시 할 일": "접수 번호·접수 일자 확인 → 운영사 약관상 환불 기한 확인 → 기한 초과 시 소비자원 신고 검토"},
                {"내 상황": "개인정보 유출 안내를 받았다",
                 "즉시 할 일": "유출 항목 확인 → 해당 서비스 비밀번호 변경·2차 인증 설정 → 다른 서비스 같은 비밀번호 사용 시 동시 변경"},
                {"내 상황": "예약·티켓팅 실패 또는 취소 분쟁",
                 "즉시 할 일": "결제 영수증·취소 사유 캡처 → 운영사 공식 약관의 취소·환불 기준 확인 → 기준 위반 시 신고"},
                {"내 상황": "운영사가 답을 주지 않는다",
                 "즉시 할 일": "문의 접수 기록·기한·답변 부재 사실을 정리 → 소비자원 1372 또는 관할 기관에 신고"},
            ],
            "actions": [
                {"번호": 1, "행동": "피해 발생 직후 캡처",
                 "설명": "결제 화면, 주문번호, 결제 시각, 오류·상태 표시를 모두 화면 캡처한다. 파일명에 날짜를 포함한다"},
                {"번호": 2, "행동": "기록 남는 채널로 접수",
                 "설명": "앱·웹 채팅, 이메일 등 텍스트 기록이 남는 경로로 피해 내용을 명확히 접수하고 접수 번호를 받는다"},
                {"번호": 3, "행동": "공식 기관 신고 단계",
                 "설명": "운영사 대응이 부족하면 한국소비자원 1372·개인정보침해 신고센터 118 등 공식 채널에 증빙과 함께 신고한다"},
            ],
            "faq": [
                {"Q": "환불을 거부당하면 어떻게 해야 하나?",
                 "A": "운영사 약관과 공정거래위원회 표준약관을 비교해 환불 거부 사유가 정당한지 확인한다. "
                      "부당하다고 판단되면 한국소비자원(1372)에 피해 구제 신청을 할 수 있다."},
                {"Q": "한국소비자원에는 어떻게 신고하나?",
                 "A": "전화 1372 또는 소비자24 누리집에서 온라인 신청이 가능하다. "
                      "결제내역, 운영사와의 상담 기록, 약관 위반 정황을 함께 제출하면 처리 속도가 빨라진다."},
                {"Q": "어떤 증거를 남겨야 하나?",
                 "A": "결제 영수증·주문번호·상담 기록·오류 화면·접수 일시가 핵심이다. "
                      "통화 내용은 통화 후 메모와 함께 채팅·이메일로 한 번 더 확인 요청을 남기는 것이 안전하다."},
            ],
            "hashtags": [
                "#소비자피해", "#환불대응", "#결제오류", "#개인정보보호",
                "#소비자원", "#증거보존", "#소비자권익", "#피해구제",
            ],
            "internal_links": [
                {"주제": "환불 지연 대응 — 운영사·소비자원 단계별 진행", "content_type": "consumer_warning"},
                {"주제": "개인정보 유출 안내 후 점검할 항목", "content_type": "consumer_warning"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    # ------------------------------------------------------------------ #
    # policy_deadline_support                                              #
    # ------------------------------------------------------------------ #

    def _build_policy_deadline(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        facts = _policy_fact_pack(topic, raw)
        subject = str(facts.get("subject") or topic or "지원금 공고")
        region_text = _fact_text(facts.get("regions") or [], "공고문에 표시된 지역")
        amount_text = _fact_text(facts.get("amounts") or [], "공고문에 표시된 지원 금액")
        target_text = _fact_text(facts.get("targets") or [], "공고문에 표시된 신청 대상")
        payment_text = _fact_text(facts.get("payments") or [], "공고문에 표시된 지급 방식")
        deadline_text = _fact_text(facts.get("deadlines") or [], "공고문에 표시된 신청 기간")
        contact_text = _fact_text(facts.get("contacts") or [], "공고문 담당 부서 또는 문의처")
        source_name_text = _fact_text(facts.get("source_names") or [], "공식 공고")
        slots: dict[str, Any] = {
            "hook_opening": (
                f"{subject}은 이름만 보고 일반 지원금처럼 넘기면 안 된다. "
                f"이 공고에서 먼저 볼 값은 지역 {region_text}, 대상 {target_text}, 금액 {amount_text}, 지급 방식 {payment_text}이다. "
                f"신청 여부는 {source_name_text} 기준으로 달라지므로, 마감 {deadline_text}와 문의처 {contact_text}를 같이 확인해야 한다. "
                "본문에서는 공고에서 독자가 바로 확인해야 할 조건만 순서대로 정리한다."
            ),
            "yomi_judgment": (
                f"핵심 관점: {subject}은 대상과 지급 방식이 정해진 공고형 지원이다. "
                f"내가 {target_text}에 해당하는지 먼저 보고, {amount_text}와 {payment_text} 조건을 확인한 뒤 신청해야 한다. "
                f"최종 기준은 {source_name_text}의 공고문과 담당 문의처다."
            ),
            "misconceptions": [
                {"착각": f"{subject}은 누구나 신청할 수 있다",
                 "실제": f"공고의 신청 대상은 {target_text}처럼 정해져 있다. 대상 조건이 맞지 않으면 신청해도 제외될 수 있다"},
                {"착각": "금액만 보면 된다",
                 "실제": f"금액 {amount_text}와 함께 지급 방식 {payment_text}, 사용처, 사용 기한을 같이 봐야 한다"},
                {"착각": "전국 공통 지원금이다",
                 "실제": f"이 공고는 지역 {region_text}와 담당 기관 {source_name_text} 기준으로 확인해야 한다"},
                {"착각": "마감 뒤에도 보완하면 된다",
                 "실제": f"신청 기간은 {deadline_text} 기준으로 달라질 수 있으므로 접수 전 담당 문의처 {contact_text}를 확인해야 한다"},
            ],
            "real_criterion": (
                f"1단계: 공고명 확인 — {subject}이 내가 찾는 공고가 맞는지 {source_name_text}에서 확인한다.\n"
                f"2단계: 대상 조건 확인 — 지역 {region_text}, 대상 {target_text}, 제외 조건을 공고문에서 대조한다.\n"
                f"3단계: 금액·지급 방식 확인 — 지원 금액 {amount_text}, 지급 방식 {payment_text}, 사용처와 사용 기한을 같이 본다.\n"
                f"4단계: 신청 기간·서류 확인 — 마감 {deadline_text}, 신청 경로, 제출 서류, 보완 가능 여부를 확인한다.\n"
                f"5단계: 문의처 기록 — 접수 전 담당 문의처 {contact_text}와 접수 번호 보관 기준을 기록한다."
            ),
            "quick_decision_table": [
                {"내 상황": f"{subject} 대상인지 모르겠다",
                 "확인할 조건": f"지원 대상 항목에서 {target_text}에 해당하는지 먼저 확인"},
                {"내 상황": "지역 조건이 헷갈린다",
                 "확인할 조건": f"지역 기준 {region_text}와 사업장·거주지 기준 중 무엇을 보는지 확인"},
                {"내 상황": "얼마를 어떤 방식으로 받는지 궁금하다",
                 "확인할 조건": f"지원 금액 {amount_text}, 지급 방식 {payment_text}, 사용처 제한 확인"},
                {"내 상황": "신청 마감이 걱정된다",
                 "확인할 조건": f"신청 기간 {deadline_text}와 예산 소진·조기 마감 여부 확인"},
                {"내 상황": "공고문만 보고 확신이 안 선다",
                 "확인할 조건": f"담당 문의처 {contact_text}에 대상·서류·접수 방법을 확인"},
            ],
            "actions": [
                {"번호": 1, "행동": "공고명과 대상 대조",
                 "설명": f"{subject} 공고에서 {target_text} 조건과 제외 조건을 먼저 대조한다"},
                {"번호": 2, "행동": "금액·지급 방식 확인",
                 "설명": f"{amount_text}와 {payment_text}가 실제로 어떻게 지급되는지 사용처까지 확인한다"},
                {"번호": 3, "행동": "마감·문의처 기록",
                 "설명": f"신청 기간 {deadline_text}, 접수 경로, 담당 문의처 {contact_text}를 저장하고 접수 번호를 보관한다"},
            ],
            "faq": [
                {"Q": f"{subject} 신청 대상은 누구인가요?",
                 "A": f"공고문에서 {target_text}, 지역 {region_text}, 제외 조건을 함께 확인해야 합니다."},
                {"Q": f"{subject} 지원 금액과 지급 방식은 어떻게 되나요?",
                 "A": f"현재 본문 기준으로 확인할 핵심값은 지원 금액 {amount_text}, 지급 방식 {payment_text}입니다. 사용처와 사용 기한은 공고문을 같이 봐야 합니다."},
                {"Q": f"{subject} 신청 기간과 문의처는 어디서 보나요?",
                 "A": f"신청 기간은 {deadline_text} 기준으로 확인하고, 불명확한 부분은 {contact_text} 또는 {source_name_text} 공고 담당 부서에 확인해야 합니다."},
            ],
            "hashtags": _policy_hashtags(facts),
            "internal_links": [],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    # ------------------------------------------------------------------ #
    # corporate_issue_decode — 기업 이슈 해석                              #
    # ------------------------------------------------------------------ #

    def _build_corporate_issue(
        self, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        # discovery 후보의 entities를 활용 — 첫 entity를 기업명으로 가정
        entities = raw.get("entities") or []
        primary_entity = next(
            (e for e, t in zip(entities, raw.get("entity_types") or [])
             if t in ("platform", "telecom", "card", "acronym")),
            entities[0] if entities else "이 기업",
        )
        slots: dict[str, Any] = {
            "hook_opening": (
                f"{primary_entity}이/가 오늘 공식 입장 또는 발표를 내놓으면서 소비자·직원·투자자에게 어떤 영향이 있는지 정리할 필요가 생겼다. "
                "기업 이슈는 공식 발표와 외부 추측이 섞이기 쉬워, 무엇이 확인된 사실이고 무엇이 단순 관측인지 구분하는 것이 중요하다. "
                "공시·공식 채널·신뢰할 수 있는 매체 보도를 우선 확인해야 한다. "
                "오늘 이슈에서 사람들이 가장 궁금해할 포인트와 직접 확인할 수 있는 채널을 정리한다."
            ),
            "yomi_judgment": (
                "요미 판단: 기업 이슈에서 가장 안전한 접근은 공식 발표·공시·운영사 공식 채널을 기준으로 보는 것이다. "
                "SNS 추측이나 단편 보도는 사실 확인이 필요하다. "
                "이용자·소비자라면 본인이 영향을 받는 범위(서비스·결제·계정·고용)만 우선 확인하면 충분하다. "
                "투자 판단은 공시 기준으로 별도 확인해야 한다."
            ),
            "misconceptions": [
                {"착각": "한 매체 보도만 보고 사실로 단정해도 된다",
                 "실제": "기업 이슈는 공시·공식 입장·복수 매체 교차 확인이 필요하다. SNS 추측은 사실과 다를 수 있다"},
                {"착각": "이슈 직후 즉시 행동해야 한다",
                 "실제": "급하게 결정하지 말고 공식 안내 시점까지 기다리는 것이 일반적으로 안전하다"},
                {"착각": "기업 발표가 곧 소비자 영향과 동일하다",
                 "실제": "내부 결정/노사 협의/사업 변경이 곧바로 소비자 서비스에 반영되지 않는 경우가 많다"},
                {"착각": "주가/시세 반응이 이슈의 실제 영향을 반영한다",
                 "실제": "단기 시세는 심리·외부 변수 영향을 받는다. 실제 영향은 후속 발표로 확인된다"},
            ],
            "real_criterion": (
                "1단계: 공식 발표 위치 확인 — 기업 공식 홈페이지 보도자료, 공시 시스템(DART), 운영사 공식 채널에서 직접 확인한다. "
                "캡처 또는 URL을 저장한다.\n"
                "2단계: 내가 영향받는 범위 점검 — 서비스 이용/결제/계정/고용/배송/예약 중 어떤 항목이 변경 영향에 들어가는지 확인한다. "
                "공식 안내에 명시되지 않은 부분은 추측하지 않는다.\n"
                "3단계: 후속 발표 기다리기 — 1차 발표 이후 보통 후속 공지가 따른다. 공식 채널 알림을 켜두고 "
                "기간 내 변화를 추적한다."
            ),
            "quick_decision_table": [
                {"이해관계자": "일반 소비자/이용자",
                 "확인 포인트": "서비스 이용·결제·요금에 변화가 있는지 공식 안내 확인"},
                {"이해관계자": "직원/임직원",
                 "확인 포인트": "고용·근무·복지 변화 여부, 공식 사내 안내 확인"},
                {"이해관계자": "투자자/주주",
                 "확인 포인트": "공시 시스템(DART) 공시 내용, 후속 IR 발표 일정"},
                {"이해관계자": "협력사/거래처",
                 "확인 포인트": "거래 조건·결제 일정 변경 여부, 운영사 공문 확인"},
                {"이해관계자": "관심 일반 독자",
                 "확인 포인트": "공식 보도자료·복수 매체 교차 확인 후 결론 판단"},
            ],
            "actions": [
                {"번호": 1, "행동": "공식 발표 위치 확인",
                 "설명": "기업 공식 홈페이지·공시(DART)·공식 SNS에서 1차 발표 원문을 확인하고 URL을 저장한다"},
                {"번호": 2, "행동": "내가 영향받는 범위 점검",
                 "설명": "서비스/결제/계정/고용/거래 중 변경 대상에 본인이 포함되는지 공식 안내로 확인한다"},
                {"번호": 3, "행동": "후속 발표 추적",
                 "설명": "공식 채널 알림을 켜두고 후속 발표·업데이트를 일정 기간 추적한다"},
            ],
            "faq": [
                {"Q": "공식 발표는 어디서 확인할 수 있나?",
                 "A": "기업 공식 홈페이지의 IR/공지사항, 금융감독원 공시 시스템(DART), 운영사 공식 SNS 채널에서 확인할 수 있다. "
                      "검색엔진의 단편 기사보다 공식 채널의 원문이 가장 신뢰 가능한 기준이다."},
                {"Q": "이슈가 소비자에게 즉시 영향을 미치나?",
                 "A": "발표 내용에 따라 다르다. 서비스·요금·계정 변경이 명시되면 즉시 영향, "
                      "내부 결정(노사·인사·경영)은 즉각적인 소비자 영향이 작을 수 있다. 공식 안내를 직접 확인해야 한다."},
                {"Q": "후속 발표는 언제쯤 나오나?",
                 "A": "기업마다 다르지만 보통 1차 발표 후 며칠 내 후속 공지 또는 IR 발표가 따른다. "
                      "공식 채널 알림을 켜두는 것이 가장 빠른 확인 방법이다."},
            ],
            "hashtags": [
                "#기업이슈", "#공식입장", "#투자자", "#공시",
                "#AI뉴스해석", "#AI트렌드", "#사실확인", "#공식안내",
            ],
            "internal_links": [
                {"주제": "공시 정보 직접 확인하는 법 — DART 활용 가이드", "content_type": "viral_issue_decode"},
                {"주제": "기업 이슈, SNS 소문과 공식 발표를 구분하는 기준", "content_type": "viral_issue_decode"},
            ],
        }
        fill_strategy = {k: "derived" for k in slots}
        fill_strategy["real_criterion"] = "lookup"
        fill_strategy["actions"] = "lookup"
        return slots, fill_strategy

    # ------------------------------------------------------------------ #
    # Generic fallback for unregistered patterns                           #
    # ------------------------------------------------------------------ #

    def _build_generic(
        self, pattern: dict, topic: str, raw: dict
    ) -> tuple[dict[str, Any], dict[str, str]]:
        strategy = pattern.get("slot_filling_strategy", {})
        required = list(pattern.get("required_slots", {}).keys())
        slots: dict[str, Any] = {}
        fill_strategy: dict[str, str] = {}
        for slot_name in required:
            hint = strategy.get(slot_name, "")
            if hint:
                slots[slot_name] = hint
                fill_strategy[slot_name] = "lookup"
            else:
                slots[slot_name] = ""
                fill_strategy[slot_name] = "empty"
        return slots, fill_strategy
