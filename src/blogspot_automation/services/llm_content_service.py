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
from html import unescape as _html_unescape
from typing import Any

from blogspot_automation.services.blog_language import is_english_mode
from blogspot_automation.services.issue_content_profile_service import IssueContentProfileService
from blogspot_automation.services.kst_clock import kst_today
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

# ─── 영어 모드 프롬프트 (2026-07-17 영어 전환) ────────────────────────────────
# 대상: 미국·영국·캐나다·인도 영어권 검색 독자 + AI 챗봇 인용(GEO).
# 수익 모델: 애드센스 단일 — thin content·낚시 제목·확인 안 된 수치가 최대 리스크.
_SYSTEM_PROMPT_EN = """You are the staff writer and quality editor for an English-language AI blog that publishes automatically to Blogspot. Readers arrive from Google search (US, UK, Canada, India) or from AI chatbots (ChatGPT, Perplexity, Google AI Overviews) citing this blog as a source.

Top priority: an article that is SAFE to auto-publish beats an article that is flashy. The blog is under AdSense review — thin content, clickbait, and unverified numbers are the fastest ways to fail.

[FACT SAFETY — the #1 rule for auto-published articles]
Never state any of the following unless it appears in the provided [SEARCH FACTS]: release dates, prices, plan names, free-tier limits, model names/version numbers, feature availability, menu paths, data-retention policies, country availability, default settings.
- Every price, limit, or spec you do state must carry an as-of date: "as of {month_year}" — and name the source in plain text (e.g. "per OpenAI's pricing page").
- If a number is not in the facts, do NOT invent it. Write "check the official pricing page for current rates" instead. One stale or invented price kills the article's credibility and its chance of being cited by AI search.
- Never invent benchmarks, statistics, or survey results. Never invent first-person usage anecdotes ("I tested", "in my testing") unless the claim is verifiable from the provided facts — describe what the facts support instead.
- Version/generation numbers: only use them exactly as written in the facts. Never guess the next version up. Product naming must be identical in title and body.

[BANNED — auto-publish gate will reject these]
- Affiliate links, promo codes, "buy through my link".
- Income guarantees ("guaranteed income", "get rich", "$X/month easily"), "100% safe", "works for everyone", "no review needed".
- Investment advice tied to specific stocks/coins, medical or legal judgments.
- AI-slop phrases and their variants: "game-changer", "revolutionize", "unlock the power", "harness the power", "in today's fast-paced world", "delve into", "it's important to note", "look no further", "elevate your", "seamlessly". Replace every one of them with a concrete fact or judgment.
- Clickbait: "you won't believe", "shocking", "insane".

[WRITING RULES]
1. English only. US blog register: short sentences, second person ("you"), active voice. No throat-clearing — never open with "In this article, we will..." or "AI is evolving rapidly". Start with the reader's situation or the direct answer.
2. Opening = the direct answer. The first paragraph answers the title's question in 2-3 sentences WITH the key number(s). AI chatbots and Google AI Overviews quote this block verbatim — make it quotable on its own.
3. Depth duty: at least 2 things a knowledgeable reader would not already know — exact limits, price math with a worked example, cause-and-effect ("turning on X cuts Y by ~Z because..."), order-of-operations that only applies to this tool. If a paragraph teaches nothing new, cut it or make it concrete.
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
4) At least 2 genuinely new concrete facts? A "use it / skip it" judgment with conditions?
5) Any banned phrase, income claim, or invented anecdote left?

[HTML — use exactly these classes; the publish CSS styles them]
- No Markdown, no HTML entity codes (&#...;) — use unicode characters directly. No hashtags in the body (the system appends them).
- Never expose internal jargon: "SEO", "GEO", "AEO", "SGE", "CTA", "AdSense" (unless AdSense itself is the article topic).
- Allowed classes only: actions-box, risk-note, quick-decision-table, quality-checklist, faq-section/faq-item/faq-q/faq-a, confirmed-needed-box. Inventing other classes or inline styles leaves the article unstyled."""

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
One person found this through a Google search. Write one continuous article they read top to bottom — a flow, not a form. Length: 1,600-2,400 words of plain text (excluding HTML tags). Never below 1,500 words — thin content fails AdSense review.

[STRUCTURE]
1) Opening paragraphs (plain <p>, no box — the system builds the top summary box from them):
   the reader's concrete situation in 1-2 lines → the direct answer to the title's question in 2-3 sentences with the key numbers and "as of {month_year}". No greetings, no "AI is changing fast".
2) 4-6 <h2> sections. Use tight noun-phrase headings ("Pricing and limits", "Where beginners get stuck") — AT MOST 2 headings in the whole article may be question-style (starting with How/What/Why or ending with "?"); the automated layout adds its own Q&A blocks and too many question headings blocks publishing. Each section goes one step deeper than the last.
   - Cover, as fits the topic: what actually changed / how it works → real numbers (pricing, limits, quotas — only from facts, each with as-of + source) → what stays the same and what is still unconfirmed → what it means for the reader's time and money → where beginners get stuck (cause + fix) + at least one little-known tip.
   - If a follow-along process has 3+ steps, use (numbers are auto-generated by CSS — do not write "1."):
     <div class="actions-box"><ol><li><strong>One-line step title</strong> — concrete instruction</li> ...</ol></div>
   - If there is one honest caveat worth isolating, use exactly one:
     <div class="risk-note"><span class="section-label">Watch out</span><p>1-2 sentences of the real risk</p></div>
3) MANDATORY: one comparison/pricing/spec table inside the flow, wrapped exactly like this (the wrapper enables mobile scroll + first-column emphasis):
   <div class="quick-decision-table"><table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table></div>
   Make it worth saving: plans vs prices vs limits, tool-by-task comparison, before/after, cost math. Columns = the reader's decision criteria. NO empty cells — write "n/a" or "check official page" when a value is unknown. Put one framing sentence before and after. Add "as of {month_year}" near the table when it contains prices/limits. LLM answer engines cite pages whose numbers sit in clean tables — this table is the citation magnet.
4) <h2>Frequently Asked Questions</h2> then EXACTLY this markup with EXACTLY 3 FAQs (each answer 15-50 words — never a one-liner under 15 words — complete and only verified content; pick real search queries NOT already covered by the body — billing, limits, alternatives, data handling, cancellation; answers must NOT repeat body sentences):
<section class="faq-section">
  <article class="faq-item"><h3 class="faq-q">Actual search question?</h3><p class="faq-a">Direct, complete answer.</p></article>
</section>
5) Closing: no summary rehash. One or two sentences: who should use this today vs. who should wait (concrete conditions). Then output this block verbatim in structure (keep id and classes exactly; fill with topic-specific items only):
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
  <div class="confirmed-section"><h3>What's confirmed</h3><ul><li>3 facts that are settled for this topic</li></ul></div>
  <div class="check-needed-section"><h3>Check for yourself</h3><ul><li>3 things that change often (prices, limits, availability) with where to check</li></ul></div>
</section>
(The system appends related internal links after your article — do not add external links or a "read more" section yourself.)

[OPTIONAL — only when the topic genuinely calls for it]
- Pre-flight checklist: <div class="quality-checklist"><ul><li>topic-specific check item</li>...</ul></div>
{asset_directive}
[DO NOT]
- Use any class not listed above, or inline style attributes.
- Pad with generic "AI productivity tips" that fit any article.
- Repeat the same guidance in multiple sections.
- Write filler FAQs that restate body paragraphs.

Output rules:
- Output only the inner HTML (no div.post-content wrapper, no <html>/<head>). Complete every tag.
- <h2> for sections, <h3> for sub-points. English only.
- No Markdown, no &#...; entities, no hashtags.

FINAL LENGTH CHECK (do this before you output): the article body must be AT LEAST 1,600 words of plain text — anything under 1,500 words is automatically rejected as thin content and never published. If your draft is short, do not pad with fluff; go deeper instead: expand the beginner-blockers section with one more concrete failure-and-fix, add a worked example under the table, and extend the judgment section with one more reader profile. Aim for 1,700-2,200 words."""

# 영어 모드 '저장용 무기' 지시 — 비교·가격·비용계산·통계 유형에서 켠다.
_ASSET_RICH_DIRECTIVE_EN = """
[This is a comparison/pricing/cost-math article — load it with savable assets]
Readers save this article to reuse its numbers. Fill 1-2 of these with REAL values from the facts (never all of them as empty scaffolding):
 - Cost math: the formula (input/output tokens × model rate) plus one worked example in a quick-decision-table. Add "as of {month_year}" and "check the official pricing page". If the rate is not in the facts, show the METHOD only — never invent a rate.
 - Comparison table: only the tools/plans this topic is about; columns are decision criteria (price, limits, speed, best-for). quick-decision-table wrapper.
 - Checklist: pre-purchase or pre-setup checks specific to this topic in a quality-checklist div.
[Honesty rule]
 - No first-person measured results ("I ran it and got X seconds"). Give the reader the experiment design instead: what to run, under which condition, what to measure.
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
        self._exa_facts_max_calls = 6
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
        if is_english_mode():
            # 영어 모드 리서치: Naver 뉴스는 한국어 소스라 스킵. Exa(영문 웹 본문
            # 발췌 — 경쟁 상위글·공식 가격 페이지)가 1차, Google News RSS(en-US)가 폴백.
            naver_text, naver_citations = "", []
        else:
            naver_text, naver_citations = self._naver_news_facts_and_citations(topic)
        exa_text, exa_citations = self._exa_facts_and_citations(topic)
        sections = [s for s in (naver_text, exa_text) if s]
        if sections:
            facts = "\n\n".join(sections)
        else:
            facts = ""
            if self._search_api_key and self._search_cx:
                facts = self._custom_search(topic)
            if not facts:
                facts = self._google_news_rss_facts(topic)
        citations = naver_citations + exa_citations
        return facts, citations

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
                    citations.append({"name": title[:40], "url": link})
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

    def _exa_facts_and_citations(self, topic: str) -> tuple[str, list[dict[str, str]]]:
        """Exa 검색 응답에서 본문 발췌 텍스트와 실제 결과 URL을 함께 뽑는다.

        응답의 url 필드는 기존에 버려졌다 — SOURCE_TRUST_BLOCK에 걸 실제 인용
        링크로 여기서 함께 반환한다. 호출 상한(_exa_facts_max_calls)은 그대로 적용.
        """
        if not self._exa_api_key or self._exa_facts_calls >= self._exa_facts_max_calls:
            return "", []
        self._exa_facts_calls += 1
        try:
            payload = json.dumps({
                "query": topic,
                "type": "auto",
                "numResults": 3,
                "contents": {"text": {"maxCharacters": 400}},
            }).encode("utf-8")
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
                if result_url.lower().startswith(("http://", "https://")) and len(citations) < 3:
                    citations.append({"name": (title or result_url)[:40], "url": result_url})
                if len(lines) >= 3:
                    break
            if not lines:
                return "", []
            logger.info("LlmContentService: Exa 팩트 %d건 (인용 URL %d건)", len(lines), len(citations))
            return "[웹 문서 발췌 (Exa)]\n" + "\n".join(lines), citations
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
        """Provider 폴백 체인으로 LLM 호출 (cli_news 전용 system_prompt 사용).

        본문 생성은 무료 모델이 흔히 내는 치명 결함(중간 절단·반복 루프·영어 혼입·
        태그 불균형)을 validator로 걸러, 불합격이면 다음 provider(→유료 OpenAI)로
        폴백한다. 정상 출력은 그대로 통과시켜 무료 우선 정책과 비용 0을 유지한다.

        영어 모드: 영어 시스템 프롬프트 + 1,500단어 하한(thin content 방지) 적용.
        """
        if is_english_mode():
            return self.call_with_fallback(
                user_prompt,
                system_prompt=_SYSTEM_PROMPT_EN.format(month_year=_month_year_en()),
                # 1,500단어 영어 본문은 태그 포함 8,000자를 훌쩍 넘는다 — 얇은 응답 조기 컷.
                min_chars=4000,
                validator=_validate_generated_content,
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
            # 영어 모드(2026-07-17): 단어 수·형식 검증 실패는 확률적(같은 모델이
            # 재호출에서 1,600단어를 내기도 함) — 전 provider가 한 번씩 짧게 쓰면
            # 그날 발행이 통째로 스킵되므로 validator 실패도 1회 재시도한다.
            # ko 모드는 기존대로 즉시 다음 provider (비용·시간 특성 유지).
            validator_retry_budget = 1 if is_english_mode() else 0
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


class _ContentValidationError(ValueError):
    """생성 콘텐츠가 잘림·반복·언어·구조 결함을 보여 다음 provider로 폴백해야 함을 뜻한다."""


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
)

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
        word_count = len(re.findall(r"[A-Za-z][A-Za-z'’-]*", text))
        if word_count < 1400:
            raise _ContentValidationError(f"영어 본문 단어 수 부족 ({word_count} < 1400)")
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
