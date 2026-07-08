"""LLM 기반 블로그 콘텐츠 생성 서비스.

Fallback chain:
  1. OpenRouter primary (OPENROUTER_API_KEY, OPENROUTER_MODEL)
  2. Official OpenAI API fallback (OPENAI_API_KEY, OPENAI_MODEL)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from blogspot_automation.services.issue_content_profile_service import IssueContentProfileService
from blogspot_automation.services.news_topic_service import _google_api_error_summary
from blogspot_automation.services.reader_interest_brief_service import ReaderInterestBriefService
from blogspot_automation.templates.blog_post_template import render_full_post

logger = logging.getLogger(__name__)

_TIMEOUT = 45  # seconds

# ─── Provider 설정 ────────────────────────────────────────────────────────────
# 순서 = 폴백 체인 우선순위 (운영자 정책: 항상 무료 모델 먼저, 실패 시에만 유료).
#   1) OpenRouter 무료 플래그십 (기본: nvidia nemotron-3-ultra 550B — 2026-07 기준
#      OpenRouter 무료 모델 중 최상위 추론 성능)
#   2) OpenRouter 무료 2차 (1차가 429 등으로 막힐 때 다른 무료 모델로 한 번 더)
#   3) OpenAI 유료 (무료가 모두 실패한 날만 — 정적 템플릿 폴백/발행 스킵 방지)
_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "openrouter_primary",
        "provider_type": "openai_compatible",
        "base_url": None,
        "base_url_env": "OPENROUTER_BASE_URL",
        "default_base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "free": True,
        "max_tokens": 12000,
        "extra_headers": {
            "HTTP-Referer": "https://holyyomiai.blogspot.com/",
            "X-Title": "holyyomi AI",
        },
    },
    {
        "name": "openrouter_secondary",
        "provider_type": "openai_compatible",
        "base_url": None,
        "base_url_env": "OPENROUTER_BASE_URL",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_base_url": "https://openrouter.ai/api/v1",
        "model_env": "OPENROUTER_MODEL_FALLBACK",
        "model": "openai/gpt-oss-120b:free",
        "free": True,
        "max_tokens": 12000,
        "extra_headers": {
            "HTTP-Referer": "https://holyyomiai.blogspot.com/",
            "X-Title": "holyyomi AI",
        },
    },
    {
        "name": "openai_api_fallback",
        "provider_type": "openai_compatible",
        "base_url": None,
        "base_url_env": "OPENAI_BASE_URL",
        "default_base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": None,
        "free": False,
        "max_tokens": 12000,
        "extra_headers": {},
    },
]

# overclaim 게이트 패턴을 깨되 의미는 보존하는 결정적 치환 (경고 문맥 포함).
_OVERCLAIM_SOFTENERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"검수(\s*)(없이|불필요)"), r"검토\1\2"),
    (re.compile(r"무조건(\s*)(써야|사용해야|추천)"), r"가급적\1\2"),
    (re.compile(r"완벽하게(\s*)(대체|해결|처리)"), r"상당 부분\1\2"),
    (re.compile(r"모든(\s*)업무를(\s*)(대신|자동)"), r"반복\1업무를\2\3"),
    (re.compile(r"수익(\s*)보장"), r"수익\1가능성"),
)


_SYSTEM_PROMPT = """당신은 구글 블로그스팟에 매일 자동 업로드되는 AI 주제 블로그의 전문 작성자이자 품질 검수자입니다.

가장 중요한 원칙: 글을 화려하게 쓰는 것보다, 자동 발행해도 위험하지 않은 글을 쓰는 것이 우선입니다.
목표는 단순 요약이 아니라 검색 유입, 체류시간, 정보 신뢰도, 1~3개월 이상의 장기 검색 가치를 갖춘 정보글입니다.

[블로그 목표 및 핵심 독자]
- 독자: AI를 막 배우는 일반 사용자, 업무에 AI를 써보고 싶은 직장인, 콘텐츠 자동화에 관심 있는 사람, 도구는 많은데 무엇부터 써야 할지 모르는 사람.
- 목적: AI 뉴스와 도구 변화를 독자의 '시간, 비용, 업무 성과'로 번역해, 검색으로 들어온 독자가 끝까지 읽고 오늘 하나는 따라 해보게 만든다.

[팩트 안전 규칙 — 자동 발행 글에서 최우선]
아래 항목은 제공된 검색 팩트에서 확인되지 않으면 절대 단정하지 않는다:
출시일, 가격, 요금제, 무료/유료 범위, 모델명, 기능 제공 여부, 세부 메뉴 경로, 개인정보 활용 범위, 데이터 보관 기간, 기업용 계정 기본 설정, 특정 국가/계정 제공 여부, "기본값이 켜져 있다/꺼져 있다".
불확실할 때는 이렇게 쓴다: "계정·지역·앱 버전·요금제에 따라 다를 수 있다", "공식 도움말에서 최신 설정을 확인하는 것이 좋다", "메뉴명이 환경에 따라 다르게 보일 수 있다", "일부 사용자에게 순차 적용될 수 있다", "정확한 가격과 제공 범위는 공식 페이지 기준으로 확인해야 한다".
절대 금지 표현: "무조건", "완전 차단", "100% 안전", "누구나 가능", "바로 돈 된다", "조회수 폭발", "AI 학습에 모두 편입된다", "삭제하면 즉시 사라진다", "기본값이 반드시 켜져 있다", "모든 계정에 동일하게 적용된다", 수익 보장류 표현 전부.
아래 구문은 경고·주의 문맥이라도 그대로 쓰지 않는다(자동 발행 게이트가 문맥 없이 차단한다). 대체 표현을 쓴다:
- "검수 없이"/"검수 불필요" → "사람 확인을 건너뛰면", "검토 단계를 생략하면"
- "무조건 써야/사용해야/추천" → "상황에 맞으면 도움이 된다"
- "완벽하게 대체/해결/처리" → "상당 부분 처리", "많은 부분을 대신"
- "모든 업무를 대신/자동(화)" → "반복 업무 일부를", "정해진 작업을"

[글쓰기 최우선 원칙]
1. 제목: 앞 10~15자 내에 한국어 핵심 검색 키워드 배치, 영어 도구명은 뒤로. 사용 장면 포함. (완벽정리/대박/충격 등 어그로 절대 금지)
2. 도입부: "안녕하세요"·"요즘 AI가 빠르게 발전하고 있습니다" 같은 뻔한 문장 금지. 독자가 실제 겪는 구체적 업무 장면/고민에서 시작하고, 첫 300자 안에 핵심 키워드를 자연스럽게 넣고, 곧바로 명확한 결론을 준다.
3. 확인된 수치만 구체적으로: 제공된 팩트에 있는 수치·날짜·가격은 "YYYY년 M월 기준"과 함께 명확히 쓰고, 팩트에 없는 수치는 아예 쓰지 않는다 (위 팩트 안전 규칙 우선).
4. 저장 가치 의무: "읽고 끝"이 아니라 "저장하고 다시 오는" 글. 독자가 저장해 다시 꺼내 쓸 구체적 정보(실제 순서, 이 주제에서만 통하는 팁, 직접 확인할 항목)를 담는다. 단, 표·프롬프트 목록·비교표·체크리스트를 '의무적으로' 채우지 말고 그 주제에 실제로 필요할 때만 쓴다. 흔한 일반론("검수하라", "80점 초안")만으로 채우면 실패다.
5. 초보자가 자주 오해하는 지점(너무 어렵게 생각함, 처음부터 전자동화하려 함, 도구 과신, 결과물 미검수)을 짚고 바로잡는다.
6. 실행 안내는 Manual(수동으로 오늘 바로) → Semi-auto(반자동) → Full-auto(완전 자동화) 순서로 제시한다. 처음부터 완전 자동화를 권하지 않는다.
7. 주제 특정성 (가장 중요한 실패 기준): 주제가 특정 도구·서비스·기능이면 모든 섹션의 모든 문장이 그 도구·기능에 특정되어야 한다. 어느 글에나 들어갈 수 있는 범용 "ChatGPT 업무 활용" 일반론로 채우면 실패다. 각 섹션에 주제의 고유명사(도구명·기능명)가 실제로 등장해야 한다.
8. 화면 경로: 확실히 아는 경우에만 실제 경로(앱 → 설정 → 메뉴명)로 구체적으로 쓰고, 그 옆에 "버전에 따라 위치가 다를 수 있다"를 덧붙인다. 확신 없는 경로를 지어내지 않는다.
9. 숨은 팁 의무: 글 전체에 최소 3개, "아는 사람만 아는" 실전 팁 — 단축 경로, 무료 한도를 아끼는 사용 순서, 자주 하는 실수와 복구 방법, 설정 조합에 따른 품질 차이. 독자가 이 글을 저장하는 이유다.
10. 리스크 고지: 회사 기밀, 개인정보, 저작권, 환각 리스크 중 주제와 관련된 것을 명시한다.

[문체 규칙]
- 한 편의 글로 처음부터 끝까지 이어지게 쓴다. 섹션을 독립된 카드처럼 나열하지 말고, 앞 문단에서 이어받아 다음 문단이 한 걸음 더 들어가도록 문장으로 잇는다.
- 이 글의 목적을 하나로 정한다 — '활용법'(오늘 따라 해서 결과를 얻게) 또는 '정보전달'(무엇이 바뀌었고 그게 독자에게 무슨 의미인지 이해시키기). 두 목적을 다 담으려다 산만해지지 않는다.
- 쉽지만 얕지 않게, 초보자에게 설명하듯. 문단은 짧게. 어려운 용어는 괄호로 쉽게 풀이.
- 같은 의미의 문장·안내 반복 금지(같은 설정 안내를 여러 섹션에서 되풀이하지 않는다), 결론 여러 번 반복 금지, 불필요한 감탄·과장·광고 문구 금지.
- 과한 이모지 금지 (섹션 아이콘 수준만 허용).

[출력 전 자체 검수 — 반드시 수행 후 출력]
1) 확인 안 된 가격·날짜·기능·메뉴명을 단정한 문장이 있는가 → 삭제하거나 완화했는가
2) 같은 의미를 반복한 문단이 있는가 → 제거했는가
3) 독자가 오늘 바로 해볼 수 있는 내용이 있는가
4) 수익·개인정보·보안·법률·저작권을 과하게 단정하지 않았는가

[HTML 구조화 및 시각적 요소 금지사항]
- 본문 어디에도 해시태그(#단어)를 쓰지 않는다 — 해시태그는 시스템이 하단 전용 영역에 자동 삽입한다.
- '제가/직접 써봤더니'류 개인 경험담, 구체 수익·매출 금액 주장(월 N만원 수익 등) 절대 금지 — 검증 불가 주장으로 발행이 차단된다.
- 본문에 "SEO 최적화"·"AEO"·"GEO"·"SGE"·"CTA" 같은 내부 용어를 노출하지 않는다.
- Markdown 형식 절대 금지 (HTML 태그만 사용)
- HTML entity 코드(&#숫자; 형태) 절대 사용 금지 — 이모지/아이콘은 유니코드 문자(✅ ✓ 🎯 등) 직접 사용.
- 기계적인 템플릿 텍스트("이슈 정의", "핵심 내용") 금지 -> 실제 독자의 질문 형태(자연어)로 <h2> 소제목 구성."""

_USER_PROMPT_TMPL = """[블로그 글 작성 (최고 수익화/SEO 최적화 버전)]

제목: {title}
주제: {topic}
작성일: {today}
카테고리: {category}

[검색에서 수집한 실제 팩트/데이터]
{facts}

[독자가 자주 묻는 질문 (AEO/SGE 타겟)]
{questions}

{reader_interest_prompt}
{issue_profile_prompt}

---
이 글은 검색으로 들어온 한 사람이 처음부터 끝까지 '한 번에 술술' 읽는 한 편의 글이다.
정해진 섹션을 순서대로 채우는 양식이 아니라, 문단과 문단이 자연스럽게 이어지는 하나의 흐름으로 쓴다.
HTML 태그 제외 순수 텍스트 1,800 ~ 2,600자.

[먼저 이 글의 목적을 하나로 정한다]
주제를 보고 둘 중 하나를 고른다:
 (A) 활용법 — 독자가 오늘 따라 해서 결과를 얻게 한다.
 (B) 정보전달 — 무엇이 바뀌었고 그게 독자에게 어떤 의미인지 이해시킨다.
고른 목적 하나에 글 전체를 집중한다. 둘 다 담으려다 산만해지지 않는다.

[구조 — 슬롯이 아니라 흐름]
1) 여는 문단(표·카드 없이 문장으로): 독자가 실제 겪는 장면 한두 줄로 시작 → 이 주제로 무엇이 달라지는지 →
   핵심 답을 곧바로 2~3문장으로 준다. "안녕하세요"·"요즘 AI가 빠르게 발전" 절대 금지. 첫 300자 안에 핵심 검색 키워드 포함.
2) 본문 <h2> 2~3개: 각 소제목은 독자가 실제로 검색할 법한 자연어 질문. 각 섹션은 앞에서 이어받아 한 걸음씩 깊어진다.
   - (A 활용법)이면: 실제 작동/설정 방식 → 그대로 따라 할 순서(정말 단계가 필요할 때만 <ol>) → 아는 사람만 아는 실전 팁과 흔한 실수 1~2개.
   - (B 정보전달)이면: 무엇이 바뀌었나(팩트의 수치·날짜와 함께) → 왜 지금 중요한가 → 독자의 시간·비용·업무에 주는 의미.
   - 어느 쪽이든 이 주제에서만 나오는 구체 정보를 최소 1개 넣는다. 아무 글에나 들어갈 범용 'ChatGPT 업무 활용' 일반론 금지.
   - 주제와 관련된 솔직한 한계·주의는 별도 경고 박스로 빼지 말고 본문 흐름 안에 1~2문장으로 녹인다.
3) 그다음 <h2>자주 묻는 질문</h2> 아래에 아래 형식 그대로 FAQ 3개(각 답 150자 이내, 확인된 내용만):
<div class="faq-section">
  <article class="faq-item"><h3 class="faq-q">독자의 실제 검색 질문</h3><p class="faq-a">빠르고 명확한 답</p></article>
  (총 3개)
</div>
4) 닫는 문단: 결론을 다시 반복하지 말 것. "무엇을 AI에 맡기고 무엇을 사람이 직접 확인할지"를 1~2문장으로.
   이어서 독자가 스스로 확인해야 할 것(요금·정책처럼 자주 바뀌는 것)을 아래 블록으로 출력(id·class 문자열 정확히 유지, 이 주제에 특정된 내용만):
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
  <div class="confirmed-section"><h3>지금까지 확인된 것</h3><ul><li>이 주제에서 사실로 확정된 것 3개</li></ul></div>
  <div class="check-needed-section"><h3>직접 확인할 것</h3><ul><li>자주 바뀌어 독자가 직접 봐야 하는 것 3개</li></ul></div>
</section>

[표 1개는 반드시 — 단, 주제에 밀착된 것으로]
본문 흐름 안에 이 주제에 실제로 쓸모 있는 표(<table>) 딱 1개를 자연스럽게 넣는다.
저장해두고 다시 꺼내 볼 만한 것 — 예: 설정 항목·경로 정리, 단계별 할 일, 상황별 선택 기준,
적용 전/후 비교, 무료 한도 등. 표 앞뒤로 한두 문장을 붙여 흐름과 이어지게 한다.
(주제와 무관한 ChatGPT/Claude 나열식 비교표는 금지 — 어디까지나 이 주제의 실용 정보를 담은 표)
{asset_directive}
[하지 않을 것]
- 요약 카드 표(summary-card), 정형 카드 블록을 의무적으로 나열하지 않는다. 표는 위 1개면 충분.
- 주제와 무관한 ChatGPT/Claude/Gemini 나열·비교, "프롬프트 5개" 나열, 마감 재촉 박스(deadline-box) 금지.
- 같은 안내(예: "설정을 켜세요")를 여러 섹션에서 반복하지 않는다 — 가장 적합한 곳에서 한 번만.

출력 규칙:
- div.post-content 태그 없이 내부 HTML만 출력
- 소제목은 <h2>, 세부는 <h3> (자연어 질문형)
- Markdown 금지, HTML entity 코드(&#숫자;) 금지, 본문 해시태그 금지"""


# 'AI 자동화 실험실' 유형(도구 비교·비용 계산·자동화 실전) 글에서만 켜지는 지시.
# 일반 뉴스/정보 글은 담백하게 두고(양식화 방지), 이 유형에서만 저장용 '무기'를 요구한다.
_ASSET_RICH_DIRECTIVE = """
[이 글은 'AI 자동화 실험실' 유형 — 저장용 도구(무기)를 실제 수치로 채운다]
이 주제는 도구 비교·비용·자동화 실전에 관한 것이다. 독자가 저장해 다시 꺼내 쓰는 '무기'를,
주제에 맞는 것으로 1~2개만 골라 실제 항목·수치로 채운다(다섯 개를 다 넣어 양식처럼 만들지 말 것):
 - 비용 계산: 공식(입력·출력 토큰 × 모델 단가)과 예시 계산을 <table>로. "YYYY년 M월 기준"과
   "정확한 가격은 공식 페이지에서 확인" 문구를 붙인다. 팩트에 단가가 없으면 지어내지 말고 계산 '방법'만 제시한다.
 - 도구 비교표: 이 주제의 도구/방식만 비교(범용 ChatGPT/Claude 나열 금지). 열은 독자의 선택 기준(속도·비용·한도·용도).
 - 체크리스트: 발행 전·설정 전 점검 항목을 <ul>로. 일반론("검수하라") 금지, 이 주제에서만 통하는 항목.
 - 재사용 템플릿: 그대로 복사해 쓰는 프롬프트·설정 예시를 <pre> 블록 1개로.
이 유형에서는 표를 2개까지 허용한다(계산 1 + 비교 1). 그 외에는 여전히 표 남발 금지.
[실험 로그·실패 사례 규칙 — 정직성 최우선]
 - '내가 해보니 몇 초/몇 원' 같은 1인칭 실측·수익 주장 금지(검증 불가로 발행 차단). 대신 독자가 직접
   돌려볼 '실험 설계'를 준다: 무엇을·어떤 조건으로·무엇을 측정할지. 결과 숫자는 독자가 채우도록 기준만 남긴다.
"""

# 이 키워드가 제목/주제/앵글에 있으면 위 지시를 켠다. 뉴스 글에 우연히 걸려도
# 계산·표는 품질 게이트가 어차피 선호하므로 해가 없다(보수적일 필요 없음).
_ASSET_RICH_KEYWORDS = (
    "비용", "요금", "계산", "api", "토큰", "단가", "자동화", "파이프라인", "워크플로",
    "도구 비교", "비교표", "cursor", "codex", "claude code", "제휴", "한도",
    "임시저장", "자동발행", "자동 발행", "실험", "100개", "대체 루트", "프롬프트 템플릿",
)


def _asset_rich_directive(title: str, topic: str, category: str, raw: dict) -> str:
    """도구·비용·자동화 유형이면 무기 지시를 반환, 아니면 빈 문자열."""
    angle = str(
        raw.get("angle_type") or (raw.get("search_angle") or {}).get("angle_type") or ""
    ).lower()
    blob = f"{title} {topic} {category} {angle}".lower()
    return _ASSET_RICH_DIRECTIVE if any(k in blob for k in _ASSET_RICH_KEYWORDS) else ""


class LlmContentService:
    """LLM 폴백 체인으로 고품질 블로그 HTML을 생성한다."""

    def __init__(
        self,
        google_search_api_key: str = "",
        google_search_cx: str = "",
        enable_custom_search: bool | None = None,
    ) -> None:
        if enable_custom_search is None:
            enable_custom_search = os.getenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "false").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self._enable_custom_search = bool(enable_custom_search)
        self._search_api_key = (
            (google_search_api_key or os.getenv("GOOGLE_SEARCH_API_KEY", ""))
            if self._enable_custom_search
            else ""
        )
        self._search_cx = (
            (google_search_cx or os.getenv("GOOGLE_SEARCH_CX", ""))
            if self._enable_custom_search
            else ""
        )

    # ─── Public API ───────────────────────────────────────────────────────────

    def generate_html(
        self,
        *,
        title: str,
        topic: str,
        category: str = "AI활용",
        content_type: str = "",
        labels: list[str] | None = None,
        hashtags: list[str] | None = None,
        reader_questions: list[str] | None = None,
        raw: dict | None = None,
    ) -> str | None:
        """LLM으로 블로그 HTML 생성. 실패 시 None 반환."""
        today = datetime.now().strftime("%Y.%m.%d")
        raw = raw or {}

        # 1. Google Search로 실제 정보 수집
        facts = self._gather_facts(topic)

        # 2. 독자 질문 목록 구성
        questions_raw = list(reader_questions or [])
        if not questions_raw:
            questions_raw = list(raw.get("reader_search_questions") or [])
        if not questions_raw:
            questions_raw = [f"{topic}이란 무엇인가요?", f"{topic} 대상은 누구인가요?"]
        questions_str = "\n".join(f"- {q}" for q in questions_raw[:6])
        content_angle = raw.get("content_angle") if isinstance(raw.get("content_angle"), dict) else {}
        issue_profile = raw.get("issue_content_profile") if isinstance(raw.get("issue_content_profile"), dict) else {}
        if not issue_profile:
            issue_profile = IssueContentProfileService().build_profile(
                topic=topic,
                summary=str(raw.get("summary") or ""),
                content_type=content_type or str(content_angle.get("content_type") or ""),
                topic_group=str(raw.get("topic_group") or content_angle.get("topic_group") or ""),
                raw=raw,
            )
        issue_profile_prompt = IssueContentProfileService.prompt_block(issue_profile)
        reader_interest_prompt = ReaderInterestBriefService.prompt_block(
            raw.get("reader_interest_brief") if isinstance(raw.get("reader_interest_brief"), dict) else {}
        )

        prompt = _USER_PROMPT_TMPL.format(
            title=title,
            topic=topic,
            today=today,
            category=category,
            facts=facts or "(검색 결과 없음 — 알려진 사실 기반으로 작성)",
            questions=questions_str,
            reader_interest_prompt=reader_interest_prompt,
            issue_profile_prompt=issue_profile_prompt,
            asset_directive=_asset_rich_directive(title, topic, category, raw),
        )

        # 3. LLM 폴백 체인
        content_html = self._run_fallback_chain(prompt)
        if not content_html:
            logger.warning("LlmContentService: 모든 provider 실패")
            return None

        # 3-1. HTML entity artifact 정제 — LLM이 &#숫자 형태로 이모지를 삽입하는 것을 방지
        content_html = _clean_entity_artifacts(content_html)

        # 3-2. overclaim 트리거 구문 중화: news_quality_gate는 '검수 없이', '무조건 써야',
        # '완벽하게 대체', '모든 업무를 자동', '수익 보장'을 문맥 없이 차단한다. LLM이
        # 정당한 경고("검수 없이 쓰면 위험")로 써도 걸리므로, 뜻을 보존한 채 게이트 패턴만
        # 깨는 결정적 치환을 적용한다(프롬프트 지침만으론 불안정).
        for _pat, _repl in _OVERCLAIM_SOFTENERS:
            content_html = _pat.sub(_repl, content_html)

        # 4. FAQ 추출 (JSON-LD용)
        schema_faq = _extract_faq(content_html)

        # 5. meta description 추출
        meta_desc = _extract_meta_description(content_html, title)

        # 6. 완성 HTML 조립
        return render_full_post(
            title=title,
            content_html=content_html,
            category=category,
            content_type=content_type,
            labels=labels,
            hashtags=hashtags,
            meta_description=meta_desc,
            today=today,
            schema_faq=schema_faq,
        )

    # ─── Internal ─────────────────────────────────────────────────────────────

    def gather_facts(self, topic: str) -> str:
        """실시간 팩트 수집 공개 진입점 — ai_slot_enricher 등 외부 모듈용.

        슬롯 보강 LLM이 모델 지식만으로 쓰면 수치·요금이 환각될 수 있어,
        생성 전에 이 결과를 프롬프트에 주입해 근거를 제공한다.
        """
        return self._gather_facts(topic)

    def _gather_facts(self, topic: str) -> str:
        """실제 팩트 수집: Custom Search(키 있을 때) → Google News RSS(키 불필요) 폴백.

        Gemini 그라운딩 폴백은 제거됨 — 운영 방침상 LLM은 OpenRouter/OpenAI만 쓰고
        GOOGLE_AI_API_KEY는 더 이상 사용하지 않는다. RSS 폴백은 키가 전혀 필요
        없어서 어떤 환경에서든 최신 헤드라인 근거를 확보할 수 있다.
        """
        facts = ""
        if self._search_api_key and self._search_cx:
            facts = self._custom_search(topic)
        if not facts:
            facts = self._google_news_rss_facts(topic)
        return facts

    def _google_news_rss_facts(self, topic: str) -> str:
        """Google News RSS에서 주제 관련 최신 헤드라인을 수집한다 (API 키 불필요)."""
        try:
            import xml.etree.ElementTree as ET
            query = urllib.parse.quote(topic)
            url = (
                f"https://news.google.com/rss/search?q={query}"
                "&hl=ko&gl=KR&ceid=KR:ko"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
            lines: list[str] = []
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                source = (item.findtext("source") or "").strip()
                if not title:
                    continue
                suffix = " · ".join(p for p in (source, pub_date[:16]) if p)
                lines.append(f"- {title}" + (f" ({suffix})" if suffix else ""))
                if len(lines) >= 6:
                    break
            result = "\n".join(lines)
            if result:
                logger.info("LlmContentService: Google News RSS 팩트 %d건", len(lines))
                return f"[최근 관련 뉴스 헤드라인]\n{result}"
            return ""
        except Exception as exc:
            logger.warning("LlmContentService: Google News RSS 팩트 수집 실패 — %s", exc)
            return ""

    def _custom_search(self, topic: str) -> str:
        """Google Custom Search API로 스니펫 수집."""
        try:
            query = f"{topic} {datetime.now().year}"
            url = (
                "https://www.googleapis.com/customsearch/v1"
                f"?key={self._search_api_key}"
                f"&cx={self._search_cx}"
                f"&q={urllib.parse.quote(query)}"
                "&num=5&hl=ko&gl=kr"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            snippets = []
            for item in data.get("items", [])[:5]:
                t = item.get("title", "")
                s = item.get("snippet", "").replace("\n", " ").strip()
                if s:
                    snippets.append(f"[{t}]\n{s}")
            result = "\n\n".join(snippets)
            logger.info("LlmContentService: Custom Search %d개 (%d자)", len(snippets), len(result))
            return result
        except urllib.error.HTTPError as exc:
            logger.warning(
                "LlmContentService: Custom Search 실패 — HTTP %s: %s",
                exc.code,
                _google_api_error_summary(exc),
            )
            return ""
        except Exception as exc:
            logger.warning("LlmContentService: Custom Search 실패 — %s", exc)
            return ""

    def _run_fallback_chain(self, user_prompt: str) -> str | None:
        """Provider 폴백 체인으로 LLM 호출 (cli_news 전용 system_prompt 사용)."""
        return self.call_with_fallback(user_prompt, system_prompt=None, min_chars=200)

    def call_with_fallback(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        min_chars: int = 200,
        validator: Any = None,
    ) -> str | None:
        """Provider 폴백 체인으로 LLM 호출 — 외부 system_prompt 주입 가능.

        OpenRouter 무료 (1차→2차) → OpenAI 유료 fallback 순서로 호출한다.
        ai_content_service 등 다른 모듈이 같은 비용 절감 정책을 따르기 위한 공용 진입점.

        validator: 응답을 추가 검증하는 callable(text). 예외 raise 시 다음 provider로 fallback.
                   응답이 길이만 통과하고 형식(JSON 등)이 깨진 경우 자동 fallback에 사용.
        """
        for provider in _PROVIDERS:
            api_key = os.getenv(provider["api_key_env"], "").strip()
            if not api_key:
                logger.debug("LlmContentService: %s — API키 없음, skip", provider["name"])
                continue
            # 순간 혼잡(429/타임아웃)이 마지막 유료 폴백까지 겹치면 그대로 발행이
            # 통째로 스킵되므로, provider 종류와 무관하게 최소 1회는 재시도한다.
            # 무료 모델은 2회, 유료(마지막 보루)도 2회 — 유료는 비용 때문에 그 이상은 안 늘린다.
            attempts = 2
            for attempt in range(1, attempts + 1):
                try:
                    result = self._call_provider(provider, api_key, user_prompt, system_prompt)
                    if not result or len(result.strip()) <= min_chars:
                        logger.warning(
                            "LlmContentService: %s 응답 너무 짧음 (%d자, min %d)",
                            provider["name"], len(result or ""), min_chars,
                        )
                        break  # 짧은 응답은 재시도로 나아질 가능성이 낮음 → 다음 provider
                    if validator is not None:
                        try:
                            validator(result)
                        except Exception as ve:
                            logger.warning(
                                "LlmContentService: %s validator 실패 — %s. 다음 provider 시도",
                                provider["name"], ve,
                            )
                            break  # 형식 불량도 provider 특성 — 다음 provider
                    logger.info(
                        "LlmContentService: %s 성공 (%d자)",
                        provider["name"], len(result),
                    )
                    return result
                except Exception as exc:
                    logger.warning(
                        "LlmContentService: %s 실패 (시도 %d/%d) — %s",
                        provider["name"], attempt, attempts, exc,
                    )
                    if attempt < attempts:
                        # 429(rate limit)는 짧은 대기로 안 풀리는 경우가 많아 더 길게 기다린다.
                        time.sleep(6.0 if "429" in str(exc) else 2.5)

        return None

    def _call_provider(
        self,
        provider: dict[str, Any],
        api_key: str,
        user_prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Configured LLM provider 호출."""
        return self._call_openai_compatible_provider(provider, api_key, user_prompt, system_prompt)

    def _resolve_provider_model(self, provider: dict[str, Any]) -> str:
        model_env = str(provider.get("model_env") or "").strip()
        if model_env:
            env_model = os.getenv(model_env, "").strip()
            if env_model:
                return env_model
        model = provider.get("model")
        if model is None:
            return os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
        return str(model).strip()

    def _call_openai_compatible_provider(
        self,
        provider: dict[str, Any],
        api_key: str,
        user_prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """OpenAI-compatible chat completions API 호출."""
        base_url = provider["base_url"]
        model = self._resolve_provider_model(provider)
        if base_url is None:
            base_url_env = str(provider.get("base_url_env") or "OPENAI_BASE_URL").strip()
            default_base_url = str(provider.get("default_base_url") or "https://api.openai.com/v1").strip()
            custom_url = os.getenv(base_url_env, default_base_url).strip().rstrip("/")
            # /chat/completions 경로 보정
            if not custom_url.endswith("/chat/completions"):
                base_url = custom_url + "/chat/completions"
            else:
                base_url = custom_url

        max_tokens = int(provider.get("max_tokens") or 8192)
        model_name = str(model or "")
        base_url_str = str(base_url or "")
        official_openai_gpt5 = "api.openai.com" in base_url_str and model_name.startswith("gpt-5")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt if system_prompt is not None else _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            # 네이버 글 재작성 시 3500~4500자 JSON 응답이 잘리지 않도록 provider별 한도를 사용한다.
        }
        if official_openai_gpt5:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = 0.7
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            **provider.get("extra_headers", {}),
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            base_url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())

        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices in response: {result}")
        content = choices[0].get("message", {}).get("content", "")
        return _clean_llm_output(content)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_llm_output(text: str) -> str:
    """마크다운 코드블록 제거 등 LLM 출력 정리."""
    text = text.strip()
    # ```html ... ``` 제거
    text = re.sub(r'^```(?:html)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


def _clean_entity_artifacts(html: str) -> str:
    """LLM 출력 HTML에서 노출 위험 entity artifact를 제거한다.

    처리 순서:
    1. &amp;#숫자  → &#숫자  (이중 escape 해소)
    2. &#숫자;     → unicode 문자 (세미콜론 있는 정상 entity 디코딩)
    3. &#숫자(세미콜론 없음) → unicode 문자 (불완전 entity 디코딩)
    HTML 태그 구조·속성은 변경하지 않는다.
    """
    # 1) 이중 escape 해소: &amp;#숫자 → &#숫자
    result = re.sub(r'&amp;(#\d+)', r'&\1', html)
    # 2) 세미콜론 있는 숫자 entity → unicode
    def _decode_entity_with_semi(m: re.Match) -> str:
        code = int(m.group(1))
        try:
            return chr(code) if 0 < code < 0x110000 else m.group(0)
        except (ValueError, OverflowError):
            return m.group(0)
    result = re.sub(r'&#(\d+);', _decode_entity_with_semi, result)
    # 3) 세미콜론 없는 entity → unicode (공백·태그·줄끝 앞에 있는 경우만)
    def _decode_entity_bare(m: re.Match) -> str:
        code = int(m.group(1))
        try:
            return chr(code) if 0 < code < 0x110000 else ''
        except (ValueError, OverflowError):
            return ''
    result = re.sub(r'&#(\d+)(?=\s|<|$)', _decode_entity_bare, result)
    return result


def _extract_faq(html: str) -> list[dict[str, str]]:
    """HTML에서 FAQ Q&A 쌍을 추출한다 (JSON-LD 생성용)."""
    faqs: list[dict[str, str]] = []
    q_matches = re.findall(r'class="faq-q"[^>]*>(.*?)</div>', html, re.DOTALL)
    a_matches = re.findall(r'class="faq-a"[^>]*>(.*?)</div>', html, re.DOTALL)
    for q, a in zip(q_matches, a_matches):
        q_clean = re.sub(r'<[^>]+>', '', q).strip()
        a_clean = re.sub(r'<[^>]+>', '', a).strip()
        if q_clean and a_clean:
            faqs.append({"Q": q_clean[:200], "A": a_clean[:400]})
    return faqs[:5]


def _extract_meta_description(html: str, title: str) -> str:
    """HTML에서 첫 번째 p 태그 텍스트를 meta description으로 추출한다."""
    m = re.search(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
    if m:
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if 80 <= len(text) <= 160:
            return text
        if len(text) > 160:
            return text[:157] + "..."
    # 제목 기반 fallback
    return f"{title} — 대상·신청방법·일정을 한눈에 정리했습니다."[:160]
