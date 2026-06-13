"""LLM 기반 블로그 콘텐츠 생성 서비스.

Fallback chain:
  1. Google Gemini API free-tier first (GOOGLE_AI_API_KEY, GEMINI_MODEL)
  2. Official OpenAI API fallback (OPENAI_API_KEY, OPENAI_MODEL)
"""
from __future__ import annotations

import json
import logging
import os
import re
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
_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "gemini_free",
        "provider_type": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GOOGLE_AI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "model": "gemini-2.5-flash",
        "free": True,
        "max_tokens": 16384,
        "extra_headers": {},
    },
    {
        # 2순위: flash 실패 시 같은 Gemini 무료 키로 flash-lite 재시도.
        "name": "gemini_flash_lite",
        "provider_type": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GOOGLE_AI_API_KEY",
        "model_env": "GEMINI_FALLBACK_MODEL",
        "model": "gemini-2.5-flash-lite",
        "free": True,
        "max_tokens": 16384,
        "extra_headers": {},
    },
    {
        "name": "openai_api_fallback",
        "provider_type": "openai_compatible",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        "model": None,
        "free": False,
        "max_tokens": 12000,
        "extra_headers": {},
    },
]

_SYSTEM_PROMPT = """당신은 한국 AI 업무 자동화·AI 도구 활용 블로그 전문 편집자입니다.

[독자] 30~50대 직장인, 블로거, 1인 사업자, AI 자동화 입문자
[목표] AI 뉴스와 도구 변화를 업무 시간, 비용, 성과, 보안 리스크 기준으로 번역하기
[수익] 독자가 오래 읽을 수 있는 실전 표·체크리스트·프롬프트 제공

[글쓰기 원칙]
1. 첫 150자 안에 이 AI 기능을 지금 써도 되는지 결론부터 말한다
2. 도구명·모델명·요금·무료 제한·출시일은 확인된 근거가 있을 때만 구체적으로 쓴다
3. 바로 복사해 쓸 프롬프트, 비교표, 체크리스트, 워크플로 중 최소 2개 이상을 넣는다
4. 회사 기밀, 개인정보, 저작권, 환각 리스크를 반드시 안내한다

[팩트 규칙 — 반드시 준수]
- 확실히 아는 사실만 쓴다. 불확실한 수치·날짜는 아예 쓰지 않는다
- 가격·출시일·성능·무료 제한은 공식 문서나 제공된 검색 결과가 없으면 단정하지 않는다
- 제공된 [검색 결과]에 근거가 있는 내용만 구체적 수치로 표기
- 제공된 검색 결과와 내 학습 지식이 충돌하면 검색 결과를 우선한다
- 직접 사용하지 않은 도구는 1인칭 체험처럼 쓰지 않는다

[섹션 제목 규칙 — 반드시 준수]
- <h2> 제목은 독자가 실제로 검색할 법한 자연스러운 질문·문장으로 쓴다
- "이슈 정의", "핵심 내용", "단계별 방법" 같은 템플릿 단어를 그대로 쓰면 실패다
- 좋은 예: "ChatGPT 새 기능, 회사 업무에 바로 써도 될까?", "무료 플랜으로 충분한 작업은 어디까지일까?"
- 나쁜 예: "이슈 정의", "핵심 내용", "AI 소개"

[금지사항]
- "안녕하세요", "오늘은 ~에 대해 알아보겠습니다"로 시작 금지
- 일반론적·추상적 설명만 늘어놓기 금지
- 근거 없는 수치 창작 금지
- AI로 월수익을 보장하거나 가짜 사용 후기를 만들기 금지
- 회사 기밀이나 개인정보 입력을 권장하는 문장 금지
- Markdown 형식 금지 (HTML 태그만 사용)
- HTML entity 코드(&#숫자; 형태) 절대 사용 금지 — 이모지/아이콘은 유니코드 문자(✅ ✓ →)를 직접 쓰거나 번호 리스트로 처리"""

_USER_PROMPT_TMPL = """[블로그 글 작성]

제목: {title}
주제: {topic}
작성일: {today}
카테고리: {category}

[검색에서 수집한 실제 정보]
{facts}

[독자가 자주 묻는 질문]
{questions}

{reader_interest_prompt}

{issue_profile_prompt}

---

아래 HTML 클래스를 활용하여 풍부하고 시각적인 블로그 본문을 작성하세요.

⚠️ 아래 8개 섹션은 모두 필수입니다. 하나라도 빠지면 실패입니다.

[섹션 1] 핵심 요약 카드 (반드시 포함)
<div class="summary-card"><table>
  <tr><td>대상</td><td>구체적 대상 명시</td></tr>
  <tr><td>핵심 혜택/영향</td><td>금액·날짜·수치 포함</td></tr>
  <tr><td>조건</td><td>해당 조건 구체적으로</td></tr>
  <tr><td>신청/확인 방법</td><td>방법 명시</td></tr>
</table></div>

[섹션 2] 오프닝 — 독자 상황 공감 2~3문장. "안녕하세요" 금지. 구체적 상황 묘사.

[섹션 3] 이슈 설명 — <h2>에 자연스러운 제목 작성 (예: "카카오톡, 정확히 어떤 기기가 종료될까?")
날짜·수치 포함. 검색 결과에 없는 수치는 쓰지 않는다.

[섹션 4] 대상 확인 — <h2>에 "나는 해당될까?" 스타일 제목
<ul class="checklist"> 또는 <div class="compare-table"> 로 즉시 확인 가능하게

[섹션 5] 핵심 상세 — <h2>에 혜택·영향 중심 제목 (예: "보험료 얼마나 줄어드나요?")
날짜·금액·영향 상세. <div class="info-box"> 활용 (warning/success/danger 중 적합한 것)

[섹션 6] 방법/절차 — <h2>에 행동 중심 제목 (예: "지금 당장 전환하는 방법 4단계")
← 반드시 아래 형식 사용
<ol class="steps">
  <li><span class="step-title">1단계명</span><span class="step-desc">구체적 설명</span></li>
  <li><span class="step-title">2단계명</span><span class="step-desc">구체적 설명</span></li>
  <li><span class="step-title">3단계명</span><span class="step-desc">구체적 설명</span></li>
</ol>

[섹션 7] <h2>자주 묻는 질문</h2> ← 3~5개 필수
<div class="faq-section">
  <div class="faq-item">
    <div class="faq-q">질문 텍스트</div>
    <div class="faq-a">답변 텍스트 (2~3문장, 구체적)</div>
  </div>
</div>

[섹션 8] 마감/행동 촉구 ← 반드시 아래 형식
<div class="deadline-box">
  <span class="dl-icon">⏰</span>
  <span class="dl-title">구체적 날짜 또는 "지금 바로"</span>
  <p class="dl-desc">독자 행동 촉구 메시지</p>
</div>

추가 활용 가능:
- <span class="hl-blue">중요</span> / <span class="hl-red">마감</span> / <span class="hl-green">혜택</span>
- <div class="card-grid"><div class="card"><span class="card-icon">🎯</span><div class="card-title">제목</div><div class="card-desc">설명</div></div></div>

출력 규칙:
- div.post-content 태그 없이 내부 HTML만 출력
- 한국어로 작성
- 최소 2,000자 (HTML 태그 제외 순수 텍스트)
- 섹션 제목은 <h2>, 소제목은 <h3>
- 8개 섹션 모두 출력 후 종료
"""


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

    def _gather_facts(self, topic: str) -> str:
        """실제 팩트 수집: Custom Search 우선, 없으면 Gemini 그라운딩으로 폴백."""
        facts = ""
        if self._search_api_key and self._search_cx:
            facts = self._custom_search(topic)
        if not facts:
            facts = self._gemini_grounding_search(topic)
        return facts

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

    def _gemini_grounding_search(self, topic: str) -> str:
        """Gemini + Google Search Grounding으로 실시간 팩트 수집."""
        gemini_key = os.getenv("GOOGLE_AI_API_KEY", "").strip()
        if not gemini_key:
            return ""
        try:
            query = (
                f"다음 주제에 대한 최신 정확한 사실을 한국어로 요약해줘. "
                f"날짜, 금액, 조건, 대상 등 구체적 수치를 포함해서 3~5문장으로.\n주제: {topic}"
            )
            payload = json.dumps({
                "contents": [{"parts": [{"text": query}]}],
                "tools": [{"google_search": {}}],
            }, ensure_ascii=False).encode("utf-8")
            url = (
                f"https://generativelanguage.googleapis.com/v1beta"
                f"/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            )
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            ).strip()
            if text:
                logger.info("LlmContentService: Gemini 그라운딩 팩트 수집 (%d자)", len(text))
                return f"[Gemini 웹검색 요약]\n{text}"
            return ""
        except Exception as exc:
            logger.warning("LlmContentService: Gemini 그라운딩 실패 — %s", exc)
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

        Gemini API free-tier 우선 → OpenAI API fallback 순서로 호출한다.
        ai_content_service 등 다른 모듈이 같은 비용 절감 정책을 따르기 위한 공용 진입점.

        validator: 응답을 추가 검증하는 callable(text). 예외 raise 시 다음 provider로 fallback.
                   응답이 길이만 통과하고 형식(JSON 등)이 깨진 경우 자동 fallback에 사용.
        """
        for provider in _PROVIDERS:
            api_key = os.getenv(provider["api_key_env"], "").strip()
            if not api_key:
                logger.debug("LlmContentService: %s — API키 없음, skip", provider["name"])
                continue
            try:
                result = self._call_provider(provider, api_key, user_prompt, system_prompt)
                if not result or len(result.strip()) <= min_chars:
                    logger.warning(
                        "LlmContentService: %s 응답 너무 짧음 (%d자, min %d)",
                        provider["name"], len(result or ""), min_chars,
                    )
                    continue
                if validator is not None:
                    try:
                        validator(result)
                    except Exception as ve:
                        logger.warning(
                            "LlmContentService: %s validator 실패 — %s. 다음 provider 시도",
                            provider["name"], ve,
                        )
                        continue
                logger.info(
                    "LlmContentService: %s 성공 (%d자)",
                    provider["name"], len(result),
                )
                return result
            except Exception as exc:
                logger.warning("LlmContentService: %s 실패 — %s", provider["name"], exc)

        return None

    def _call_provider(
        self,
        provider: dict[str, Any],
        api_key: str,
        user_prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Configured LLM provider 호출."""
        if provider.get("provider_type") == "gemini":
            return self._call_gemini_provider(provider, api_key, user_prompt, system_prompt)
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

    def _call_gemini_provider(
        self,
        provider: dict[str, Any],
        api_key: str,
        user_prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Gemini native generateContent API 호출."""
        base_url = str(provider["base_url"]).strip().rstrip("/")
        model = self._resolve_provider_model(provider)
        max_tokens = int(provider.get("max_tokens") or 8192)
        payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt if system_prompt is not None else _SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
                # gemini-2.5-flash는 기본 thinking이 출력 토큰 예산을 잠식해 JSON이 잘림
                # → 빈/invalid 응답. thinkingBudget=0으로 thinking 끄고 전량 출력에 쓴다.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/models/{urllib.parse.quote(model, safe='')}:generateContent?key={api_key}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())

        parts = (
            result.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        content = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        if not content:
            raise RuntimeError(f"No Gemini content in response: {result}")
        return _clean_llm_output(content)

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
            custom_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
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
