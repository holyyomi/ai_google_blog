from __future__ import annotations

import re
from typing import Any


STRONG_PUBLIC_BENEFIT_KEYWORDS = (
    "고유가 피해지원금",
    "소상공인 고용보험료 환급",
    "고용보험료 환급",
    "통신비 환급",
    "보험료 환급",
    "국세 환급",
    "종합소득세 환급",
    "연말정산 환급",
    "세금 환급",
    "교통비 지원",
    "소상공인 지원금",
    "전기요금 할인",
    "난방비 지원",
    "근로장려금",
    "자녀장려금",
    "생활지원금",
    "민생지원금",
    "피해지원금",
    "부모급여",
    "청년지원금",
)
GENERIC_SUPPORT_KEYWORDS = ("지원금", "보조금", "혜택")
PUBLIC_BENEFIT_KEYWORDS = STRONG_PUBLIC_BENEFIT_KEYWORDS + GENERIC_SUPPORT_KEYWORDS
_SPECIFIC_SUPPORT_SUFFIXES = ("지원금", "보조금", "환급금")
_SPECIFIC_SUPPORT_STOPWORDS = {
    "정부",
    "지자체",
    "공식",
    "대한민국",
    "정책브리핑",
    "위키트리",
    "신청",
    "방법",
    "대상",
    "조건",
    "기간",
    "마감",
    "지급",
    "사용처",
    "확인",
    "어떻게",
    "받나",
    "최대",
    "최소",
    "원",
    "만원",
    "줍니다",
    "지원한다",
    "이를",
    "달간",
    "달간의",
    "개월간",
    "개월간의",
}
_INVALID_SUPPORT_DESCRIPTOR_ENDINGS = (
    "한다",
    "했다",
    "된다",
    "됐다",
    "하는",
    "되는",
    "이라는",
    "라는",
    "까지",
    "부터",
    "동안",
    "달간",
    "달간의",
    "개월간",
    "개월간의",
)
_REFUND_SUPPORT_DESCRIPTOR_CONTEXT = (
    "세금",
    "국세",
    "홈택스",
    "손택스",
    "통신비",
    "보험료",
    "연말정산",
    "종합소득세",
    "미수령",
    "환급계좌",
)
PUBLIC_BENEFIT_CONTEXT_SIGNALS = (
    "정부",
    "지자체",
    "시청",
    "구청",
    "주민센터",
    "복지",
    "대상자",
    "신청 기간",
    "지급일",
    "카드 지급",
    "지역사랑상품권",
    "기초생활수급자",
    "차상위계층",
    "한부모가족",
    "소상공인",
    "청년",
    "복지로",
    "정부24",
    "공식 신청",
)
COMMERCIAL_SUPPORT_KEYWORDS = (
    "성지폰",
    "휴대폰 성지",
    "동시가입",
    "번호이동",
    "기기변경",
    "최소 지원금",
    "최대 지원금",
    "특별 이벤트",
    "이벤트 진행",
    "프로모션",
    "혜택 제공",
    "매장 확대",
    "가맹점",
    "구매 혜택",
    "사은품",
    "할인 행사",
    "판매점",
    "대리점",
    "통신사 보조금",
)
PROMOTION_LIKE_TITLE_KEYWORDS = (
    "매장 확대",
    "확대 운영",
    "운영",
    "프랜차이즈",
    "가맹점",
    "브랜드",
    "프로모션",
    "이벤트",
)
TAX_REFUND_KEYWORDS = (
    "세금 환급",
    "국세 환급",
    "홈택스",
    "손택스",
    "종합소득세 환급",
    "연말정산 환급",
)
STRICT_MARKET_FINANCE_KEYWORDS = (
    "시총",
    "시가총액",
    "우선주",
    "보통주",
    "주가",
    "코스피",
    "코스닥",
    "특징주",
    "상한가",
    "하한가",
    "증시",
    "종목",
    "거래대금",
    "거래량",
    "목표주가",
    "투자의견",
    "52주 신고가",
    "신고가",
)
CORPORATE_FINANCE_KEYWORDS = (
    "공시",
    "실적",
    "영업이익",
    "순이익",
    "분기 매출",
    "어닝",
)
MARKET_FINANCE_CONTEXT_KEYWORDS = (
    "주식",
    "증권",
    "투자자",
    "외국인",
    "기관",
    "개미",
    "상장",
    "ipo",
)


TOPIC_GROUPS = (
    "delivery_money",
    "refund_consumer",
    "privacy_security",
    "ai_work",
    "trend_meme",
    "entertainment_sports",
    "ott_platform",
    "fandom_consumer",
    "policy_benefit",
    "platform_issue",
    "today_issue",
    "general_life",
)

VIRAL_RISK_KEYWORDS = (
    "열애설",
    "이혼설",
    "불륜",
    "사생활 폭로",
    "루머",
    "확인되지 않은",
    "찌라시",
    "미성년자",
    "외모 비하",
    "악플 유도",
    "선정",
    "성적",
    "피해자 신상",
    "정치 선동",
    "정치권",
    "선거",
    "표심",
    "민심",
    "한강벨트",
    "오세훈",
    "충격 근황",
    "결국 터졌다",
    "소름 돋는 이유",
    "사생활 논란 총정리",
)

VIRAL_SAFE_SIGNALS = (
    "반응이 갈린",
    "반응 분석",
    "팬덤 소비",
    "팬덤 구조",
    "OTT 전략",
    "요금제 변화",
    "티켓팅",
    "굿즈 품절",
    "플랫폼 알고리즘",
    "콘텐츠 전략",
    "시청자 반응",
    "경기 반응",
    "드라마 반응",
    "예능 화제",
    "클릭 이유",
    "커뮤니티 반응",
)

TOPIC_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "delivery_money": (
        "배달료", "배달비", "배달앱", "배민", "배달의민족", "쿠팡이츠", "요기요",
        "라이더", "무료배달", "최소주문금액", "최소 주문", "쿠폰", "배달 수수료", "플랫폼 수수료",
    ),
    "refund_consumer": (
        "환불", "환급", "결제취소", "결제 취소", "소비자 피해", "배송중단", "배송 중단", "연락두절", "연락 두절", "고객센터",
        "약관 논란", "결제 오류", "취소 오류", "환불 논란",
        "결제 피해", "이용자 피해", "소비자 논란",
    ),
    "privacy_security": (
        "개인정보 유출", "개인정보 보호", "본인확인", "본인 확인", "본인인증",
        "피싱", "스미싱", "보이스피싱", "사기 문자", "인증 문자", "사칭 문자",
        "계정 해킹", "계정 도용", "비밀번호 유출", "2차 인증",
        "개인정보위", "개인정보위원회", "정보 유출", "보안 사고", "해킹사고",
        "개인정보 안내", "본인확인 요청", "비밀번호 변경", "비밀번호 전면 변경",
        "계정 정보", "전화번호 유출", "아이디 유출",
    ),
    "ai_work": (
        "챗GPT", "ChatGPT", "생성형", "업무 자동화", "생산성", "AI 채용", "AI 해고", "저작권",
    ),
    "ai_prompt": (
        "프롬프트", "prompt", "프롬프트 템플릿", "프롬프트 작성", "프롬프트 예시",
        "프롬프트 레시피", "프롬프트 엔지니어링", "지시문", "프롬프트 모음", "프롬프트 작성법",
        "프롬프트 패턴", "프롬프트 양식", "프롬프트 공식", "프롬프트 꿀팁",
    ),
    "ai_tool": (
        "AI 도구", "AI 툴", "AI 리뷰", "도구 리뷰", "툴 리뷰", "AI 후기", "사용 후기",
        "AI 서비스", "AI 글쓰기", "AI 이미지", "AI 도구 추천", "AI 툴 추천",
        "Perplexity", "Copilot", "Notion AI", "AI 평가",
    ),
    "ai_model": (
        "모델 업데이트", "AI 업데이트", "새 모델", "신규 모델", "모델 출시", "GPT-5", "GPT5",
        "Claude 3", "Gemini", "오픈AI", "OpenAI", "Anthropic", "업그레이드", "신기능 출시", "버전 공개",
    ),
    "ai_search": (
        "AI 검색", "AI 오버뷰", "AI Overview", "SGE", "GEO", "AEO", "생성형 검색",
        "답변엔진", "검색 변화", "AI 인용", "제로클릭", "생성형 엔진", "검색 최적화 변화",
    ),
    "ai_blog": (
        "AI 블로그", "블로그 자동화", "블로그 수익화", "애드센스", "블로그 조회수", "블로그 RPM",
        "블로그 운영", "콘텐츠 자동화", "수익형 블로그", "블로그 트래픽", "포스팅 자동화",
    ),
    "ai_compare": (
        "AI 비교", "모델 비교", "도구 비교", "요금제 비교", "ChatGPT vs", "Claude vs", "Gemini vs",
        "어떤 AI", "무엇이 다를까", "성능 비교", "가격 비교", "플랜 비교", "AI 선택",
    ),
    "ai_risk": (
        "AI 보안", "AI 개인정보", "AI 저작권", "환각", "hallucination", "AI 리스크", "AI 위험",
        "데이터 유출", "AI 윤리", "프라이버시", "기밀 유출", "AI 규제",
    ),
    "ai_beginner": (
        "AI 입문", "AI 초보", "AI 처음", "AI 기초", "AI 시작", "왕초보 AI", "초보자 AI",
        "AI 첫걸음", "쉬운 AI", "AI 배우기", "AI 입문 가이드",
    ),
    "trend_meme": (
        "밈", "틱톡", "인스타", "릴스", "오픈런", "품절", "인증샷", "유행", "신조어",
    ),
    "entertainment_sports": (
        "손흥민", "축구", "야구", "스포츠", "팬 반응", "아이돌", "BTS", "넷플릭스", "영화", "예능",
        "드라마 반응", "경기 반응", "시즌2", "팬덤",
    ),
    "ott_platform": (
        "넷플릭스", "왓챠", "티빙", "웨이브", "디즈니플러스", "쿠팡플레이", "시즌", "OTT",
        "OTT 요금", "스트리밍", "오리지널", "드라마 반응", "시청자 반응", "콘텐츠 전략",
    ),
    "fandom_consumer": (
        "아이돌", "아이돌굿즈", "굿즈", "티켓팅", "콘서트 티켓", "팬미팅", "팬덤 소비",
        "공연 티켓", "앨범 판매", "초동", "팬클럽",
    ),
    "policy_benefit": (
        "지원금", "환급", "신청", "마감", "청년지원", "청년 지원", "부모지원", "부모 지원",
        "자영업자지원", "자영업자 지원", "소상공인 지원", "교통비 지원", "세금 환급", "정부 지원", "세금",
    ),
    "platform_issue": (
        "카카오", "네이버", "유튜브", "쿠팡", "구글", "애플", "삼성", "서비스 종료", "오류", "정책 변경",
        "앱 개편", "요금제 변경", "약관 변경", "멤버십 변경", "구독료 인상", "서비스 변경",
        "멤버십", "요금 인상", "앱 업데이트", "서비스 중단", "플랫폼 변경", "쿠팡 멤버십",
        "넷플릭스 요금", "OTT 요금", "유튜브 요금", "네이버페이",
    ),
}

CONTENT_TYPE_BY_TOPIC_GROUP: dict[str, str] = {
    "delivery_money": "money_checklist",
    "refund_consumer": "consumer_warning",
    "privacy_security": "consumer_warning",
    "ai_work": "ai_work_tip",
    "ai_prompt": "ai_prompt_recipe",
    "ai_tool": "ai_tool_review",
    "ai_model": "ai_model_update",
    "ai_search": "ai_search_change",
    "ai_blog": "ai_blog_growth",
    "ai_compare": "ai_comparison",
    "ai_risk": "ai_risk_security",
    "ai_beginner": "ai_beginner_guide",
    "trend_meme": "trend_decode",
    "entertainment_sports": "viral_issue_decode",
    "ott_platform": "viral_issue_decode",
    "fandom_consumer": "viral_issue_decode",
    "policy_benefit": "policy_deadline",
    "platform_issue": "platform_change",
    "today_issue": "today_issue_explainer",
    "general_life": "general_life",
}

EDITORIAL_AXIS_BY_TOPIC_GROUP: dict[str, str] = {
    "ai_work": "AI 자동화",
    "ai_prompt": "AI 자동화",
    "ai_tool": "AI 자동화",
    "ai_model": "AI 자동화",
    "ai_search": "AI 자동화",
    "ai_blog": "AI 자동화",
    "ai_compare": "AI 자동화",
    "ai_risk": "AI 자동화",
    "ai_beginner": "AI 자동화",
    "policy_benefit": "돈 되는 이슈",
    "delivery_money": "돈 되는 이슈",
    "refund_consumer": "생활 선택 기준",
    "trend_meme": "생활 선택 기준",
    "entertainment_sports": "연예·스포츠·OTT 이슈 해석",
    "ott_platform": "연예·스포츠·OTT 이슈 해석",
    "fandom_consumer": "연예·스포츠·OTT 이슈 해석",
    "platform_issue": "디지털 생존법",
    "today_issue": "today issue context",
    "general_life": "생활 선택 기준",
}

EDITORIAL_AXIS_BY_CONTENT_TYPE: dict[str, str] = {
    "ai_work_tip": "AI 자동화",
    # AI 블로그 전용 content_type (Phase B taxonomy 등록)
    "ai_tool_review": "AI 자동화",
    "ai_workflow_guide": "AI 자동화",
    "ai_prompt_recipe": "AI 자동화",
    "ai_model_update": "AI 자동화",
    "ai_search_change": "AI 자동화",
    "ai_blog_growth": "AI 자동화",
    "ai_comparison": "AI 자동화",
    "ai_risk_security": "AI 자동화",
    "ai_beginner_guide": "AI 자동화",
    "policy_deadline": "돈 되는 이슈",
    "tax_refund": "돈 되는 이슈",
    "money_checklist": "돈 되는 이슈",
    "consumer_warning": "생활 선택 기준",
    "trend_decode": "생활 선택 기준",
    "viral_issue_decode": "연예·스포츠·OTT 이슈 해석",
    "platform_change": "디지털 생존법",
    "today_issue_explainer": "today issue context",
    "general_life": "생활 선택 기준",
}

ARTICLE_TYPE_BY_CONTENT_TYPE: dict[str, str] = {
    "policy_deadline": "방법론가이드형",
    "tax_refund": "돈수익 분석형",
    "money_checklist": "비교선택형",
    "consumer_warning": "실수 방지형",
    "platform_change": "실수 방지형",
    "ai_work_tip": "방법론가이드형",
    # AI 블로그 전용 content_type별 본문 구조 성격 (Phase B)
    "ai_tool_review": "방법론가이드형",
    "ai_workflow_guide": "방법론가이드형",
    "ai_prompt_recipe": "레시피형",
    "ai_model_update": "업데이트 해설형",
    "ai_search_change": "이슈 해석형",
    "ai_blog_growth": "방법론가이드형",
    "ai_comparison": "비교선택형",
    "ai_risk_security": "실수 방지형",
    "ai_beginner_guide": "방법론가이드형",
    "trend_decode": "이슈 해석형",
    "viral_issue_decode": "viral_issue_decode형",
    "today_issue_explainer": "today_issue_explainer",
    "general_life": "큐레이션형",
}

_TOPIC_GROUP_PRIORITY = (
    "privacy_security",   # 개인정보/본인확인은 refund_consumer보다 우선
    "delivery_money",
    "refund_consumer",
    "fandom_consumer",
    "ott_platform",
    "trend_meme",
    "entertainment_sports",
    "policy_benefit",
    "platform_issue",
)
_POLICY_BENEFIT_TEXT_KEYWORDS = TOPIC_GROUP_KEYWORDS["policy_benefit"] + ("대상", "조건", "대상 조건")
_PRIVACY_CONTEXT_KEYWORDS = (
    "유출", "노출", "털렸", "탈탈", "해킹", "도용", "비밀번호",
    "2차 인증", "계정", "아이디", "id", "전화번호", "이름",
    "본인확인", "본인인증", "보안", "피싱", "스미싱", "사칭",
    "신고센터", "118",
)


def classify_topic_group(text: str, category: str = "", raw: dict[str, Any] | None = None) -> str:
    raw_group = str((raw or {}).get("topic_group") or "").strip()
    if raw_group in TOPIC_GROUPS:
        return raw_group

    haystack = f"{text or ''} category:{category or ''}".lower()
    if is_market_finance_text(haystack):
        return "general_life"
    if is_rank_stats_text(haystack):
        return "general_life"
    if is_privacy_security_text(haystack):
        return "privacy_security"
    if _is_delivery_worker_platform_text(haystack):
        return "platform_issue"
    if extract_public_benefit_keyword(haystack):
        return "policy_benefit"
    # AI 세부 그룹 라우팅 (2026-07-08 주제 틀 붕괴 수정): ai_model/ai_search/
    # ai_risk/ai_compare 그룹과 골든 패턴(ai_model_update 등)이 Phase 3부터
    # 존재했지만 어떤 분류 경로도 이 그룹들에 도달하지 못해 모든 AI 뉴스가
    # ai_work로 뭉개졌다 — 다양한 패턴이 "도달 불가능한 코드"였다.
    # 그룹을 build_search_angle과 같은 사건 분류기(_classify_ai_event)에서
    # 파생시켜, 앵글 프레임 ↔ 그룹 ↔ 골든 패턴이 한 출처로 일관되게 한다.
    if _has_ai_signal(haystack):
        event = _classify_ai_event(text or haystack)
        return _AI_EVENT_TOPIC_GROUP.get(event, "ai_work")
    for group in _TOPIC_GROUP_PRIORITY:
        if any(keyword.lower() in haystack for keyword in TOPIC_GROUP_KEYWORDS[group]):
            return group
    if any(keyword.lower() in haystack for keyword in TOPIC_GROUP_KEYWORDS["ai_work"]):
        return "ai_work"
    return "general_life"


def content_type_for_topic_group(topic_group: str) -> str:
    return CONTENT_TYPE_BY_TOPIC_GROUP.get(topic_group or "", "general_life")


def editorial_axis_for_topic_group(topic_group: str) -> str:
    return EDITORIAL_AXIS_BY_TOPIC_GROUP.get(topic_group or "", "생활 선택 기준")


def editorial_axis_for_content_type(content_type: str, topic_group: str = "") -> str:
    return EDITORIAL_AXIS_BY_CONTENT_TYPE.get(
        content_type or "",
        editorial_axis_for_topic_group(topic_group),
    )


def article_type_for_content_type(content_type: str) -> str:
    return ARTICLE_TYPE_BY_CONTENT_TYPE.get(content_type or "", "큐레이션형")


def is_delivery_money_text(text: str) -> bool:
    haystack = (text or "").lower()
    return any(keyword.lower() in haystack for keyword in TOPIC_GROUP_KEYWORDS["delivery_money"])


def is_privacy_security_text(text: str) -> bool:
    haystack = text or ""
    lowered = haystack.lower()
    compact = lowered.replace(" ", "")

    if any(keyword.replace(" ", "").lower() in compact for keyword in TOPIC_GROUP_KEYWORDS["privacy_security"]):
        return True
    if "개인정보" in haystack and any(keyword in lowered for keyword in _PRIVACY_CONTEXT_KEYWORDS):
        return True
    if any(
        marker in compact
        for marker in (
            "id이름전화번호",
            "아이디이름전화번호",
            "계정정보",
            "내정보도포함",
            "비밀번호변경",
            "비밀번호전면변경",
        )
    ):
        return True
    if "전화번호" in haystack and any(
        keyword in lowered for keyword in ("id", "아이디", "이름", "비밀번호", "유출", "탈탈", "털렸", "계정")
    ):
        return True
    if "비밀번호" in haystack and any(keyword in haystack for keyword in ("변경", "유출", "계정", "2차 인증")):
        return True
    return False


def is_policy_benefit_text(text: str) -> bool:
    haystack = (text or "").lower()
    benefit_info = classify_public_benefit(text)
    if benefit_info.get("public_benefit_keyword"):
        return True
    if benefit_info.get("generic_support_keyword") or benefit_info.get("commercial_support_signal"):
        return False
    return any(keyword.lower() in haystack for keyword in _POLICY_BENEFIT_TEXT_KEYWORDS)


def is_tax_refund_text(text: str) -> bool:
    haystack = text or ""
    compact = haystack.replace(" ", "").lower()
    if any(keyword.replace(" ", "").lower() in compact for keyword in TAX_REFUND_KEYWORDS):
        return True
    return "환급금" in haystack and any(token in haystack for token in ("세금", "국세", "홈택스", "손택스", "연말정산", "종합소득세"))


_RANK_STATS_RE = re.compile(r"\d+\s*위")
_RANK_STATS_CONTEXT = ("이용자", "사용자 수", "다운로드", "mau", "wau", "증가", "감소", "점유율", "순위", "집계")


def is_rank_stats_text(text: str) -> bool:
    """앱 사용량 순위·이용자 통계 집계 보도인지 감지 (2026-07-10).

    실측: "상반기 인기 앱 1위 유튜브...챗GPT 이용자 16.4% 증가하며 17위" 같은
    순위 집계 기사가 AI 단어만으로 ai_work 최상위 후보로 뽑혀 how-to 틀에 강제
    매칭됐고, 원문 보존/구체성 게이트에 막혀 발행 시도만 소모했다. 이런 기사엔
    독자가 실행할 내용이 없다 — general_life로 보내 골든 자동발행 경로에서 제외.
    """
    haystack = (text or "").lower()
    if not _RANK_STATS_RE.search(haystack):
        return False
    return any(token in haystack for token in _RANK_STATS_CONTEXT)


def is_market_finance_text(text: str) -> bool:
    haystack = (text or "").lower()
    compact = haystack.replace(" ", "")
    if any(keyword.replace(" ", "").lower() in compact for keyword in STRICT_MARKET_FINANCE_KEYWORDS):
        return True
    has_corporate_finance = any(
        keyword.replace(" ", "").lower() in compact
        for keyword in CORPORATE_FINANCE_KEYWORDS
    )
    has_market_context = any(
        keyword.replace(" ", "").lower() in compact
        for keyword in MARKET_FINANCE_CONTEXT_KEYWORDS
    )
    return has_corporate_finance and has_market_context


def extract_public_benefit_keyword(text: str) -> str:
    return str(classify_public_benefit(text).get("public_benefit_keyword") or "")


def classify_public_benefit(text: str) -> dict[str, Any]:
    haystack = text or ""
    compact = haystack.replace(" ", "").lower()
    lowered = haystack.lower()
    commercial_support_signal = any(keyword.lower() in lowered for keyword in COMMERCIAL_SUPPORT_KEYWORDS)
    public_signal = any(keyword.lower() in lowered for keyword in PUBLIC_BENEFIT_CONTEXT_SIGNALS)
    strong_keyword = _special_public_benefit_keyword(compact)
    for keyword in STRONG_PUBLIC_BENEFIT_KEYWORDS:
        if strong_keyword:
            break
        if keyword.replace(" ", "").lower() in compact:
            strong_keyword = keyword
            break
    generic_keyword = ""
    for keyword in GENERIC_SUPPORT_KEYWORDS:
        if keyword.replace(" ", "").lower() in compact:
            generic_keyword = keyword
            break
    specific_keyword = "" if commercial_support_signal else _extract_specific_support_keyword(haystack)

    keyword = ""
    confidence = "none"
    if strong_keyword:
        keyword = strong_keyword
        confidence = "high"
    elif specific_keyword:
        keyword = specific_keyword
        confidence = "high"
    elif generic_keyword and public_signal and not commercial_support_signal:
        keyword = generic_keyword
        confidence = "medium"
    elif generic_keyword:
        confidence = "low"

    return {
        "public_benefit_keyword": keyword,
        "generic_support_keyword": generic_keyword,
        "public_benefit_confidence": confidence,
        "commercial_support_signal": commercial_support_signal,
        "public_context_signal": public_signal,
        "public_benefit_promotion_blocked": bool(generic_keyword and commercial_support_signal and not strong_keyword),
    }


def _extract_specific_support_keyword(text: str) -> str:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text or "")
    for index, token in enumerate(tokens):
        suffix = next((item for item in _SPECIFIC_SUPPORT_SUFFIXES if token.endswith(item)), "")
        if not suffix:
            continue

        if token != suffix:
            prefix = token[: -len(suffix)].strip()
            if _is_specific_support_descriptor(prefix):
                if suffix == "환급금" and not _has_refund_support_context([prefix], text):
                    continue
                return f"{prefix} {suffix}".strip()

        descriptors: list[str] = []
        for previous in reversed(tokens[max(0, index - 6):index]):
            if _is_specific_support_descriptor(previous):
                descriptors.append(previous)
                if len(descriptors) >= 3:
                    break
        if descriptors:
            candidate = " ".join([*reversed(descriptors), suffix]).strip()
            if suffix == "환급금" and not _has_refund_support_context(descriptors, text):
                continue
            if not _is_too_generic_support_keyword(candidate):
                return candidate
    return ""


def _is_specific_support_descriptor(token: str) -> bool:
    value = (token or "").strip()
    if len(value) < 2:
        return False
    if value in _SPECIFIC_SUPPORT_STOPWORDS:
        return False
    if any(value.endswith(suffix) for suffix in _INVALID_SUPPORT_DESCRIPTOR_ENDINGS):
        return False
    if re.search(r"\d", value):
        return False
    return bool(re.search(r"[가-힣A-Za-z]", value))


def _special_public_benefit_keyword(compact_lower: str) -> str:
    if "고용보험료" in compact_lower and ("환급" in compact_lower or "돌려받" in compact_lower):
        if "소상공인" in compact_lower:
            return "소상공인 고용보험료 환급"
        return "고용보험료 환급"
    return ""


def _has_refund_support_context(descriptors: list[str], text: str) -> bool:
    compact = (text or "").replace(" ", "")
    descriptor_compact = "".join(descriptors)
    return any(
        token.replace(" ", "") in compact or token.replace(" ", "") in descriptor_compact
        for token in _REFUND_SUPPORT_DESCRIPTOR_CONTEXT
    )


def _is_too_generic_support_keyword(keyword: str) -> bool:
    compact = (keyword or "").replace(" ", "")
    generic_compact = {item.replace(" ", "") for item in GENERIC_SUPPORT_KEYWORDS}
    generic_compact.update({"정부지원금", "지자체지원금", "공식지원금"})
    return compact in generic_compact


def is_promotion_like_title(text: str) -> bool:
    haystack = (text or "").lower()
    return any(keyword.lower() in haystack for keyword in PROMOTION_LIKE_TITLE_KEYWORDS)


def transformed_public_benefit_topic(keyword: str, text: str = "") -> str:
    core = (keyword or "").strip()
    if not core:
        return ""
    haystack = text or ""
    if is_tax_refund_text(f"{core} {haystack}"):
        return f"{core} 대상과 조회 방법"
    if "사용처" in haystack or "사용 매장" in haystack or "매장" in haystack:
        return f"{core} 신청방법과 사용처 확인"
    if "지급" in haystack or "지급일" in haystack:
        return f"{core} 지급일과 신청방법 정리"
    return f"{core} 신청방법과 대상 조건"


def build_search_angle(
    topic: str,
    *,
    summary: str = "",
    category: str = "",
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original_topic = " ".join((topic or "").split()).strip()
    text = f"{original_topic} {summary or ''} {category or ''}".strip()
    compact = text.replace(" ", "")
    lower = text.lower()
    benefit_info = classify_public_benefit(text)
    benefit_keyword = str(benefit_info.get("public_benefit_keyword") or "")
    generic_support_keyword = str(benefit_info.get("generic_support_keyword") or "")
    commercial_support_signal = bool(benefit_info.get("commercial_support_signal"))

    def angle(
        *,
        search_demand_topic: str,
        questions: list[str],
        click_reason: str,
        reader_benefit: str,
        urgency_reason: str,
        content_promise: str,
        angle_type: str,
        should_transform_title: bool = True,
    ) -> dict[str, Any]:
        return {
            "original_topic": original_topic,
            "search_demand_topic": search_demand_topic,
            "reader_search_questions": questions[:3],
            "click_reason": click_reason,
            "reader_benefit": reader_benefit,
            "urgency_reason": urgency_reason,
            "content_promise": content_promise,
            "angle_type": angle_type,
            "should_transform_title": should_transform_title,
            "commercial_support_signal": commercial_support_signal,
            "generic_support_keyword": generic_support_keyword,
            "public_benefit_keyword": benefit_keyword,
            "public_benefit_confidence": str(benefit_info.get("public_benefit_confidence") or "none"),
            "public_benefit_promotion_blocked": bool(benefit_info.get("public_benefit_promotion_blocked")),
        }

    if commercial_support_signal and not benefit_keyword:
        return angle(
            search_demand_topic="휴대폰 구매 지원금 조건 확인" if "폰" in text or "휴대폰" in text else "",
            questions=[
                "상업성 지원금 조건은 어디서 확인해야 하나요?",
                "구매 혜택이 실제 결제금액에 어떻게 반영되나요?",
                "프로모션 조건에서 약정이나 추가 비용은 무엇인가요?",
            ],
            click_reason="상업성 지원금은 약정, 기기값, 추가 조건에 따라 실제 혜택이 달라질 수 있다.",
            reader_benefit="구매 전 지원금 조건과 약정, 추가 비용을 확인하는 기준을 얻는다.",
            urgency_reason="프로모션 조건은 매장과 기간에 따라 달라져 공식 조건 확인이 필요하다.",
            content_promise="상업성 프로모션의 조건 확인 포인트만 제한적으로 정리한다.",
            angle_type="consumer_warning",
            should_transform_title=False,
        )

    if benefit_keyword and is_tax_refund_text(f"{benefit_keyword} {text}"):
        demand_topic = transformed_public_benefit_topic(benefit_keyword, text)
        return angle(
            search_demand_topic=demand_topic,
            questions=[
                f"{benefit_keyword} 대상은 어떻게 확인하나요?",
                f"{benefit_keyword}은 어디에서 조회하나요?",
                f"{benefit_keyword} 신청 전에 어떤 정보를 준비해야 하나요?",
            ],
            click_reason="환급 대상 여부와 조회 경로를 놓치면 돌려받을 수 있는 금액 확인이 늦어질 수 있다.",
            reader_benefit="환급 대상, 조회 방법, 신청 경로, 환급 계좌와 필요 서류를 확인하는 기준을 얻는다.",
            urgency_reason="환급 조회와 신청 정보는 신고 기간과 계좌 확인 상태에 따라 처리 시점이 달라질 수 있다.",
            content_promise="환급 대상 여부, 홈택스·손택스 조회 경로, 필요 서류와 계좌 확인 항목을 정리한다.",
            angle_type="tax_refund",
        )

    if benefit_keyword:
        demand_topic = transformed_public_benefit_topic(benefit_keyword, text)
        angle_type = "deadline_check" if any(token in text for token in ("마감", "기한", "기간", "지급", "오늘")) else "benefit_howto"
        return angle(
            search_demand_topic=demand_topic,
            questions=[
                f"{benefit_keyword} 신청 대상은 누구인가요?",
                f"{benefit_keyword} 신청 기간은 언제까지인가요?",
                f"{benefit_keyword} 사용처는 어디인가요?",
            ],
            click_reason="신청 기간과 대상 조건을 놓치면 받을 수 있는 지원금을 놓칠 수 있다.",
            reader_benefit="신청 전 확인할 대상 조건, 신청 기간, 사용처 체크리스트를 얻는다.",
            urgency_reason="지원금은 신청 기간, 지급 방식, 사용처 조건을 놓치면 나중에 확인해도 늦을 수 있다.",
            content_promise="대상 조건, 신청방법, 지급일, 사용처를 한 번에 확인하는 생활 정보로 정리한다.",
            angle_type=angle_type,
        )

    if is_market_finance_text(text):
        entity = _leading_entity(original_topic) or "증시 이슈"
        return angle(
            search_demand_topic=f"{entity} 시장 반응과 확인할 사실",
            questions=[
                f"{entity} 수치는 어떤 기준으로 보도됐나요?",
                "공식 공시나 거래소 기준으로 확인할 항목은 무엇인가요?",
                "장중 변동 가능성이 있는 정보는 무엇인가요?",
            ],
            click_reason="주가와 시총 뉴스는 수치가 빠르게 바뀌고 투자 판단으로 오해될 수 있다.",
            reader_benefit="기사 원문, 공시, 거래소 기준을 분리해 확인하는 관점을 얻는다.",
            urgency_reason="시장 수치는 장중에도 바뀔 수 있어 발행 전 재확인이 필요하다.",
            content_promise="확인된 수치와 공시 여부 중심으로만 정리한다.",
            angle_type="market_finance",
            should_transform_title=False,
        )

    if is_privacy_security_text(text):
        entity = _leading_entity(original_topic) or "개인정보 안내"
        demand_topic = (
            f"{entity} 비밀번호 변경 안내 후 확인할 것"
            if "비밀번호" in text
            else f"{entity} 개인정보 안내 후 먼저 확인할 것"
        )
        return angle(
            search_demand_topic=demand_topic,
            questions=[
                f"{entity} 안내를 받았다면 비밀번호를 바로 바꿔야 하나요?",
                "같은 비밀번호를 쓴 다른 서비스도 함께 바꿔야 하나요?",
                "개인정보 유출 안내 뒤 피싱이나 추가 피해는 어떻게 확인하나요?",
            ],
            click_reason="개인정보나 계정 정보 안내를 놓치면 비밀번호 재사용, 피싱 문자, 추가 도용 대응이 늦어질 수 있다.",
            reader_benefit="유출 항목, 비밀번호 변경, 2차 인증, 공식 신고 채널 확인 순서를 얻는다.",
            urgency_reason="계정 보안 사고는 안내를 받은 직후 같은 비밀번호를 쓰는 다른 서비스까지 확인해야 한다.",
            content_promise="공식 안내 확인, 비밀번호 변경, 2차 인증, 피싱 주의 순서를 체크리스트로 정리한다.",
            angle_type="consumer_warning",
        )

    voucher_match = re.search(r"([가-힣A-Za-z0-9]+).*?(\d+\s*만원)\s*이용권", text)
    if voucher_match or "이용권" in text:
        brand = voucher_match.group(1) if voucher_match else _leading_entity(original_topic)
        amount = voucher_match.group(2).replace(" ", "") if voucher_match else ""
        benefit_name = f"{brand} {amount} 이용권".strip()
        return angle(
            search_demand_topic=f"{benefit_name} 대상과 사용기한 확인",
            questions=[
                f"{benefit_name} 대상은 누구인가요?",
                f"{benefit_name} 사용기한은 언제까지인가요?",
                "차액 환불이 안 되면 어떻게 확인해야 하나요?",
            ],
            click_reason="사용기한과 환불 조건을 모르면 받은 혜택을 제대로 쓰지 못할 수 있다.",
            reader_benefit="이용권 대상, 사용기한, 차액 환불 조건을 확인할 수 있다.",
            urgency_reason="오늘 지급, 석 달 기한 같은 조건은 사용 가능 기간을 바로 확인해야 한다.",
            content_promise="이용권 대상과 사용기한, 환불 제한 조건을 체크리스트로 정리한다.",
            angle_type="deadline_check",
        )

    if _is_platform_fee_change_text(text):
        service = "구글" if "구글" in text else ("앱마켓" if "앱마켓" in text else _leading_entity(original_topic) or "플랫폼")
        return angle(
            search_demand_topic=f"{service} 수수료 변경 전에 확인할 것",
            questions=[
                f"{service} 수수료 변경은 언제부터 적용되나요?",
                "수수료 변경 대상 서비스는 어디서 확인하나요?",
                "이용자와 사업자가 직접 확인할 조건은 무엇인가요?",
            ],
            click_reason="플랫폼 수수료 변경은 적용 시점과 대상에 따라 사업자·이용자 영향이 달라질 수 있다.",
            reader_benefit="적용 시점, 대상, 공식 공지에서 직접 확인할 조건을 분리해 볼 수 있다.",
            urgency_reason="수수료 변경 공지는 시행 전후 조건이 바뀔 수 있어 최신 확인이 필요하다.",
            content_promise="플랫폼 수수료 변경의 적용 시점과 확인 조건을 체크리스트로 정리한다.",
            angle_type="platform_check",
        )

    if ("카카오톡" in text or "카톡" in text) and any(token in text for token in ("지원 종료", "구형폰", "종료", "혼란")):
        return angle(
            search_demand_topic="내 폰에서 카카오톡이 안 될 수 있는지 확인하는 법",
            questions=[
                "내 휴대폰도 카카오톡 지원 종료 대상인가요?",
                "구형폰 카카오톡은 언제부터 안 되나요?",
                "카카오톡 지원 종료 전에 백업해야 할 것은 무엇인가요?",
            ],
            click_reason="내 기기가 지원 종료 대상인지 모르면 갑자기 앱 사용이 불편해질 수 있다.",
            reader_benefit="앱 지원 종료 전에 백업과 업데이트 여부를 확인할 수 있다.",
            urgency_reason="지원 종료 공지가 나오면 내 기기와 계정 백업 여부를 바로 확인해야 한다.",
            content_promise="지원 종료 대상 기기, 백업, 업데이트 확인 순서를 정리한다.",
            angle_type="platform_check",
        )

    if any(token in text for token in ("지원 종료", "서비스 종료", "정책 변경", "앱 업데이트", "구형폰")):
        service = "카카오톡" if "카카오" in text else _leading_entity(original_topic) or "서비스"
        return angle(
            search_demand_topic=f"{service} 지원 종료 전에 확인할 것",
            questions=[
                f"{service} 지원 종료 대상은 어떻게 확인하나요?",
                f"{service} 종료 전에 백업해야 할 것은 무엇인가요?",
                f"{service} 대체 방법은 어디서 확인하나요?",
            ],
            click_reason="지원 종료 대상인지 모르면 갑자기 서비스 이용이 막힐 수 있다.",
            reader_benefit="계정, 백업, 업데이트, 대체 서비스 확인 순서를 알 수 있다.",
            urgency_reason="지원 종료와 정책 변경은 공지 후 준비 기간이 짧을 수 있다.",
            content_promise="내 계정과 기기에서 먼저 확인할 항목을 체크리스트로 정리한다.",
            angle_type="platform_check",
        )

    if "환불" in text or "결제취소" in compact or "차액환불" in compact:
        return angle(
            search_demand_topic="환불 지연 때 소비자가 먼저 남겨야 할 증거",
            questions=[
                "환불이 늦어질 때 가장 먼저 남길 증거는 무엇인가요?",
                "고객센터 답변이 늦으면 어디에 기록해야 하나요?",
                "결제 취소가 안 되면 카드사에 무엇을 확인해야 하나요?",
            ],
            click_reason="환불 지연 때 증거를 늦게 남기면 소비자가 손해를 줄이기 어렵다.",
            reader_benefit="환불 지연 때 증거를 남기는 순서를 알 수 있다.",
            urgency_reason="결제내역과 상담 기록은 시간이 지나면 찾기 어려워질 수 있다.",
            content_promise="결제내역, 주문번호, 상담 기록을 남기는 순서를 정리한다.",
            angle_type="refund_action",
        )

    viral_entities = ("드라마", "OTT", "넷플릭스", "예능", "아이돌", "팬덤", "굿즈", "티켓팅", "경기", "손흥민", "야구", "축구", "스포츠", "콘서트", "유튜버", "스트리밍")
    is_viral_candidate = any(token in text for token in viral_entities)
    has_viral_safe_signal = any(signal in text for signal in VIRAL_SAFE_SIGNALS)
    has_viral_risk = any(kw in text for kw in VIRAL_RISK_KEYWORDS)
    if is_viral_candidate and not has_viral_risk:
        entity = _leading_entity(original_topic) or "이슈"
        if has_viral_safe_signal:
            demand_topic = f"{entity} 반응이 갈린 이유와 핵심 포인트"
        else:
            demand_topic = f"{entity}{_subject_particle(entity)} 화제 된 이유, 사람들이 본 핵심 포인트"
        return angle(
            search_demand_topic=demand_topic,
            questions=[
                f"{entity} 반응이 갈린 이유는 무엇인가요?",
                f"{entity}에서 팬덤·플랫폼·소비 구조는 어떻게 작동하나요?",
                f"{entity} 이후 독자가 확인할 다음 포인트는 무엇인가요?",
            ],
            click_reason="공식 콘텐츠·경기·방송 이슈가 왜 반응을 만들었는지 구조적으로 보면 다음 포인트가 보인다.",
            reader_benefit="이슈 해석, 반응 포인트, 팬덤·플랫폼·소비 구조를 한 번에 정리한다.",
            urgency_reason="반응이 갈린 직후가 검색 수요가 가장 높다.",
            content_promise="공식 기사·공개 콘텐츠 기반으로 반응 구조를 해석하고 evergreen 내부링크 후보를 제시한다.",
            angle_type="viral_issue_decode",
        )

    if _has_ai_signal(text):
        product = "크롬" if "크롬" in text else _leading_entity(original_topic) or "AI"
        # 엔티티가 이미 "…AI"로 끝나면 템플릿의 "AI 기능"과 붙어 "AI AI"가 된다
        # (실제 발행 사고: "구글 지도+제미나이 AI AI 기능…") — 꼬리 AI를 제거한다.
        # 단, 구분자 없이 붙은 브랜드명(OpenAI, xAI)은 자르면 안 된다
        # (실측: "OpenAI"가 "Open"이 됐음) — 구분자(공백/+/·)가 있을 때만 제거.
        product = re.sub(r"[\s+·]+(?:AI|인공지능)\s*$", "", product).strip() or "AI"
        # 원문 헤드라인의 실제 이슈 명사를 topic/제목에 보존 (PR #28의 교훈 유지).
        focus = _ai_setting_focus(original_topic) or _ai_setting_focus(text)
        # 주제 틀 붕괴 수정(2026-07-08): "AI 뉴스 = 설정 how-to" 단일 틀을 폐기하고
        # 사건 유형(_classify_ai_event)별로 프레임을 배정한다. 설정이 없는 사건
        # (광고·요금·규제·모델 발표)에 설정 글을 지어내지 않는다.
        event = _classify_ai_event(text)

        if event == "pricing":
            core = _dedupe_tokens(f"{product} AI {focus} 요금 변화" if focus else f"{product} AI 요금 변화")
            return angle(
                search_demand_topic=core,
                questions=[
                    f"{product} AI 요금은 무엇이 어떻게 바뀌나요?",
                    "무료로 쓸 수 있는 범위는 어디까지인가요?",
                    "유료 전환을 고민할 때 기준은 무엇인가요?",
                ],
                click_reason="요금과 무료 한도가 바뀌면 지금 쓰던 방식의 비용이 달라질 수 있다.",
                reader_benefit=f"{product} AI의 바뀐 요금 조건과 무료·유료 선택 기준을 얻는다.",
                urgency_reason="요금 변경 직후에는 기존 사용자 적용 시점과 조건 확인이 필요하다.",
                content_promise="바뀐 요금 조건, 무료 한도, 전환 판단 기준을 비교표로 정리한다.",
                angle_type="money_compare",
            )
        if event == "risk":
            risk_focus = focus or "보안"
            core = _dedupe_tokens(f"{product} AI {risk_focus} 이슈")
            return angle(
                search_demand_topic=core,
                questions=[
                    f"{product} AI {risk_focus} 이슈는 무엇이 확인된 건가요?",
                    "내 계정과 데이터에서 지금 확인할 것은 무엇인가요?",
                    "공식 안내는 어디에서 확인하나요?",
                ],
                click_reason=f"{risk_focus} 이슈를 모르고 쓰면 내 데이터와 계정이 영향을 받을 수 있다.",
                reader_benefit=f"확인된 사실과 내 계정에서 점검할 {risk_focus} 항목을 얻는다.",
                urgency_reason="보안·데이터 이슈는 공지 직후 확인이 가장 유리하다.",
                content_promise=f"확인된 {risk_focus} 사실, 사용자 점검 항목, 공식 확인 경로를 정리한다.",
                angle_type="ai_risk_check",
            )
        if event == "model_release":
            core = _dedupe_tokens(f"{product} 새 AI 모델 발표")
            return angle(
                search_demand_topic=core,
                questions=[
                    f"{product} 새 AI 모델은 무엇이 달라졌나요?",
                    "기존 사용자는 무엇이 바뀌나요?",
                    "지금 도구를 바꿀 필요가 있나요?",
                ],
                click_reason="새 모델 발표 직후에는 과장과 실제 변화가 섞여 판단이 어렵다.",
                reader_benefit="확인된 변경점과 내 용도 기준의 선택 판단 기준을 얻는다.",
                urgency_reason="적용 시점과 제공 범위는 계정·지역별로 순차 적용될 수 있다.",
                content_promise="발표에서 확인된 것, 기존 사용자에게 달라지는 것, 선택 기준을 정리한다.",
                angle_type="ai_model_release",
            )
        if event == "regulation":
            core = _dedupe_tokens(f"{product} AI {focus} 규제 움직임" if focus else f"{product} AI 규제 움직임")
            return angle(
                search_demand_topic=core,
                questions=[
                    "이번 규제 논의에서 확정된 것은 무엇인가요?",
                    "일반 사용자에게 당장 달라지는 것이 있나요?",
                    "시행 시점과 적용 범위는 어떻게 되나요?",
                ],
                click_reason="규제 뉴스는 확정과 논의가 섞여 있어 당장 달라지는 것을 구분해야 한다.",
                reader_benefit="확정 사항과 논의 단계를 구분하고 사용자 영향만 추려 확인한다.",
                urgency_reason="시행 시점 전후로 서비스 약관과 기능이 바뀔 수 있다.",
                content_promise="확정된 내용, 시행 시점, 사용자에게 달라지는 것을 구분해 정리한다.",
                angle_type="ai_policy_impact",
            )
        if event == "business":
            biz_focus = focus or "서비스"
            core = _dedupe_tokens(f"{product} AI {biz_focus} 확대")
            return angle(
                search_demand_topic=core,
                questions=[
                    f"{product}의 이번 발표는 무엇을 하겠다는 건가요?",
                    "사용자 화면과 기능에는 무엇이 달라지나요?",
                    "내 데이터 사용 방식에 영향이 있나요?",
                ],
                click_reason="기업 발표는 사업 이야기지만 결국 사용자 화면과 데이터 정책이 바뀐다.",
                reader_benefit=f"발표 내용 중 사용자에게 실제로 달라지는 것과 확인할 것을 얻는다.",
                urgency_reason="적용 초기에 기본값과 안내가 바뀌는 경우가 많다.",
                content_promise="발표의 확인된 사실과 사용자에게 달라지는 것만 추려 정리한다.",
                angle_type="ai_service_change",
            )
        if event == "search":
            core = _dedupe_tokens(f"{product} AI 검색 변화")
            return angle(
                search_demand_topic=core,
                questions=[
                    f"{product} AI 검색은 무엇이 달라졌나요?",
                    "검색 결과 화면에서 어디가 바뀌나요?",
                    "정보 확인 습관은 어떻게 바꿔야 하나요?",
                ],
                click_reason="AI 검색 변화는 매일 쓰는 검색 결과와 출처 확인 방식에 바로 영향을 준다.",
                reader_benefit="바뀐 검색 화면의 확인 포인트와 출처 검증 습관을 얻는다.",
                urgency_reason="검색 변화는 순차 적용되므로 내 계정 적용 여부 확인이 필요하다.",
                content_promise="달라진 검색 화면, 확인 포인트, 출처 검증 방법을 정리한다.",
                angle_type="ai_search_change",
            )
        if event == "comparison":
            core = _dedupe_tokens(f"{product} AI 비교 선택 기준")
            return angle(
                search_demand_topic=core,
                questions=[
                    "어떤 기준으로 비교해야 하나요?",
                    "내 용도에는 어느 쪽이 맞나요?",
                    "요금과 한도 차이는 어떻게 확인하나요?",
                ],
                click_reason="스펙 나열 비교는 실제 선택에 도움이 안 되고 용도별 기준이 필요하다.",
                reader_benefit="용도·요금·한도 기준의 선택 판단 기준을 얻는다.",
                urgency_reason="요금과 제공 범위는 자주 바뀌어 최신 조건 확인이 필요하다.",
                content_promise="용도별 선택 기준과 확인할 조건을 비교표로 정리한다.",
                angle_type="ai_comparison",
            )
        if event == "feature":
            # 설정·기능 신호가 실제로 있는 사건만 how-to 프레임 (기존 ai_setting 유지)
            head = f"{product} AI {focus} 기능 설정" if focus else f"{product} AI 기능 설정"
            demand_topic = _dedupe_tokens(head)
            subject = _dedupe_tokens(f"{product} AI {focus}" if focus else f"{product} AI 기능")
            benefit = (
                f"{product} AI의 {focus} 관련 설정과 확인 기준을 알 수 있다."
                if focus else "새 AI 기능의 기본 설정과 검수 기준을 알 수 있다."
            )
            return angle(
                search_demand_topic=demand_topic,
                questions=[
                    f"{subject} 설정은 어디서 바꾸나요?",
                    f"{product} AI 기능을 쓰기 전에 어떤 설정을 확인해야 하나요?",
                    "AI 기능이 업무 흐름에 영향을 주는 부분은 무엇인가요?",
                ],
                click_reason="AI 기능의 설정과 데이터 사용 기준을 모르면 업무 흐름이 꼬일 수 있다.",
                reader_benefit=benefit,
                urgency_reason="새 기능 출시 직후에는 기본 설정과 사용 범위를 먼저 확인해야 한다.",
                content_promise="AI 기능 설정, 업무 적용 기준, 주의점을 정리한다.",
                angle_type="ai_setting",
            )
        # announcement — 신호 불명: 설정을 지어내지 않고 해설 프레임으로.
        core = _dedupe_tokens(f"{product} AI {focus} 소식" if focus else f"{product} AI 소식")
        return angle(
            search_demand_topic=core,
            questions=[
                f"{product} AI 소식에서 확인된 사실은 무엇인가요?",
                "일반 사용자에게 달라지는 것이 있나요?",
                "지금 해야 할 일이 있나요?",
            ],
            click_reason="새 소식은 과장과 사실이 섞여 있어 확인된 것만 구분할 기준이 필요하다.",
            reader_benefit="확인된 사실과 내게 영향 있는 부분만 추려 확인한다.",
            urgency_reason="초기 보도는 조건이 바뀔 수 있어 공식 발표 기준 확인이 필요하다.",
            content_promise="확인된 사실, 사용자 영향, 직접 확인할 것을 구분해 정리한다.",
            angle_type="ai_service_change",
        )

    if _is_delivery_worker_platform_text(text):
        service = "배달앱 새벽배달" if "새벽배달" in text or "심야배달" in text else "배달앱 운영"
        return angle(
            search_demand_topic=f"{service} 변경 전에 확인할 것",
            questions=[
                f"{service} 변경으로 이용자와 라이더에게 무엇이 달라지나요?",
                "배달비, 배차, 안전 조건은 어디서 확인해야 하나요?",
                "새 운영 정책에서 소비자가 확인할 조건은 무엇인가요?",
            ],
            click_reason="배달 운영 변경은 배달비, 배차, 라이더 안전, 이용 가능 시간에 영향을 줄 수 있다.",
            reader_benefit="이용자 화면의 조건과 라이더 안전·수익 논점을 분리해 확인하는 기준을 얻는다.",
            urgency_reason="새벽배달이나 배차 정책은 시행 직후 현장 반응과 조건이 빠르게 바뀔 수 있다.",
            content_promise="운영 변경, 배달비 표시, 안전 논점, 공식 안내 확인 순서를 체크리스트로 정리한다.",
            angle_type="platform_check",
        )

    if _is_consumer_money_compare_text(text):
        keyword = "배달앱 결제금액" if "배달" in text else _leading_entity(original_topic) or "요금"
        return angle(
            search_demand_topic=f"{keyword} 비교 전에 확인할 조건",
            questions=[
                f"{keyword}은 무엇을 기준으로 비교해야 하나요?",
                "쿠폰을 쓰면 항상 더 저렴한가요?",
                "최종 결제금액은 어디서 확인해야 하나요?",
            ],
            click_reason="쿠폰, 수수료, 최소 조건을 놓치면 할인받고도 더 낼 수 있다.",
            reader_benefit="최종 결제금액을 비교하는 기준과 체크 순서를 얻는다.",
            urgency_reason="요금과 쿠폰 조건은 자주 바뀌어 결제 전 확인이 필요하다.",
            content_promise="가격, 수수료, 쿠폰 조건을 비교표 관점으로 정리한다.",
            angle_type="money_compare",
        )

    if any(token in text for token in ("피해", "주의", "약관", "개인정보", "고객센터")):
        return angle(
            search_demand_topic=f"{_leading_entity(original_topic) or '소비자 피해'} 확인 전에 볼 주의점",
            questions=[
                "소비자 피해가 의심될 때 먼저 확인할 것은 무엇인가요?",
                "약관이나 개인정보 조건은 어디서 확인해야 하나요?",
                "고객센터 문의 전에 남겨야 할 기록은 무엇인가요?",
            ],
            click_reason="주의 조건을 놓치면 환불, 보상, 개인정보 대응이 늦어질 수 있다.",
            reader_benefit="피해를 줄이기 위해 먼저 확인할 기록과 조건을 알 수 있다.",
            urgency_reason="피해 대응은 초기 기록을 빨리 남길수록 유리하다.",
            content_promise="주의점, 증거, 문의 순서를 생활 체크리스트로 정리한다.",
            angle_type="consumer_warning",
        )

    trend_topic = _leading_entity(original_topic) or "오늘 이슈"
    return angle(
        search_demand_topic=f"{trend_topic} 왜 관심이 커졌는지 확인",
        questions=[
            f"{trend_topic}은 왜 관심이 커졌나요?",
            f"{trend_topic}에서 소비자가 확인할 점은 무엇인가요?",
            f"{trend_topic}은 일시적 유행인가요?",
        ],
        click_reason="단순 화제처럼 보여도 내 소비 선택에 영향을 줄 수 있다.",
        reader_benefit="유행을 따라가기 전 가격, 필요성, 지속성을 판단할 기준을 얻는다.",
        urgency_reason="화제가 커진 직후에는 정보가 과장될 수 있어 판단 기준이 필요하다.",
        content_promise="왜 퍼졌는지와 소비 전에 볼 기준을 짧게 정리한다.",
        angle_type="trend_reason",
        should_transform_title=False,
    )


def is_viral_safe(text: str) -> bool:
    haystack = (text or "").lower()
    if any(kw.lower() in haystack for kw in VIRAL_RISK_KEYWORDS):
        return False
    return True


def viral_safety_score(text: str) -> int:
    haystack = (text or "").lower()
    risk_count = sum(1 for kw in VIRAL_RISK_KEYWORDS if kw.lower() in haystack)
    safe_count = sum(1 for sig in VIRAL_SAFE_SIGNALS if sig.lower() in haystack)
    return max(0, min(100, 70 + safe_count * 5 - risk_count * 20))


_ENTITY_SPLIT_PATTERN = re.compile(r"[,，:;!?·…—/]|\.{2,}")
_MAX_ENTITY_TOKENS = 3
_MAX_ENTITY_TOKEN_CHARS = 8
_INVALID_ENTITY_TOKEN_ENDINGS = (
    "됐고", "했고", "되고", "였고",
    "이라고", "라고", "라며", "라는",
    "이다", "한다", "된다", "있다", "없다", "했다", "였다",
    "처럼", "면서", "지만",
    "에서", "에는", "에게", "으로", "하고", "이고",
)


def _leading_entity(text: str) -> str:
    lead = _ENTITY_SPLIT_PATTERN.split(text or "")[0].strip(" ,.-'\"“”‘’[]()")
    lead = re.sub(r'^[\'"“”‘’][^\'"“”‘’]{2,40}[\'"“”‘’]\s*', "", lead).strip(" ,.-'\"“”‘’[]()")
    if not lead:
        return ""
    tokens = lead.split()
    if not tokens:
        return ""
    cleaned: list[str] = []
    for tok in tokens[:_MAX_ENTITY_TOKENS]:
        tok = tok.strip(" ,.-'\"“”‘’[]()")
        if not tok:
            continue
        if len(tok) > _MAX_ENTITY_TOKEN_CHARS:
            return ""
        if any(tok.endswith(suf) for suf in _INVALID_ENTITY_TOKEN_ENDINGS):
            break
        cleaned.append(tok)
    if not cleaned:
        return ""
    result = " ".join(cleaned).strip(" ,.-'\"“”‘’[]()")
    if len(result) < 2:
        return ""
    return result


# ai_setting 앵글에서 원문 헤드라인의 실제 이슈 명사를 골라 topic/제목에 보존한다.
# "AI 설정" 소비자 콘텐츠와 자연스럽게 붙고, AI 뉴스 본문에도 자주 등장해
# original_issue_preservation·title_body 게이트를 정직하게 통과시키는 명사만 담는다.
_AI_SETTING_FOCUS_NOUNS = (
    "보안", "정보보호", "개인정보", "데이터", "계정",
    "검색", "번역", "요약", "광고", "쇼핑", "결제", "알림",
    "음성", "이미지", "영상", "문서", "메일", "일정", "코딩", "학습", "추천", "챗봇",
)


def _ai_setting_focus(text: str) -> str:
    haystack = text or ""
    for noun in _AI_SETTING_FOCUS_NOUNS:
        if noun in haystack:
            return noun
    return ""


# 사건 유형 → 토픽 그룹 (그룹별 골든 패턴: ai_risk_security / ai_model_update /
# ai_search_change / ai_comparison). 나머지 유형(요금·사업·규제·기능·소식)은
# ai_work(ai_work_time_savings)로 — 프레임 어휘를 패턴 match_keywords와 정렬해 둔다.
_AI_EVENT_TOPIC_GROUP = {
    "risk": "ai_risk",
    "model_release": "ai_model",
    "search": "ai_search",
    "comparison": "ai_compare",
}

# AI 제품명 — "AI"라는 단어 없이 제품명만 나오는 헤드라인("제미나이 3 공개…")도
# AI 뉴스로 인식해야 한다 (실측: 문자열 "AI" 부재로 AI 분기 자체를 놓쳤음).
_AI_PRODUCT_SIGNALS = (
    "인공지능", "챗gpt", "chatgpt", "gpt", "제미나이", "gemini", "클로드", "claude",
    "코파일럿", "copilot", "퍼플렉시티", "perplexity", "미스트랄", "mistral",
    "클로바", "clova", "카나나", "kanana", "소라", "sora", "그록", "grok", "llm",
)


def _has_ai_signal(text: str) -> bool:
    haystack = (text or "").lower()
    if re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", haystack):
        return True
    return any(signal in haystack for signal in _AI_PRODUCT_SIGNALS)


def _classify_ai_event(text: str) -> str:
    """AI 뉴스의 사건 유형 분류 — 앵글 프레임 라우팅의 기준 (2026-07-08).

    배경: "AI" 단어만 있으면 광고 출시·요금 개편·규제·모델 발표까지 전부
    "{제품} AI 기능 설정" how-to 하나로 뭉갰다. 설정이 없는 사건에 설정 글을
    쓰니 제목↔본문 불일치·원문 이슈 소실 게이트에 걸렸고(5일 미발행 사건의
    뿌리), 통과한 날에는 같은 모양의 글만 연속 발행됐다(네이버 AI 3연속).

    순서 중요: 더 구체적인 신호를 먼저 본다. 어느 신호에도 안 걸리면
    "announcement"(해설 프레임) — 근거 없이 설정 how-to로 보내지 않는다.
    """
    haystack = text or ""
    lower = haystack.lower()
    if re.search(r"\bvs\.?(?:\s|$)", lower) or "비교" in haystack:
        return "comparison"
    if any(t in haystack for t in ("요금", "가격", "구독료", "무료", "유료", "과금", "인상", "인하", "할인", "사용량 한도")):
        return "pricing"
    if any(t in haystack for t in ("보안", "유출", "해킹", "저작권", "환각", "리스크", "취약점", "딥페이크", "정보보호", "개인정보 침해")):
        return "risk"
    if any(t in haystack for t in ("모델", "버전", "파라미터", "벤치마크")) and any(
        t in haystack for t in ("공개", "출시", "발표", "업데이트", "선보")
    ):
        return "model_release"
    if any(t in haystack for t in ("규제", "법안", "기본법", "시행령", "소송", "제재", "가이드라인", "공정위", "법원")):
        return "regulation"
    if any(t in haystack for t in ("광고", "매출", "실적", "투자", "인수", "합병", "제휴", "협약", "상장", "수익화", "구조조정")):
        return "business"
    # 안전·거버넌스·윤리 체계는 "출시/발표"가 붙어도 사용자 설정이 없다 —
    # feature(설정 how-to)로 보내면 없는 설정을 지어낸다. 해설(announcement)로.
    # (실측: 같은 "네이버 AI 안전관리 2.0" 뉴스가 소스에 따라 "발표"→소식,
    #  "출시"→설정으로 갈리던 불일치를 여기서 통일한다.)
    if any(t in haystack for t in ("안전성", "안전관리", "안전 체계", "거버넌스", "윤리", "책임있는", "책임 있는")):
        return "announcement"
    if "검색" in haystack:
        return "search"
    if any(t in haystack for t in ("기능", "도입", "탑재", "지원", "업데이트", "출시", "개방", "적용", "추가")):
        return "feature"
    return "announcement"


def _dedupe_tokens(text: str) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for tok in (text or "").split():
        if tok in seen:
            continue
        seen.add(tok)
        result.append(tok)
    return " ".join(result)


def _subject_particle(word: str) -> str:
    cleaned = (word or "").strip()
    if not cleaned:
        return "가"
    last = cleaned[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return "이" if (code - 0xAC00) % 28 else "가"
    return "가"


def _is_platform_fee_change_text(text: str) -> bool:
    haystack = text or ""
    if "수수료" not in haystack:
        return False
    return any(token in haystack for token in ("구글", "앱마켓", "플랫폼", "인앱결제", "게임협", "개발사"))


def _is_delivery_worker_platform_text(text: str) -> bool:
    haystack = text or ""
    compact = haystack.replace(" ", "")
    has_delivery_platform = any(token in compact for token in ("배달앱", "배민", "배달의민족", "쿠팡이츠", "요기요"))
    has_worker_or_operation = any(
        token in compact
        for token in ("라이더", "배달기사", "새벽배달", "심야배달", "배차", "운행", "운영", "노조")
    )
    has_safety_or_income = any(
        token in compact
        for token in ("위험", "안전", "수익", "분통", "확대", "정책", "대기시간", "노동", "처우")
    )
    return has_delivery_platform and has_worker_or_operation and has_safety_or_income


def _is_consumer_money_compare_text(text: str) -> bool:
    haystack = text or ""
    if is_privacy_security_text(haystack):
        return False
    if _is_delivery_worker_platform_text(haystack):
        return False
    delivery_or_checkout = (
        "배달비", "배달료", "무료배달", "최소주문", "최소 주문",
        "쿠폰", "배송비", "결제금액", "최종금액", "최종 금액", "장바구니",
    )
    household_fee = (
        "구독료", "통신비", "요금제", "생활비", "자동결제", "카드 혜택",
        "전월 실적",
    )
    price_change = ("가격 인상", "요금 인상", "가격 비교", "요금 비교")
    if any(token in haystack for token in delivery_or_checkout + household_fee + price_change):
        return True
    if "배달앱" in haystack and any(token in haystack for token in ("수수료", "가격", "요금", "쿠폰", "무료배달", "최소주문", "결제")):
        return True
    if "수수료" in haystack and any(token in haystack for token in ("배달", "라이더", "자영업자", "사장님", "음식점")):
        return True
    return False
