from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import json
import logging
import os
import random
import re
from typing import Any
from xml.etree import ElementTree
from urllib.parse import urlencode, urlsplit
import urllib.error
import urllib.request

from blogspot_automation.models.news_models import NewsCandidate
from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.external_news_search_service import (
    ExternalNewsSearchService,
    ExternalSearchDocument,
)
from blogspot_automation.services.title_integrity_policy import clean_source_title

logger = logging.getLogger(__name__)


SEARCH_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
def _google_api_error_summary(exc: urllib.error.HTTPError) -> str:
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="ignore")
    except Exception:
        body = ""
    message = ""
    reason = ""
    status = ""
    if body:
        try:
            payload = json.loads(body)
            error = payload.get("error") if isinstance(payload, dict) else {}
            if isinstance(error, dict):
                message = str(error.get("message") or "").strip()
                status = str(error.get("status") or "").strip()
                details = error.get("errors")
                if isinstance(details, list) and details:
                    first = details[0]
                    if isinstance(first, dict):
                        reason = str(first.get("reason") or "").strip()
        except Exception:
            message = " ".join(body.split())[:300]
    parts = [part for part in (status, reason, message) if part]
    if parts:
        return " | ".join(parts)
    if exc.reason:
        return str(exc.reason)
    return "API key/CX/quota or request configuration may be invalid"


def _is_official_source_url(url_or_host: str) -> bool:
    value = str(url_or_host or "").strip().lower()
    if not value:
        return False
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split("@")[-1].split(":")[0].removeprefix("www.")
    return host.endswith(".go.kr") or host.endswith(".or.kr") or host in {
        "gov.kr",
        "bokjiro.go.kr",
        "epeople.go.kr",
        "consumer.go.kr",
    }


RSS_SOURCE_SUFFIXES = (
    "데일리안",
    "미디어펜",
    "더퍼블릭",
    "국제뉴스",
    "한국경제",
    "매일경제",
    "서울경제",
    "조선일보",
    "중앙일보",
    "동아일보",
    "연합뉴스",
    "뉴스1",
    "뉴시스",
    "머니투데이",
    "이데일리",
    "아시아경제",
    "헤럴드경제",
    "스포츠서울",
    "OSEN",
    "엑스포츠뉴스",
    "스타뉴스",
    "텐아시아",
    "KBS 뉴스",
    "v.daum.net",
    "n.news.naver.com",
    "daum.net",
    "naver.com",
)
RSS_SUFFIX_PATTERN = re.compile(
    r"\s*(?:-|[|]|::)\s*(?:"
    + "|".join(re.escape(source) for source in RSS_SOURCE_SUFFIXES)
    + r"|[A-Za-z0-9_.-]+\.(?:com|co\.kr|net|kr))\s*$",
    re.IGNORECASE,
)
# ─── 영어 모드 쿼리 뱅크 (2026-07-17 영어 전환) ──────────────────────────────
# 미국·영국·캐나다·인도 영어권 대상. 가격·요금제 변경이 최우선(검색 폭발 대비
# 정리 글이 늦게 나오는 틈새), 그다음 신모델·기능 출시, 무료화/유료화 전환,
# 장애/제한(문제해결형 롱테일) 순. 엔티티 기반 — 실제 뉴스 헤드라인에 매칭된다.
EN_QUERY_GROUPS: dict[str, list[str]] = {
    "ai_work": [
        # 가격·요금제 변경 (최우선)
        "ChatGPT pricing",
        "OpenAI API pricing",
        "Claude pricing",
        "Gemini pricing",
        "Copilot pricing",
        "AI subscription price increase",
        "AI free tier",
        "GitHub Copilot price",
        # 신모델·신기능 출시
        "OpenAI announces",
        "OpenAI new model",
        "ChatGPT new feature",
        "Anthropic Claude update",
        "Google Gemini update",
        "Microsoft Copilot update",
        "Perplexity AI update",
        "xAI Grok update",
        "Meta Llama model",
        "DeepSeek model",
        "Mistral AI release",
        "AI agent launch",
        "AI coding assistant",
        "Cursor AI editor",
        "NotebookLM update",
        "Midjourney update",
        "ElevenLabs AI voice",
        "Runway AI video",
        # 장애·제한·정책 (문제해결형 소재)
        "ChatGPT outage",
        "ChatGPT rate limit",
        "Claude usage limit",
        "AI tool shutting down",
        "AI copyright lawsuit",
        "AI regulation bill",
    ],
}

QUERY_GROUPS: dict[str, list[str]] = {
    "breaking_issue": [
        "오늘 갑자기 중단",
        "오늘 논란 반발",
        "오늘 왜 난리",
        "오늘 알고 보니",
        "오늘 결국 변경",
        "오늘 긴급 변경",
        "오늘 반응 폭발",
    ],
    "money_life": [
        "오늘 가격 인상",
        "오늘 수수료 인상",
        "오늘 배달비 논란",
        "오늘 통신비 변화",
        "오늘 보험료 인상",
        "오늘 세금 환급",
        "오늘 생활비 부담",
        "오늘 월급 연봉 이슈",
        "전기요금 인상",
        "교통비 변화",
        "정부 정책 소비자 영향",
        "물가 상승 소비자",
        "구독료 인상",
        "보험료 변화",
    ],
    "platform_consumer": [
        "오늘 쿠팡 환불",
        "오늘 배달앱 수수료",
        "오늘 카카오 오류",
        "오늘 네이버 서비스 변경",
        "오늘 유튜브 정책 변경",
        "오늘 소비자 피해",
        "오늘 플랫폼 논란",
        "오늘 구독료 인상",
        "쿠팡 멤버십 변경",
        "네이버페이 변경",
        "카카오 서비스 변경",
        "유튜브 요금제",
        "OTT 요금 인상",
        "앱 서비스 개편",
        "플랫폼 약관 변경",
    ],
    "ai_work": [
        # 엔티티 기반 이슈 쿼리 — 실제 뉴스 헤드라인에 매칭되는 브랜드/제품명 위주
        "챗GPT 업데이트",
        "오픈AI 발표",
        "GPT 새 모델",
        "앤스로픽 클로드",
        "구글 제미나이",
        "마이크로소프트 코파일럿",
        "퍼플렉시티 AI",
        "네이버 AI 서비스",
        "카카오 AI 서비스",
        "삼성 갤럭시 AI",
        "AI 에이전트 출시",
        "AI 신기능 출시",
        "생성형 AI 서비스",
        "AI 요금제 변경",
        "AI 구독료 인상",
        "무료 AI 도구 제한",
        "챗GPT 장애",
        "AI 보안 개인정보 유출",
        "AI 저작권 논란",
        "오늘 생성형 AI 논란",
        "오늘 AI 서비스 변경",
        "ChatGPT 새 기능 업무 활용",
        "OpenAI 모델 업데이트 직장인",
        "Claude 새 기능 보고서 작성",
        "Gemini AI 기능 구글 문서",
        "AI 업무 자동화 워크플로",
        # 2026-07-13 소스 다양화: 특정 몇 개 헤드라인 반복 소진 방지 —
        # 국내외 AI 기업·제품군을 넓혀 매일 다른 실제 뉴스가 잡히게 함.
        "메타 라마 AI",
        "엔비디아 AI 신제품",
        "AI 반도체 소식",
        "AI 스타트업 투자",
        "아마존 AI 서비스",
        "미드저니 이미지 생성",
        "런웨이 AI 영상 생성",
        "일레븐랩스 AI 음성",
        "딥시크 AI",
        "AI 저작권 소송",
        "AI 규제 법안",
        "AI 채용 이력서 심사",
        "xAI 그록",
        "AI 데이터센터 소식",
        "AI 에이전트 서비스 출시",
    ],
    "trend_meme": [
        "오늘 틱톡 화제",
        "오늘 인스타 릴스 화제",
        "오늘 커뮤니티 난리",
        "오늘 오픈런 품절",
        "오늘 인증샷 유행",
        "오늘 신조어 밈",
        "오늘 디저트 트렌드",
        "오늘 굿즈 품절",
    ],
    "entertainment_sports": [
        "오늘 손흥민 이슈",
        "오늘 BTS 화제",
        "오늘 아이돌 논란",
        "오늘 넷플릭스 화제",
        "오늘 스포츠 팬 반응",
        "오늘 예능 화제",
        "오늘 영화 반응",
    ],
    "entertainment_reaction": [
        "드라마 반응 갈린 이유",
        "예능 장면 화제 이유",
        "연예 이슈 반응 분석",
        "드라마 결말 반응",
        "방송 출연 반응 갈린 포인트",
    ],
    "ott_drama_reaction": [
        "넷플릭스 신작 반응",
        "OTT 화제 드라마 반응",
        "티빙 시즌제 반응 갈림",
        "OTT 요금제 변화 반응",
        "스트리밍 오리지널 반응",
        "티빙 신작 반응",
        "디즈니플러스 신작",
        "예능 화제성",
        "드라마 반응",
        "아이돌 반응",
        "방송 화제성",
    ],
    "sports_reaction": [
        "손흥민 경기 반응",
        "야구 팬 반응 갈린 포인트",
        "축구 국가대표 반응",
        "스포츠 경기 후 댓글 분석",
        "스포츠 선수 이슈 반응",
        "오늘 야구 이슈",
        "KBO 화제",
        "스포츠 팬 반응",
    ],
    "fandom_consumption": [
        "아이돌 굿즈 품절 이유",
        "콘서트 티켓팅 구조",
        "팬덤 소비 구조",
        "한정판 품절 반복 이유",
        "팝업스토어 오픈런 구조",
    ],
    "community_hot_issue": [
        "커뮤니티 반응 갈린 이유",
        "유튜버 플랫폼 수익 구조",
        "SNS 화제 이유",
        "숏폼 알고리즘 반응",
        "인플루언서 논란 구조",
    ],
    "ticketing_goods_issue": [
        "콘서트 티켓팅 실패 이유",
        "아이돌 굿즈 품절 반복 이유",
        "티켓팅 구조 팬덤 소비",
        "팝업스토어 품절 구조",
        "한정판 티켓팅 실패 원인",
    ],
    "youtube_creator_issue": [
        "유튜버 수익 구조 논란",
        "크리에이터 브랜드 딜 논란",
        "유튜브 알고리즘 수익 변화",
        "숏폼 크리에이터 수익 구조",
        "유튜버 뒷광고 논란 구조",
    ],
    "policy_benefit": [
        "오늘 정부 지원금",
        "오늘 신청 마감",
        "오늘 환급 대상",
        "오늘 청년 지원",
        "오늘 부모 지원",
        "오늘 자영업자 지원",
        "오늘 소상공인 지원",
        "오늘 교통비 지원",
    ],
    "consumer_warning_issue": [
        "환불 논란",
        "소비자 피해 사례",
        "개인정보 유출 논란",
        "서비스 장애 논란",
        "예약 취소 피해",
        "결제 오류 피해",
        "약관 논란 소비자",
        "서비스 중단 피해",
    ],
}
RSS_PRIORITY_QUERY_GROUPS: dict[str, list[str]] = {
    "ai_work": [
        "챗GPT 업데이트",
        "오픈AI 새 기능",
        "클로드 AI 업데이트",
        "제미나이 업데이트",
        "AI 요금제 변경",
        "생성형 AI 출시",
        "AI 서비스 논란",
        "메타 AI 신기능",
        "엔비디아 AI 발표",
        "AI 스타트업 투자 유치",
        "AI 반도체 경쟁",
        "AI 규제 법안 발의",
    ],
    "policy_benefit": [
        "정부 지원금 신청 마감",
        "소상공인 지원금 신청 대상",
        "청년 지원금 신청 기간",
        "교통비 지원 신청 조건",
        "환급금 조회 대상",
    ],
    "consumer_warning_issue": [
        "공정위 소비자 피해 보상",
        "소비자원 환불 피해 주의",
        "결제 오류 환불 보상",
        "개인정보 유출 보상 안내",
        "서비스 장애 보상 기준",
    ],
    "platform_consumer": [
        "쿠팡 환불 지연 보상",
        "카카오 서비스 오류 보상",
        "네이버 서비스 변경 이용자",
        "배달앱 수수료 변경 소비자",
        "OTT 요금제 변경 이용자",
    ],
    "money_life": [
        "통신비 환급 조회",
        "보험료 인상 소비자 영향",
        "전기요금 복지할인 신청",
        "교통비 인상 환급 지원",
        "구독료 인상 해지 환불",
    ],
    "entertainment_sports": [
        "오늘 연예 스포츠 화제",
        "오늘 넷플릭스 반응",
        "오늘 아이돌 이슈",
        "오늘 스포츠 팬 반응",
        "오늘 예능 화제",
    ],
    "ott_drama_reaction": [
        "넷플릭스 신작 반응",
        "OTT 화제 드라마 반응",
    ],
    "sports_reaction": [
        "오늘 KBO 화제",
        "오늘 축구 대표팀 반응",
    ],
    "breaking_issue": [
        "택배 배송 지연 집화 마감",
        "서비스 중단 환불 안내",
        "앱 장애 보상 안내",
    ],
}
RSS_CANDIDATES_PER_QUERY = 3
SECONDARY_QUERY_GROUPS: dict[str, list[str]] = {
    "ai_work": [
        "AI 도구 출시",
        "AI 서비스 요금",
        "오픈AI",
        "챗GPT",
        "클로드 AI",
        "제미나이 AI",
        "AI 검색 기능",
        "코파일럿 업데이트",
        "AI 앱 업데이트",
        "미드저니",
        "일레븐랩스",
        "딥시크",
        "xAI 그록",
        "AI 데이터센터",
    ],
    "consumer_warning_secondary": [
        "환불 논란 소비자",
        "소비자 피해 대응",
        "개인정보 유출 피해",
        "서비스 장애 보상",
        "결제 오류 환불",
        "약관 변경 논란",
        "서비스 중단 공지",
        "티켓팅 실패 논란",
    ],
    "platform_change_secondary": [
        "플랫폼 정책 변경",
        "앱 서비스 개편",
        "요금제 변경 논란",
        "멤버십 변경 영향",
        "서비스 종료 안내",
        "앱 업데이트 주의",
        "OTT 요금 인상",
        "구독료 인상 이유",
    ],
    "viral_decode_secondary": [
        "화제 드라마 반응",
        "예능 화제 이유",
        "스포츠 팬 반응",
        "아이돌 이슈 반응",
        "OTT 신작 화제",
        "KBO 화제",
        "축구 대표팀 반응",
        "스포츠 중계 반응",
    ],
    "money_secondary": [
        "생활비 부담 증가",
        "구독료 인상 영향",
        "전기요금 인상",
        "교통비 변화",
        "물가 부담 소비자",
        "보험료 인상",
        "통신비 절약 방법",
    ],
    "policy_secondary": [
        "정부 지원금 신청",
        "지원금 마감 일정",
        "청년 지원 조건",
        "소상공인 지원 신청",
        "지원금 대상 확인",
        "복지 혜택 신청",
    ],
}
WEAK_BROAD_QUERIES: tuple[str, ...] = (
    "오늘 가장 화제 뉴스",
    "오늘 실시간 이슈",
    "오늘 사람들이 가장 궁금해하는 뉴스",
    "오늘 국민 관심 뉴스",
    "오늘 대기업 이슈",
    "오늘 연예 스포츠 화제",
    "오늘 커뮤니티 화제",
    "이번주 MZ 트렌드",
    "요즘 뜨는 유행",
)
BLOCKED_KEYWORDS = (
    "성인",
    "아동 대상",
    "고어",
    "살인",
    "혐오",
    "자극적 범죄 묘사",
    "루머",
    "정치 선동",
    "특정 인물 비방",
    "열애설",
    "이혼설",
    "불륜",
    "사생활 폭로",
    "찌라시",
    "외모 비하",
    "피해자 신상",
    "악플 유도",
)

# 한국 독자에게 부적합한 외국 출처 차단 — 한국어 검색결과지만 베트남/일본/중국 등 외국 뉴스가 섞이면 제외
# 원문 변질(외국 통화/날짜/지역 정보를 한국 가이드로 잘못 변환) 방지
BLOCKED_SOURCE_HINTS: tuple[str, ...] = (
    "Vietnam.vn",
    "vietnam.vn",
    "vnexpress",
    "thanhnien",
    "tuoitre",
)

VIRAL_BLOCKED_TITLE_PATTERNS = (
    "충격 근황",
    "결국 터졌다",
    "소름 돋는 이유",
    "사생활 논란 총정리",
    "루머 진짜일까",
    "역대급 상황",
    "난리난",
)
BORING_KEYWORDS = (
    "실적",
    "실적 발표",
    "분기 실적",
    "보고서",
    "산업 보고서",
    "산업 전망",
    "보도자료",
    "기관 보도자료",
    "정례회의",
    "정례 회의",
    "외교 회담",
    "외교 회의",
    "증권사 리포트",
    "시세 동향",
    "지역 시세",
)
BORING_EXEMPTION_KEYWORDS = (
    "환불",
    "지원금",
    "신청",
    "가격",
    "수수료",
    "소비자 피해",
    "배달비",
    "통신비",
    "보험료",
    "세금",
)
HOOK_KEYWORDS = {
    # 영어 토큰 추가(2026-07-17): 영어 모드 후보가 훅 0개로 전부 boring 필터에
    # 걸리는 것을 방지. 한국어 후보에는 사실상 등장하지 않아 기존 동작 불변.
    "money": ("물가", "가격", "월급", "연봉", "세금", "대출", "금리", "지원금", "환급", "보험료", "수수료", "배달비", "구독료", "인상", "인하",
              "pricing", "price", "cost", "subscription", "free tier", "per month", "fee", "cheaper", "expensive", "price hike", "discount"),
    "life": ("병원", "학교", "교통", "통신비", "배달", "택배", "플랫폼", "소비자", "소비자 피해", "직장인", "부모", "학생",
             "users", "workers", "students", "developers", "small business"),
    "famous_entity": ("삼성", "애플", "쿠팡", "네이버", "카카오", "현대차", "유튜브", "인스타", "틱톡", "넷플릭스", "손흥민", "bts",
                      "openai", "chatgpt", "anthropic", "claude", "google", "gemini", "microsoft", "copilot", "perplexity", "meta", "nvidia", "apple", "grok", "deepseek", "midjourney", "cursor"),
    "controversy": ("논란", "반발", "갑자기", "왜", "알고 보니", "결국", "중단", "변경", "오류", "해고",
                    "backlash", "controversy", "outage", "shutting down", "discontinued", "lawsuit", "banned", "leaked", "quietly"),
    "mass_impact": ("직장인", "부모", "학생", "자영업자", "소상공인", "투자자", "소비자", "운전자", "청년",
                    "everyone", "millions", "all users", "free users", "subscribers"),
    "trend": ("유행", "밈", "신조어", "챌린지", "오픈런", "품절", "굿즈", "인증샷", "팬덤", "릴스", "쇼츠",
              "viral", "trending"),
}
TREND_KEYWORDS = {
    "meme": ("밈", "짤", "드립"),
    "sns": ("sns", "인스타", "틱톡", "유튜브", "릴스", "쇼츠", "인증샷"),
    "food_trend": ("디저트", "카페", "먹거리", "편의점", "신제품"),
    "open_run": ("오픈런", "줄서기"),
    "sold_out": ("품절", "매진"),
    "fandom": ("팬덤", "팬", "굿즈"),
    "new_word": ("신조어", "유행어"),
    "community_buzz": ("커뮤니티", "화제", "실시간", "난리"),
}
CATEGORY_KEYWORDS = {
    "food": ("디저트", "카페", "먹거리", "편의점", "식품"),
    "meme": ("밈", "짤", "신조어", "유행어", "챌린지"),
    "trend": ("트렌드", "화제", "오픈런", "품절", "굿즈", "팬덤", "sns"),
    "sports": ("스포츠", "축구", "야구", "손흥민", "경기"),
    "entertainment": ("연예", "아이돌", "드라마", "영화", "예능", "넷플릭스", "bts"),
    "tech": ("ai", "챗gpt", "생성형 ai", "플랫폼", "앱", "서비스", "테크", "chatgpt", "openai", "claude", "gemini", "copilot", "llm", "model"),
    "money": ("물가", "가격", "월급", "연봉", "세금", "대출", "금리", "지원금", "환급", "수수료", "보험료"),
    "life": ("생활", "교통", "학교", "병원", "통신비", "배달", "배달비", "택배", "환불", "소비자 피해"),
    "global": ("글로벌", "해외", "국제", "미국", "중국", "일본"),
    "social": ("사회", "정책", "노동", "고용", "복지"),
}


class NewsTopicService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        search_cx: str | None = None,
        candidate_limit: int = 20,
        excluded_query_groups: list[str] | tuple[str, ...] | None = None,
        enable_custom_search: bool | None = None,
        external_search_service: ExternalNewsSearchService | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.search_cx = (search_cx or "").strip()
        self.candidate_limit = max(1, candidate_limit)
        if enable_custom_search is None:
            enable_custom_search = os.getenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "false").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.enable_custom_search = bool(enable_custom_search)
        self.external_search_service = external_search_service
        seed = os.getenv("NEWS_TOPIC_RANDOM_SEED", "").strip()
        self._query_random_seed = seed or f"{datetime.now(UTC).isoformat()}:{os.getpid()}:{id(self)}"
        self.ai_blog_mode = os.getenv("AI_BLOG_MODE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        raw_excluded = excluded_query_groups
        if raw_excluded is None:
            raw_excluded = tuple(
                part.strip()
                for part in os.getenv("NEWS_EXCLUDED_QUERY_GROUPS", "").split(",")
                if part.strip()
            )
        if self.ai_blog_mode:
            raw_excluded = tuple(dict.fromkeys([*raw_excluded, *self._non_ai_query_groups()]))
        self.excluded_query_groups = {str(group).strip() for group in raw_excluded if str(group).strip()}

    @staticmethod
    def _non_ai_query_groups() -> tuple[str, ...]:
        allowed = {"ai_work"}
        all_groups = set(QUERY_GROUPS) | set(RSS_PRIORITY_QUERY_GROUPS) | set(SECONDARY_QUERY_GROUPS)
        return tuple(sorted(group for group in all_groups if group not in allowed))

    def collect_candidates(self) -> list[NewsCandidate]:
        all_candidates: list[NewsCandidate] = []

        if self.external_search_service is not None and is_english_mode():
            # 영어 모드: Naver 뉴스 검색은 한국어 소스 — 호출 낭비·노이즈라 스킵하고
            # Google News RSS(en-US)를 1차 소스로 쓴다.
            pass
        elif self.external_search_service is not None:
            try:
                naver_documents = self.external_search_service.collect_naver_documents(self._query_plan())
                if naver_documents:
                    all_candidates = self._deduplicate_candidates(
                        all_candidates + self._documents_to_candidates(naver_documents)
                    )
                    logger.info("Naver search 후보 %d개 수집", len(all_candidates))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Naver search 수집 실패, Google News RSS 사용 시도: %s", exc)

        if self.enable_custom_search and self.api_key and self.search_cx:
            try:
                all_candidates = self._deduplicate_candidates(all_candidates + self._collect_from_google())
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Google Custom Search 수집 실패, Google News RSS 사용 시도: %s",
                    exc,
                )
                all_candidates = []
        elif self.api_key and self.search_cx:
            logger.info("Google Custom Search 비활성화: Google News RSS 후보를 우선 사용")
        else:
            logger.info("Google API 설정 누락으로 Google News RSS 후보 사용 시도")

        if len(all_candidates) < self.candidate_limit:
            try:
                rss_candidates = self._collect_from_google_news_rss()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Google News RSS 수집 실패, 정적 fallback 사용 가능: %s", exc)
                rss_candidates = []

            if rss_candidates:
                all_candidates = self._deduplicate_candidates(all_candidates + rss_candidates)

        force_viral = os.getenv("FORCE_VIRAL_ISSUE_TEST", "").strip().lower() in ("true", "1", "yes")
        if force_viral:
            viral_fallbacks = self._viral_fallback_candidates()
            all_candidates = viral_fallbacks + all_candidates

        if not all_candidates:
            all_candidates = self._fallback_candidates()

        filtered = [c for c in all_candidates if not self._is_boring_candidate(c)]
        if not filtered:
            filtered = all_candidates

        unique = self._deduplicate_candidates(filtered)
        if self.external_search_service is not None:
            try:
                if not is_english_mode():
                    # DataLab은 한국어 검색량 API — 영어 모드에선 무의미한 호출 스킵
                    unique = self.external_search_service.annotate_naver_datalab(unique)
                unique = self.external_search_service.verify_candidates(unique)
            except Exception as exc:  # noqa: BLE001
                logger.warning("External search verification failed: %s", exc)
        return unique[: self.candidate_limit]

    def collect_secondary_candidates(self) -> list[NewsCandidate]:
        """primary 수집 후 real news 후보가 없을 때 2차 확장 쿼리로 재시도."""
        collected: list[NewsCandidate] = []
        try:
            rss_candidates = self._collect_from_google_news_rss(query_plan=self._secondary_query_plan())
            if rss_candidates:
                collected = self._deduplicate_candidates(rss_candidates)
        except Exception as exc:  # noqa: BLE001
            logger.warning("secondary RSS 수집 실패: %s", exc)
        return collected[: self.candidate_limit]

    def _query_plan(self) -> list[tuple[str, str]]:
        if is_english_mode():
            # 영어 모드: 영어 AI 쿼리 뱅크만 사용 (한국어 쿼리는 en-US RSS에서 무의미)
            return self._randomized_query_items(EN_QUERY_GROUPS, salt="en-standard")
        priority = self._randomized_query_items(
            RSS_PRIORITY_QUERY_GROUPS,
            salt="rss-priority",
        )
        standard = self._randomized_query_items(
            QUERY_GROUPS,
            salt="standard",
        )
        return list(dict.fromkeys(priority + standard))

    def _randomized_query_items(
        self,
        groups: dict[str, list[str]],
        *,
        salt: str,
    ) -> list[tuple[str, str]]:
        rng = random.Random(f"{self._query_random_seed}:{salt}")
        group_names = [
            group for group in groups.keys()
            if group not in self.excluded_query_groups
        ]
        rng.shuffle(group_names)
        queries_by_group: dict[str, list[str]] = {}
        for group in group_names:
            queries = [
                query for query in groups.get(group, [])
                if query not in WEAK_BROAD_QUERIES
            ]
            rng.shuffle(queries)
            if queries:
                queries_by_group[group] = queries

        if not queries_by_group:
            return []

        items: list[tuple[str, str]] = []
        max_len = max(len(queries) for queries in queries_by_group.values())
        for index in range(max_len):
            round_groups = list(queries_by_group.keys())
            rng.shuffle(round_groups)
            for group in round_groups:
                queries = queries_by_group[group]
                if index < len(queries):
                    items.append((queries[index], group))
        return items

    def _secondary_query_plan(self) -> list[tuple[str, str]]:
        if is_english_mode():
            # 2차 확장: 1차보다 넓은 일반 쿼리 (엔티티 미포함 이슈 캐치)
            return [
                ("AI news today", "ai_work"),
                ("artificial intelligence announcement", "ai_work"),
                ("AI tool update", "ai_work"),
                ("LLM release", "ai_work"),
            ]
        return [
            (query, query_group)
            for query_group, queries in SECONDARY_QUERY_GROUPS.items()
            for query in queries
            if query_group not in self.excluded_query_groups
        ]

    def _collect_from_google(self) -> list[NewsCandidate]:
        collected: list[NewsCandidate] = []
        per_query_num = 2

        for query, query_group in self._query_plan():
            params = {
                "key": self.api_key,
                "cx": self.search_cx,
                "q": query,
                "num": per_query_num,
                "hl": "ko",
                "gl": "KR",
                "cr": "countryKR",
                "dateRestrict": "d1",
                "safe": "active",
            }
            url = f"{SEARCH_ENDPOINT}?{urlencode(params)}"
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            except urllib.error.HTTPError as exc:
                raise RuntimeError(
                    f"Google Custom Search HTTP {exc.code}: {_google_api_error_summary(exc)}"
                ) from exc

            for item in payload.get("items", []):
                title = str(item.get("title", "")).strip()
                snippet = str(item.get("snippet", "")).strip()
                if not title or self._is_blocked_topic(title, snippet):
                    continue
                hook_signals = self._build_hook_signals(title, snippet)
                trend_signals = self._build_trend_signals(title, snippet)
                boring_signals = self._build_boring_signals(title, snippet, query_group)
                candidate = NewsCandidate(
                    topic=self._short_topic(title),
                    category=self._classify_category(title, snippet, query_group),
                    summary=snippet,
                    source_hint=item.get("displayLink"),
                    published_at=None,
                    url=item.get("link"),
                    raw={
                        "google_item": item if isinstance(item, dict) else {"raw_item": str(item)},
                        "query": query,
                        "query_group": query_group,
                        "source_type": "google_custom_search",
                        "hook_signals": hook_signals,
                        "trend_signals": trend_signals,
                        "boring_signals": boring_signals,
                    },
                )
                collected.append(candidate)
                if len(collected) >= self.candidate_limit:
                    return collected

        return collected

    def _collect_from_google_news_rss(
        self,
        query_plan: list[tuple[str, str]] | None = None,
    ) -> list[NewsCandidate]:
        collected: list[NewsCandidate] = []

        for query, query_group in (query_plan if query_plan is not None else self._query_plan()):
            if is_english_mode():
                params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
            else:
                params = {
                    "q": query,
                    "hl": "ko",
                    "gl": "KR",
                    "ceid": "KR:ko",
                }
            url = f"{GOOGLE_NEWS_RSS_ENDPOINT}?{urlencode(params)}"
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=9) as response:
                payload = response.read()

            try:
                root = ElementTree.fromstring(payload)
            except ElementTree.ParseError as exc:
                logger.warning("Google News RSS XML 파싱 실패(query=%s): %s", query, exc)
                continue

            query_candidates: list[NewsCandidate] = []
            for item in root.iter():
                if self._xml_tag_name(item) != "item":
                    continue
                original_title = self._xml_child_text(item, "title")
                cleaned_title = self._clean_rss_title(original_title)
                link = self._xml_child_text(item, "link")
                pub_date = self._xml_child_text(item, "pubDate")
                parsed_pub_date = self._parse_rss_pub_date(pub_date)
                parsed_pub_date_value = parsed_pub_date.isoformat() if parsed_pub_date else ""
                is_stale = self._is_stale_pub_date(parsed_pub_date)
                source = self._xml_child_text(item, "source")
                summary = source or pub_date or query

                if not cleaned_title or self._is_blocked_topic(cleaned_title, summary):
                    continue
                # 외국 출처 차단 — 베트남 금/돼지고기 가격 등 한국 독자 무관 콘텐츠 제외
                if source and any(blocked.lower() in source.lower() for blocked in BLOCKED_SOURCE_HINTS):
                    continue

                hook_signals = self._build_hook_signals(cleaned_title, summary)
                trend_signals = self._build_trend_signals(cleaned_title, summary)
                boring_signals = self._build_boring_signals(cleaned_title, summary, query_group)
                query_candidates.append(
                    NewsCandidate(
                        topic=self._short_topic(cleaned_title),
                        category=self._classify_category(cleaned_title, summary, query_group),
                        summary=summary,
                        source_hint=source or None,
                        published_at=parsed_pub_date_value or pub_date or None,
                        url=link or None,
                        raw={
                            "source_type": "google_news_rss",
                            "query": query,
                            "query_group": query_group,
                            "pubDate": pub_date,
                            "parsed_pub_date": parsed_pub_date_value,
                            "is_stale": is_stale,
                            "source": source,
                            "original_title": original_title,
                            "cleaned_title": cleaned_title,
                            "hook_signals": hook_signals,
                            "trend_signals": trend_signals,
                            "boring_signals": boring_signals,
                        },
                    )
                )

            fresh_candidates = [
                candidate
                for candidate in query_candidates
                if not bool(candidate.raw.get("is_stale"))
            ]
            collected.extend((fresh_candidates or query_candidates[:2])[:RSS_CANDIDATES_PER_QUERY])

            if len(collected) >= self.candidate_limit:
                return collected[: self.candidate_limit]

        return collected

    def _documents_to_candidates(self, documents: list[ExternalSearchDocument]) -> list[NewsCandidate]:
        candidates: list[NewsCandidate] = []
        for document in documents:
            title = self._clean_rss_title(document.title)
            summary = document.snippet or document.source_hint or document.query
            if not title or self._is_blocked_topic(title, summary):
                continue
            parsed_pub_date = self._parse_rss_pub_date(document.published_at or "")
            parsed_pub_date_value = parsed_pub_date.isoformat() if parsed_pub_date else ""
            is_stale = self._is_stale_pub_date(parsed_pub_date)
            hook_signals = self._build_hook_signals(title, summary)
            trend_signals = self._build_trend_signals(title, summary)
            boring_signals = self._build_boring_signals(title, summary, document.query_group)
            raw = {
                "source_type": document.source_type,
                "provider": document.provider,
                "query": document.query,
                "query_group": document.query_group,
                "pubDate": document.published_at or "",
                "parsed_pub_date": parsed_pub_date_value,
                "is_stale": is_stale,
                "source": document.source_hint or "",
                "original_title": document.title,
                "cleaned_title": title,
                "hook_signals": hook_signals,
                "trend_signals": trend_signals,
                "boring_signals": boring_signals,
                "external_search_providers": [document.provider] if document.provider else [],
                "source_urls": [document.url] if document.url else [],
                "source_titles": [title],
                "official_source_found": _is_official_source_url(document.url or document.source_hint or ""),
            }
            raw.update(document.raw)
            candidates.append(
                NewsCandidate(
                    topic=self._short_topic(title),
                    category=self._classify_category(title, summary, document.query_group),
                    summary=summary,
                    source_hint=document.source_hint,
                    published_at=parsed_pub_date_value or document.published_at,
                    url=document.url,
                    raw=raw,
                )
            )
        return candidates

    def _fallback_candidates(self) -> list[NewsCandidate]:
        fallback_topics: list[tuple[str, str, str, str]] = [
            ("갑자기 중단된 생활 서비스, 이용자 반응이 갈린 이유", "social", "breaking_issue 그룹 동작을 확인하는 테스트 후보", "breaking_issue"),
            ("배달비와 수수료 부담, 소비자와 사장님 모두 불만?", "money", "money_life 그룹 동작을 확인하는 테스트 후보", "money_life"),
            ("쿠팡 환불 지연 논란, 소비자 피해 대응법 관심 증가", "life", "platform_consumer 그룹 동작을 확인하는 테스트 후보", "platform_consumer"),
            ("AI 업무 도구 변경, 직장인 생산성 논쟁이 커진 이유", "tech", "ai_work 그룹 동작을 확인하는 테스트 후보", "ai_work"),
            ("디저트 오픈런 품절, 인증샷 유행의 진짜 이유", "food", "trend_meme 그룹 동작을 확인하는 테스트 후보", "trend_meme"),
            ("손흥민 경기 반응, 팬들 사이에서 갈린 포인트", "sports", "entertainment_sports 그룹 동작을 확인하는 테스트 후보", "entertainment_sports"),
            ("정부 지원금 신청 조건, 놓치면 손해라는 말이 나온 이유", "money", "policy_benefit 그룹 동작을 확인하는 테스트 후보", "policy_benefit"),
            ("통신비·구독료 인상설, 가계 부담이 커졌다는 반응", "life", "money_life 그룹 보강용 테스트 후보", "money_life"),
            ("카카오 서비스 오류 이후 보상 기준에 관심 집중", "tech", "platform_consumer 그룹 보강용 테스트 후보", "platform_consumer"),
            ("챗GPT 업무 활용 확산, 직장인 평가가 엇갈리는 이유", "tech", "ai_work 그룹 보강용 테스트 후보", "ai_work"),
            ("굿즈 품절과 팬덤 인증샷, 커뮤니티가 들썩인 포인트", "meme", "trend_meme 그룹 보강용 테스트 후보", "trend_meme"),
            ("청년 지원금 신청 마감, 대상 조건 다시 확인하는 이유", "money", "policy_benefit 그룹 보강용 테스트 후보", "policy_benefit"),
        ]
        candidates: list[NewsCandidate] = []
        for topic, category, summary, query_group in fallback_topics:
            if query_group in self.excluded_query_groups:
                continue
            if self._is_blocked_topic(topic, summary):
                continue
            hook_signals = self._build_hook_signals(topic, summary)
            trend_signals = self._build_trend_signals(topic, summary)
            boring_signals = self._build_boring_signals(topic, summary, query_group)
            candidates.append(
                NewsCandidate(
                    topic=topic,
                    category=category,
                    summary=summary,
                    source_hint=None,
                    published_at=None,
                    url=None,
                    raw={
                        "is_test_candidate": True,
                        "source": "fallback",
                        "source_type": "fallback",
                        "publish_allowed": False,
                        "query": topic,
                        "query_group": query_group,
                        "hook_signals": hook_signals,
                        "trend_signals": trend_signals,
                        "boring_signals": boring_signals,
                    },
                )
            )
        return candidates

    def _deduplicate_candidates(self, candidates: list[NewsCandidate]) -> list[NewsCandidate]:
        seen: set[str] = set()
        by_key: dict[str, NewsCandidate] = {}
        unique: list[NewsCandidate] = []
        for candidate in candidates:
            key = self._dedup_key(candidate)
            if key in seen:
                existing = by_key.get(key)
                if existing is not None:
                    self._merge_candidate_evidence(existing, candidate)
                continue
            seen.add(key)
            by_key[key] = candidate
            unique.append(candidate)
        return unique

    def _dedup_key(self, candidate: NewsCandidate) -> str:
        title = re.sub(r"\s+", " ", (candidate.topic or "").lower()).strip()
        title = re.sub(r"[^\w가-힣]+", " ", title, flags=re.UNICODE)
        return re.sub(r"\s+", " ", title).strip()

    def _merge_candidate_evidence(self, existing: NewsCandidate, incoming: NewsCandidate) -> None:
        existing_raw = existing.raw if isinstance(existing.raw, dict) else {}
        incoming_raw = incoming.raw if isinstance(incoming.raw, dict) else {}
        existing.raw = existing_raw
        providers = list(existing_raw.get("external_search_providers") or [])
        for provider in incoming_raw.get("external_search_providers") or []:
            if provider and provider not in providers:
                providers.append(provider)
        incoming_source_type = str(incoming_raw.get("source_type") or incoming_raw.get("source") or "").strip()
        if incoming_source_type and incoming_source_type not in providers:
            providers.append(incoming_source_type)
        existing_raw["external_search_providers"] = providers

        source_urls = list(existing_raw.get("source_urls") or [])
        for url in list(incoming_raw.get("source_urls") or []) + ([incoming.url] if incoming.url else []):
            if url and url not in source_urls:
                source_urls.append(url)
        existing_raw["source_urls"] = source_urls[:10]

        source_titles = list(existing_raw.get("source_titles") or [])
        incoming_title = incoming.topic or str(incoming_raw.get("cleaned_title") or "")
        for title in list(incoming_raw.get("source_titles") or []) + ([incoming_title] if incoming_title else []):
            if title and title not in source_titles:
                source_titles.append(title)
        existing_raw["source_titles"] = source_titles[:10]

        hosts = {
            urlsplit(str(url)).netloc.lower().removeprefix("www.")
            for url in source_urls
            if str(url).strip()
        }
        existing_raw["verified_source_count"] = max(
            int(existing_raw.get("verified_source_count") or 0),
            int(incoming_raw.get("verified_source_count") or 0),
            len(source_urls),
        )
        existing_raw["source_diversity_score"] = max(
            int(existing_raw.get("source_diversity_score") or 0),
            int(incoming_raw.get("source_diversity_score") or 0),
            min(5, len(hosts) + max(0, len(providers) - 1)),
        )
        existing_raw["official_source_found"] = bool(existing_raw.get("official_source_found")) or bool(
            incoming_raw.get("official_source_found")
        ) or any(
            _is_official_source_url(str(url)) for url in source_urls
        )

    def _xml_child_text(self, item: ElementTree.Element, child_name: str) -> str:
        for child in list(item):
            if self._xml_tag_name(child) == child_name:
                return (child.text or "").strip()
        return ""

    def _xml_tag_name(self, item: ElementTree.Element) -> str:
        return item.tag.rsplit("}", 1)[-1] if isinstance(item.tag, str) else ""

    def _clean_rss_title(self, title: str) -> str:
        cleaned = clean_source_title(title)
        cleaned = RSS_SUFFIX_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"\s+-\s+[^-]+(?:뉴스|일보|신문|방송|경제|닷컴)\s*$", "", cleaned, flags=re.IGNORECASE)
        if is_english_mode():
            # 영어 RSS 제목의 매체/저자 접미사 제거: "Headline - The Verge" /
            # "… - De'aaron Fox (nAmerica)". 영어 헤드라인 본문은 하이픈 대신
            # em dash·콜론을 쓰므로, 마지막 " - " 뒤 꼬리가 45자 이하면 매체·저자로
            # 보고 통째로 잘라낸다 (드라이런 #4: 괄호 낀 저자명이 部分 절단돼
            # 깨진 주제 표면으로 패턴 confidence가 25로 캡되던 사고).
            head, sep, tail = cleaned.rpartition(" - ")
            if sep and head and len(tail) <= 45:
                cleaned = head
            cleaned = re.sub(r"\s+[|–]\s+[^|–]{1,45}$", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        quote_count = cleaned.count('"')
        if quote_count % 2 == 1:
            cleaned = cleaned.replace('"', "")
        return cleaned.strip(" \"'“”‘’[]()")

    def _parse_rss_pub_date(self, pub_date: str) -> datetime | None:
        if not pub_date:
            return None
        try:
            parsed = parsedate_to_datetime(pub_date)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _is_stale_pub_date(self, parsed_pub_date: datetime | None) -> bool:
        if parsed_pub_date is None:
            return False
        return datetime.now(UTC) - parsed_pub_date > timedelta(hours=48)

    def _is_blocked_topic(self, *values: str) -> bool:
        lowered = " ".join(values).lower()
        if any(keyword in lowered for keyword in BLOCKED_KEYWORDS):
            return True
        if any(pattern in lowered for pattern in VIRAL_BLOCKED_TITLE_PATTERNS):
            return True
        return False

    def _viral_fallback_candidates(self) -> list[NewsCandidate]:
        viral_topics: list[tuple[str, str, str, str]] = [
            (
                "넷플릭스 신작 반응이 갈린 이유, 시청자가 먼저 본 3가지",
                "entertainment",
                "OTT 신작 반응 분석 — FORCE_VIRAL_ISSUE_TEST 테스트 후보",
                "ott_drama_reaction",
            ),
            (
                "손흥민 경기 반응이 갈린 이유, 팬들이 본 핵심 장면",
                "sports",
                "스포츠 경기 반응 분석 — FORCE_VIRAL_ISSUE_TEST 테스트 후보",
                "sports_reaction",
            ),
            (
                "아이돌 굿즈 품절이 반복되는 이유, 팬덤 소비 구조로 보면",
                "entertainment",
                "팬덤 소비 구조 분석 — FORCE_VIRAL_ISSUE_TEST 테스트 후보",
                "fandom_consumption",
            ),
            (
                "콘서트 티켓팅이 매번 어려운 이유, 플랫폼 구조로 보면",
                "entertainment",
                "티켓팅 구조 분석 — FORCE_VIRAL_ISSUE_TEST 테스트 후보",
                "fandom_consumption",
            ),
            (
                "OTT 요금제 변화가 시청자에게 미치는 실질 영향",
                "tech",
                "OTT 플랫폼 전략 분석 — FORCE_VIRAL_ISSUE_TEST 테스트 후보",
                "ott_drama_reaction",
            ),
        ]
        candidates: list[NewsCandidate] = []
        for topic, category, summary, query_group in viral_topics:
            if self._is_blocked_topic(topic, summary):
                continue
            hook_signals = self._build_hook_signals(topic, summary)
            trend_signals = self._build_trend_signals(topic, summary)
            boring_signals = self._build_boring_signals(topic, summary, query_group)
            candidates.append(
                NewsCandidate(
                    topic=topic,
                    category=category,
                    summary=summary,
                    source_hint=None,
                    published_at=None,
                    url=None,
                    raw={
                        "is_test_candidate": True,
                        "source": "viral_fallback",
                        "source_type": "viral_fallback",
                        "publish_allowed": False,
                        "query": topic,
                        "query_group": query_group,
                        "hook_signals": hook_signals,
                        "trend_signals": trend_signals,
                        "boring_signals": boring_signals,
                        "force_viral_test": True,
                    },
                )
            )
        return candidates

    def _is_boring_candidate(self, candidate: NewsCandidate) -> bool:
        raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        boring_signals = raw.get("boring_signals", {})
        if isinstance(boring_signals, dict) and bool(boring_signals.get("is_boring")):
            hook_signals = raw.get("hook_signals", {})
            if isinstance(hook_signals, dict):
                hook_count = sum(1 for value in hook_signals.values() if value)
                return hook_count < 2
            return True
        return False

    def _build_hook_signals(self, title: str, snippet: str) -> dict[str, bool]:
        text = f"{title} {snippet}".lower()
        return {
            key: any(keyword in text for keyword in keywords)
            for key, keywords in HOOK_KEYWORDS.items()
        }

    def _build_trend_signals(self, title: str, snippet: str) -> dict[str, bool]:
        text = f"{title} {snippet}".lower()
        return {
            key: any(keyword in text for keyword in keywords)
            for key, keywords in TREND_KEYWORDS.items()
        }

    def _build_boring_signals(self, title: str, snippet: str, query_group: str) -> dict[str, bool]:
        text = f"{title} {snippet}".lower()
        raw_boring_keyword_hit = any(keyword in text for keyword in BORING_KEYWORDS)
        boring_exception_hit = any(keyword in text for keyword in BORING_EXEMPTION_KEYWORDS)
        boring_keyword_hit = raw_boring_keyword_hit and not boring_exception_hit
        hook_signals = self._build_hook_signals(title, snippet)
        trend_signals = self._build_trend_signals(title, snippet)
        reaction_signal = any(token in text for token in (
            "논란", "반응", "갑자기", "화제", "왜", "결국", "유행",
            # 영어 모드 반응/변화 신호 — 한국어 텍스트엔 등장하지 않아 기존 동작 불변
            "launches", "launched", "announces", "announced", "unveils", "rolls out",
            "update", "pricing", "release", "released", "new ", "cuts", "raises", "why ",
        ))
        hook_count = sum(1 for value in hook_signals.values() if value)
        trend_count = sum(1 for value in trend_signals.values() if value)
        is_boring = boring_keyword_hit or (hook_count == 0 and trend_count == 0 and not reaction_signal and query_group != "trend_meme")
        return {
            "raw_boring_keyword_hit": raw_boring_keyword_hit,
            "boring_exception_hit": boring_exception_hit,
            "boring_keyword_hit": boring_keyword_hit,
            "no_hook_or_trend_signal": hook_count == 0 and trend_count == 0,
            "no_reaction_signal": not reaction_signal,
            "is_boring": is_boring,
        }

    def _classify_category(self, title: str, snippet: str, query_group: str) -> str:
        text = f"{title} {snippet}".lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return category
        if query_group == "trend_meme":
            return "trend"
        if query_group in {"money_life", "platform_consumer", "policy_benefit"}:
            return "life"
        if query_group == "ai_work":
            return "tech"
        if query_group == "entertainment_sports":
            return "entertainment"
        return "social"

    def _short_topic(self, title: str) -> str:
        compact = " ".join(title.split()).strip()
        return compact[:90]
