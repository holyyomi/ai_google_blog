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

_SYSTEM_PROMPT = """당신은 한국 AI 업무 자동화·AI 수익화·콘텐츠 전략 최고 권위의 블로그 전문 편집장입니다.

[블로그 목표 및 핵심 독자]
- 독자: 30~50대 직장인, N잡러, 1인 사업자, 자동화 입문자
- 목적: AI 뉴스와 최신 도구의 변화를 독자의 '시간, 비용, 업무 성과, 수익화 가능성'으로 철저히 번역하여 전달.
- 결과: 독자가 구글 검색(SEO), AI 추천(SGE/AEO/GEO)을 통해 유입되어 오래 체류하고(Dwell time), 광고(AdSense) 클릭 확률이 극대화되는 고가치 실용 콘텐츠.

[글쓰기 및 수익화(AdSense/SEO) 최우선 원칙]
1. 제목 최적화: 제목 앞 10~15자 내에 반드시 한국어 핵심 검색 키워드를 배치하고, 영어 도구명은 뒤로 뺀다. 사용 장면을 포함해 클릭률(CTR)을 극대화하라. (예: 완벽정리, 대박, 충격 등 저품질 어그로 절대 금지)
2. 시선 고정 도입부(Hook): 첫 150자 내에 기계적인 인사말("안녕하세요")을 금지하고, 독자가 깊이 공감할 '실제 겪는 구체적 업무 문제나 장면'으로 시작해 몰입도를 끌어올린다. 이후 바로 명확한 결론(이 도구를 당장 써야 하는가?)을 제시한다.
3. SGE/GEO 알고리즘 타겟팅: AI 검색 엔진이 발췌하기 쉽도록 명확하고 구체적인 수치, 날짜, 가격, 한도 등을 포함한다. 불확실한 수치는 아예 쓰지 않는다.
4. 저장 가치(Save-worthiness) 의무: "읽고 끝"이 아니라 "저장하고 다시 오는" 글만 발행한다. 독자가 복사해서 바로 쓰는 [업무별 실전 프롬프트 5개], [도구/모델 용도별 비교표], [무료·유료 비용 전략], [도입 전 체크리스트]를 본문에 반드시 배치한다. 인터넷에 흔한 일반론(예: "80점 초안으로 써라", "검수하라")만으로 섹션을 채우지 않는다.
5. 리스크 고지 (신뢰도 E-E-A-T 상승): 회사 기밀 유출, 개인정보, 저작권, 환각 리스크를 명시하여 전문성과 객관성을 높인다.
6. 단정 금지: 직접 사용해본 데이터가 없거나 제공된 검색 결과에 없는 수치는 단정하여 쓰지 않는다. (공식 문서를 인용하는 형태 유지)

[HTML 구조화 및 시각적 요소 금지사항]
- 본문 어디에도 해시태그(#단어)를 쓰지 않는다 — 해시태그는 시스템이 하단 전용 영역에 자동 삽입한다.
- '제가/직접 써봤더니'류 개인 경험담, 구체 수익·매출 금액 주장(월 N만원 수익 등) 절대 금지 — 검증 불가 주장으로 발행이 차단된다.
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
아래 HTML 구조를 엄격히 따라 독자의 체류 시간을 극대화하는 블로그 본문을 작성하세요.
총 2,500 ~ 3,500자 (HTML 태그 제외 순수 텍스트) 분량 권장.

⚠️ 모든 섹션은 필수입니다. HTML 클래스를 활용해 모바일 가독성을 극대화하세요.

[섹션 1] 🎯 1분 핵심 요약 카드 (결론 먼저 - BLUF)
<div class="summary-card"><table>
  <tr><td>추천 대상</td><td>(누가 써야 하는지 구체적 직업/상황)</td></tr>
  <tr><td>핵심 변화/이점</td><td>(시간/비용 절약 등 수치화된 데이터 필수)</td></tr>
  <tr><td>무료/비용 한도</td><td>(구체적 조건 명시)</td></tr>
  <tr><td>당장 적용할 곳</td><td>(실무 적용처 1순위)</td></tr>
</table></div>

[섹션 2] 도입부 (공감 Hook)
독자가 겪고 있는 답답한 실무 장면 묘사로 시작 (2~3문장). "안녕하세요" 절대 금지.
독자가 이 글을 끝까지 읽어야 할 이유와 시간 가치를 부여.

[섹션 3] <h2>독자가 자연스럽게 검색할 법한 질문형 제목</h2> (이슈/도구 핵심 파헤치기)
- 도구가 해결해주는 핵심 문제와 작동 방식을 구체적 수치와 함께 설명.

[섹션 4] <h2>어떤 도구를 언제 쓸까? (용도별 비교표)</h2>
이 주제와 관련된 도구/모델(예: ChatGPT, Claude, Gemini, Perplexity 중 관련 있는 것)의 용도별 비교를 <table>로 제공.
컬럼: 도구 | 이 주제에서 최적 용도 | 무료 한도/제한 | 유료 전환 기준.
확실하지 않은 가격·한도는 "공식 요금 페이지 확인"으로 표기 (허위 수치 금지).
표 아래 2~3문장으로 "무료로 버티는 법 vs 유료가 이득인 경우" 비용 전략 제시.

[섹션 5] <h2>실전 적용: 그대로 복사해서 쓰는 업무별 프롬프트</h2>
서로 다른 업무(이메일/보고서/회의록/데이터 정리/기획 등) 프롬프트 5개.
각 프롬프트는 <div class="prompt-card"><p class="prompt-card-label">용도</p><pre class="prompt-code">프롬프트 전문</pre></div> 형식.
역할 지정 + 입력 조건 + 출력 형식 + 예시 값까지 채운 완성형(8줄 내외)으로 — 인터넷에 흔한 한 줄짜리 프롬프트 금지.
이어서 실제 워크플로 1개를 "기존 30분 -> AI 적용 후 10분"처럼 단계·시간과 함께 <ol>로 제시.

[섹션 6] <h2>주의사항: 도입 전 반드시 알아야 할 리스크</h2>
회사 기밀, 저작권, 환각 문제 등 치명적일 수 있는 주의점을 <div class="info-box warning"> 등을 활용해 경고.
+ 회사에서 쓸 때 확인할 보안 체크리스트 4~5개를 <ul class="checklist">로 제공 (기밀·개인정보 입력 금지, 사내 AI 정책, 결과물 검증 등).

[섹션 7] <h2>핵심 Q&A (SGE/AEO 최적화)</h2> (검색엔진 발췌용)
<div class="faq-section">
  <article class="faq-item">
    <h3 class="faq-q">독자의 실제 검색 질문 1</h3>
    <p class="faq-a">150자 이내의 빠르고 명확한 정답 (수치 포함)</p>
  </article>
  <article class="faq-item">
    <h3 class="faq-q">질문 2</h3>
    <p class="faq-a">답변 2</p>
  </article>
  (총 3~4개 구성)
</div>

[섹션 8] 마감/오늘의 행동 촉구 (Action Plan)
<div class="deadline-box">
  <span class="dl-icon">🚀</span>
  <span class="dl-title">오늘 당장 해볼 1가지 행동</span>
  <p class="dl-desc">댓글 구걸 금지. 이 글을 읽고 독자가 즉시 실행할 수 있는 구체적 미션 1개 제안.</p>
</div>
마지막에 1문장: 이 블로그는 매일 아침 최신 AI 이슈를 업무 관점으로 정리한다는 안내 + 이 글의 프롬프트/표는 저장해두고 다시 꺼내 쓰라는 권유.

출력 규칙:
- div.post-content 태그 없이 내부 HTML만 출력
- 섹션 제목은 <h2>, 소제목은 <h3> (자연어 질문형)
- 8개 섹션 순서대로 모두 출력 후 종료"""


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
        )

        # 3. LLM 폴백 체인
        content_html = self._run_fallback_chain(prompt)
        if not content_html:
            logger.warning("LlmContentService: 모든 provider 실패")
            return None

        # 3-1. HTML entity artifact 정제 — LLM이 &#숫자 형태로 이모지를 삽입하는 것을 방지
        content_html = _clean_entity_artifacts(content_html)

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
