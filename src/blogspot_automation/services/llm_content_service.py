"""LLM 기반 블로그 콘텐츠 생성 서비스.

Fallback chain (2026-07-20 재정렬 — 유료 폴백 빈도를 낮추기 위해 무료 단계를
3중으로 늘렸다. OpenRouter 무료 티어는 계정 평생 충전액이 $10 미만이면 하루
50회로 제한되고(충전 시 1000회), 고정 모델 하나에만 의존하면 그 모델의 공급자
쪽 용량 소진에 그대로 노출된다 — 둘 다 유료 폴백을 앞당기는 실제 원인이었다):
  1. Claude Code CLI, 구독 인증 (CLAUDE_CODE_OAUTH_TOKEN — 토큰당 과금 없음,
     `claude setup-token`으로 발급. Cloud Run 등 GHA 이외 환경 전용 — 이 키가
     없으면 조용히 skip되고 기존 체인으로 폴백된다)
  2. OpenRouter primary — 고정 무료 모델 (OPENROUTER_API_KEY, OPENROUTER_MODEL)
  3. OpenRouter secondary — 고정 무료 대체 모델 (OPENROUTER_MODEL_FALLBACK)
  4. OpenRouter free router (`openrouter/free`) — 그 순간 여유 있는 무료 모델로
     자동 라우팅, 특정 모델 용량 소진에 안 걸림
  5. Official OpenAI API fallback (OPENAI_API_KEY, OPENAI_MODEL) — 최종 유료
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape as _html_unescape
from typing import Any

from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.issue_content_profile_service import IssueContentProfileService
from blogspot_automation.services.kst_clock import kst_today
from blogspot_automation.services.news_topic_service import _google_api_error_summary
from blogspot_automation.services.readability_service import (
    is_below_target as _readability_below_target,
    measure_html as _measure_readability_html,
)
from blogspot_automation.services.reader_interest_brief_service import ReaderInterestBriefService
from blogspot_automation.templates.blog_post_template import render_full_post

logger = logging.getLogger(__name__)

_TIMEOUT = 45  # seconds

# ─── Provider 설정 ────────────────────────────────────────────────────────────
# 순서 = 폴백 체인 우선순위 (운영자 정책: 항상 무료/구독 먼저, 실패 시에만 유료).
#   0) Claude Code CLI 구독 인증 (2026-07-20, GHA Actions 분당 한도 소진 대응—
#      Cloud Run 등 컴퓨터/GHA 무관 환경에서 토큰 과금 없이 Pro/Max 구독으로 생성)
#   1) OpenRouter 무료 플래그십 (기본: nvidia nemotron-3-ultra 550B — 2026-07 기준
#      OpenRouter 무료 모델 중 최상위 추론 성능)
#   2) OpenRouter 무료 2차 (1차가 429 등으로 막힐 때 다른 무료 모델로 한 번 더)
#   3) OpenAI 유료 (무료가 모두 실패한 날만 — 정적 템플릿 폴백/발행 스킵 방지)
_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "claude_code_cli",
        "provider_type": "claude_code_cli",
        "api_key_env": "CLAUDE_CODE_OAUTH_TOKEN",
        "model_env": "CLAUDE_CODE_CLI_MODEL",
        "model": None,  # None이면 claude CLI 기본 모델 사용
        "free": True,
        # claude -p는 풀 하네스(컨텍스트 로딩 등) 기동 비용이 있어 API 직접
        # 호출보다 느리다 — 2000~3000단어 HTML 생성 기준 여유 있게 잡음.
        "timeout": 180,
    },
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
        # 2026-07-20: 1·2차 무료 모델이 둘 다 고정 모델이라, 그 모델의 공급자 쪽
        # 용량 소진(예: "Worker local total request limit reached")이나 카탈로그
        # 이탈에 그대로 노출됐다 — OpenAI 유료 폴백 빈도가 늘어난 원인 중 하나.
        # OpenRouter 공식 무료 라우터(`openrouter/free`)는 요청 시점에 여유 있는
        # 무료 모델로 자동 라우팅한다 — 유료로 넘어가기 전 마지막 무료 시도.
        "name": "openrouter_free_router",
        "provider_type": "openai_compatible",
        "base_url": None,
        "base_url_env": "OPENROUTER_BASE_URL",
        "default_base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "model": "openrouter/free",
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
        # 유료 최종 폴백까지 read timeout으로 죽으면 그날 발행이 0이 된다.
        # gpt-5 계열이 12,000 completion tokens를 채우는 데 45초를 넘는 일이
        # 상시 관측됨(2026-07-19~20 전 실행 "The read operation timed out")
        "timeout": 300,
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

[제품 버전·세대 숫자 규칙 — 가장 자주 나는 사고, 반드시 지킨다]
- 제품의 버전·세대 숫자(예: "제미나이 3.5", "GPT-5.2", "클로드 4.1", "3.5 프로", "3.5 플래시")는 [검색 팩트]에 그 숫자·표기가 그대로 있을 때만 쓴다. 팩트에 없으면 버전 숫자를 지어내지 말고 제품명만 쓴다(예: "구글 제미나이", "오픈AI의 최신 모델"). 세대 번호를 추측해서 올리거나(3→3.5→5) 새 라인업(프로/플래시/울트라)을 만들어내지 않는다.
- 팩트에 없는 출시일·가격(예: "100만 토큰당 $0.15")·벤치마크 순위·점수는 절대 지어내지 않는다. "정확한 버전·출시 시점·가격은 공식 발표 기준으로 확인"이라고 처리한다.
- 제목에 쓴 제품명·버전 표기와 본문에 쓴 표기는 글 전체에서 완전히 동일해야 한다(제목이 "플래시"인데 본문이 "프로"가 되는 불일치 금지). 한 글 안에서 같은 제품을 여러 버전으로 섞어 부르지 않는다.
- 확신이 서지 않는 제품·버전이면 그 제품을 글의 중심 소재로 삼지 말고, 팩트에서 확인된 범위 안에서 쓴다.
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
3-1. 근거 신선도: 발행 시점 기준 12개월 이상 지난 조사·통계·발표는 글의 핵심 근거(도입부 훅, 제목 뒷받침, 결론 근거)로 쓰지 않는다. 오래된 수치는 배경 맥락으로만 짧게 언급하고, 도입부와 결론은 [검색 팩트]의 가장 최근 사실이 끌고 가야 한다. 최근 팩트가 부족하면 오래된 조사를 부풀리지 말고 "직접 확인할 것" 항목으로 돌린다.
4. 저장 가치·공부값 의무 (이 글의 존재 이유): 독자가 "아, 이건 몰랐네"라고 느낄 구체적 지식이 최소 2개는 있어야 한다. 저장해 다시 꺼내 쓸 실제 정보 — 정확한 설정 경로·값, 계산 공식과 예시, 원인과 결과("A를 켜면 B가 20% 줄어든다, 왜냐하면…"), 이 주제에서만 통하는 순서·조합·함정. 추상적 조언이 아니라 "그래서 구체적으로 무엇을 어떻게"까지 내려가야 한다.
   다음처럼 누구나 이미 아는 뻔한 문장으로 분량을 채우면 실패다(금지): "범위를 좁혀라", "먼저 기준을 세워라", "결과를 검토하라", "반복되는 일부터 시작하라", "도구를 과신하지 마라", "상황에 따라 다르다"로 끝내기. 이런 말을 쓸 거면 반드시 그 뒤에 이 주제만의 구체적 방법·수치·예시를 붙여 실제 지식으로 만든다.
   한 문단을 쓸 때마다 자문한다: "이 문단이 독자에게 새로 가르치는 게 있나, 아니면 당연한 말인가?" 당연한 말이면 지우거나 구체화한다.
4-2. 독자 계약 (쓰기 전에 정한다): 본문을 쓰기 전에 이 한 문장을 속으로 완성한다 — "이 글을 읽은 독자는 (1)무엇을 새롭게 이해하고, (2)무엇을 스스로 판단할 수 있게 되고, (3)무엇을 오늘 직접 해볼 수 있는가." 세 칸 중 하나라도 못 채우면 그 부분의 깊이가 부족하다는 신호이니 팩트를 다시 보고 채운 뒤 쓴다. 닫는 문단은 이 계약을 회수해야 한다 — 독자가 얻은 판단과 다음 행동이 닫는 문단에서 명확해야 한다.
5. 초보자가 막히는 지점: 이 주제에서 실제로 처음 시도하면 막힐 지점을 1~3개 짚고, 각각 "왜 막히는지(원인)"와 "어떻게 넘어가는지(해결)"를 함께 쓴다. 어느 글에나 붙는 범용 오해(도구 과신, 미검수)가 아니라 이 도구·기능에서만 나오는 구체적 걸림돌이어야 한다.
5-1. 판단 기준 의무: 도구·기능을 다루면 무조건 추천으로 끝내지 않는다. "지금 써볼 만한 사람(조건)"과 "기다리거나 기존 방식이 나은 사람(조건)"을 구체 조건으로 구분해준다. 이 구분이 이 블로그가 보도자료 요약과 달라지는 지점이다 — 조건은 요금제·사용량·업무 유형처럼 독자가 자기 상황을 대입할 수 있는 것이어야 한다.
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
- AI 상투 문구 금지 — 다음 표현과 그 변형을 쓰지 않는다: "게임 체인저", "귀추가 주목", "단순한 도구를 넘어", "무궁무진한 가능성", "우리의 삶을 혁신", "빠르게 변화하는 디지털 시대", "새로운 시대를 열다", "혁신적인 변화의 물결", "주목할 만한 행보". 근거 없는 감탄과 수사적 질문 남발도 같은 부류다. 이런 문장이 나오는 자리는 항상 구체적 사실이나 판단으로 바꿀 수 있다.
- 과한 이모지 금지 (섹션 아이콘 수준만 허용).

[언어·완결성 규칙 — 어기면 발행이 자동 차단된다]
- 전체를 한국어로 쓴다. 영어 문장·영어 도입부 금지. 영문은 제품명·기능명 등 고유명사, 코드, 숫자 단위(예: API, RAG, $0.15)에만 허용하고 설명 문장은 반드시 한국어.
- 글을 처음부터 끝까지 완결한다. 문장·소제목·표·FAQ 답을 중간에서 끊지 않는다. 마지막 블록까지 닫는 태그를 정확히 닫는다.
- 도입부/앞 문단의 문장이나 문장 조각을 뒤에서 다시 반복하지 않는다. 같은 문장을 두 번 이상 쓰지 않는다(모델이 같은 구절을 되풀이하는 '반복 루프'는 실패다).
- <h2>·<h3> 소제목은 한 줄짜리 짧은 질문/구절이다. 소제목 안에 긴 설명 문장이나 도입부 문장을 넣지 않는다.

[출력 전 자체 검수 — 반드시 수행 후 출력]
1) 확인 안 된 가격·날짜·버전·기능·메뉴명을 단정한 문장이 있는가 → 삭제하거나 완화했는가
2) 제품 버전·세대 숫자가 팩트에 근거하는가, 제목과 본문의 제품명·버전 표기가 일치하는가
3) 같은 의미를 반복한 문단, 되풀이된 문장, 잘린 문장·FAQ 답이 있는가 → 제거·완결했는가
3-1) 독자가 이 글에서 '새로 배우는' 구체적 지식이 최소 2개 있는가 — 뻔한 일반론만 있으면 실패, 구체화했는가
3-2) 이 글의 도구·기능 이름을 다른 도구 이름으로 바꿔도 글이 그대로 성립하는가 → 성립하면 주제 특정 정보가 부족한 것이니 이 주제에서만 나오는 사실·조건·함정을 더 넣었는가
4) 독자가 오늘 바로 해볼 수 있는 내용이 있는가, "지금 써볼 사람 / 기다릴 사람" 판단 기준이 있는가
5) 수익·개인정보·보안·법률·저작권을 과하게 단정하지 않았는가
6) 오타·띄어쓰기·조사(을/를, 이/가) 오류·중복 어절을 한 번 더 훑어 교정했는가 — 자동 발행이므로 사람이 고쳐줄 수 없다

[HTML 구조·시각 요소 — 가독성을 위해 적극 활용하되, 채우기용 남발은 금지]
이 글은 문단만 늘어놓는 '벽 같은 글'이 아니라, 스타일이 입혀진 HTML 요소로 눈에 잘 들어오게 만든다.
시스템에 아래 클래스의 예쁜 스타일이 이미 준비돼 있으니, 내용에 실제로 도움이 될 때 그 클래스를 정확히 써서 시각적 리듬을 준다(구체 사용법은 아래 작성 지시에 있다). 단, 내용 없이 칸만 채우는 카드 나열은 금지다.
- 본문 어디에도 해시태그(#단어)를 쓰지 않는다 — 해시태그는 시스템이 하단 전용 영역에 자동 삽입한다.
- '제가/직접 써봤더니'류 개인 경험담, 구체 수익·매출 금액 주장(월 N만원 수익 등) 절대 금지 — 검증 불가 주장으로 발행이 차단된다.
- 본문에 "SEO 최적화"·"AEO"·"GEO"·"SGE"·"CTA" 같은 내부 용어를 노출하지 않는다.
- Markdown 형식 절대 금지 (HTML 태그만 사용)
- HTML entity 코드(&#숫자; 형태) 절대 사용 금지 — 이모지/아이콘은 유니코드 문자(✅ ✓ 🎯 등) 직접 사용.
- 기계적인 템플릿 텍스트("이슈 정의", "핵심 내용") 금지 -> 실제 독자의 질문 형태(자연어)로 <h2> 소제목 구성."""

# ─── 영어 본문 길이 계약 (2026-08-03 통일) ────────────────────────────────────
# 이전에는 하한이 세 군데로 갈려 있었다: 프롬프트 본문 "1,600+ words", 프롬프트
# 마지막 체크 "under 1,500 rejected", 검증기 `word_count < 1400`. 모델은 가장
# 낮은 숫자(그리고 자기가 세는 방식)를 목표로 삼아 1,336~1,393단어를 냈고, 그때마다
# 초안을 통째로 폐기하고 처음부터 재생성했다(호출 1회당 ~2분, 재시도 6회 안에서 반복
# → 30분 타임아웃의 주범). 이제 하한은 이 상수 하나가 유일한 소스이고, 프롬프트는
# 하한보다 확실히 위인 목표 구간을 요구한다(여유 200~700단어).
#
# 참고: 발행 게이트(news_quality_gate)에는 영어 단어 수 검사가 없다 — 게이트의
# 길이 조건은 `article_body_too_short`(plain text 800자)뿐이라 이 하한과 충돌하지
# 않는다. 즉 이 값은 애드센스 thin-content 방어를 위한 자체 계약이다.
EN_MIN_BODY_WORDS = 1500
EN_TARGET_BODY_WORDS_MIN = 1700
EN_TARGET_BODY_WORDS_MAX = 2200

# 최후 수단 하한(2026-08-26). 전 provider가 길이 때문에 실패했을 때, 그날 발행을
# 통째로 버리는 대신 "가장 긴 초안"이 이 값을 넘으면 채택한다.
#
# 근거(2026-08-26 GHA 리허설 실측): 후보 4개가 연속으로 1119·1153·1277·1392단어를
# 냈고 전부 폐기돼 클러스터 슬롯이 하루 밀렸다. 대안은 1500단어 글이 아니라
# **글 없음**이다. 1300단어는 어떤 기준으로도 thin content가 아니다.
#
# 값의 근거(2026-08-26, nemotron-3-ultra:free에 동일 프롬프트 12회):
#   1041 1152 1213 1357 1387 1409 1536 1681 1686 1692 1713 1719  (중앙값 1473)
#   하한 1500 → 6/12 통과, 하한 1300 → 9/12 통과.
# 분산이 크고 중앙값이 하한에 걸쳐 있는 게 문제의 본질이라, 프롬프트로는 못 고친다.
# 실제로 "섹션당 단어 예산" 프롬프트(7-9 섹션 × 180-260단어)를 6회씩 A/B로 재봤고
# 평균 1477 → 1454로 **개선 없음**(섹션만 잘게 쪼개졌다) — 그래서 도입하지 않았다.
# 같은 걸 다시 시도하지 말 것.
#
# 중요: 길이 미달(_WordCountShortfallError)에만 적용한다. 절단·한국어 혼입·FAQ
# 마크업 파손 같은 다른 검증 실패는 그대로 폐기한다 — 그건 짧은 게 아니라 깨진 것이다.
EN_ACCEPTABLE_BODY_WORDS = 1300


def _acceptable_body_words() -> int:
    """최후 수단 하한. 발행률을 보며 조절할 값이라 env로 뺀다."""
    raw = (os.getenv("EN_ACCEPTABLE_BODY_WORDS", "") or "").strip()
    try:
        return int(raw) if raw else EN_ACCEPTABLE_BODY_WORDS
    except ValueError:
        return EN_ACCEPTABLE_BODY_WORDS


def count_body_words(text: str) -> int:
    """영어 본문의 '단어 수'를 센다 (HTML 태그 제거 후 호출할 것).

    2026-08-03: 예전 정규식 `[A-Za-z][A-Za-z'’-]*`는 **숫자를 아예 세지 않았다**.
    이 블로그의 핵심 자산이 가격·한도·토큰 수치라, 데이터가 많은 글일수록 단어 수가
    깎여 불리해지는 역인센티브가 있었다("$20 a month for 200K tokens" = 4단어로 계산).
    지금은 사람이 세는 방식(공백으로 끊고, 영숫자를 하나라도 포함한 토큰만 셈)과
    같게 센다 — 발행 게이트에는 대응 계산이 없어 새 불일치가 생기지 않는다.
    """
    plain = re.sub(r"\s+", " ", text or "").strip()
    if not plain:
        return 0
    return sum(1 for token in plain.split(" ") if re.search(r"[A-Za-z0-9]", token))


# ─── 영어 모드 프롬프트 (2026-07-17 영어 전환) ────────────────────────────────
# 대상: 미국·영국·캐나다·인도 영어권 검색 독자 + AI 챗봇 인용(GEO).
# 수익 모델: 애드센스 단일 — thin content·낚시 제목·확인 안 된 수치가 최대 리스크.
_SYSTEM_PROMPT_EN = """You are the staff writer and quality editor for an English-language AI blog that publishes automatically to Blogspot.

MISSION: this is not a news-summary site. It is a practical reference that helps English-speaking readers choose, compare, price, fix, and apply AI tools using VERIFIED information. Every article must let the reader do at least one of these: pick a tool for their situation, judge a cost, solve an actual error or limit, understand verified numbers, or know what a change means for them specifically. If a draft achieves none of these, it is not worth publishing.

AUDIENCE: US-first English (US dollar prices, US availability by default); UK, Canada, and India readers are secondary. Whenever pricing, features, or availability can differ by market, say so plainly — "pricing may vary by region; check the official pricing page for your country." Never present a US price as universal.

Top priority: an article that is SAFE to auto-publish beats an article that is flashy. The blog is under AdSense review — thin content, clickbait, and unverified numbers are the fastest ways to fail.

[FACT SAFETY — the #1 rule for auto-published articles]
Never state any of the following unless it appears in the provided [SEARCH FACTS]: release dates, prices, plan names, free-tier limits, model names/version numbers, feature availability, menu paths, data-retention policies, country availability, default settings.
- SOURCE PRIORITY: official pricing pages > official release notes/changelogs > official docs > vendor blogs/newsrooms > reputable secondary coverage. Community posts (Reddit, X, forums) may inform which pain points to cover, but are NEVER the source of a price, limit, spec, or benchmark.
- Every price, limit, or spec you do state must carry an as-of date: "as of {month_year}" — and name the source in plain text (e.g. "per OpenAI's pricing page").
- If a number is not in the facts, do NOT invent it. Write "check the official pricing page for current rates" instead. One stale or invented price kills the article's credibility and its usefulness as a reference.
- HEDGE BUDGET: deferrals like "check the official page", "not published", "unconfirmed" are a last resort, not a writing style — the whole article may contain AT MOST 3 of them. If the facts can't support the full breadth the title promises, NARROW THE SCOPE: cover only the tools/plans whose numbers ARE verified and go deep on those. One tool with real numbers beats five tools with "check the official page". An article that mostly tells the reader to go look somewhere else is worthless and will be rejected automatically.
- Write about the AI tools themselves — never about the websites, GitHub tracker repos, or listicles that collect data about them. If the facts mainly describe a price-tracker project or a "top tools" roundup, extract the underlying tool facts and write about the tools. A reader searching for prices wants prices, not a tour of tracking projects; tracker/roundup sites may only be named as a source, never treated as the topic.
- NEVER invent product names, tool names, GitHub repositories, or URLs. Only name a specific tool, app, repo, or link if it appears in the provided [SEARCH FACTS]. If you want to point readers to a resource but have no verified URL, describe how to find it ("search GitHub for an open-source Etsy listing helper") instead of fabricating an owner/repo path or link — a made-up repo like "github.com/someuser/some-tool" that 404s destroys reader trust and will block publishing.
- Statistics: name the source, the year, and the scope (who/where was surveyed) next to every statistic — "According to [source]'s [year] survey of [scope], ..." — and never merge numbers from different surveys or methodologies into one comparison as if they measured the same thing.
- Never invent benchmarks, statistics, or survey results. NEVER write first-person testing claims — "I tested", "in my testing", "I personally used" — this publication cannot run hands-on tests, so any such sentence is fabricated. When a walkthrough helps, present it as a reproducible recipe the reader runs themselves: the exact prompt/settings, the expected output shape, and what to measure.
- Version/generation numbers: only use them exactly as written in the facts. Never guess the next version up. Product naming must be identical in title and body.

[BANNED — auto-publish gate will reject these]
- Affiliate links, promo codes, "buy through my link".
- Income guarantees ("guaranteed income", "get rich", "$X/month easily"), "100% safe", "works for everyone", "no review needed".
- Circumvention framing: "bypass the limit", "unlock paid features", "get around restrictions", "avoid detection", "exploit". Frame solutions as legitimate fixes instead — "reduce file size", "split large files", "fix upload errors", "what to do when X rejects your file". Same solution, lawful framing.
- Investment advice tied to specific stocks/coins, medical or legal judgments.
- AI-slop phrases and their variants: "game-changer", "revolutionize", "unlock the power", "harness the power", "in today's fast-paced world", "delve into", "it's important to note", "look no further", "elevate your", "seamlessly". Replace every one of them with a concrete fact or judgment.
- Clickbait: "you won't believe", "shocking", "insane".

[WRITING RULES]
1. English only. US blog register: short sentences, second person ("you"), active voice. No throat-clearing — never open with "In this article, we will..." or "AI is evolving rapidly". Start with the reader's situation or the direct answer.
1-0. PLAIN LANGUAGE (readability is a ranking factor): write for a smart friend, not a boardroom — 8th-grade reading level, everyday words, contractions (you're, it's, don't) welcome. Say "costs $20 a month", never "is priced at a monthly rate of $20". Define any technical term in plain words the first time it appears — "per-seat pricing (you pay separately for each team member)". If the topic itself is built out of specialist jargon (architecture patterns, framework names, protocol names), do not assume the reader already works in that specialty — translate every such term into a one-clause plain-English gloss the first time it appears, or cut it if it cannot be made concrete for a general reader in one clause. No academic connectors ("thus", "moreover", "functions as", "constructs", "concentrates on") — use "so", "also", "works as", "builds", "focuses on". Facts are raw material, not quotes: never copy sentences from [SEARCH FACTS] verbatim or wrap them in quotation marks — rewrite every fact in your own plain words. Quotation marks are only for words an actual named person said.
1-1. PARAGRAPH RHYTHM (readability contract): each paragraph is 2-3 sentences and at most 70 words; the opening paragraph stays under 60 words. NEVER write two consecutive <p> paragraphs on the same sub-idea without a visual break between them — a table, list, step card, callout box, or the who-for-cols block. If a section's content is a repeated pattern (multiple causes-and-fixes, multiple reader types, multiple tools) — not just a single flowing explanation — put it in a list or card block instead of stacking paragraphs; a section is not "explained better" by adding a second dense paragraph, it is explained better by breaking the second paragraph's content into scannable pieces. One idea per paragraph; when the idea grows, split the paragraph instead of stretching it. Never use <br> for line breaks inside prose.
    SHORT PARAGRAPHS DO NOT MEAN A SHORT ARTICLE: keep total length at {target_min}-{target_max} words by writing MORE paragraphs and sections, not longer ones. A typical section runs 2-3 short paragraphs plus a visual element. If you feel the article getting thin, add depth (another first-time blocker, another concrete calculation, another reader profile in the judgment) — never re-inflate paragraph size.
1-2. NO REPEATED FACTS: state each concrete fact (a name, number, date, or license/spec detail) only once in the whole article. The opening paragraphs, the Quick Verdict box (when present), and the closing confirmed-facts list must each contribute DIFFERENT facts — never restate a fact from an earlier section just to fill a required block. If you cannot find 3 genuinely new confirmed facts for the closing block that were not already stated, list fewer than 3 rather than repeating one.
2. Opening = the direct answer. The first paragraph answers the title's question in 2-3 sentences WITH the key number(s). Write it so a search user — or an AI search system assembling an answer — can lift it accurately on its own. A clear, sourced, self-contained answer raises the chance of being cited; nothing guarantees it, so optimize for the reader first.
3. Depth duty: at least 2 things a knowledgeable reader would not already know — exact limits, price math with a concrete calculation, cause-and-effect ("turning on X cuts Y by ~Z because..."), order-of-operations that only applies to this tool. If a paragraph teaches nothing new, cut it or make it concrete.
4. Judgment duty: never end on "it depends". Give explicit conditions: "Use it now if [plan/usage/job condition]. Skip it if [condition]." This is what separates the article from a press-release summary.
5. Beginner blockers: name 1-3 places where a first-time user actually gets stuck WITH the cause and the fix — specific to this tool, not generic AI advice.
6. Freshness: facts older than 12 months may only appear as background, never as the hook or the conclusion's basis.
7. Topic specificity: if the topic names a tool/feature, every section must be about THAT tool. If you could swap the tool name and the article still reads fine, it has failed.

[COMPLETENESS — violations block publishing]
- Finish the article completely. Never cut a sentence, table, or FAQ answer mid-way. Close every tag.
- Never repeat a sentence or recycle the opening paragraph later in the article.
- <h2>/<h3> headings are one-line natural search questions or short noun phrases — no full paragraphs in headings.

[SELF-REVIEW BEFORE OUTPUT]
1) Any price/date/version/feature stated without support in the facts? Remove or soften it.
2) Every number carries "as of {month_year}" + a named source?
3) Any repeated paragraphs, truncated sentences, unfinished FAQ answers?
3-1) Any two <p> in a row over 70 words each on the same sub-idea, or the same fact stated in the opening AND the Quick Verdict AND the closing confirmed list? Cut the repeat or convert the pair into a list/card.
3-2) Any jargon term (a framework name, protocol name, or specialist concept) used without a plain-English gloss in parentheses the first time it appears?
4) At least 2 genuinely new concrete facts? A "use it / skip it" judgment with conditions?
5) Any banned phrase, income claim, or invented anecdote left?

[HTML — use exactly these classes; the publish CSS styles them]
- No Markdown, no HTML entity codes (&#...;) — use unicode characters directly. No hashtags in the body (the system appends them).
- Never expose internal jargon: "SEO", "GEO", "AEO", "SGE", "CTA", "AdSense" (unless AdSense itself is the article topic).
- Allowed classes only: actions-box, risk-note, verdict-box, quick-decision-table, quality-checklist, faq-section/faq-item/faq-q/faq-a, confirmed-needed-box, who-for (see STRUCTURE section 5). Inventing other classes or inline styles leaves the article unstyled.
- DEBUG-LOOKING TEXT IS AUTO-BLOCKED: an automated scan rejects the article if the visible body contains the words "fallback", "raw", or "scoring" used as a label — i.e. immediately followed by ":" or "=" ("Fallback: Claude", "raw = the model output", "scoring: 90/100") — or wrapped in double quotes ("fallback", "raw", "scoring"). These read as leaked debug output. Write "Backup option: Claude", "the unedited model output", "how it scores" instead. Using the words inside ordinary prose ("the fallback model kicks in", "raw text files") is fine — it is the label form and the quoted form that are blocked."""

_USER_PROMPT_TMPL_EN = """[Write one complete blog article]

Title: {title}
Topic: {topic}
Date: {today}
Content family: {content_family}

[SEARCH FACTS — collected from live web search today]
{facts}

[Questions real searchers ask (target for FAQ and headings)]
{questions}

---
One person found this through a Google search. Write one continuous article they read top to bottom — a flow, not a form.

LENGTH CONTRACT (one number, no ambiguity): the body must be AT LEAST {min_words} words of plain text and should land between {target_min} and {target_max} words. Aim for {target_min}+ so you are never near the floor. How the automatic counter works: HTML tags do not count; everything else separated by spaces does, including numbers and prices ("$20 a month" = 4 words). Anything under {min_words} words is thin content and is sent back for expansion before it can be published.

[STRUCTURE]
1) Opening paragraphs (plain <p>, no box — the system builds the top summary box from them):
   the reader's concrete situation in 1-2 lines → the direct answer to the title's question in 2-3 sentences with the key numbers and "as of {month_year}". No greetings, no "AI is changing fast". Keep the opening paragraph under 60 words — a skimmer decides in 10 seconds.
2) 4-6 <h2> sections. Each <h2> must come from this article's subject: a product name, plan, task, risk, limit, audience, number, or measured search intent. Do not use generic stock labels that could be moved unchanged to another article. If the facts include a [MEASURED GOOGLE AUTOCOMPLETE SEARCH DEMAND] block, at least 2 <h2> headings must turn those measured queries into section titles. AT MOST 2 headings in the whole article may be question-style (starting with How/What/Why or ending with "?"); the automated layout adds its own Q&A blocks and too many question headings blocks publishing. Each section goes one step deeper than the last.
   - Cover, as fits the topic: what actually changed / how it works → real numbers (pricing, limits, quotas — only from facts, each with as-of + source) → what stays the same and what is still unconfirmed → what it means for the reader's time and money → first-time failure points (cause + fix) + at least one little-known tip.
   - Any time you cover 2+ repeated instances of the same pattern (multiple causes-and-fixes, multiple reader profiles, multiple gotchas) — write them as a plain <ul> with one <li> per instance, each opening with a bolded 2-4 word label (<li><strong>Cause: outdated file path</strong> — the one-sentence fix.</li>), never as a run of paragraphs. A list of 3 short items reads faster than one paragraph saying the same thing.
   - If a follow-along process has 3+ steps, use (numbers are auto-generated by CSS — do not write "1."):
     <div class="actions-box"><ol><li><strong>One-line step title</strong> — concrete instruction</li> ...</ol></div>
   - If there is one honest caveat worth isolating, use exactly one:
     <div class="risk-note"><span class="section-label">Watch out</span><p>1-2 sentences of the real risk</p></div>
3) MANDATORY: one comparison/pricing/spec table inside the flow, wrapped exactly like this (the wrapper enables mobile scroll + first-column emphasis):
   <div class="quick-decision-table"><table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table></div>
   Make it worth saving: plans vs prices vs limits, tool-by-task comparison, before/after, cost math. Columns = the reader's decision criteria. NO empty cells, and at least half of the data cells must carry REAL verified values (a number, a limit, a plan name) from the facts. "check official page" / "n/a" may fill AT MOST 2 cells in the whole table — if you can't verify enough values, drop that column or shrink the table to the tools you CAN verify; a table of deferrals is a blocked article. Put one framing sentence before and after. Add "as of {month_year}" near the table when it contains prices/limits. Clean, sourced tables are what readers save and what answer engines most readily cite.
   PRICE-CELL RULE — checked mechanically, and failing it blocks publishing outright:
   - It applies whenever the Title above contains any of: "pricing", "price", "prices", "cost", "costs", "subscription", "fee", "fees", or "/month".
   - When it applies, the FIRST quick-decision-table in the article must contain AT LEAST 2 data cells (<td>) whose text holds a real currency amount — "$20", "$0.50", "USD 20", "£16", "€18", "₹1,999" — or the single word "Free".
   - ONLY those two forms count. A cell reading "200K tokens", "Pro plan", "unlimited", "5 seats", "20 dollars", "check the official page", or "n/a" counts as ZERO. Limits and plan names are useful columns, but they are not prices.
   - So build the table with a dedicated price column and put the currency symbol inside each cell: <td>$20/month</td>, <td>Free</td>, <td>$0.003 per 1K input tokens</td>.
   - If the facts verify fewer than 2 real prices, do NOT fake them and do NOT fill the price column with deferrals — both fail. Write the article around what IS verified (limits, quotas, feature differences) and keep price framing out of the body. A price-promising title with no verifiable prices is the wrong article to write; the correct fix is a different title/topic, not a padded table.
4) <h2>Frequently Asked Questions</h2> then EXACTLY this markup with EXACTLY 3 FAQs. Pick real search queries NOT already covered by the body — billing, limits, alternatives, data handling, cancellation — and never restate a body sentence:
<section class="faq-section">
  <article class="faq-item"><h3 class="faq-q">Actual search question?</h3><p class="faq-a">Direct, complete answer.</p></article>
</section>
   THE MARKUP IS PARSED MECHANICALLY — an answer is only recognized when a <p> follows its <h3> IMMEDIATELY, with nothing in between. Break the adjacency and the checker sees ZERO answers and blocks the article as "FAQ answers too short":
   - The question must be <h3 class="faq-q">…</h3> — never <h4>, <strong>, <dt>, <p>, or a heading wrapped in a <div>.
   - The answer must be the very next tag: <h3 class="faq-q">Question?</h3><p class="faq-a">Answer.</p>. Put NOTHING between them — no <div>, no <br>, no "A:" prefix, no <strong>Answer</strong> label, no comment, no extra wrapper around the <p>.
   - Answer length: 25-50 words (roughly 150-300 characters). The automatic check measures CHARACTERS and rejects anything under 20, so aim at the word range and you are never close to the floor. One-line fragments read as filler and get cut.
   - Each of the 3 items is its own <article class="faq-item"> inside the single <section class="faq-section">.
5) Closing: no summary rehash. Give the who-should-use-this judgment as a scannable two-column block, not a paragraph — concrete conditions on each side, 2-4 short bullets per side, no restating facts already given above:
<div class="who-for"><div class="who-for-cols">
  <div class="who-for-rec"><h3>Use this if</h3><ul><li>concrete condition</li></ul></div>
  <div class="who-for-non"><h3>Skip it if</h3><ul><li>concrete condition</li></ul></div>
</div></div>
Then output this block verbatim in structure (keep id and classes exactly; fill with topic-specific items only — facts NOT already stated earlier in the article):
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
  <div class="confirmed-section"><h3>Confirmed facts</h3><ul><li>3 facts that are settled for this topic</li></ul></div>
  <div class="check-needed-section"><h3>Check for yourself</h3><ul><li>3 things that change often (prices, limits, availability) with where to check</li></ul></div>
</section>
(The system appends related internal links after your article — do not add external links or a "read more" section yourself.)

[OPTIONAL — only when the topic genuinely calls for it]
- Pre-flight checklist: <div class="quality-checklist"><ul><li>topic-specific check item</li>...</ul></div>
{asset_directive}
[DO NOT]
- Use any class not listed above (plus verdict-box when the asset directive asks for it), or inline style attributes.
- Pad with generic "AI productivity tips" that fit any article.
- Repeat the same guidance in multiple sections.
- Write filler FAQs that restate body paragraphs.

Output rules:
- Output only the inner HTML (no div.post-content wrapper, no <html>/<head>). Complete every tag.
- <h2> for sections, <h3> for sub-points. English only.
- No Markdown, no &#...; entities, no hashtags.
- Never use "fallback", "raw", or "scoring" as a label followed by ":" or "=", and never put those three words in double quotes — the publish scan reads that shape as leaked debug output and blocks the article. Write "Backup option:", "the unedited output", "how it scores" instead.

FINAL LENGTH CHECK (do this before you output): count the words of plain text — HTML tags excluded, numbers and prices included. The body must be AT LEAST {min_words} words; target {target_min}-{target_max}. If your draft is short, do not pad with fluff; go deeper instead: expand the first-time failure section with one more concrete failure-and-fix, add a calculation walkthrough under the table, and extend the judgment section with one more reader profile."""

# 영어 모드 '저장용 무기' 지시 — 비교·가격·비용계산·통계 유형에서 켠다.
_ASSET_RICH_DIRECTIVE_EN = """
[This is a comparison/pricing/cost-math article — load it with savable assets]
Readers save this article to reuse its numbers. Fill 1-2 of these with REAL values from the facts (never all of them as empty scaffolding):
 - Quick Verdict box: place it right after the opening paragraphs, before the first <h2> — a skimmer should get the decision in 5 seconds:
   <div class="verdict-box"><span class="section-label">Quick Verdict</span><ul>
   <li><strong>Best for:</strong> [specific reader/job]</li>
   <li><strong>Not ideal for:</strong> [specific reader/job]</li>
   <li><strong>Free plan:</strong> [what it covers, or "check official page"]</li>
   <li><strong>Main limitation:</strong> [the honest one]</li>
   <li><strong>Last checked:</strong> {month_year}</li>
   </ul></div>
   Only include a price line when the facts verify it. Never leave placeholder brackets in the output.
 - Cost math: the formula (input/output tokens × model rate) plus one topic-specific calculation in a quick-decision-table. Add "as of {month_year}" and "check the official pricing page". If the rate is not in the facts, show the METHOD only — never invent a rate.
 - Comparison table: only the tools/plans this topic is about; columns are decision criteria (price, limits, speed, best-for). quick-decision-table wrapper.
 - Checklist: pre-purchase or pre-setup checks specific to this topic in a quality-checklist div.
[Honesty rule]
 - No first-person measured results ("I ran it and got X seconds"). Give the reader a reproducible recipe instead: the exact prompt/settings to run, under which condition, and what to measure — so they generate the evidence themselves.
"""

# ─── 길이 미달 '보강(repair)' 프롬프트 (2026-08-03) ───────────────────────────
# 예전에는 단어 수가 하한에 몇십 단어 모자라면 초안을 통째로 버리고 처음부터 다시
# 생성했다(실측: 1393·1336단어에서 전면 재생성). 재생성은 (1) 2분짜리 호출을 통째로
# 다시 쓰고 (2) 이미 통과한 팩트 정합·표·FAQ까지 주사위를 다시 굴린다. 지금은 초안을
# 그대로 돌려주며 "어디를 얼마나 늘려라"만 지시한다 — 좋은 부분 보존이 최우선이라
# 프롬프트가 전면 재작성을 명시적으로 금지한다.
_REPAIR_LENGTH_INSTRUCTIONS_EN = """[REVISION TASK — expand an existing draft, do not rewrite it]

Your previous draft is below. It is good but TOO SHORT: it has about {word_count} words of plain text, and the minimum is {min_words}. You need to add roughly {needed_words} more words to land in the {target_min}-{target_max} target range.

HOW TO REVISE (this is an expansion, not a rewrite):
1. Keep every existing sentence, heading, table, FAQ, and block EXACTLY as written unless it is factually wrong. Do not reorder sections, do not re-phrase paragraphs you already wrote, do not "improve" wording. Anything you change costs quality that already passed review.
2. Add the missing length as NEW material in these places, in this order of preference:
   a. The beginner-blockers section: one more concrete place a first-time user gets stuck, with the cause and the fix.
   b. Under the table: a concrete calculation that walks one number through the reader's real situation (e.g. what the plan costs for 40 hours of use a month).
   c. The judgment section: one more reader profile with an explicit "use it if / skip it if" condition.
   d. One additional <h2> section that goes a step deeper on the topic — only if a-c are not enough.
3. Do NOT pad. No filler sentences, no restating what the article already said, no generic "AI is useful" paragraphs, no repeated guidance. Every added sentence must carry a fact, a number, a cause-and-effect, or a decision rule. Repeated sentences are detected and rejected.
4. Do NOT add new prices, dates, versions, limits, or product names that are not in the original [SEARCH FACTS]. If you need more length and have no more facts, go deeper on explaining and applying the facts you already used.
5. Keep all the original constraints: same allowed HTML classes, EXACTLY 3 FAQs in <h3 class="faq-q">…</h3><p class="faq-a">…</p> pairs with the <p> immediately after the <h3>, the CONFIRMED_VS_CHECK_NEEDED_BLOCK unchanged at the end, no Markdown, no hashtags, no &#...; entities, English only, at most 3 deferral phrases in the whole article.

OUTPUT: the COMPLETE revised article as inner HTML — the original content plus your additions, from the first paragraph to the closing block. Do not output a diff, a fragment, a note, or a comment about what you changed. Output nothing but the article HTML.
"""

_REPAIR_READABILITY_INSTRUCTIONS_EN = """[REVISION TASK — make the existing draft easier to read]

The draft below already passed the structural checks, but its English is too hard for a general reader.

Current readability:
- Flesch Reading Ease: {fre}
- Average sentence length: {asl} words
- Long-word share: {long_word_pct}%

Rewrite the COMPLETE article in easier English without changing the meaning, facts, numbers, prices, links, HTML structure, or allowed classes.

Rules:
1. Keep each sentence under 20 words where possible.
2. Use common words. If you must use technical terms such as SLA, latency, tenant, OAuth, throughput, inference, connector, or Zero Trust, add a plain-English explanation in the same sentence.
3. Keep one reader in mind: a worker or small business owner trying an AI tool, not a developer or enterprise admin.
4. Do not add new facts, prices, dates, versions, tools, URLs, or claims.
5. Fix these hard sentences first:
{hard_sentences}

OUTPUT: the COMPLETE revised article as inner HTML. Do not output notes, Markdown, a diff, or a fragment.
"""

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

[구조 — 슬롯이 아니라 흐름. 아래 클래스는 발행 CSS가 실제로 예쁘게 스타일하는 정식 클래스다. 정확히 이 이름만 쓴다]
1) 여는 문단(문장으로): 독자가 실제 겪는 장면 한두 줄로 시작 → 이 주제로 무엇이 달라지는지 →
   핵심 답을 곧바로 2~3문장으로 준다. "안녕하세요"·"요즘 AI가 빠르게 발전" 절대 금지. 첫 300자 안에 핵심 검색 키워드 포함.
   (상단 '핵심 요약' 강조 박스는 시스템이 자동으로 붙이므로 직접 만들지 않는다 — 여는 문단은 순수 문장으로.)
2) 본문 <h2> 2~3개: 각 소제목은 독자가 실제로 검색할 법한 자연어 질문(한 줄). 각 섹션은 앞에서 이어받아 한 걸음씩 깊어진다.
   - (A 활용법)이면: 실제 작동/설정 방식 → 그대로 따라 할 순서 → 이 주제에서 초보자가 실제로 막히는 지점 1~2개(원인과 해결 방향 포함) + 아는 사람만 아는 실전 팁.
     · 따라 할 순서가 3단계 이상이면 아래 번호 스텝 카드로 낸다(번호는 CSS가 자동으로 매기므로 "1." 같은 숫자를 직접 쓰지 말 것):
       <div class="actions-box"><ol><li><strong>할 일 한 줄 제목</strong> — 구체 설명</li> ...</ol></div>
   - (B 정보전달)이면 네 가지를 구분해서 쓴다(이 구분이 보도자료 요약과 해설의 차이다):
     ① 이전에는 어땠나 → ② 무엇이 바뀌었나(팩트의 수치·날짜와 함께) → ③ 바뀌지 않은 것·아직 확인되지 않은 것 → ④ 그래서 독자의 시간·비용·업무에 주는 의미.
     ③을 건너뛰지 말 것 — "무엇이 안 바뀌었는지"와 "무엇이 미확인인지"를 말해주는 글이 신뢰를 얻고 AI 검색에도 인용된다.
   - 어느 쪽이든 이 주제에서만 나오는 구체 정보를 최소 1개 넣는다. 아무 글에나 들어갈 범용 'ChatGPT 업무 활용' 일반론 금지.
   - 주제와 관련된 솔직한 한계·주의가 있으면, 흐름 중 적절한 한 곳에서 아래 주의 박스로 딱 1개만 뺀다(남발 금지):
     <div class="risk-note"><span class="section-label">이것만은 주의</span><p>이 주제에서 실제로 조심할 점 1~2문장</p></div>
3) 그다음 <h2>자주 묻는 질문</h2> 아래에 아래 형식 그대로 FAQ 3개(각 답 150자 이내, 확인된 내용만, 답을 끝까지 완결).
   본문에서 이미 설명한 내용을 문장만 바꿔 반복하지 말 것 — 본문이 다루지 않은 실제 검색 질문(요금·호환·한도·대안·이전 데이터 처리 등)을 고른다:
<div class="faq-section">
  <article class="faq-item"><h3 class="faq-q">독자의 실제 검색 질문</h3><p class="faq-a">빠르고 명확한 답</p></article>
  (총 3개)
</div>
4) 닫는 문단: 결론을 다시 반복하지 말 것. "무엇을 AI에 맡기고 무엇을 사람이 직접 확인할지"를 1~2문장으로,
   가능하면 "지금 써볼 사람 / 기다리는 게 나은 사람"을 한 문장으로 구분해 독자 계약(새 이해·판단·오늘 할 일)을 회수한다.
   이어서 독자가 스스로 확인해야 할 것(요금·정책처럼 자주 바뀌는 것)을 아래 블록으로 출력(id·class 문자열 정확히 유지, 이 주제에 특정된 내용만):
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
  <div class="confirmed-section"><h3>지금까지 확인된 것</h3><ul><li>이 주제에서 사실로 확정된 것 3개</li></ul></div>
  <div class="check-needed-section"><h3>직접 확인할 것</h3><ul><li>자주 바뀌어 독자가 직접 봐야 하는 것 3개</li></ul></div>
</section>

[표 1개는 반드시 — 단, 주제에 밀착된 것으로]
본문 흐름 안에 이 주제에 실제로 쓸모 있는 표를 딱 1개, 아래처럼 감싸서 넣는다(감싸는 div가 있어야 모바일 가로 스크롤과 첫 열 강조가 적용된다):
<div class="quick-decision-table"><table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table></div>
저장해두고 다시 꺼내 볼 만한 것 — 예: 설정 항목·경로 정리, 단계별 할 일, 상황별 선택 기준, 적용 전/후 비교, 무료 한도 등.
표 앞뒤로 한두 문장을 붙여 흐름과 이어지게 한다. (주제와 무관한 ChatGPT/Claude 나열식 비교표는 금지)

[체크리스트 — 점검할 항목이 있을 때만 1개]
독자가 실행 전에 짚을 항목이 있으면(설정 전 점검, 발행 전 확인 등) 아래 체크리스트로 준다(일반론 금지, 이 주제에서만 통하는 항목):
<div class="quality-checklist"><ul><li>이 주제에 특정된 점검 항목</li> ...</ul></div>
{asset_directive}
[하지 않을 것]
- 위에 안내한 정식 클래스(actions-box, risk-note, quick-decision-table, quality-checklist, faq-section/faq-item, confirmed-needed-box)만 쓴다. 그 외 클래스나 인라인 style 속성을 지어내면 발행 CSS가 스타일을 못 입혀 밋밋해진다.
- 시각 요소는 '내용이 있을 때'만. 표는 기본으로 1개, 스텝 카드·주의 박스·체크리스트는 주제에 실제로 필요할 때만 넣는다(빈 껍데기 카드 나열 금지).
- 요약 카드(summary-card), 마감 재촉 박스(deadline-box), 이모지 머리글("⚡ 팁1")로 소제목 흉내내기 금지.
- 주제와 무관한 ChatGPT/Claude/Gemini 나열·비교, "프롬프트 5개" 나열 금지.
- 같은 안내(예: "설정을 켜세요")를 여러 섹션에서 반복하지 않는다 — 가장 적합한 곳에서 한 번만.

출력 규칙:
- div.post-content 태그 없이 내부 HTML만 출력. 처음부터 끝까지 완결하고 모든 태그를 닫는다.
- 소제목은 <h2>, 세부는 <h3> (자연어 질문형, 한 줄)
- 전체 한국어. 영어 설명 문장 금지(고유명사·코드·단위만 영문 허용)
- Markdown 금지, HTML entity 코드(&#숫자;) 금지, 본문 해시태그 금지"""


# 'AI 자동화 실험실' 유형(도구 비교·비용 계산·자동화 실전) 글에서만 켜지는 지시.
# 일반 뉴스/정보 글은 담백하게 두고(양식화 방지), 이 유형에서만 저장용 '무기'를 요구한다.
_ASSET_RICH_DIRECTIVE = """
[이 글은 'AI 자동화 실험실' 유형 — 저장용 도구(무기)를 실제 수치로 채운다]
이 주제는 도구 비교·비용·자동화 실전에 관한 것이다. 독자가 저장해 다시 꺼내 쓰는 '무기'를,
주제에 맞는 것으로 1~2개만 골라 실제 항목·수치로 채운다(다섯 개를 다 넣어 양식처럼 만들지 말 것).
표·체크리스트·프롬프트는 반드시 아래 정식 클래스로 감싸야 발행 CSS가 스타일을 입힌다:
 - 비용 계산: 공식(입력·출력 토큰 × 모델 단가)과 예시 계산을 <div class="quick-decision-table"><table>...</table></div>로.
   "YYYY년 M월 기준"과 "정확한 가격은 공식 페이지에서 확인" 문구를 붙인다. 팩트에 단가가 없으면 지어내지 말고 계산 '방법'만 제시한다.
 - 도구 비교표: 이 주제의 도구/방식만 비교(범용 ChatGPT/Claude 나열 금지). 열은 독자의 선택 기준(속도·비용·한도·용도). 역시 quick-decision-table로 감싼다.
 - 체크리스트: 발행 전·설정 전 점검 항목을 <div class="quality-checklist"><ul><li>...</li></ul></div>로. 일반론("검수하라") 금지, 이 주제에서만 통하는 항목.
 - 재사용 템플릿: 그대로 복사해 쓰는 프롬프트·설정 예시를
   <div class="prompt-recipe-box"><div class="prompt-card"><p class="prompt-card-label">복사해 쓰는 프롬프트</p><div class="prompt-code">내용</div></div></div>로 1개.
이 유형에서는 quick-decision-table을 2개까지 허용한다(계산 1 + 비교 1). 그 외에는 여전히 표 남발 금지.
[실험 로그·실패 사례 규칙 — 정직성 최우선]
 - '내가 해보니 몇 초/몇 원' 같은 1인칭 실측·수익 주장 금지(검증 불가로 발행 차단). 대신 독자가 직접
   돌려볼 '실험 설계'를 준다: 무엇을·어떤 조건으로·무엇을 측정할지. 결과 숫자는 독자가 채우도록 기준만 남긴다.
"""

# 이 키워드가 제목/주제/앵글에 있으면 위 지시를 켠다. 뉴스 글에 우연히 걸려도
# 계산·표는 품질 게이트가 어차피 선호하므로 해가 없다(보수적일 필요 없음).
# 2026-07-16 확장: "직장인 생산성/시간 절약"류 evergreen(ai_work_tip)이 이 목록에
# 안 걸려 무기 지시 없이 밋밋하게 나가던 갭(2026-07-11 사용자 피드백 — 게이트는
# 통과하는데 저장할 정보 밀도가 부족) 대응.
_ASSET_RICH_KEYWORDS = (
    "비용", "요금", "계산", "api", "토큰", "단가", "자동화", "파이프라인", "워크플로",
    "도구 비교", "비교표", "cursor", "codex", "claude code", "제휴", "한도",
    "임시저장", "자동발행", "자동 발행", "실험", "100개", "대체 루트", "프롬프트 템플릿",
    "시간 절약", "시간을 줄", "업무 시간", "생산성", "활용법", "활용 팁", "업무 팁",
    # 영어 모드 트리거 — 비교·가격·비용계산·통계 유형(고 CPC·AI 인용 자석)
    "pricing", "price", "cost", " vs ", "vs.", "comparison", "compare",
    "alternatives", "worth it", "free tier", "limit", "calculator",
    "statistics", "benchmark", "automation", "workflow", "tokens",
)


# 영어 모드 콘텐츠 유형(운영 전략의 6개 주제군) 판별 — 프롬프트·라벨에 쓰인다.
_CONTENT_FAMILY_RULES_EN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Comparisons", (" vs ", "vs.", "versus", "alternative", "best ai", "best free", "worth it", "compare", "comparison")),
    ("Pricing", ("pricing", "price", "cost", "fee", "subscription", "per month", "/month", "free tier", "paid plan", "hidden cost")),
    ("Fixes", ("not working", "fix", "error", "limit", "blocked", "bypass", "slow", "wrong answers", "troubleshoot", "refused")),
    ("Data & Stats", ("statistics", "stats", "benchmark", "adoption", "numbers", "context window", "comparison table")),
    ("How-To", ("how to", "guide", "tutorial", "setup", "use ", "using ", "workflow", "automate")),
)


def content_family_en(*parts: str) -> str:
    """제목·주제 텍스트에서 6개 주제군 라벨 하나를 고른다 (기본 News)."""
    blob = " ".join(str(p or "") for p in parts).lower()
    for family, tokens in _CONTENT_FAMILY_RULES_EN:
        if any(tok in blob for tok in tokens):
            return family
    return "News"


_EN_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _month_year_en() -> str:
    """as-of 표기용 'July 2026' 형태 현재 월 (%B는 로케일 의존이라 직접 조립)."""
    ym = kst_today("%Y-%m")
    year, month = ym.split("-")
    return f"{_EN_MONTHS[int(month) - 1]} {year}"


def _asset_rich_directive(title: str, topic: str, category: str, raw: dict) -> str:
    """도구·비용·자동화 유형이면 무기 지시를 반환, 아니면 빈 문자열."""
    angle = str(
        raw.get("angle_type") or (raw.get("search_angle") or {}).get("angle_type") or ""
    ).lower()
    blob = f"{title} {topic} {category} {angle}".lower()
    return _ASSET_RICH_DIRECTIVE if any(k in blob for k in _ASSET_RICH_KEYWORDS) else ""


def _strip_search_markup(text: str) -> str:
    """Naver 검색 API 응답의 <b> 강조 태그·HTML 엔티티를 제거한다."""
    cleaned = re.sub(r"</?b>", "", text or "")
    return " ".join(_html_unescape(cleaned).split())


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
        # 팩트 수집 소스 (2026-07-10 재편): Custom Search는 Google이 신규 고객에게
        # 폐쇄해 전 호출 403 — 살아있는 키(Naver 뉴스 검색·Exa)를 팩트 소스로 승격.
        # 키가 있고 ENABLE_*가 명시적 false가 아니면 사용 (settings.py 기본값과 동일 규칙).
        self._naver_client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
        self._naver_client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
        if os.getenv("ENABLE_NAVER_SEARCH", "").strip().lower() in {"0", "false", "no", "off"}:
            self._naver_client_id = ""
        self._exa_api_key = os.getenv("EXA_API_KEY", "").strip()
        if os.getenv("ENABLE_EXA_SEARCH", "").strip().lower() in {"0", "false", "no", "off"}:
            self._exa_api_key = ""
        # Exa는 크레딧 과금 — 재시도 루프(최대 12회 × 시도당 1~2회 수집)에서
        # 무제한 호출되지 않게 프로세스당 상한을 둔다.
        self._exa_facts_calls = 0
        # 2026-07-25: 상한 6은 주제당 2회(공식+일반) 구조에서 주제 3개면 소진됐고,
        # 그 뒤 재시도는 헤드라인만으로 글을 썼다(7/24 사고, 재시도 6번째). 지금은
        # 주제당 최대 2회를 쓰되 본문 발췌를 얻으면 조기 종료하므로 실사용은 보통
        # 1회다. 재시도 상한(기본 6)까지 본문 팩트를 확보하도록 12를 기본값으로 두고
        # env로 조절 가능하게 한다 — Exa는 검색당 과금이라 상한 자체는 유지한다.
        try:
            self._exa_facts_max_calls = max(
                2, int(os.getenv("NEWS_EXA_MAX_FACT_CALLS", "12").strip() or "12")
            )
        except ValueError:
            self._exa_facts_max_calls = 12
        # 2026-07-25: 마지막 수집의 소스 품질 진단. 상한 6회는 주제당 2회(공식+일반)를
        # 쓰므로 주제 3개에서 소진되고, 그 뒤 재시도는 Google News RSS **헤드라인만**으로
        # 글을 쓴다 — 7/24 발행글(재시도 6번째)이 정확히 그 상태였고, 실제로는 공개된
        # 커넥터 목록·언어 수를 "보도에 안 나왔다"고 서술했다. 본문 발췌가 하나도 없는
        # 상태를 게이트가 알 수 있게 여기에 남긴다.
        self.last_fact_supply: dict[str, object] = {
            "has_source_body": False,
            "official_count": 0,
            "tier1_count": 0,
            "headline_only": False,
            "sources_used": [],
        }
        # 마지막 generate_html() 호출에서 실제로 수집된 인용 URL(Naver 원문 링크·
        # Exa 결과 URL). generate_html은 문자열만 반환하므로, 호출부(news_pipeline)가
        # SOURCE_TRUST_BLOCK에 실제 <a href> 근거를 걸려면 이 속성을 함께 읽는다.
        self.last_source_citations: list[dict[str, str]] = []

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
        english = is_english_mode()
        if english:
            # %B는 로케일 의존 — 영어 월명으로 직접 조립 ("July 17, 2026")
            today = f"{_month_year_en().split(' ')[0]} {int(kst_today('%d'))}, {kst_today('%Y')}"
        else:
            today = kst_today("%Y.%m.%d")
        raw = raw or {}

        # 1. Google Search로 실제 정보 수집 (+ 실제 인용 URL도 함께 보관 —
        # 호출부가 SOURCE_TRUST_BLOCK에 실제 근거 링크를 걸 수 있게 한다)
        facts, self.last_source_citations = self.gather_facts_with_citations(topic)

        # 2. 독자 질문 목록 구성
        questions_raw = list(reader_questions or [])
        if not questions_raw:
            questions_raw = list(raw.get("reader_search_questions") or [])
        if not questions_raw:
            if english:
                questions_raw = [
                    f"What is {topic} and how does it work?",
                    f"How much does {topic} cost?",
                    f"Is {topic} worth it?",
                ]
            else:
                questions_raw = [f"{topic}이란 무엇인가요?", f"{topic} 대상은 누구인가요?"]
        questions_str = "\n".join(f"- {q}" for q in questions_raw[:6])

        if english:
            # 영어 모드: 한국어 전용 프로필/브리프 블록은 주입하지 않는다.
            month_year = _month_year_en()
            asset_directive = _asset_rich_directive(title, topic, category, raw)
            if asset_directive:
                asset_directive = _ASSET_RICH_DIRECTIVE_EN.format(month_year=month_year)
            prompt = _USER_PROMPT_TMPL_EN.format(
                title=title,
                topic=topic,
                today=today,
                content_family=content_family_en(title, topic, category),
                facts=facts or "(no live search results — write conservatively; do not state any specific price/date/version, direct readers to official pages instead)",
                questions=questions_str,
                asset_directive=asset_directive,
                month_year=month_year,
                min_words=EN_MIN_BODY_WORDS,
                target_min=EN_TARGET_BODY_WORDS_MIN,
                target_max=EN_TARGET_BODY_WORDS_MAX,
            )
        else:
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
        if english:
            for _pat, _repl in _OVERCLAIM_SOFTENERS_EN:
                content_html = _pat.sub(_repl, content_html)
            # LLM이 금지 지시를 어기고 본문에 해시태그를 넣으면(무료 모델 관측)
            # uncontrolled_visible_body_hashtags 게이트가 발행을 막는다 — '#'만 제거.
            # URL 프래그먼트(#anchor 등 /:. 뒤)는 게이트와 같은 예외 규칙으로 보존.
            content_html = re.sub(r"(?<![\w/:.\-])#([A-Za-z][A-Za-z0-9_]+)", r"\1", content_html)
            # 발행 게이트의 FAQ 추출기는 <section class="*faq*"> 안의 h3+p만 읽는다 —
            # LLM이 div로 내면 intent 블록(h3 없음)이 먼저 잡혀 faq_answer_too_short가
            # 난다(드라이런 #10 실측). 본문 FAQ 래퍼를 section으로 정규화한다.
            content_html = re.sub(
                r'<div(\s+class="faq-section")', r"<section\1", content_html, count=1
            )
            content_html = _close_faq_section_wrapper(content_html)
            # 빈 표 셀은 empty_table_cells 게이트가 차단한다 — "n/a"로 결정적 채움.
            content_html = re.sub(r"(<t[dh]\b[^>]*>)\s*(</t[dh]>)", r"\1n/a\2", content_html)

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

    def gather_facts_with_citations(self, topic: str) -> tuple[str, list[dict[str, str]]]:
        """팩트 텍스트 + 실제 인용 가능한 출처 URL을 함께 반환.

        2026-07-16: 기존 gather_facts()/_gather_facts()는 Naver 뉴스·Exa 응답에서
        본문 스니펫만 뽑고 원문 링크(link/originallink, url)를 버렸다 — 그 결과
        SOURCE_TRUST_BLOCK에는 실제 <a href> 인용 링크가 단 하나도 남지 않았고,
        official_source_links_below_2 게이트가 실제 근거가 있었음에도 발행을
        차단했다(실측: run 29464514437). 이 메서드는 같은 API 응답에서 텍스트와
        URL을 한 번에 뽑아, 호출부가 실제 근거 링크를 렌더링할 수 있게 한다.
        Naver/Exa 호출은 한 번씩만 수행한다(중복 호출로 Exa 크레딧을 낭비하지 않음).
        """
        official_text, official_citations = "", []
        tier1_text, tier1_citations = "", []
        if is_english_mode():
            # 영어 모드 리서치: Naver 뉴스는 한국어 소스라 스킵. Exa(영문 웹 본문
            # 발췌 — 경쟁 상위글·공식 가격 페이지)가 1차, Google News RSS(en-US)가 폴백.
            naver_text, naver_citations = "", []
            # 2026-07-18 실측 사고: 주제어만으로 Exa를 돌리면 가격 글의 출처가
            # 전부 SEO 블로그(콘텐츠팜)로 채워진다 — 라이브 발행글의 Sources가
            # prophetchrome.com류 3개뿐이었고 공식 가격 페이지가 0개였다.
            # 공식 벤더 도메인으로 한정한 2차 검색을 추가해 공식 출처를 확보하고,
            # 인용 목록 맨 앞에 배치한다(SOURCE_TRUST_BLOCK은 앞에서 4개만 쓴다).
            official_text, official_citations = self._exa_official_facts_and_citations(topic)
            # 2026-07-25: 공식 소스가 비면 1티어 매체로 한 번 더 시도한다. 뉴스
            # 주제는 벤더가 아직 문서화하지 않은 경우가 많아 공식 검색이 자주 빈다 —
            # 그때 곧바로 무제한 일반 검색으로 내려가면 애그리게이터만 걸린다.
            if not official_text:
                tier1_text, tier1_citations = self._exa_tier1_facts_and_citations(topic)
        else:
            naver_text, naver_citations = self._naver_news_facts_and_citations(topic)
        # 공식/1티어에서 본문 발췌를 이미 얻었으면 일반 검색은 생략한다 — Exa 예산을
        # 재시도 후반 주제까지 남기기 위한 절약이다(예산 고갈이 7/24 껍데기 글의 원인).
        if official_text or tier1_text:
            exa_text, exa_citations = "", []
        else:
            exa_text, exa_citations = self._exa_facts_and_citations(topic)
        sections = [s for s in (official_text, tier1_text, naver_text, exa_text) if s]
        headline_only = False
        if sections:
            facts = "\n\n".join(sections)
        else:
            facts = ""
            if self._search_api_key and self._search_cx:
                facts = self._custom_search(topic)
            if not facts:
                facts = self._google_news_rss_facts(topic)
            # RSS/Custom Search 폴백은 본문 발췌가 없는 헤드라인 수준이다.
            headline_only = bool(facts)
        citations = official_citations + tier1_citations + naver_citations + exa_citations
        self.last_fact_supply = {
            "has_source_body": bool(sections),
            "official_count": sum(
                1 for c in citations if self._domain_tier(str(c.get("url") or "")) == "official"
            ),
            "tier1_count": sum(
                1 for c in citations if self._domain_tier(str(c.get("url") or "")) == "tier1"
            ),
            "headline_only": headline_only,
            "sources_used": [
                name
                for name, present in (
                    ("official", bool(official_text)),
                    ("tier1", bool(tier1_text)),
                    ("naver", bool(naver_text)),
                    ("exa_generic", bool(exa_text)),
                    ("headline_fallback", headline_only),
                )
                if present
            ],
        }
        if headline_only:
            logger.warning(
                "LlmContentService: 팩트가 헤드라인 수준뿐 (Exa 호출 %d/%d 소진) — "
                "구체 사실 없는 껍데기 글 위험",
                self._exa_facts_calls,
                self._exa_facts_max_calls,
            )
        if is_english_mode():
            # 2026-07-21 라이브 실측: Sources 블록이 GitHub 트래커 레포 2개 +
            # SEO 애그리게이터 2개로 채워졌다(공식 출처 0). 블록은 앞 4개만
            # 쓰므로 공식 벤더 도메인을 앞으로 당기고, 코드 저장소 링크는
            # 다른 출처가 있으면 뺀다(레포는 가격·스펙의 출처가 아니다).
            citations = self._prefer_trustworthy_citations(citations)
        return facts, citations

    @classmethod
    def _prefer_trustworthy_citations(
        cls, citations: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """SOURCE_TRUST용 인용을 공식 도메인 우선으로 정렬하고 레포 링크를 강등한다."""
        def _is_repo_link(url: str) -> bool:
            if not re.match(r"https?://(?:www\.)?github\.com/[^/]+/[^/?#]+", url or ""):
                return False
            # github.com/features/* , /pricing 등 제품 페이지는 공식 출처로 유지.
            path = re.sub(r"https?://(?:www\.)?github\.com/", "", url).lower()
            return not path.startswith(("features/", "pricing", "customer-terms", "enterprise"))

        def _is_official(url: str) -> bool:
            host = re.sub(r"https?://(?:www\.)?", "", url or "").split("/")[0].lower()
            return any(host == d or host.endswith("." + d) for d in cls._OFFICIAL_VENDOR_DOMAINS)

        non_repo = [c for c in citations if not _is_repo_link(str(c.get("url") or ""))]
        pool = non_repo if non_repo else citations
        official = [c for c in pool if _is_official(str(c.get("url") or ""))]
        # 2026-07-25: 공식 다음은 1티어 매체다. 예전엔 official/rest 2단이라
        # MacRumors와 무명 애그리게이터가 같은 취급을 받아, SOURCE_TRUST_BLOCK 앞
        # 4칸이 애그리게이터로 채워질 수 있었다.
        tier1 = [
            c
            for c in pool
            if c not in official
            and cls._domain_tier(str(c.get("url") or "")) == "tier1"
        ]
        rest = [c for c in pool if c not in official and c not in tier1]
        return official + tier1 + rest

    def _gather_facts(self, topic: str) -> str:
        """실제 팩트 수집: Naver 뉴스 스니펫 + Exa 본문 발췌 병합 → 폴백 체인.

        2026-07-10 재편: Custom Search는 Google이 신규 고객에게 폐쇄(전 호출 403)돼
        헤드라인만 있는 RSS 폴백으로만 돌던 것을, 실측으로 살아있음을 확인한
        Naver 뉴스 검색(한국어 스니펫)과 Exa(본문 발췌)를 1차 소스로 승격.
        두 소스는 상호 보완(국내 보도 + 글로벌/공식 문서)이라 병합해 주입한다.
        전부 실패하면 기존대로 Custom Search(활성 시) → Google News RSS(키 불필요).
        모든 실패는 비치명 — 빈 문자열이면 LLM이 보수적 서술로 폴백한다.
        """
        sections: list[str] = []
        naver = "" if is_english_mode() else self._naver_news_facts(topic)
        if naver:
            sections.append(naver)
        exa = self._exa_facts(topic)
        if exa:
            sections.append(exa)
        if sections:
            return "\n\n".join(sections)
        facts = ""
        if self._search_api_key and self._search_cx:
            facts = self._custom_search(topic)
        if not facts:
            facts = self._google_news_rss_facts(topic)
        return facts

    def _naver_news_facts(self, topic: str) -> str:
        """Naver 뉴스 검색 API로 주제 관련 기사 제목+요약 스니펫을 수집한다."""
        text, _ = self._naver_news_facts_and_citations(topic)
        return text

    def _naver_news_facts_and_citations(self, topic: str) -> tuple[str, list[dict[str, str]]]:
        """Naver 뉴스 검색 API 응답에서 스니펫 텍스트와 실제 기사 URL을 함께 뽑는다.

        응답의 originallink(언론사 원문)·link(네이버 뉴스 미러) 필드는 기존에
        버려졌다 — SOURCE_TRUST_BLOCK에 걸 실제 인용 링크로 여기서 함께 반환한다.
        """
        if not (self._naver_client_id and self._naver_client_secret):
            return "", []
        try:
            query = urllib.parse.quote(topic)
            url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=4&sort=sim"
            req = urllib.request.Request(
                url,
                headers={
                    "X-Naver-Client-Id": self._naver_client_id,
                    "X-Naver-Client-Secret": self._naver_client_secret,
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            lines: list[str] = []
            citations: list[dict[str, str]] = []
            for item in body.get("items") or []:
                title = _strip_search_markup(str(item.get("title") or ""))
                desc = _strip_search_markup(str(item.get("description") or ""))
                pub = str(item.get("pubDate") or "")[:16]
                link = str(item.get("originallink") or item.get("link") or "").strip()
                if not title:
                    continue
                line = f"- {title}"
                if desc:
                    line += f": {desc}"
                if pub:
                    line += f" ({pub})"
                lines.append(line)
                if link.lower().startswith(("http://", "https://")) and len(citations) < 4:
                    from blogspot_automation.utils.text_clip import clip_at_word_boundary
                    citations.append({"name": clip_at_word_boundary(title, 60, ellipsis="…"), "url": link})
                if len(lines) >= 4:
                    break
            if not lines:
                return "", []
            logger.info("LlmContentService: Naver 뉴스 팩트 %d건 (인용 URL %d건)", len(lines), len(citations))
            return "[네이버 뉴스 검색 결과]\n" + "\n".join(lines), citations
        except Exception as exc:  # noqa: BLE001 — 팩트 수집 실패는 비치명
            logger.warning("LlmContentService: Naver 뉴스 팩트 수집 실패 — %s", exc)
            return "", []

    def _exa_facts(self, topic: str) -> str:
        """Exa 검색으로 주제 관련 웹 문서의 본문 발췌를 수집한다 (크레딧 과금 — 호출 상한)."""
        text, _ = self._exa_facts_and_citations(topic)
        return text

    # AI 벤더 공식 도메인 — 영어 모드에서 가격·스펙 수치의 1순위 출처.
    # (콘텐츠 전략: 공식 가격 페이지 > 릴리즈 노트 > 문서 > 벤더 블로그 > 2차 매체)
    _OFFICIAL_VENDOR_DOMAINS = (
        "openai.com",
        "anthropic.com",
        "x.ai",
        "blog.google",
        "microsoft.com",
        "perplexity.ai",
        "cursor.com",
        "mistral.ai",
        "ai.meta.com",
        "github.com",
        "deepseek.com",
        "midjourney.com",
        "elevenlabs.io",
    )

    # 1티어 기술/경제 매체 — 공식 발표가 아직 없는 뉴스 주제의 정당한 2순위 출처.
    # 2026-07-25 추가 사유: 7/24 발행글의 인용 매체가 SQ Magazine / Tech My Money /
    # Crypto Briefing이었는데, 같은 사건을 MacRumors·Engadget 등이 훨씬 구체적으로
    # (커넥터 목록·언어 18개·기존 기본모델 Haiku) 보도하고 있었다. 애그리게이터만
    # 물면 "구체적인 건 안 나왔다"는 껍데기 글이 된다.
    _TIER1_MEDIA_DOMAINS = (
        "techcrunch.com", "theverge.com", "arstechnica.com", "engadget.com",
        "wired.com", "macrumors.com", "9to5google.com", "9to5mac.com",
        "androidpolice.com", "zdnet.com", "venturebeat.com", "theinformation.com",
        "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com",
        "axios.com", "semianalysis.com", "techmeme.com", "nytimes.com",
        "bbc.com", "theregister.com", "tomshardware.com", "anandtech.com",
        "spectrum.ieee.org", "technologyreview.com", "nature.com", "science.org",
    )

    @classmethod
    def _domain_tier(cls, url: str) -> str:
        """URL을 official / tier1 / other 로 분류한다."""
        host = re.sub(r"https?://(?:www\.)?", "", url or "").split("/")[0].lower()
        if not host:
            return "other"
        if any(host == d or host.endswith("." + d) for d in cls._OFFICIAL_VENDOR_DOMAINS):
            return "official"
        if any(host == d or host.endswith("." + d) for d in cls._TIER1_MEDIA_DOMAINS):
            return "tier1"
        return "other"

    def _exa_tier1_facts_and_citations(self, topic: str) -> tuple[str, list[dict[str, str]]]:
        """1티어 매체로 한정한 Exa 검색 — 공식 발표 전 뉴스의 구체 사실 확보용."""
        return self._exa_facts_and_citations(
            topic,
            include_domains=list(self._TIER1_MEDIA_DOMAINS),
            num_results=2,
            section_label=(
                "[TIER-1 MEDIA SOURCES — prefer these over aggregators for "
                "specifics like feature lists, counts, and prior defaults]"
            ),
        )

    def _exa_official_facts_and_citations(self, topic: str) -> tuple[str, list[dict[str, str]]]:
        """공식 벤더 도메인으로 한정한 Exa 검색 — 가격·스펙의 공식 근거 확보용.

        2026-07-18 실측: 주제어만으로 검색하면 "hidden costs of AI subscriptions"류
        가격 주제에서 SEO 블로그만 걸리고 공식 페이지가 0건이었다. numResults 2로
        크레딧을 아끼고, 실패는 비치명(일반 검색 결과만으로 진행).
        """
        text, citations = self._exa_facts_and_citations(
            topic,
            include_domains=list(self._OFFICIAL_VENDOR_DOMAINS),
            num_results=2,
            section_label="[OFFICIAL VENDOR SOURCES — cite these first for any price/limit/spec]",
        )
        return text, citations

    def _exa_facts_and_citations(
        self,
        topic: str,
        *,
        include_domains: list[str] | None = None,
        num_results: int = 3,
        section_label: str = "",
    ) -> tuple[str, list[dict[str, str]]]:
        """Exa 검색 응답에서 본문 발췌 텍스트와 실제 결과 URL을 함께 뽑는다.

        응답의 url 필드는 기존에 버려졌다 — SOURCE_TRUST_BLOCK에 걸 실제 인용
        링크로 여기서 함께 반환한다. 호출 상한(_exa_facts_max_calls)은 그대로 적용.
        """
        if not self._exa_api_key or self._exa_facts_calls >= self._exa_facts_max_calls:
            return "", []
        self._exa_facts_calls += 1
        try:
            request_body: dict[str, Any] = {
                "query": topic,
                "type": "auto",
                "numResults": num_results,
                "contents": {"text": {"maxCharacters": 400}},
            }
            if include_domains:
                request_body["includeDomains"] = include_domains
            payload = json.dumps(request_body).encode("utf-8")
            req = urllib.request.Request(
                "https://api.exa.ai/search",
                data=payload,
                headers={
                    "x-api-key": self._exa_api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            lines: list[str] = []
            citations: list[dict[str, str]] = []
            for item in body.get("results") or []:
                title = " ".join(str(item.get("title") or "").split())
                text = " ".join(str(item.get("text") or "").split())[:300]
                pub = str(item.get("publishedDate") or "")[:10]
                result_url = str(item.get("url") or "").strip()
                if not (title or text):
                    continue
                line = f"- {title}" if title else "-"
                if text:
                    line += f": {text}"
                if pub:
                    line += f" ({pub})"
                lines.append(line)
                if result_url.lower().startswith(("http://", "https://")) and len(citations) < max(3, num_results):
                    from blogspot_automation.utils.text_clip import clip_at_word_boundary
                    citations.append(
                        {"name": clip_at_word_boundary(title or result_url, 60, ellipsis="…"), "url": result_url}
                    )
                if len(lines) >= num_results:
                    break
            if not lines:
                return "", []
            logger.info("LlmContentService: Exa 팩트 %d건 (인용 URL %d건)", len(lines), len(citations))
            header = section_label or "[웹 문서 발췌 (Exa)]"
            return f"{header}\n" + "\n".join(lines), citations
        except Exception as exc:  # noqa: BLE001 — 팩트 수집 실패는 비치명
            logger.warning("LlmContentService: Exa 팩트 수집 실패 — %s", exc)
            return "", []

    def _google_news_rss_facts(self, topic: str) -> str:
        """Google News RSS에서 주제 관련 최신 헤드라인을 수집한다 (API 키 불필요)."""
        try:
            import xml.etree.ElementTree as ET
            query = urllib.parse.quote(topic)
            locale_params = (
                "&hl=en-US&gl=US&ceid=US:en" if is_english_mode() else "&hl=ko&gl=KR&ceid=KR:ko"
            )
            url = f"https://news.google.com/rss/search?q={query}{locale_params}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
            # 2026-07-25: 예전에는 RSS 순서대로 앞 6건을 그대로 썼다 — 그래서 7/24
            # 글의 근거가 SQ Magazine·Tech My Money 같은 애그리게이터로 채워졌다.
            # 이제 1티어 매체 기사를 앞으로 당긴다(헤드라인뿐이라 본문 발췌를
            # 대체하지는 못하지만, 최소한 어느 매체를 인용할지는 개선된다).
            tier1_names = tuple(
                d.split(".")[0].lower() for d in self._TIER1_MEDIA_DOMAINS
            )
            ranked: list[tuple[int, str]] = []
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                source = (item.findtext("source") or "").strip()
                if not title:
                    continue
                link = (item.findtext("link") or "").strip()
                tier = self._domain_tier(link)
                source_low = source.lower().replace(" ", "")
                is_tier1 = tier == "tier1" or any(n in source_low for n in tier1_names)
                rank = 0 if tier == "official" else (1 if is_tier1 else 2)
                suffix = " · ".join(p for p in (source, pub_date[:16]) if p)
                ranked.append((rank, f"- {title}" + (f" ({suffix})" if suffix else "")))
            ranked.sort(key=lambda pair: pair[0])
            lines = [line for _, line in ranked[:6]]
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
        """Provider 폴백 체인으로 LLM 호출 (cli_news 전용 system_prompt 사용).

        본문 생성은 무료 모델이 흔히 내는 치명 결함(중간 절단·반복 루프·영어 혼입·
        태그 불균형)을 validator로 걸러, 불합격이면 다음 provider(→유료 OpenAI)로
        폴백한다. 정상 출력은 그대로 통과시켜 무료 우선 정책과 비용 0을 유지한다.

        영어 모드: 영어 시스템 프롬프트 + EN_MIN_BODY_WORDS 하한(thin content 방지)
        적용. 길이만 모자란 초안은 버리지 않고 같은 provider에 '보강(repair)'을
        요청한다(_build_length_repair_prompt).
        """
        if is_english_mode():
            return self.call_with_fallback(
                user_prompt,
                system_prompt=_SYSTEM_PROMPT_EN.format(
                    month_year=_month_year_en(),
                    target_min=EN_TARGET_BODY_WORDS_MIN,
                    target_max=EN_TARGET_BODY_WORDS_MAX,
                ),
                # 하한 단어수의 영어 본문은 태그 포함 8,000자를 훌쩍 넘는다 — 얇은 응답 조기 컷.
                min_chars=4000,
                validator=_validate_generated_content,
                repair_builder=_build_length_repair_prompt,
                acceptance_repair_builder=_build_readability_repair_prompt,
            )
        return self.call_with_fallback(
            user_prompt,
            system_prompt=None,
            min_chars=1200,
            validator=_validate_generated_content,
        )

    def call_with_fallback(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        min_chars: int = 200,
        validator: Any = None,
        repair_builder: Any = None,
        acceptance_repair_builder: Any = None,
        max_repairs: int = 2,
    ) -> str | None:
        """Provider 폴백 체인으로 LLM 호출 — 외부 system_prompt 주입 가능.

        OpenRouter 무료 (1차→2차) → OpenAI 유료 fallback 순서로 호출한다.
        ai_content_service 등 다른 모듈이 같은 비용 절감 정책을 따르기 위한 공용 진입점.

        validator: 응답을 추가 검증하는 callable(text). 예외 raise 시 다음 provider로 fallback.
                   응답이 길이만 통과하고 형식(JSON 등)이 깨진 경우 자동 fallback에 사용.
        repair_builder: callable(draft, error) -> str | None. validator가 실패했을 때
                   "고쳐 쓸 수 있는 결함"이면 보강용 프롬프트를 돌려준다(아니면 None).
                   반환값이 있으면 초안을 버리지 않고 **같은 provider**에 그 프롬프트로
                   1회 재호출해 보강본을 받고, 보강본이 validator를 통과하면 채택한다.
                   기본 None — 기존 호출부(ko 모드·ai_slot_enricher 등) 동작은 그대로다.
        acceptance_repair_builder: callable(draft) -> str | None. validator를 통과한
                   초안에 대해 1회 후처리 보정이 필요하면 프롬프트를 돌려준다.
                   이 호출도 max_repairs 예산을 같이 쓴다. 보정본이 원본보다 나쁘면
                   원본을 유지한다.
        max_repairs: 체인 전체에서 허용하는 보강 호출 총 횟수(무한루프 방지 상한).
        """
        repairs_used = 0
        # 길이만 모자라 폐기된 초안 중 가장 긴 것. 전 provider가 실패했을 때의
        # 최후 수단이다 — 대안은 1500단어 글이 아니라 '글 없음'이다.
        best_effort_draft: str | None = None
        best_effort_words = 0

        def _remember_best_effort(candidate: str | None) -> None:
            nonlocal best_effort_draft, best_effort_words
            if not candidate or not is_english_mode():
                return
            words = count_body_words(re.sub(r"<[^>]+>", " ", candidate))
            if words > best_effort_words:
                best_effort_draft, best_effort_words = candidate, words

        for provider in _PROVIDERS:
            api_key = os.getenv(provider["api_key_env"], "").strip()
            if not api_key:
                logger.debug("LlmContentService: %s — API키 없음, skip", provider["name"])
                continue
            # 순간 혼잡(429/타임아웃)이 마지막 유료 폴백까지 겹치면 그대로 발행이
            # 통째로 스킵되므로, provider 종류와 무관하게 최소 1회는 재시도한다.
            # 무료(구독 포함)는 재시도가 비용이 안 들어 3회, 유료(마지막 보루)는
            # 2회로 제한 — 2026-07-20: 유료 폴백 빈도를 낮추려고 무료 쪽 인내심을
            # 늘렸다(자원 소진성 502/429는 짧은 대기로 안 풀리는 경우가 많아
            # 시도를 하나 더 주는 쪽이 그대로 유료로 넘어가는 것보다 싸다).
            attempts = 2 if provider.get("free") is False else 3
            # 영어 모드(2026-07-17): 단어 수·형식 검증 실패는 확률적(같은 모델이
            # 재호출에서 1,600단어를 내기도 함) — 전 provider가 한 번씩 짧게 쓰면
            # 그날 발행이 통째로 스킵되므로 validator 실패도 1회 재시도한다.
            # ko 모드는 기존대로 즉시 다음 provider (비용·시간 특성 유지).
            validator_retry_budget = 1 if is_english_mode() else 0
            for attempt in range(1, attempts + 1):
                def _maybe_acceptance_repair(draft: str) -> str:
                    nonlocal repairs_used
                    if acceptance_repair_builder is None or repairs_used >= max_repairs:
                        return draft
                    repair_prompt = None
                    try:
                        repair_prompt = acceptance_repair_builder(draft)
                    except Exception as rb_exc:  # noqa: BLE001 — 보정 실패는 비치명
                        logger.warning(
                            "LlmContentService: acceptance repair 프롬프트 생성 실패 — %s",
                            rb_exc,
                        )
                    if not repair_prompt:
                        return draft
                    repairs_used += 1
                    return self._attempt_acceptance_repair(
                        provider=provider,
                        api_key=api_key,
                        draft=draft,
                        repair_prompt=repair_prompt,
                        system_prompt=system_prompt,
                        min_chars=min_chars,
                        validator=validator,
                    )

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
                            # 길이만 모자란 초안은 보강이 실패해도 최후 수단으로 남긴다.
                            if isinstance(ve, _WordCountShortfallError):
                                _remember_best_effort(result)
                            # 1) 고칠 수 있는 결함(예: 길이 미달)이면 초안을 버리지 않고
                            #    같은 provider에 보강을 요청한다 — 전면 재생성은 이미
                            #    통과한 팩트·표·FAQ까지 주사위를 다시 굴리고 2분을 더 쓴다.
                            if repair_builder is not None and repairs_used < max_repairs:
                                repair_prompt = None
                                try:
                                    repair_prompt = repair_builder(result, ve)
                                except Exception as rb_exc:  # noqa: BLE001 — 보강 실패는 비치명
                                    logger.warning(
                                        "LlmContentService: repair 프롬프트 생성 실패 — %s", rb_exc
                                    )
                                if repair_prompt:
                                    repairs_used += 1
                                    repaired, repaired_best_effort = self._attempt_repair(
                                        provider=provider,
                                        api_key=api_key,
                                        repair_prompt=repair_prompt,
                                        system_prompt=system_prompt,
                                        min_chars=min_chars,
                                        validator=validator,
                                        reason=str(ve),
                                    )
                                    _remember_best_effort(repaired_best_effort)
                                    if repaired:
                                        return _maybe_acceptance_repair(repaired)
                                    # 자기 초안을 손에 쥐고도 못 고친 모델이 백지에서
                                    # 다시 굴려 성공할 확률은 낮다 — 같은 provider
                                    # 전면 재생성(≈2분)을 태우지 않고 바로 다음 provider로.
                                    validator_retry_budget = 0
                            if validator_retry_budget > 0 and attempt < attempts:
                                validator_retry_budget -= 1
                                logger.warning(
                                    "LlmContentService: %s validator 실패 — %s. 같은 provider 1회 재시도",
                                    provider["name"], ve,
                                )
                                continue
                            logger.warning(
                                "LlmContentService: %s validator 실패 — %s. 다음 provider 시도",
                                provider["name"], ve,
                            )
                            break  # 형식 불량도 provider 특성 — 다음 provider
                    logger.info(
                        "LlmContentService: %s 성공 (%d자)",
                        provider["name"], len(result),
                    )
                    return _maybe_acceptance_repair(result)
                except Exception as exc:
                    logger.warning(
                        "LlmContentService: %s 실패 (시도 %d/%d) — %s",
                        provider["name"], attempt, attempts, exc,
                    )
                    if attempt < attempts:
                        # 자원 소진성 오류(429 rate limit, 502 ResourceExhausted 등
                        # 공급자 쪽 용량 초과)는 짧은 대기로 안 풀리는 경우가 많아
                        # 더 길게 기다린다. 2026-07-20: "429" 리터럴만 보던 조건을
                        # 넓혔다 — 실측에 502 ResourceExhausted("Worker local total
                        # request limit reached")가 짧은 backoff만 받고 있었다.
                        exc_text = str(exc)
                        is_capacity_exhausted = any(
                            token in exc_text
                            for token in ("429", "502", "ResourceExhausted", "rate limit", "Rate limit")
                        )
                        time.sleep(6.0 if is_capacity_exhausted else 2.5)

        # 전 provider 실패 — 길이만 모자란 초안이 남아 있으면 그걸 쓴다.
        # 이 경로가 없던 2026-08-26 리허설에서는 1119·1153·1277·1392단어 초안 4개가
        # 전부 폐기되고 그날 클러스터 슬롯이 통째로 밀렸다.
        if best_effort_draft and best_effort_words >= _acceptable_body_words():
            logger.warning(
                "LlmContentService: 전 provider 실패 — 최선 초안 채택 (%d단어, 하한 %d, 목표 %d). "
                "길이 외 검증은 모두 통과한 초안이다.",
                best_effort_words, _acceptable_body_words(), EN_MIN_BODY_WORDS,
            )
            return best_effort_draft
        if best_effort_draft:
            logger.warning(
                "LlmContentService: 최선 초안도 하한 미달 (%d < %d) — 채택하지 않는다",
                best_effort_words, _acceptable_body_words(),
            )
        return None

    def _attempt_acceptance_repair(
        self,
        *,
        provider: dict[str, Any],
        api_key: str,
        draft: str,
        repair_prompt: str,
        system_prompt: str | None,
        min_chars: int,
        validator: Any,
    ) -> str:
        """validator 통과 후 보정 1회. 실패하거나 나빠지면 원본을 유지한다."""
        before = _measure_readability_html(draft)
        logger.info(
            "LlmContentService: %s readability 보정 시도 (fre=%.1f asl=%.1f)",
            provider["name"],
            float(before.get("flesch_reading_ease") or 0.0),
            float(before.get("avg_sentence_words") or 0.0),
        )
        try:
            repaired = self._call_provider(provider, api_key, repair_prompt, system_prompt)
        except Exception as exc:  # noqa: BLE001 — 보정 실패는 비치명
            logger.warning("LlmContentService: %s readability 보정 호출 실패 — %s", provider["name"], exc)
            return draft
        if not repaired or len(repaired.strip()) <= min_chars:
            logger.warning(
                "LlmContentService: %s readability 보정본이 너무 짧음 (%d자) — 원본 유지",
                provider["name"], len(repaired or ""),
            )
            return draft
        if validator is not None:
            try:
                validator(repaired)
            except Exception as ve:  # noqa: BLE001
                logger.warning(
                    "LlmContentService: %s readability 보정본 검증 실패 — %s. 원본 유지",
                    provider["name"], ve,
                )
                return draft
        selected = _select_readability_repair(draft, repaired)
        after = _measure_readability_html(selected)
        if selected == draft:
            logger.info(
                "LlmContentService: %s readability 보정본 회귀 — 원본 유지 (fre=%.1f asl=%.1f)",
                provider["name"],
                float(before.get("flesch_reading_ease") or 0.0),
                float(before.get("avg_sentence_words") or 0.0),
            )
            return draft
        logger.info(
            "LlmContentService: %s readability 보정 채택 (fre %.1f→%.1f, asl %.1f→%.1f)",
            provider["name"],
            float(before.get("flesch_reading_ease") or 0.0),
            float(after.get("flesch_reading_ease") or 0.0),
            float(before.get("avg_sentence_words") or 0.0),
            float(after.get("avg_sentence_words") or 0.0),
        )
        return selected

    def _attempt_repair(
        self,
        *,
        provider: dict[str, Any],
        api_key: str,
        repair_prompt: str,
        system_prompt: str | None,
        min_chars: int,
        validator: Any,
        reason: str,
    ) -> tuple[str | None, str | None]:
        """초안 보강 1회 시도 — (채택본, 최선노력본)을 돌려준다.

        채택본은 validator를 통과한 보강본이고, 없으면 None이다. 최선노력본은
        "길이만 모자란" 보강본 — 호출부가 전 provider 실패 시 최후 수단으로 쓸 수
        있게 버리지 않고 돌려준다(EN_ACCEPTABLE_BODY_WORDS 참고). 다른 사유로
        깨진 보강본은 최선노력본으로도 돌려주지 않는다.

        같은 provider를 쓴다(초안을 쓴 모델이 자기 글을 이어 쓰는 게 가장 자연스럽고,
        폴백 체인의 무료 우선 순서도 흐트러지지 않는다). 여기서 절대 재귀하지 않으므로
        보강 호출은 항상 정확히 1회다 — 총량은 call_with_fallback의 max_repairs가 막는다.
        """
        logger.info(
            "LlmContentService: %s 초안 보강 시도 (사유: %s)", provider["name"], reason
        )
        try:
            repaired = self._call_provider(provider, api_key, repair_prompt, system_prompt)
        except Exception as exc:  # noqa: BLE001 — 보강 실패는 비치명, 기존 폴백으로 진행
            logger.warning("LlmContentService: %s 보강 호출 실패 — %s", provider["name"], exc)
            return None, None
        if not repaired or len(repaired.strip()) <= min_chars:
            logger.warning(
                "LlmContentService: %s 보강본이 너무 짧음 (%d자) — 폴백 계속",
                provider["name"], len(repaired or ""),
            )
            return None, None
        if validator is not None:
            try:
                validator(repaired)
            except _WordCountShortfallError as ve:
                # 길이만 모자란 보강본은 버리지 않는다 — 전 provider가 실패했을 때
                # "글 없음"보다 낫다. 채택 여부는 호출부가 정한다.
                logger.warning(
                    "LlmContentService: %s 보강본도 길이 미달 — %s. 폴백 계속(최선본 보관)",
                    provider["name"], ve,
                )
                return None, repaired
            except Exception as ve:  # noqa: BLE001
                logger.warning(
                    "LlmContentService: %s 보강본도 검증 실패 — %s. 폴백 계속",
                    provider["name"], ve,
                )
                return None, None
        logger.info(
            "LlmContentService: %s 보강 성공 (%d자) — 재생성 없이 채택",
            provider["name"], len(repaired),
        )
        return repaired, None

    def _call_provider(
        self,
        provider: dict[str, Any],
        api_key: str,
        user_prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Configured LLM provider 호출."""
        if provider.get("provider_type") == "claude_code_cli":
            return self._call_claude_code_cli(provider, api_key, user_prompt, system_prompt)
        return self._call_openai_compatible_provider(provider, api_key, user_prompt, system_prompt)

    def _resolve_provider_model(self, provider: dict[str, Any]) -> str:
        model_env = str(provider.get("model_env") or "").strip()
        if model_env:
            env_model = os.getenv(model_env, "").strip()
            if env_model:
                return env_model
        model = provider.get("model")
        if model is None:
            # claude_code_cli는 model=None이면 CLI 기본 모델을 그대로 쓴다
            # (OpenAI 기본값 "gpt-5-mini"를 --model로 넘기면 안 됨).
            if provider.get("provider_type") == "claude_code_cli":
                return ""
            return os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
        return str(model).strip()

    def _call_claude_code_cli(
        self,
        provider: dict[str, Any],
        api_key: str,
        user_prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Claude Code CLI(`claude -p`)로 본문을 생성한다 — 구독 인증, 토큰 과금 없음.

        2026-07-20: GitHub Actions Actions 분당 무료 한도 소진 대응으로 Cloud Run
        등 별도 인프라에서 이 경로를 1순위로 쓴다. 핵심 제약:
        - `--bare`는 절대 쓰지 않는다 — 공식 도움말에 "OAuth and keychain are
          never read"라고 명시돼 있어 구독 인증(CLAUDE_CODE_OAUTH_TOKEN)이 아예
          안 먹고 조용히 API 키 과금으로 새거나 인증 실패한다.
        - `--tools ""`로 모든 도구를 꺼서 순수 텍스트 완성만 하게 한다(파일/bash
          접근 없이 임의 프롬프트를 안전하게 처리하기 위함).
        - 작업 디렉터리를 리포 밖의 빈 임시 폴더로 둔다 — cwd가 리포 루트면
          CLAUDE.md 자동 발견으로 파이프라인 운영 지침이 본문 생성 프롬프트에
          불필요하게 섞여 들어간다.
        """
        model = self._resolve_provider_model(provider)
        timeout = int(provider.get("timeout") or 180)
        args = [
            "claude", "-p",
            "--tools", "",
            "--output-format", "json",
            "--no-session-persistence",
            "--system-prompt", system_prompt if system_prompt is not None else _SYSTEM_PROMPT,
        ]
        if model:
            args.extend(["--model", model])
        args.append(user_prompt)

        env = dict(os.environ)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = api_key
        # ANTHROPIC_API_KEY가 같이 설정돼 있으면 SDK가 두 인증을 동시에 보내
        # 요청이 거부될 수 있다 — 구독 인증 경로에서는 명시적으로 비운다.
        env.pop("ANTHROPIC_API_KEY", None)

        with tempfile.TemporaryDirectory(prefix="claude_cli_cwd_") as cwd:
            result = subprocess.run(
                args,
                env=env,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude -p exited {result.returncode}: {(result.stderr or '').strip()[:500]}"
            )
        stdout = (result.stdout or "").strip()
        try:
            payload = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"claude -p produced non-JSON output: {exc}") from exc
        text = str(payload.get("result") or "").strip()
        if not text:
            raise RuntimeError(f"claude -p JSON response had no 'result' field: {stdout[:300]}")
        return _clean_llm_output(text)

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
        provider_timeout = int(provider.get("timeout") or _TIMEOUT)
        result, _elapsed = post_chat_completion(
            endpoint=base_url,
            headers=headers,
            payload=payload,
            timeout=provider_timeout,
        )

        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices in response: {result}")
        # content가 키는 있는데 값이 null인 응답이 실제로 온다(2026-08-26 GHA 실측:
        # openrouter_free_router 보정 호출이 "'NoneType' object has no attribute
        # 'strip'"으로 죽었다). .get(key, "") 기본값은 키가 없을 때만 쓰이므로
        # 명시적 null은 걸러지지 않는다 — `or ""`로 받아야 한다.
        content = (choices[0].get("message") or {}).get("content") or ""
        return _clean_llm_output(content)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def free_openai_compatible_providers() -> list[dict[str, Any]]:
    """본문 생성에 실제로 쓰는 무료 OpenAI 호환 provider 목록(사본).

    model_benchmark_service가 "우리가 무엇으로 글을 쓰는가"를 재려면 이 목록이
    유일한 출처여야 한다. 재는 쪽에 모델을 따로 적어두면 provider를 바꿨을 때
    발행 글의 표만 옛 모델을 가리키게 된다.
    """
    return [
        dict(provider)
        for provider in _PROVIDERS
        if provider.get("provider_type") == "openai_compatible" and provider.get("free")
    ]


def post_chat_completion(
    *,
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> tuple[dict[str, Any], float]:
    """OpenAI 호환 chat/completions 1회 호출. (응답 JSON, 소요 초)를 돌려준다.

    본문 생성과 model_benchmark_service가 같은 전송 경로를 쓰게 하려고 뽑아낸
    함수다. 이 저장소는 같은 일을 하는 클라이언트가 3개까지 늘어난 적이 있고
    (자동완성 전송 3중복, 2026-08-25 PR #68로 정리), 전송이 갈라지면 헤더 하나가
    한쪽에만 적용되는 종류의 버그가 조용히 생긴다.

    소요 시간을 함께 돌려주는 이유: 벤치마크 쪽에서 응답 시간이 곧 측정값이라,
    호출부가 따로 재면 재시도·리다이렉트가 포함되는지 여부가 달라진다.
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_obj = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    started = time.monotonic()
    with urllib.request.urlopen(request_obj, timeout=timeout) as resp:
        result = json.loads(resp.read().decode())
    return result, time.monotonic() - started


def _clean_llm_output(text: str) -> str:
    """마크다운 코드블록 제거 등 LLM 출력 정리."""
    text = text.strip()
    # ```html ... ``` 제거
    text = re.sub(r'^```(?:html)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


class _ContentValidationError(ValueError):
    """생성 콘텐츠가 잘림·반복·언어·구조 결함을 보여 다음 provider로 폴백해야 함을 뜻한다."""


class _WordCountShortfallError(_ContentValidationError):
    """길이만 모자란 초안 — 폐기 대상이 아니라 '보강(repair)' 대상이다.

    다른 결함(절단·태그 불균형·한국어 혼입·상투구·헤지 포화)과 달리 길이 미달은
    이미 쓴 내용이 멀쩡하다는 뜻이라, 초안을 돌려주며 섹션을 늘리게 하는 편이
    전면 재생성보다 싸고(호출 1회 ~2분 절약) 품질 분산도 작다.
    """

    def __init__(self, word_count: int, min_words: int) -> None:
        self.word_count = int(word_count)
        self.min_words = int(min_words)
        super().__init__(f"영어 본문 단어 수 부족 ({self.word_count} < {self.min_words})")


def _build_length_repair_prompt(draft: str, error: Exception) -> str | None:
    """길이 미달 초안에 대한 보강 프롬프트를 만든다 (다른 결함이면 None).

    초안 HTML은 `.format()`에 넣지 않고 뒤에 붙인다 — 본문에 중괄호가 있으면
    포맷이 터지기 때문이다.
    """
    if not isinstance(error, _WordCountShortfallError):
        return None
    # 하한에 딱 맞추려다 또 미달하는 것을 막기 위해 목표 하단까지 요구한다.
    needed = max(150, EN_TARGET_BODY_WORDS_MIN - error.word_count)
    head = _REPAIR_LENGTH_INSTRUCTIONS_EN.format(
        word_count=error.word_count,
        min_words=error.min_words,
        needed_words=needed,
        target_min=EN_TARGET_BODY_WORDS_MIN,
        target_max=EN_TARGET_BODY_WORDS_MAX,
    )
    return f"{head}\n[PREVIOUS DRAFT — expand this exact HTML]\n{draft}"


def _build_readability_repair_prompt(draft: str) -> str | None:
    """영어 초안이 soft readability 목표를 못 맞추면 1회 보정 프롬프트를 만든다."""
    if not is_english_mode():
        return None
    metrics = _measure_readability_html(draft)
    if not _readability_below_target(metrics):
        return None
    hard = [str(s).strip() for s in list(metrics.get("hard_sentences") or []) if str(s).strip()]
    if hard:
        hard_lines = "\n".join(f"- {sentence}" for sentence in hard[:5])
    else:
        hard_lines = "- No single sentence crossed the hard-sentence threshold; shorten the longest sentences anyway."
    head = _REPAIR_READABILITY_INSTRUCTIONS_EN.format(
        fre=f"{float(metrics.get('flesch_reading_ease') or 0.0):.1f}",
        asl=f"{float(metrics.get('avg_sentence_words') or 0.0):.1f}",
        long_word_pct=f"{float(metrics.get('long_word_pct') or 0.0):.1f}",
        hard_sentences=hard_lines,
    )
    return f"{head}\n[PREVIOUS DRAFT — rewrite this exact HTML in easier English]\n{draft}"


def _readability_rank(metrics: dict[str, object]) -> tuple[float, float, float]:
    return (
        float(metrics.get("flesch_reading_ease") or 0.0),
        -float(metrics.get("avg_sentence_words") or 0.0),
        -float(metrics.get("long_word_pct") or 0.0),
    )


def _select_readability_repair(original: str, repaired: str) -> str:
    """보정본이 원본보다 읽기쉬움 지표상 나쁘면 원본을 유지한다."""
    original_metrics = _measure_readability_html(original)
    repaired_metrics = _measure_readability_html(repaired)
    if int(repaired_metrics.get("words") or 0) <= 0:
        return original
    if int(original_metrics.get("words") or 0) <= 0:
        return repaired
    if _readability_rank(repaired_metrics) < _readability_rank(original_metrics):
        return original
    return repaired


# 시스템 프롬프트의 문체 규칙이 금지한 대표 AI 필러 표현. 오탐을 피하기 위해
# 문맥과 무관하게 항상 저품질 신호인 표현만 담는다(일반 문장에도 흔한 단어 제외).
_AI_CLICHE_PHRASES = (
    "게임 체인저",
    "게임체인저",
    "귀추가 주목",
    "무궁무진한 가능성",
    "단순한 도구를 넘어",
    "우리의 삶을 혁신",
    "빠르게 변화하는 디지털 시대",
    "새로운 시대를 열",
    "혁신적인 변화의 물결",
)

# 영어 모드 상투 문구 — 시스템 프롬프트가 금지한 대표 AI 필러. 문맥과 무관하게
# 항상 저품질 신호인 것만 담는다(일반 문장에 흔한 단어 제외). 소문자 비교.
_AI_CLICHE_PHRASES_EN = (
    "game-changer",
    "game changer",
    "in today's fast-paced world",
    "in today's fast-paced digital",
    "delve into",
    "unlock the power",
    "harness the power",
    "revolutionize the way",
    "look no further",
    "it's important to note that",
    "elevate your",
    "in this article, we will",
    # 날조 1인칭 테스트 주장 — 자동 파이프라인은 실테스트가 불가능하므로 항상 허위
    "i tested",
    "in my testing",
    "i personally used",
    "in my experience",
    # 우회/탈취 프레이밍 — 애드센스 정책 지뢰 (합법적 해결 프레이밍으로 재생성 유도)
    "how to bypass",
    "bypass the limit",
    "unlock paid features",
    "avoid detection",
)

# 영어 모드 헤지(책임 회피) 문구 — 2026-07-21 발행 2건 실측에서 "check the
# official page"류가 글당 29·36회 등장해 가격비교 글에 정작 가격이 없는 껍데기가
# 됐다. 팩트 안전 원칙(모르는 수치는 안 쓴다)은 유지하되, 헤지가 본문을 지배하면
# 검증기/게이트가 잡는다. 정규식 교대는 긴 패턴 우선이라 중복 계산이 없다.
_HEDGE_PHRASES_EN_RE = re.compile(
    r"(?:"
    r"check\s+(?:the\s+)?official(?:\s+\w+){0,3}\s+page"
    r"|check\s+(?:the\s+)?official\s+(?:docs|documentation|announcements?)"
    r"|check\s+(?:each\s+|the\s+)?vendors?(?:'s?)?\s+(?:page|pages|site|sites|help)"
    r"|consult\s+(?:the\s+|each\s+)?(?:official|vendors?)"
    r"|not\s+published|isn'?t\s+published|aren'?t\s+published"
    r"|don'?t\s+publish|doesn'?t\s+publish|unpublished"
    r"|unconfirmed|not\s+confirmed|isn'?t\s+confirmed|aren'?t\s+confirmed"
    r"|remains?\s+unverified|no\s+verified"
    r"|not\s+disclosed|isn'?t\s+disclosed|aren'?t\s+disclosed"
    # --- 2026-07-25 추가: 7/24 발행글 실측에서 위 패턴을 전부 비껴간 지배적 헤지들.
    # 그 글은 실제 헤지 21문장(28.4%)인데 위 정규식은 3개만 잡아 임계값 14에
    # 걸리지 않았다. "정보를 안 준다"를 서술하는 어법이 훨씬 다양하다.
    r"|(?:does|do|did)\s?n'?t\s+(?:list|spell\s+out|detail|specify|break\s+out|name|itemi[sz]e|say)"
    r"|(?:was|were|is|are)\s?n'?t\s+(?:detailed|specified|broken\s+out|itemi[sz]ed|named|listed|spelled\s+out|clear)"
    r"|has\s?n'?t\s+(?:shown\s+up|been\s+(?:named|detailed|published|specified|broken\s+out))"
    r"|have\s?n'?t\s+been\s+(?:named|detailed|published|specified)"
    r"|(?:not|never)\s+(?:named|itemi[sz]ed|broken\s+out|spelled\s+out)\s+(?:in|anywhere|by)"
    r"|no(?:ne)?\s+of\s+the\s+(?:outlets?|reports?|coverage)\s+(?:published|named|detailed|broke)"
    r"|confirm\s+(?:the\s+)?(?:specifics|details|mechanics|numbers)"
    r"|confirm\s+(?:it|this|these|them|those)?\s*(?:directly|yourself|inside)"
    r"|verify\s+(?:the\s+)?(?:specifics|details|numbers|this|it)\s+(?:before|yourself|directly)"
    r"|don'?t\s+assume|do\s+not\s+assume"
    r"|don'?t\s+plan\s+(?:a\s+)?workflow|don'?t\s+build\s+(?:a\s+)?workflow"
    r"|treat\s+(?:the\s+|these\s+|this\s+|it\s+)?\w*\s*as\s+(?:still\s+settling|reported|secondary|provisional)"
    r"|still\s+settling|still\s+catching\s+up"
    r"|hold\s+off\s+(?:on\s+)?(?:building|planning)"
    r"|see\s+what'?s\s+listed\s+for\s+your\s+account"
    r"|(?:open|check)\s+(?:your|the)\s+(?:app|account)(?:'s)?\s+\w*\s*settings"
    r")",
    re.IGNORECASE,
)


def hedge_phrase_hits_en(text: str) -> list[str]:
    """영어 본문에서 헤지 문구를 찾아 돌려준다 (HTML 태그 제거 후 비교)."""
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or ""))
    return [m.group(0) for m in _HEDGE_PHRASES_EN_RE.finditer(plain)]


def hedge_saturation_en(text: str) -> dict[str, object]:
    """헤지를 '글 길이로 정규화한 비율'로 잰다.

    2026-07-25: 절대 개수 임계값(>=14)이 무력했던 이유가 두 가지였다.
    (1) 정규식이 좁아 실제 헤지를 못 셌고, (2) 74문장 글과 113문장 글에 같은
    절대값을 적용해 긴 글이 유리했다. 실측(최근 5개 발행글)에서 헤지 **문장 비율**은
    문제 글 28.4% / 정상 글 8.7~16.5%로 깔끔히 갈렸다 — 그래서 비율을 1차 지표로 쓴다.

    반환: count(히트 수), hedge_sentences(헤지가 든 문장 수), sentence_count,
    ratio(hedge_sentences/sentence_count), samples.
    """
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()
    hits = [m.group(0) for m in _HEDGE_PHRASES_EN_RE.finditer(plain)]
    # 문장 분리는 대략치로 충분하다 — 25자 미만 조각(표 셀·라벨 잔여물)은 제외해
    # 분모가 부풀지 않게 한다.
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", plain) if len(s) > 25]
    hedge_sentences = sum(
        1 for s in sentences if _HEDGE_PHRASES_EN_RE.search(s) is not None
    )
    sentence_count = len(sentences)
    ratio = (hedge_sentences / sentence_count) if sentence_count else 0.0
    return {
        "count": len(hits),
        "hedge_sentences": hedge_sentences,
        "sentence_count": sentence_count,
        "ratio": round(ratio, 4),
        "samples": hits[:8],
    }


# 영어 모드 overclaim 중화 — 게이트 패턴을 깨되 의미는 보존하는 결정적 치환.
_OVERCLAIM_SOFTENERS_EN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"guaranteed (income|profit|returns?)", re.IGNORECASE), r"potential \1"),
    (re.compile(r"100%\s*safe", re.IGNORECASE), "generally safe"),
    (re.compile(r"works for everyone", re.IGNORECASE), "works for many users"),
    (re.compile(r"no (human )?review (is )?needed", re.IGNORECASE), "with a quick review"),
    (re.compile(r"replaces? (all|every) (your )?(work|jobs?|tasks?)", re.IGNORECASE), "handles part of the work"),
)


def _validate_generated_content(html: str) -> None:
    """무료 모델이 흔히 내는 치명 결함을 검출한다(하나라도 걸리면 예외 → 다음 provider).

    2026-07-08 라이브 사고(제미나이 3.5 글)에서 실제로 관측된 결함들을 겨냥한다:
    글 뒤 30%가 max_tokens에서 잘리고, 도입부 문장이 소제목·본문에 반복 삽입되고,
    영어 도입부가 섞이고, 깨진 태그를 조립기가 못 살려 해시태그가 본문 중간에 낀 사고.
    정상 출력은 통과시켜 무료 우선 정책(비용 0)을 지키고, 깨진 출력만 유료로 넘긴다.
    """
    raw = (html or "").strip()
    if not raw:
        raise _ContentValidationError("빈 응답")
    english = is_english_mode()

    # 1) 중간 절단: 정상 출력은 닫는 태그(</section> 등)로 끝난다. 태그로 끝나지
    #    않으면 max_tokens에서 문장 중간에 잘린 것으로 본다.
    if not raw.endswith(">"):
        raise _ContentValidationError("응답이 태그로 끝나지 않음 — 중간 절단 의심")

    # 2) 구조 태그 불균형: 열림≠닫힘이면 조립기가 GEO 블록 배치·해시태그 삽입에서
    #    앵커를 잘못 잡아 본문이 스크램블된다(어제 사고의 직접 원인).
    for tag in ("div", "section", "article", "table", "ul", "ol"):
        opens = len(re.findall(rf"<{tag}\b", raw, re.IGNORECASE))
        closes = len(re.findall(rf"</{tag}>", raw, re.IGNORECASE))
        if opens != closes:
            raise _ContentValidationError(f"<{tag}> 태그 불균형(열림 {opens}/닫힘 {closes})")

    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()

    # 3) FAQ 답 미완성: 비었거나 지나치게 짧은 faq-a는 잘림/오류.
    #    영어 모드는 발행 게이트(faq_answer_too_short, 20자)와 같은 하한을 여기서
    #    먼저 걸어 재시도로 회복한다 (드라이런 #9: 한 줄 답변이 게이트에서 차단).
    _faq_min = 20 if english else 5
    for ans in re.findall(r'class="faq-a"[^>]*>(.*?)</', raw, re.DOTALL):
        if len(re.sub(r"<[^>]+>", "", ans).strip()) < _faq_min:
            raise _ContentValidationError("FAQ 답이 비었거나 잘림")

    # 4) 언어 정합: 한국어 모드에서는 영어 설명 문장 혼입(연속 영단어 6개 이상),
    #    영어 모드에서는 한글 혼입·단어 수 미달(thin content)을 걸러낸다.
    if english:
        if re.search(r"[가-힣]", text):
            raise _ContentValidationError("영어 모드에 한국어 혼입")
        word_count = count_body_words(text)
        if word_count < EN_MIN_BODY_WORDS:
            # 길이만 모자란 경우는 전용 예외 — 호출부가 재생성 대신 보강을 시도한다.
            raise _WordCountShortfallError(word_count, EN_MIN_BODY_WORDS)
    elif re.search(r"[A-Za-z]{2,}(?:[ ,]+[A-Za-z]{2,}){5,}", text):
        raise _ContentValidationError("영어 문장 혼입 의심")

    # 5) 반복 루프: 20자 이상 문장이 본문에 두 번 이상 등장(도입부 문장이 뒤에서
    #    재등장하는 어제 유형 포함).
    for s in [s.strip() for s in re.split(r"[.。!?]\s+", text) if len(s.strip()) >= 20][:8]:
        if text.count(s) >= 2:
            raise _ContentValidationError("문장 반복 — 반복 루프 의심")

    # 6) AI 상투 문구(2026-07-16): 시스템 프롬프트가 명시적으로 금지한 대표 필러
    #    표현. 금지 지시를 무시한 출력은 나머지 본문도 일반론 채우기일 가능성이
    #    높다 → 다음 provider로 폴백. (전 provider 실패 시 템플릿 폴백이 있어
    #    발행 회귀는 없다.)
    for phrase in _AI_CLICHE_PHRASES:
        if phrase in text:
            raise _ContentValidationError(f"AI 상투 문구 검출: {phrase}")
    if english:
        lowered = text.lower()
        for phrase in _AI_CLICHE_PHRASES_EN:
            if phrase in lowered:
                raise _ContentValidationError(f"AI 상투 문구 검출(EN): {phrase}")

        # 7) 헤지 포화(2026-07-22): "check the official page"류가 본문을 지배하면
        #    가격비교 글에 가격이 없는 껍데기다(2026-07-21 발행 2건 실측 29·36회).
        #    재시도로 회복 가능한 결함이라 게이트(최종 14회 차단)보다 낮은 10회에서
        #    먼저 걸어 재생성을 유도한다.
        hedge_hits = hedge_phrase_hits_en(raw)
        if len(hedge_hits) >= 10:
            raise _ContentValidationError(
                f"헤지 문구 포화 ({len(hedge_hits)}회) — 검증된 팩트 중심으로 재생성 필요"
            )


def _close_faq_section_wrapper(html: str) -> str:
    """div→section으로 바꾼 FAQ 래퍼의 '짝 닫는 태그'를 </section>으로 맞춘다.

    div 중첩을 걸어가며 변환된 <section class="faq-section"> 바로 안쪽 깊이에서
    처음 만나는 </div>를 </section>으로 치환한다. 매칭 실패 시 원문 그대로 반환.
    """
    open_match = re.search(r'<section\s+class="faq-section"[^>]*>', html)
    if not open_match:
        return html
    pos = open_match.end()
    depth = 0
    for m in re.finditer(r"</?div\b[^>]*>", html[pos:]):
        token = m.group(0)
        if token.startswith("</"):
            if depth == 0:
                start = pos + m.start()
                return html[:start] + "</section>" + html[start + len(token):]
            depth -= 1
        else:
            depth += 1
    return html


def _clean_entity_artifacts(html: str) -> str:
    """LLM 출력 HTML에서 노출 위험 entity artifact를 제거한다.

    처리 순서:
    1. &amp;#숫자  → &#숫자  (이중 escape 해소)
    2. &#숫자;     → unicode 문자 (세미콜론 있는 정상 entity 디코딩)
    3. &#숫자(세미콜론 없음) → unicode 문자 (불완전 entity 디코딩)
    HTML 태그 구조·속성은 변경하지 않는다.
    """
    # 1) 이중 escape 해소: &amp;#숫자 / &amp;#x16진수 → &#...
    result = re.sub(r'&amp;(#(?:[xX][0-9a-fA-F]+|\d+))', r'&\1', html)
    # 2) 세미콜론 있는 숫자 entity → unicode (10진 + 16진 &#x27; 모두 —
    #    2026-07-16 실측: LLM이 작은따옴표를 &#x27;로 내는 케이스가 관측됐고
    #    기존 10진 전용 처리·게이트 둘 다 hex 표기를 놓치는 블라인드 스팟이 있었다)
    def _decode_entity_with_semi(m: re.Match) -> str:
        token = m.group(1)
        code = int(token[1:], 16) if token[0] in "xX" else int(token)
        try:
            return chr(code) if 0 < code < 0x110000 else m.group(0)
        except (ValueError, OverflowError):
            return m.group(0)
    result = re.sub(r'&#([xX][0-9a-fA-F]+|\d+);', _decode_entity_with_semi, result)
    # 3) 세미콜론 없는 entity → unicode (공백·태그·줄끝 앞에 있는 경우만)
    def _decode_entity_bare(m: re.Match) -> str:
        token = m.group(1)
        code = int(token[1:], 16) if token[0] in "xX" else int(token)
        try:
            return chr(code) if 0 < code < 0x110000 else ''
        except (ValueError, OverflowError):
            return ''
    result = re.sub(r'&#([xX][0-9a-fA-F]+|\d+)(?=\s|<|$)', _decode_entity_bare, result)
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
    if is_english_mode():
        return f"{title} — pricing, limits, and what to check before you rely on it."[:160]
    return f"{title} — 대상·신청방법·일정을 한눈에 정리했습니다."[:160]
