from __future__ import annotations

import html
import logging
import re
from typing import Any

from blogspot_automation.services.title_integrity_policy import audit_title_integrity

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# 상수                                                                 #
# ------------------------------------------------------------------ #

_BLOCKED_PHRASES: tuple[str, ...] = (
    "충격", "소름", "난리났다", "결국 터졌다", "실화냐", "역대급 반전",
    "루머", "진짜일까", "사생활", "폭로", "불륜", "열애설", "이혼설",
    "미성년자", "외모 비하", "외모비하", "경악", "발칵", "무조건",
    "재계는 지금",
)

_VIRAL_EXTRA_BLOCK: tuple[str, ...] = (
    "열애", "이혼", "불륜", "사생활", "폭로", "루머",
    "미성년자", "외모", "비하", "악플", "신상",
)

_MALFORMED_TITLE_PATTERNS: tuple[str, ...] = (
    r"\s{2,}",
    r"^[가-힣A-Za-z0-9·\s]{2,24\]\s+",
    r"확인할\s+전에",
    r"확인할\s*,",
    r"확인할\s+[을를이가은는]\b",
    r"\b[을를이가은는]\s+(?:제대로|먼저|확인|보기|볼)\b",
    r"화제\s*된\s*이\s*반응",
    r"사람들이\s*본\s*[의에](?:\s|$)",
)

_GOOD_SIGNALS: tuple[str, ...] = (
    "이유", "확인", "방법", "줄이는", "차이", "비교",
    "조회", "반응", "체크", "손해", "시간", "돈", "기준",
)

_PATTERN_REQUIRED_KEYWORDS: dict[str, list[str]] = {
    "tax_refund_hometax_check": ["환급금", "홈택스", "국세환급금", "세금환급", "종합소득세", "연말정산환급", "손택스", "환급"],
    "viral_ott_reaction_decode": ["넷플릭스", "OTT", "드라마", "반응", "시청자", "신작", "예능", "팬덤"],
    "ai_work_time_savings": ["ChatGPT", "챗GPT", "직장인", "AI", "업무", "시간", "생산성", "자동화"],
    "ai_tool_comparison": ["AI 도구", "ChatGPT", "Claude", "비교", "업무용", "선택", "AI", "생산성 도구"],
    "ai_automation_workflow": ["자동화", "워크플로우", "반복 업무", "AI 자동화", "업무 자동화", "프로세스"],
    "ai_prompt_recipe": ["프롬프트", "ChatGPT", "AI", "템플릿", "프롬프트 템플릿", "지시문", "보고서", "요약"],
    "ai_tool_review": ["AI 도구", "AI 툴", "리뷰", "후기", "AI", "사용법", "무료", "유료", "추천"],
    "ai_model_update": ["AI", "모델", "업데이트", "출시", "GPT", "Claude", "Gemini", "버전", "신기능"],
    "ai_search_change": ["AI 검색", "AEO", "GEO", "SGE", "AI", "검색", "인용", "블로그", "노출"],
    "ai_blog_growth": ["블로그", "조회수", "수익", "애드센스", "자동화", "AI", "트래픽", "운영"],
    "ai_comparison": ["AI", "비교", "vs", "차이", "도구", "모델", "요금제", "선택", "무료", "유료"],
    "ai_risk_security": ["AI", "보안", "개인정보", "저작권", "리스크", "위험", "환각", "주의"],
    "ai_beginner_guide": ["AI", "초보", "입문", "처음", "기초", "사용법", "시작", "쉽게"],
    "delivery_money_checklist": ["배달앱", "배달비", "결제금액", "쿠폰", "무료배달", "최소주문", "배달"],
}

# 과장 표현 감점을 공유하는 AI 패턴 집합
_AI_PATTERN_IDS: frozenset[str] = frozenset({
    "ai_work_time_savings",
    "ai_tool_comparison",
    "ai_automation_workflow",
    "ai_prompt_recipe",
    "ai_tool_review",
    "ai_model_update",
    "ai_search_change",
    "ai_blog_growth",
    "ai_comparison",
    "ai_risk_security",
    "ai_beginner_guide",
})

_PATTERN_FORBIDDEN_CROSSOVER: dict[str, list[str]] = {
    "tax_refund_hometax_check": ["지원금", "사용처", "바우처", "가맹점", "드라마", "넷플릭스"],
    "viral_ott_reaction_decode": [
        "사생활", "루머", "폭로", "불륜", "열애설", "이혼설",
        "요금제", "통신비", "선택약정", "가족결합", "결합할인", "멤버십",
        "통신사", "KT초이스", "KT", "SKT", "SK텔레콤", "LG유플러스", "LGU+",
    ],
    "ai_work_time_savings": ["지원금", "환급금", "드라마", "넷플릭스", "사생활"],
    "ai_tool_comparison": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스"],
    "ai_automation_workflow": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스"],
    "ai_prompt_recipe": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_tool_review": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_model_update": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_search_change": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_blog_growth": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_comparison": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_risk_security": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "ai_beginner_guide": ["지원금", "환급금", "세금", "홈택스", "드라마", "넷플릭스", "배달"],
    "delivery_money_checklist": ["지원금", "환급", "세금", "홈택스", "신청마감", "복지급여", "드라마", "넷플릭스"],
}

# pattern별 제목 공식
_PATTERN_TITLE_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "tax_refund_hometax_check": [
        ("세금 환급금 조회 전 홈택스에서 먼저 볼 3가지", "search"),
        ("홈택스 환급금 조회, 0원으로 보일 때 먼저 볼 것", "howto"),
        ("세금 환급금이 늦어질 때 계좌보다 먼저 볼 항목", "loss"),
        ("국세환급금·종합소득세 환급, 메뉴를 헷갈리면 0원으로 보입니다", "loss"),
        ("세금 환급금 안 들어온 이유, 홈택스에서 먼저 확인할 3단계", "howto"),
        ("홈택스 환급 조회, 이 메뉴부터 열어야 하는 이유", "curiosity"),
        ("세금 환급금 5년 소멸 전에 홈택스에서 먼저 볼 것", "save_time"),
        ("연말정산·종합소득세 환급 차이, 홈택스 메뉴가 다릅니다", "comparison"),
        ("환급금 있는데 입금 안 됐다면 먼저 확인할 원인 3가지", "loss"),
        ("국세환급금 조회 전 계좌 오류부터 먼저 확인해야 하는 이유", "search"),
    ],
    "viral_ott_reaction_decode": [
        ("넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지", "viral"),
        ("넷플릭스 신작이 호불호 갈린 이유, 작품보다 기대 코드가 문제였다", "curiosity"),
        ("OTT 신작 반응이 갈리는 이유, 평점보다 먼저 볼 것", "search"),
        ("드라마 반응이 갈린 이유, 시청자가 기대한 장르가 달랐다", "curiosity"),
        ("넷플릭스 1위인데 별로인 이유, 순위가 퀄리티가 아닌 까닭", "comparison"),
        ("OTT 드라마 반응이 극단으로 갈리는 3가지 구조", "howto"),
        ("내가 재미없었던 드라마, 타인은 왜 극찬했을까", "curiosity"),
        ("OTT 시청자 반응 갈림, 장르 기대값이 다를 때 생기는 일", "viral"),
        ("드라마 완주율과 순위, 같은 작품 다른 반응의 진짜 이유", "comparison"),
        ("넷플릭스 호불호 갈리는 작품, 망작이 아닌 개성의 증거다", "safe"),
    ],
    "ai_work_time_savings": [
        ("직장인이 ChatGPT를 써도 시간이 안 줄어드는 이유", "search"),
        ("ChatGPT로 업무 시간이 안 줄어드는 진짜 이유", "curiosity"),
        ("AI를 써도 일이 줄지 않는 사람들의 공통 실수", "loss"),
        ("직장인 AI 활용, 시간을 줄이려면 글쓰기부터 하면 안 됩니다", "howto"),
        ("ChatGPT 쓰는데 오히려 더 바빠진 이유", "curiosity"),
        ("AI 업무 자동화 전에 먼저 정해야 할 2가지 기준", "howto"),
        ("검수 시간이 늘면 AI는 시간을 줄이는 도구가 아닙니다", "loss"),
        ("직장인 ChatGPT, 반복 텍스트부터 써야 시간이 줄어드는 이유", "save_time"),
        ("AI 초안과 완성본의 차이, 직장인이 오해하는 핵심", "comparison"),
        ("무료 ChatGPT로도 업무 시간 줄이는 3가지 패턴", "save_time"),
    ],
    "ai_tool_comparison": [
        ("ChatGPT vs Claude, 직장인 업무용으로 어떤 AI가 더 맞을까", "comparison"),
        ("AI 도구 선택 전 먼저 확인할 3가지 기준", "search"),
        ("업무용 AI 도구, 기능보다 먼저 봐야 할 것", "howto"),
        ("ChatGPT와 Claude 차이, 업무 유형별로 고르는 법", "comparison"),
        ("무료 AI 도구로 업무 시간 줄이는 법, 유료 필요 없는 경우", "save_time"),
        ("AI 도구 비교 전에 먼저 정해야 할 내 업무 패턴", "howto"),
        ("생산성 AI 도구, 써봐야 아는 실제 차이", "curiosity"),
        ("AI 어시스턴트 선택 기준, 기능 목록이 아닌 워크플로우 적합성", "search"),
        ("ChatGPT 유료 전환 전에 먼저 해볼 무료 테스트", "save_time"),
        ("AI 도구를 바꿔야 할 타이밍과 판단 기준 3가지", "loss"),
    ],
    "ai_automation_workflow": [
        ("반복 업무 자동화 전 먼저 정해야 할 3가지", "howto"),
        ("업무 자동화 시작 전에 막히는 이유와 해결 순서", "search"),
        ("n8n vs Zapier, 처음 자동화 도구 고를 때 기준", "comparison"),
        ("AI 자동화 워크플로우 설계, 도구보다 프로세스가 먼저다", "howto"),
        ("반복 업무 자동화 실패하는 이유 3가지", "loss"),
        ("자동화 적합한 업무와 아닌 업무 구분하는 법", "search"),
        ("업무 자동화 파일럿 테스트, 이렇게 하면 오류를 줄인다", "save_time"),
        ("자동화 도구 설치 전에 프로세스 정의가 먼저인 이유", "curiosity"),
        ("직장인 업무 자동화 입문, 처음 자동화할 업무 고르는 기준", "howto"),
        ("AI 자동화 워크플로우, 검수 루프 없이 확대하면 안 되는 이유", "loss"),
    ],
    "ai_model_update": [
        ("새 AI 모델 업데이트, 내 업무가 진짜 달라지는 부분", "search"),
        ("AI 모델 업데이트에서 확인된 것과 아직 추측인 것", "curiosity"),
        ("벤치마크 1위가 내 업무 최고는 아닌 이유", "comparison"),
        ("새 AI 모델, 바꿔야 할 사람과 그대로 둬도 되는 사람", "howto"),
        ("AI 모델 업데이트 전에 요금·제한부터 확인해야 하는 이유", "loss"),
        ("새 모델 나왔을 때 내 업무로 직접 비교하는 법", "howto"),
        ("AI 업데이트 소식, 화려한 데모와 실제 체감의 차이", "curiosity"),
        ("모델 업그레이드, 코딩·요약 작업에서 체감이 다른 이유", "comparison"),
        ("새 AI 모델 발표, 무료로 쓸 수 있는 범위는 어디까지", "search"),
        ("AI 모델 업데이트 후 출력이 달라졌다면 점검할 것", "loss"),
    ],
    "ai_search_change": [
        ("AI 검색 시대, 블로그 글이 인용되려면 필요한 구조", "search"),
        ("AEO·GEO·SGE 차이, 한 번에 정리하기", "howto"),
        ("AI 검색이 떠도 SEO가 끝나지 않는 이유", "curiosity"),
        ("내 글이 AI 답변에 인용되게 만드는 3단계", "howto"),
        ("AI 오버뷰 시대, 조회수를 지키는 글 구조", "loss"),
        ("AI가 인용하는 글과 무시하는 글의 차이", "comparison"),
        ("검색이 AI 답변으로 바뀔 때 블로거가 할 일", "search"),
        ("질문형 제목과 첫 문장 답변이 인용을 좌우하는 이유", "curiosity"),
        ("AI 검색 최적화, 키워드보다 구조가 중요한 이유", "comparison"),
        ("AI 답변엔진에 내 글을 노출시키는 신뢰 신호", "howto"),
    ],
    "ai_blog_growth": [
        ("AI 블로그 자동화에서 조회수를 망치는 글 구조", "loss"),
        ("AI로 글 쓰는데 조회수가 안 느는 진짜 이유", "curiosity"),
        ("AI 블로그, 발행량보다 중요한 검색 의도 충족", "search"),
        ("AI 초안을 그대로 올리면 안 되는 이유와 보완법", "howto"),
        ("AI 블로그 수익화, RPM을 높이는 글 주제 고르는 법", "save_time"),
        ("조회수 낮은 글을 살리는 구조 점검 순서", "howto"),
        ("AI 블로그 자동화, 검수 루프 없이 확대하면 안 되는 이유", "loss"),
        ("비슷한 AI 글 사이에서 내 글을 띄우는 차별화", "comparison"),
        ("AI 블로그 내부 링크 허브, 트래픽이 순환하는 구조", "howto"),
        ("AI 블로그 운영, 적게 써도 트래픽 모으는 기준", "search"),
    ],
    "ai_comparison": [
        ("AI 도구 비교, 절대 승자가 없는 이유와 고르는 법", "comparison"),
        ("ChatGPT·Claude·Gemini, 업무 유형별로 고르는 기준", "comparison"),
        ("AI 요금제 비교, 무료로 충분한 경우와 유료가 필요한 순간", "search"),
        ("AI 도구 둘 중 고민될 때 검수 시간으로 정하는 법", "howto"),
        ("기능 목록 비교가 의미 없는 이유와 진짜 비교 기준", "curiosity"),
        ("AI 모델 비교, 글쓰기와 코딩에서 갈리는 강점", "comparison"),
        ("무료 AI vs 유료 AI, 전환해야 할 타이밍", "loss"),
        ("비슷한 AI 도구 중 내게 맞는 걸 고르는 순서", "howto"),
        ("AI 도구 가격 비교, 공식 페이지부터 확인해야 하는 이유", "search"),
        ("AI 도구 비교표로 보는 무료/유료 경계", "comparison"),
    ],
    "ai_risk_security": [
        ("AI에 회사 자료 넣기 전 꼭 확인할 보안 기준", "loss"),
        ("AI 쓸 때 개인정보·기밀이 새는 흔한 실수", "curiosity"),
        ("AI 환각, 결과를 그대로 믿으면 안 되는 이유", "loss"),
        ("AI 생성물 저작권, 그대로 쓰면 위험한 경우", "howto"),
        ("AI 보안 사고를 막는 입력 단계 규칙 3가지", "howto"),
        ("사내 자료를 AI에 안전하게 쓰는 방법", "search"),
        ("AI 결과 검증, 어떤 것부터 직접 확인해야 하나", "howto"),
        ("AI 리스크, 막연한 공포 대신 지킬 규칙으로", "curiosity"),
        ("AI 쓰기 전 회사 정책에서 확인할 데이터 기준", "loss"),
        ("AI 개인정보·저작권·환각, 한 번에 점검하기", "search"),
    ],
    "ai_beginner_guide": [
        ("AI 처음 쓸 때 뭐부터 시작해야 할까", "search"),
        ("왕초보를 위한 AI 첫 사용, 작은 일부터 맡기기", "howto"),
        ("AI 입문, 무료로 시작하는 순서와 첫 점검표", "howto"),
        ("AI가 처음이라면 알아야 할 기본 용어 쉽게 풀기", "curiosity"),
        ("AI 초보가 자주 하는 실수와 피하는 법", "loss"),
        ("처음 쓰는 AI, 결과가 이상할 때 요청 고치는 법", "howto"),
        ("AI 입문자가 무료로 바로 해볼 수 있는 작업", "save_time"),
        ("AI 초보, 도구를 하나만 정해 익숙해지는 이유", "curiosity"),
        ("AI 첫걸음, 이메일·요약부터 맡겨 보기", "howto"),
        ("초보자용 AI 활용, 결과를 다듬는 기본 습관", "search"),
    ],
    "ai_tool_review": [
        ("직접 써본 AI 도구 후기, 무료로 어디까지 되나", "search"),
        ("이 AI 도구, 이런 사람에게 맞고 이런 사람은 패스", "curiosity"),
        ("AI 도구 고를 때 기능 목록보다 먼저 봐야 할 것", "howto"),
        ("무료 AI 도구로 충분한 경우와 유료가 필요한 순간", "comparison"),
        ("광고 후기 말고, 내 업무로 검증한 AI 도구 판단 기준", "loss"),
        ("AI 도구 무료/유료 경계, 가격표로 한눈에 보기", "comparison"),
        ("써보기 전에 알았으면 좋았을 AI 도구 한계", "curiosity"),
        ("AI 도구 도입 전 무료로 먼저 테스트하는 순서", "howto"),
        ("비슷한 AI 도구 중 내게 맞는 걸 고르는 법", "search"),
        ("AI 도구 리뷰, 별점보다 중요한 실제 사용 기준", "curiosity"),
    ],
    "ai_prompt_recipe": [
        ("복사해서 쓰는 ChatGPT 보고서 프롬프트, 값만 바꾸면 끝", "howto"),
        ("좋은 프롬프트는 길이가 아니라 구조에서 나온다", "curiosity"),
        ("프롬프트가 매번 달라 결과가 들쭉날쭉할 때 고정할 것", "loss"),
        ("ChatGPT 프롬프트, 매번 새로 쓰지 말고 템플릿으로 굳히는 법", "save_time"),
        ("보고서 초안용 프롬프트, 역할·목적·출력 형식부터 정하기", "howto"),
        ("AI에게 요약 시킬 때 결과 품질을 정하는 프롬프트 한 줄", "curiosity"),
        ("프롬프트 잘 쓰는 법, 예시보다 출력 형식을 먼저 지정하라", "howto"),
        ("업무용 프롬프트 템플릿, 복사해서 바로 쓰는 기본 양식", "search"),
        ("AI 결과물이 매번 다른 이유와 프롬프트로 고정하는 법", "search"),
        ("프롬프트 한 줄 차이로 보고서 초안 품질이 달라지는 이유", "curiosity"),
    ],
    "delivery_money_checklist": [
        ("배달앱 결제 전 확인할 배달비·쿠폰·최소주문금액 3가지", "howto"),
        ("배달앱 주문 전 최종금액이 달라지는 이유와 확인 순서", "search"),
        ("배달비 무료인데 왜 결제금액이 많이 나왔을까", "curiosity"),
        ("배달의민족·쿠팡이츠 결제 전 먼저 볼 쿠폰 조건", "howto"),
        ("배달앱 쿠폰 있는데 적용 안 될 때 먼저 확인할 것", "loss"),
        ("배달비 절약하는 법, 쿠폰보다 먼저 확인해야 할 조건", "save_time"),
        ("배달앱별 같은 가게 최종금액이 다른 이유", "comparison"),
        ("배달앱 구독권, 실제로 이득 되는 조건과 아닌 경우", "comparison"),
        ("최소주문금액 조건, 배달앱마다 다른 이유와 확인법", "search"),
        ("배달앱 주문 후 후회 줄이는 결제 전 3단계 체크", "howto"),
    ],
    "corporate_issue_decode": [
        # discovery 후보의 entity가 동적으로 채워지므로 generic template은 placeholder 역할
        # _generate_dynamic_candidates에서 entity를 prefix로 실제 제목 생성
        ("오늘 발표된 기업 이슈, 소비자와 투자자가 궁금해할 3가지", "search"),
        ("기업 공식 입장 후 사람들이 가장 궁금해한 포인트", "curiosity"),
        ("기업 이슈, 공식 발표와 외부 추측을 구분하는 기준", "howto"),
        ("기업 노사 협상 이슈, 소비자에게 어떤 영향이 있을까", "search"),
        ("이번 기업 이슈가 일반 이용자에게 미치는 실제 영향", "curiosity"),
        ("기업 공시·공식 입장, 어디서 직접 확인해야 할까", "howto"),
    ],
}


_GENERAL_LIFE_POLICY_PHRASES = ("신청 전", "대상 조건", "환급", "지원금")


class TitleCandidateService:
    """골든 패턴 기반 제목 후보 10개를 생성하고 CTR 예상 점수로 평가한다."""

    def generate_candidates(
        self,
        topic: str,
        content_type: str = "",
        topic_group: str = "",
        pattern_id: str = "",
        candidate_raw: dict | None = None,
    ) -> dict[str, Any]:
        """제목 후보 목록과 최적 제목을 반환한다."""
        raw = candidate_raw or {}

        # pattern_id 기반 공식 제목 로드 (없으면 topic 기반 동적 생성)
        templates = _PATTERN_TITLE_TEMPLATES.get(pattern_id, [])
        candidates: list[dict[str, Any]] = []

        # search_demand_topic / hook_angle 기반 제목을 먼저 생성한다.
        # 패턴 템플릿은 안전하지만 실제 주제 고유명사를 놓칠 수 있어, 최종 H1에
        # 쓰일 후보는 독자 검색어와 클릭 이유를 반영한 제목을 우선 포함한다.
        contextual_titles = _build_contextual_hook_titles(
            topic=topic,
            content_type=content_type,
            topic_group=topic_group,
            pattern_id=pattern_id,
            raw=raw,
        )
        for title, title_type in contextual_titles:
            scored = self.score_title(title, content_type=content_type, topic_group=topic_group, pattern_id=pattern_id)
            bonus = _contextual_hook_bonus(title, raw, pattern_id)
            scored["ctr_score"] = min(100, scored["ctr_score"] + bonus)
            candidates.append({
                "title": title,
                "title_type": title_type,
                "ctr_score": scored["ctr_score"],
                "risk_score": scored["risk_score"],
                "promise_match_score": scored["promise_match_score"],
                "is_allowed": scored["is_allowed"],
                "blocking_issues": scored["blocking_issues"],
                "reason": f"{scored['reason']} + contextual_bonus={bonus}",
            })

        seen_titles = {c["title"] for c in candidates}

        # discovery_engine 후보면 entity 기반 entity-specific title을 우선 생성
        if bool(raw.get("discovery_engine")):
            entity_specific = _build_entity_specific_titles(
                topic=topic,
                entities=list(raw.get("entities") or []),
                entity_types=list(raw.get("entity_types") or []),
                content_type=content_type,
                pattern_id=pattern_id,
            )
            for title, title_type in entity_specific:
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                scored = self.score_title(title, content_type=content_type, topic_group=topic_group, pattern_id=pattern_id)
                # discovery 후보는 entity 보존이 우선 — risk score 약간 완화 안전 제목
                candidates.append({
                    "title": title,
                    "title_type": title_type,
                    "ctr_score": scored["ctr_score"],
                    "risk_score": scored["risk_score"],
                    "promise_match_score": scored["promise_match_score"],
                    "is_allowed": scored["is_allowed"],
                    "blocking_issues": scored["blocking_issues"],
                    "reason": scored["reason"],
                })

        for title, title_type in templates:
            if title in seen_titles:
                continue
            seen_titles.add(title)
            scored = self.score_title(title, content_type=content_type, topic_group=topic_group, pattern_id=pattern_id)
            candidates.append({
                "title": title,
                "title_type": title_type,
                "ctr_score": scored["ctr_score"],
                "risk_score": scored["risk_score"],
                "promise_match_score": scored["promise_match_score"],
                "is_allowed": scored["is_allowed"],
                "blocking_issues": scored["blocking_issues"],
                "reason": scored["reason"],
            })

        # 공식 제목이 부족하면 topic 기반으로 동적 보완
        if len(candidates) < 8:
            dynamic = self._generate_dynamic_candidates(
                topic=topic,
                content_type=content_type,
                topic_group=topic_group,
                pattern_id=pattern_id,
                existing_count=len(candidates),
            )
            for t in dynamic:
                if t["title"] in seen_titles:
                    continue
                seen_titles.add(t["title"])
                scored = self.score_title(t["title"], content_type=content_type, topic_group=topic_group, pattern_id=pattern_id)
                candidates.append({
                    "title": t["title"],
                    "title_type": t["title_type"],
                    "ctr_score": scored["ctr_score"],
                    "risk_score": scored["risk_score"],
                    "promise_match_score": scored["promise_match_score"],
                    "is_allowed": scored["is_allowed"],
                    "blocking_issues": scored["blocking_issues"],
                    "reason": scored["reason"],
                })

        allowed = [c for c in candidates if c["is_allowed"]]
        blocked = [c for c in candidates if not c["is_allowed"]]

        # search_demand_topic 핵심 키워드 추출 (제목 구체성 우선 선택용)
        _search_topic = str(raw.get("search_demand_topic") or topic)
        _topic_kws = _extract_topic_keywords(_search_topic, pattern_id)
        best = self.select_best_title(allowed, topic_keywords=_topic_kws) if allowed else {}

        logger.info(
            "%s | pattern=%s topic=%s candidates=%d allowed=%d best=%s",
            __name__, pattern_id, topic[:40], len(candidates), len(allowed),
            best.get("title", "")[:40],
        )

        return {
            "topic": topic,
            "primary_title": best.get("title", topic),
            "candidates": candidates,
            "best_title": best,
            "blocked_titles": blocked,
            "topic_keywords": _topic_kws,
            "selected_title_specificity_score": best.get("specificity_score", 0),
            "selected_title_keyword_coverage": best.get("selected_title_keyword_coverage", 0),
        }

    def score_title(
        self,
        title: str,
        content_type: str = "",
        topic_group: str = "",
        pattern_id: str = "",
    ) -> dict[str, Any]:
        """단일 제목의 CTR/risk/promise_match 점수를 반환한다."""
        blocking: list[str] = []
        title_lower = title.lower()

        # ── 금지어 검사 ──
        for phrase in _BLOCKED_PHRASES:
            if phrase in title:
                blocking.append(f"blocked_phrase:{phrase}")
        if content_type == "viral_issue_decode" or topic_group in {"entertainment_sports", "ott_platform", "fandom_consumer"}:
            for phrase in _VIRAL_EXTRA_BLOCK:
                if phrase in title:
                    blocking.append(f"viral_blocked_phrase:{phrase}")
        if content_type == "general_life":
            for phrase in _GENERAL_LIFE_POLICY_PHRASES:
                if phrase in title:
                    blocking.append(f"general_life_policy_phrase:{phrase}")

        # ── pattern 크로스오버 금지어 ──
        for forbidden in _PATTERN_FORBIDDEN_CROSSOVER.get(pattern_id, []):
            if forbidden in title:
                blocking.append(f"pattern_crossover:{forbidden}")
        for pattern in _MALFORMED_TITLE_PATTERNS:
            if re.search(pattern, title):
                blocking.append("malformed_title_phrase")
                break
        if _has_bad_subject_particle(title):
            blocking.append("bad_subject_particle")
        if (
            (content_type == "viral_issue_decode" or pattern_id == "viral_ott_reaction_decode")
            and "평점보다 먼저 볼 포인트" in title
        ):
            blocking.append("low_value_viral_rating_title")
        integrity = audit_title_integrity(
            title,
            content_type=content_type,
            topic_group=topic_group,
            pattern_id=pattern_id,
        )
        for issue in integrity.get("blocking_issues", []):
            if str(issue).startswith("source_series_name_leaked:"):
                blocking.append("malformed_title_phrase")
            elif issue in {
                "source_series_prefix_visible",
                "duplicated_confirm_before",
                "orphan_confirm_particle",
                "orphan_function_particle",
                "malformed_reaction_phrase",
                "empty_seen_object_particle",
                "policy_faq_heading_leak",
            }:
                blocking.append("malformed_title_phrase")
            elif str(issue).startswith("broken_title_phrase:"):
                blocking.append("malformed_title_phrase")
            elif issue == "bad_subject_particle":
                blocking.append("bad_subject_particle")
            elif issue == "low_value_viral_rating_title":
                blocking.append("low_value_viral_rating_title")
            elif issue == "telecom_plan_topic_using_viral_reaction_template":
                blocking.append("pattern_crossover:telecom_plan")
        blocking = list(dict.fromkeys(blocking))

        is_allowed = not blocking

        # ── CTR score (0~100) ──
        ctr = 50  # base

        # 길이 보너스 (20~42자 최적)
        length = len(title)
        if 20 <= length <= 42:
            ctr += 10
        elif length < 15 or length > 55:
            ctr -= 10
        elif length > 45:
            ctr -= 5

        # 좋은 신호 가산
        for signal in _GOOD_SIGNALS:
            if signal in title:
                ctr += 5
                break  # 첫 히트만

        # 숫자 포함
        if re.search(r"\d", title):
            ctr += 8

        # 구체 명사 (pattern 핵심 키워드)
        kw_hits = sum(1 for kw in _PATTERN_REQUIRED_KEYWORDS.get(pattern_id, []) if kw in title)
        ctr += min(15, kw_hits * 5)

        # 과장어 감점 (일반)
        for phrase in ("무조건", "반드시", "절대", "역대급", "충격"):
            if phrase in title:
                ctr -= 8

        # tax_refund 전용 과장 표현 감점
        if pattern_id == "tax_refund_hometax_check":
            for phrase in ("0원으로 보입니다", "못 받습니다", "사라집니다", "꼭", "무조건"):
                if phrase in title:
                    ctr -= 10

        # AI 패턴 전용 과장 표현 감점
        if pattern_id in _AI_PATTERN_IDS:
            for phrase in ("대박", "끝판왕", "인생이 바뀐다", "돈 복사", "자동수익", "충격"):
                if phrase in title:
                    ctr -= 15
            # 매일 반복되는 "먼저 볼/확인할 N가지"류 정형구 — 사람이 쓴 제목처럼 읽히지 않는다는
            # 지적을 반영해 강하게 감점(다른 후보가 있으면 확실히 밀려나도록).
            if re.search(r"먼저\s*(볼|확인할|정할|해야)\s*(\d+\s*가지|것)", title):
                ctr -= 30

        # 단어 반복 감점
        words = re.split(r"[\s,·\-]+", title)
        if len(words) != len(set(words)):
            ctr -= 5

        # 금지어 포함 시 CTR 0
        if not is_allowed:
            ctr = 0

        ctr = max(0, min(100, ctr))

        # ── risk score (0=안전 ~100=위험) ──
        risk = 0
        for phrase in _BLOCKED_PHRASES:
            if phrase in title:
                risk += 30
        for phrase in _VIRAL_EXTRA_BLOCK:
            if phrase in title:
                risk += 20
        risk = min(100, risk)

        # ── promise_match_score (0~100) ──
        pms = 70  # base
        if pattern_id:
            match_kws = _PATTERN_REQUIRED_KEYWORDS.get(pattern_id, [])
            pms += min(20, sum(5 for kw in match_kws if kw in title))
            # 크로스오버 감점
            cross_hits = sum(1 for kw in _PATTERN_FORBIDDEN_CROSSOVER.get(pattern_id, []) if kw in title)
            pms -= cross_hits * 20
        if pattern_id == "tax_refund_hometax_check":
            for phrase in ("0원으로 보입니다", "못 받습니다", "사라집니다"):
                if phrase in title:
                    pms -= 15
        if pattern_id in _AI_PATTERN_IDS:
            for phrase in ("대박", "끝판왕", "인생이 바뀐다", "돈 복사", "자동수익"):
                if phrase in title:
                    pms -= 20
        pms = max(0, min(100, pms))

        reason = (
            f"ctr={ctr} risk={risk} pms={pms}"
            + (f" | blocked: {blocking[0]}" if blocking else "")
        )

        return {
            "ctr_score": ctr,
            "risk_score": risk,
            "promise_match_score": pms,
            "is_allowed": is_allowed,
            "blocking_issues": blocking,
            "reason": reason,
        }

    def select_best_title(
        self,
        candidates: list[dict],
        topic_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """허용된 후보 중 최적 제목을 선택한다.

        선택 기준: is_allowed=true, specificity_score 우선, ctr_score, risk_score 낮음
        topic_keywords가 있으면 해당 키워드 포함 제목을 우선 선택한다.
        """
        if not candidates:
            return {}
        allowed = [c for c in candidates if c.get("is_allowed")]
        if not allowed:
            return {}
        kws = [k.lower() for k in (topic_keywords or [])]
        for c in allowed:
            title_lower = c.get("title", "").lower()
            c["specificity_score"] = sum(1 for k in kws if k in title_lower)
            c["selected_title_keyword_coverage"] = c["specificity_score"]
        return sorted(
            allowed,
            key=lambda c: (
                -c.get("specificity_score", 0),   # 구체적 키워드 포함 우선
                -c.get("ctr_score", 0),
                c.get("risk_score", 100),
                -c.get("promise_match_score", 0),
            ),
        )[0]

    def validate_title(
        self, title: str, content_type: str = ""
    ) -> dict[str, Any]:
        """제목의 발행 가능 여부를 검사한다."""
        scored = self.score_title(title, content_type=content_type)
        return {
            "title": title,
            "is_valid": scored["is_allowed"],
            "ctr_score": scored["ctr_score"],
            "risk_score": scored["risk_score"],
            "promise_match_score": scored["promise_match_score"],
            "blocking_issues": scored["blocking_issues"],
        }

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generate_dynamic_candidates(
        *,
        topic: str,
        content_type: str,
        topic_group: str,
        pattern_id: str,
        existing_count: int,
    ) -> list[dict[str, str]]:
        """pattern_id 공식 제목이 부족할 때 topic 기반으로 동적 보완한다."""
        needed = max(0, 8 - existing_count)
        if needed <= 0:
            return []
        core = _contextual_title_core(topic) or topic
        short_core = _truncate_contextual_text(core, 30)

        base_templates: list[tuple[str, str]] = [  # type: ignore[assignment]
            (f"{core} — 먼저 확인할 3가지", "search"),
            (f"{short_core}을 제대로 이해하는 방법", "howto"),
            (f"{short_core} 전에 먼저 볼 것", "howto"),
            (f"{short_core}, 놓치면 손해인 이유", "loss"),
            (f"{short_core} 바로 확인하는 순서", "save_time"),
            (f"{short_core}이 헷갈리는 이유와 기준", "curiosity"),
            (f"{short_core} 한 줄 정리", "safe"),
            (f"{short_core} 체크리스트", "search"),
        ]
        return [{"title": t, "title_type": tt} for t, tt in base_templates[:needed]]


# ------------------------------------------------------------------ #
# 모듈 헬퍼                                                            #
# ------------------------------------------------------------------ #

_CONTEXTUAL_TITLE_MAX_LEN = 45
# core가 길이 제한으로 잘릴 때 끝에 남으면 문장이 조각나는 토큰들.
# 관형형 어미(미치는/주는/하는 등)는 뒤에 수식할 명사가 잘려나간 상태라
# "…에 미치는, 시간이 줄지 않는 이유"처럼 비문이 된다 — 함께 제거한다.
_BAD_CONTEXTUAL_TAIL_TOKENS = {
    "vs", "vs.", "전", "때", "및", "과", "와", "의", "로",
    "미치는", "주는", "하는", "되는", "대한", "관한", "위한", "따른", "향한",
}

_CONTEXTUAL_SUFFIX_PATTERNS: tuple[tuple[str, str], ...] = (
    # 시드 topic 자체에 "…5가지"/"…3단계"처럼 개수가 이미 붙어 있으면, 뒤에 다른
    # 제목 템플릿을 이어붙일 때 "…5가지 써도 일이 줄지 않는 이유"처럼 어색한
    # 문장이 된다. core로 쓰기 전에 미리 잘라낸다.
    (r"\s*\d+\s*(가지|단계|개)$", ""),
    (r"\s*(켜기|쓰기|사용하기|신청하기)?\s*전(?:에)?\s*(먼저\s*)?(확인할|볼)\s*(설정|조건|항목|것|체크리스트)?$", ""),
    (r"^직장인이\s+(.+?)로\s+업무\s*시간을\s*줄이는\s*방법$", r"직장인 \1"),
    (r"\s*로\s*업무\s*시간을\s*줄이는\s*방법$", ""),
    (r"\s*업무\s*시간을\s*줄이는\s*방법$", ""),
    (r"\s*업무용\s*선택\s*기준$", " 업무용 선택"),
    (r"\s*수익화\s*목적\s*비교$", " 수익화 비교"),
    (r"\s*설계\s*방법$", " 설계"),
    (r"\s*체크리스트$", ""),
    (r"\s*(방법|기준|정리|가이드|확인|조회)$", ""),
)


def _build_contextual_hook_titles(
    *,
    topic: str,
    content_type: str,
    topic_group: str,
    pattern_id: str,
    raw: dict[str, Any],
) -> list[tuple[str, str]]:
    """실제 검색 수요/후킹 키워드 기반 제목 후보를 만든다.

    고정 패턴 제목은 안전하지만 특정 이슈명이나 검색어가 빠질 수 있다. 이 후보들은
    article_candidate의 H1/title에 쓰일 수 있도록 topic 고유명사와 후킹 공식을 함께
    담는 데 목적이 있다.
    """
    seeds = _contextual_title_seeds(topic=topic, raw=raw)
    if not seeds:
        return []

    _search_angle = raw.get("search_angle", {}) if isinstance(raw.get("search_angle"), dict) else {}
    templates = _contextual_title_templates(
        content_type=content_type,
        topic_group=topic_group,
        pattern_id=pattern_id,
        angle_type=str(_search_angle.get("angle_type") or raw.get("angle_type") or ""),
    )
    titles: list[tuple[str, str]] = []
    seen: set[str] = set()
    for seed in seeds:
        core = _contextual_title_core(seed)
        if not core:
            continue
        seed_templates = _seed_specific_contextual_templates(
            seed=seed,
            content_type=content_type,
            topic_group=topic_group,
            pattern_id=pattern_id,
        )
        for title_type, template in seed_templates + templates:
            title = _format_contextual_title(core, template)
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            titles.append((title, title_type))
            if len(titles) >= 5:
                return titles
    return titles


def _seed_specific_contextual_templates(
    *,
    seed: str,
    content_type: str,
    topic_group: str,
    pattern_id: str,
) -> list[tuple[str, str]]:
    compact = (seed or "").replace(" ", "")
    if pattern_id == "ai_tool_comparison" and re.search(r"\bvs\.?\b", seed, flags=re.IGNORECASE):
        return [
            ("comparison", "{core}, 고를 때 볼 기준 3가지"),
            ("comparison", "{core}, 업무용 선택 기준"),
        ]
    if (
        (pattern_id == "ai_work_time_savings" or content_type == "ai_work_tip" or topic_group == "ai_work")
        and "설정" in compact
        and ("켜기" in compact or "AI기능" in compact or "기능" in compact)
    ):
        # "켜기/확인할"은 제목 골격어일 뿐 본문 산문에는 거의 안 나와
        # title_body_entity_mismatch 게이트에 걸린다. 본문에 실제로 존재하는
        # 명사(설정 등) 중심으로 구성하고, 나머지는 게이트 stop-token(먼저 등)만 쓴다.
        return [
            ("setting", "{core} 설정 3가지"),
            ("setting", "{core}, 먼저 볼 설정 3가지"),
        ]
    return []


def _contextual_title_templates(
    *,
    content_type: str,
    topic_group: str,
    pattern_id: str,
    angle_type: str = "",
) -> list[tuple[str, str]]:
    if pattern_id == "tax_refund_hometax_check" or content_type == "tax_refund":
        return [
            ("search", "{core} 조회 전 먼저 볼 3가지"),
            ("loss", "{core} 안 들어올 때 먼저 확인할 원인"),
            ("howto", "{core}, 홈택스에서 먼저 확인할 것"),
        ]
    if pattern_id == "viral_ott_reaction_decode" or content_type == "viral_issue_decode":
        return [
            ("viral", "{core} 반응이 갈린 이유, 먼저 볼 3가지"),
            ("curiosity", "{core} 호불호가 갈린 진짜 이유"),
            ("search", "{core}, 보기 전 먼저 확인할 반응 포인트"),
        ]
    if pattern_id == "ai_tool_comparison":
        return [
            ("comparison", "{core}, 기능표보다 중요한 선택 기준"),
            ("howto", "{core}, 업무별로 갈리는 이유"),
            ("loss", "{core} 바꾸기 전 놓치면 손해인 것"),
        ]
    if pattern_id == "ai_automation_workflow":
        return [
            ("howto", "{core}, 처음 막히는 이유와 해결 순서"),
            ("reason", "{core}가 자꾸 실패하는 이유"),
            ("loss", "{core} 실패 전에 확인할 기준"),
        ]
    if pattern_id == "ai_work_time_savings" or content_type == "ai_work_tip" or topic_group == "ai_work":
        # 앵글별 프레임(2026-07-10): pricing/발표/규제 사건까지 전부 ai_work로 모이는데
        # 하나의 "반복 업무/시간 단축" 틀만 쓰면 피드가 같은 제목으로 도배된다(라이브 실측:
        # 발행 5건 제목이 전부 같은 계열). 제목 어휘는 title_body_entity_mismatch 게이트의
        # stop-token(확인된/것/조건/정리/기준/먼저 등) 위주로 구성해 본문에 없는 명사를
        # 새로 만들지 않는다 — "켜기/확인할" 사건(PR #28)의 교훈.
        if angle_type == "money_compare":
            return [
                ("save_money", "{core}, 무료 기준 먼저 확인"),
                ("loss", "{core}, 놓치면 더 내는 조건"),
                ("search", "{core} 조건, 먼저 볼 3가지"),
            ]
        if angle_type in {"ai_service_change", "ai_policy_impact"}:
            return [
                ("search", "{core}, 확인된 것 먼저 정리"),
                ("howto", "{core} 핵심 포인트 3가지"),
            ]
        return [
            ("reason", "{core}, 왜 오히려 시간이 더 걸릴까"),
            ("howto", "{core}, 반복 업무부터 맡겨야 하는 이유"),
            # "{core} 써도"는 core가 도구명(ChatGPT 등)일 때만 자연스럽고, core가
            # "AI 업무 자동화 처음 버릴 반복 작업"처럼 긴 구절이면 "써도"가 붙을
            # 자리가 없어 어색해진다. "써도" 없이도 성립하도록 수정.
            ("loss", "{core}, 시간이 줄지 않는 이유"),
        ]
    if pattern_id == "delivery_money_checklist" or content_type == "money_checklist":
        return [
            ("howto", "{core}, 결제 전 먼저 볼 3가지"),
            ("curiosity", "{core}, 최종금액이 달라지는 이유"),
            ("loss", "{core}, 놓치면 더 내는 조건"),
        ]
    if topic_group == "policy_benefit" or content_type in {"policy_deadline", "policy_benefit"}:
        return [
            ("howto", "{core}, 신청 전 먼저 볼 3가지"),
            ("deadline", "{core}, 마감 전에 확인할 조건"),
            ("search", "{core} 대상 조건과 신청 방법"),
        ]
    if topic_group == "platform_issue" or content_type == "platform_change":
        return [
            ("search", "{core}, 기존 이용자가 먼저 볼 3가지"),
            ("howto", "{core} 변경 전 확인할 조건"),
            ("curiosity", "{core}, 뭐가 달라지는지 보는 기준"),
        ]
    if topic_group == "privacy_security":
        return [
            ("howto", "{core}, 비밀번호부터 확인할 것"),
            ("search", "{core}, 같은 비밀번호 쓴 계정도 봐야 할까"),
            ("loss", "{core}, 피싱 문자 전에 확인할 3가지"),
        ]
    if topic_group == "refund_consumer" or content_type == "consumer_warning":
        return [
            ("loss", "{core}, 기다리기 전 먼저 남길 증거"),
            ("howto", "{core}, 소비자가 먼저 확인할 3가지"),
            ("search", "{core} 대응 전 확인할 기록"),
        ]
    return [
        ("search", "{core}, 헷갈리는 기준 정리"),
        ("curiosity", "{core}이 헷갈리는 이유와 기준"),
        ("howto", "{core}, 실제로는 무엇이 다른가"),
    ]


def _contextual_title_seeds(*, topic: str, raw: dict[str, Any]) -> list[str]:
    search_angle = raw.get("search_angle", {}) if isinstance(raw.get("search_angle"), dict) else {}
    hook_angle = raw.get("hook_angle", {}) if isinstance(raw.get("hook_angle"), dict) else {}

    public_benefit_keyword = str(raw.get("public_benefit_keyword") or search_angle.get("public_benefit_keyword") or "")
    raw_values = [
        public_benefit_keyword,
        search_angle.get("search_demand_topic"),
        raw.get("search_demand_topic"),
        hook_angle.get("safe_title_keyword"),
        raw.get("source_title"),
        topic,
    ]

    seeds: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        normalized = _normalize_contextual_seed(str(value or ""))
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        seeds.append(normalized)
    return seeds


def _normalize_contextual_seed(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"\([^)]*(?:단독|속보|종합|영상|인터뷰)[^)]*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.-:;!?\"'")
    for phrase in _BLOCKED_PHRASES:
        text = text.replace(phrase, "")
    text = re.sub(r"\s+", " ", text).strip(" ,.-:;!?\"'")
    if len(text) < 2 or text.startswith("http"):
        return ""
    return text


def _contextual_title_core(seed: str) -> str:
    core = " ".join((seed or "").split()).strip(" ,.-:;!?")
    if not core:
        return ""
    core = re.split(r"\s+[|\-]\s+", core)[0].strip(" ,.-:;!?")
    for pattern, replacement in _CONTEXTUAL_SUFFIX_PATTERNS:
        core = re.sub(pattern, replacement, core).strip(" ,.-:;!?")
    core = re.sub(r"\s+", " ", core)
    vs_match = re.search(r"([A-Za-z0-9가-힣]+)\s+vs\.?\s+([A-Za-z0-9가-힣]+)", core, flags=re.IGNORECASE)
    if vs_match:
        pair = f"{vs_match.group(1)} vs {vs_match.group(2)}"
        if all(token in core for token in ("AI", "도구", "비교")):
            return f"AI 도구 비교 {pair}"
        return pair
    return _trim_contextual_tail(_truncate_contextual_text(core, 24))


def _format_contextual_title(core: str, template: str) -> str:
    for limit in (30, 28, 24, 22, 18, 14, 10):
        short_core = _truncate_contextual_text(core, limit)
        title = " ".join(template.format(core=short_core).split()).strip(" ,.-")
        if len(title) <= _CONTEXTUAL_TITLE_MAX_LEN and _looks_complete_contextual_title(title):
            return title
    return ""


def _looks_complete_contextual_title(title: str) -> bool:
    if not title:
        return False
    if any(phrase in title for phrase in _BLOCKED_PHRASES):
        return False
    last = title.split()[-1].strip(" ,.-")
    return len(last) > 1 and last not in {"전", "때", "및", "과", "와", "의"}


def _truncate_contextual_text(text: str, max_len: int) -> str:
    compact = " ".join((text or "").split()).strip(" ,.-")
    if len(compact) <= max_len:
        return compact
    tokens = compact.split()
    output: list[str] = []
    for token in tokens:
        candidate = " ".join(output + [token])
        if len(candidate) > max_len:
            break
        output.append(token)
    if output:
        return _trim_contextual_tail(" ".join(output).strip(" ,.-"))
    return _trim_contextual_tail(compact[:max_len].rstrip(" ,.-"))


def _trim_contextual_tail(text: str) -> str:
    parts = text.split()
    trimmed = False
    while parts and parts[-1].strip(" ,.-").lower() in _BAD_CONTEXTUAL_TAIL_TOKENS:
        parts.pop()
        trimmed = True
    # 관형형을 걷어낸 뒤 끝 단어에 부사격 조사가 매달려 있으면
    # ("…직장인 업무에") 조사만 떼어 명사로 끝나게 한다.
    if parts:
        last = parts[-1]
        stripped = re.sub(r"(에서|에게|으로|까지|부터|에)$", "", last)
        if stripped and stripped != last and len(stripped) >= 2:
            parts[-1] = stripped
            trimmed = True
    # 문장이 중간에서 잘린 경우("구글 AI 검색 변화가 직장인 업무") 주격 조사
    # 뒤에 서술어가 없어 비문이 된다 — 마지막 주어 경계까지 되돌리고 조사를
    # 떼어 온전한 명사구("구글 AI 검색 변화")로 끝낸다. 잘림이 실제로 일어난
    # 경우에만 적용해 멀쩡한 core를 건드리지 않는다.
    if trimmed and len(parts) >= 2:
        for i in range(len(parts) - 1, -1, -1):
            token = parts[i]
            if len(token) >= 3 and re.search(r"[가-힣](가|이)$", token):
                parts = parts[: i + 1]
                parts[-1] = token[:-1]
                break
    return " ".join(parts).strip(" ,.-")


def _has_bad_subject_particle(title: str) -> bool:
    for match in re.finditer(r"(?:^|\s)([가-힣A-Za-z0-9·]{2,})가(?=\s|,|$)", title or ""):
        stem = match.group(1)
        if _has_korean_final_consonant(stem[-1]):
            return True
    return False


def _has_korean_final_consonant(ch: str) -> bool:
    code = ord(ch)
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def _contextual_hook_bonus(title: str, raw: dict[str, Any], pattern_id: str) -> int:
    search_angle = raw.get("search_angle", {}) if isinstance(raw.get("search_angle"), dict) else {}
    search_topic = str(
        search_angle.get("search_demand_topic")
        or raw.get("search_demand_topic")
        or raw.get("source_title")
        or ""
    )
    keywords = _extract_topic_keywords(search_topic, pattern_id) if search_topic else []
    title_lower = title.lower()
    coverage = sum(1 for kw in keywords if kw.lower() in title_lower)

    bonus = min(12, coverage * 3)
    if any(token in title for token in ("이유", "손해", "갈린", "달라지는", "막히는", "안 들어", "줄지 않는")):
        bonus += 5
    if any(token in title for token in ("먼저", "확인", "체크", "기준", "순서", "방법", "3가지")):
        bonus += 5
    if re.search(r"\d", title):
        bonus += 3
    return min(22, bonus)


_SPECIFICITY_KEYWORDS: dict[str, list[str]] = {
    "tax_refund_hometax_check": ["종합소득세", "연말정산", "국세환급금", "미수령", "손택스"],
    "viral_ott_reaction_decode": ["넷플릭스", "티빙", "웨이브", "디즈니플러스"],
    "ai_work_time_savings": ["ChatGPT", "챗GPT", "생산성", "검수"],
    "ai_tool_comparison": ["ChatGPT", "Claude", "Copilot", "비교", "업무용"],
    "ai_automation_workflow": ["자동화", "워크플로우", "n8n", "Zapier", "프로세스"],
    "delivery_money_checklist": ["배달의민족", "쿠팡이츠", "요기요", "배달비", "쿠폰", "최소주문"],
}

_KOREAN_PARTICLE_SUFFIXES: tuple[str, ...] = (
    "으로도", "로도", "에서", "에게", "부터", "까지", "으로", "은", "는",
    "이", "가", "을", "를", "로", "도",
)

_GENERIC_TOPIC_KEYWORDS: frozenset[str] = frozenset({
    "전에",
    "전",
    "후",
    "확인할",
    "확인",
    "것",
    "먼저",
    "보기",
    "볼",
    "방법",
    "기준",
    "정리",
    "체크",
})


def _extract_topic_keywords(search_topic: str, pattern_id: str) -> list[str]:
    """search_demand_topic과 pattern_id에서 핵심 키워드를 추출한다."""
    kws: list[str] = []
    # pattern별 구체성 키워드 우선
    for kw in _SPECIFICITY_KEYWORDS.get(pattern_id, []):
        if kw in search_topic:
            kws.append(kw)
    # 추가로 topic에서 의미 있는 명사 추출 (간단 규칙)
    for token in re.split(r'[\s,·\-/]+', search_topic):
        normalized = _normalize_topic_keyword_token(token)
        if normalized in _GENERIC_TOPIC_KEYWORDS:
            continue
        if len(normalized) >= 2 and normalized not in kws:
            kws.append(normalized)
    return kws[:6]


def _normalize_topic_keyword_token(token: str) -> str:
    normalized = token.strip(" ,.-:;!?\"'")
    if not normalized:
        return ""
    for suffix in _KOREAN_PARTICLE_SUFFIXES:
        if len(normalized) > len(suffix) + 1 and normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized.strip(" ,.-:;!?\"'")


def _build_entity_specific_titles(
    *,
    topic: str,
    entities: list[str],
    entity_types: list[str],
    content_type: str,
    pattern_id: str,
) -> list[tuple[str, str]]:
    """discovery 후보의 entity로 entity-specific 제목 5개 생성.

    제목에 entity가 반드시 포함되어 title_has_specific_entity gate 통과.
    """
    strong_types = {"platform", "agency", "telecom", "card", "acronym"}
    # primary entity = 첫 strong entity
    primary = next(
        (e for e, t in zip(entities, entity_types) if t in strong_types),
        entities[0] if entities else None,
    )
    if not primary:
        return []

    titles: list[tuple[str, str]] = []

    if content_type == "viral_issue_decode" or pattern_id == "corporate_issue_decode":
        titles.extend([
            (f"{primary} 이슈, 소비자와 투자자가 궁금해할 3가지", "search"),
            (f"{primary} 오늘 발표/공식 입장, 사람들이 가장 궁금해한 포인트", "curiosity"),
            (f"{primary} 이슈 — 공식 발표와 외부 추측을 구분하는 기준", "howto"),
            (f"{primary} 노사·공시·발표 이슈, 일반 이용자에 미치는 실제 영향", "search"),
            (f"{primary} 이슈가 후속 발표까지 추적해야 하는 이유", "curiosity"),
        ])
    elif content_type == "platform_change" or pattern_id == "platform_change_service_update":
        titles.extend([
            (f"{primary} 서비스 변경, 기존 이용자에게 뭐가 달라질까", "search"),
            (f"{primary} 변경 안내, 적용 일자 전 확인할 3가지", "howto"),
            (f"{primary} 약관·요금 변경, 자동결제와 환불 기준은", "search"),
            (f"{primary} 정책 변경 후 이용자가 먼저 점검할 항목", "howto"),
            (f"{primary} 서비스 변경, 기존 사용자 예외는 어떻게 되나", "curiosity"),
        ])
    elif content_type == "consumer_warning":
        titles.extend([
            (f"{primary} 관련 소비자 피해 사례, 먼저 확인할 증거 3가지", "howto"),
            (f"{primary} 이슈, 환불·보상 가능 여부와 신고 절차", "search"),
            (f"{primary} 피해 의심 시 직접 남겨야 할 기록", "howto"),
            (f"{primary} 관련 공식 안내와 소비자 보호 기준", "search"),
        ])
    elif content_type in ("policy_deadline", "policy_benefit"):
        titles.extend([
            (f"{primary} 발표 정책, 대상자가 먼저 확인할 3가지", "howto"),
            (f"{primary} 신청 기준과 마감일, 누가 영향받는가", "search"),
            (f"{primary} 정책 시행, 직접 확인할 채널과 절차", "howto"),
            (f"{primary} 지원 대상과 신청 방법 정리", "search"),
        ])
    elif content_type == "money_checklist":
        titles.extend([
            (f"{primary} 가격/요금 변화, 이용자가 비교할 3가지 조건", "comparison"),
            (f"{primary} 최종 비용이 달라지는 이유와 확인 순서", "search"),
            (f"{primary} 결제 전 비교해야 할 핵심 기준", "howto"),
        ])
    else:
        # 안전 default
        titles.extend([
            (f"{primary} 오늘 이슈, 사람들이 궁금해한 3가지", "search"),
            (f"{primary} 발표 내용, 일반 이용자에게 미치는 영향", "curiosity"),
        ])

    return titles
