from __future__ import annotations

import json
import urllib.request

from blogspot_automation.services import llm_content_service as module
from blogspot_automation.services.llm_content_service import LlmContentService


def test_llm_provider_order_free_first_then_paid_fallback() -> None:
    # 운영자 정책: 구독 인증(claude_code_cli) -> 무료(OpenRouter) 2단 -> 유료(OpenAI) 폴백.
    names = [provider["name"] for provider in module._PROVIDERS]

    assert names == [
        "claude_code_cli",
        "openrouter_primary",
        "openrouter_secondary",
        "openai_api_fallback",
    ]
    assert [p["api_key_env"] for p in module._PROVIDERS] == [
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]
    assert module._PROVIDERS[1]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert module._PROVIDERS[2]["model"] == "openai/gpt-oss-120b:free"


def test_llm_provider_chain_excludes_gemini_for_main_generation() -> None:
    assert all(provider["api_key_env"] != "GOOGLE_AI_API_KEY" for provider in module._PROVIDERS)
    assert all("gemini" not in provider["name"] for provider in module._PROVIDERS)


def test_custom_search_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_GOOGLE_CUSTOM_SEARCH", raising=False)
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx")

    svc = LlmContentService()

    assert svc._enable_custom_search is False
    assert svc._search_api_key == ""
    assert svc._search_cx == ""


def test_custom_search_can_be_enabled_for_fact_gathering(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_GOOGLE_CUSTOM_SEARCH", "true")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx")

    svc = LlmContentService()

    assert svc._enable_custom_search is True
    assert svc._search_api_key == "search-key"
    assert svc._search_cx == "cx"


def test_google_news_rss_facts_parses_headlines(monkeypatch) -> None:
    # Gemini 그라운딩 제거 후 키 없는 팩트 폴백 — RSS 헤드라인 파싱 검증
    rss = (
        '<?xml version="1.0"?><rss><channel>'
        '<item><title>네이버, 사내 문서에 AI 도입 확대</title>'
        '<pubDate>Thu, 03 Jul 2026 01:00:00 GMT</pubDate>'
        '<source url="https://example.com">예시뉴스</source></item>'
        '<item><title>카카오 AI 요약 기능 출시</title>'
        '<pubDate>Thu, 03 Jul 2026 02:00:00 GMT</pubDate>'
        '<source url="https://example.com">다른뉴스</source></item>'
        '</channel></rss>'
    ).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return rss

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        assert "news.google.com/rss/search" in req.full_url
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    facts = LlmContentService()._google_news_rss_facts("네이버 AI")

    assert "최근 관련 뉴스 헤드라인" in facts
    assert "네이버, 사내 문서에 AI 도입 확대" in facts
    assert "카카오 AI 요약 기능 출시" in facts


def test_naver_news_facts_parses_snippets(monkeypatch) -> None:
    # 2026-07-10 팩트 소스 재편: Custom Search 폐쇄로 Naver 뉴스 스니펫이 1차 소스.
    body = json.dumps({
        "items": [
            {"title": "네이버 <b>AI탭</b> 출시", "description": "스마트렌즈 &amp; AI 브리핑 연동", "pubDate": "Sun, 05 Jul 2026 08:00:00 +0900"},
            {"title": "AI탭 기술 공개", "description": "실행형 에이전트로 진화", "pubDate": "Sun, 05 Jul 2026 09:00:00 +0900"},
        ]
    }).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return body

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        assert "openapi.naver.com/v1/search/news.json" in req.full_url
        return FakeResponse()

    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "csec")
    monkeypatch.delenv("ENABLE_NAVER_SEARCH", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    facts = LlmContentService()._naver_news_facts("네이버 AI탭")

    assert "네이버 뉴스 검색 결과" in facts
    # <b> 태그·HTML 엔티티 제거 확인
    assert "네이버 AI탭 출시" in facts
    assert "<b>" not in facts
    assert "&amp;" not in facts
    assert "스마트렌즈 & AI 브리핑 연동" in facts


def test_naver_news_facts_and_citations_extracts_real_urls(monkeypatch) -> None:
    # 2026-07-16 회귀: Naver 응답의 originallink/link는 기존에 텍스트 추출 후 버려졌다
    # — SOURCE_TRUST_BLOCK에 걸 실제 인용 링크가 전혀 없었던 원인. 이제 텍스트와
    # 함께 실제 기사 URL도 반환해야 한다.
    body = json.dumps({
        "items": [
            {
                "title": "네이버 <b>AI탭</b> 출시",
                "description": "스마트렌즈 &amp; AI 브리핑 연동",
                "pubDate": "Sun, 05 Jul 2026 08:00:00 +0900",
                "originallink": "https://press.example.com/naver-ai-tab",
                "link": "https://news.naver.com/mnews/article/000/000",
            },
            {
                "title": "AI탭 기술 공개",
                "description": "실행형 에이전트로 진화",
                "pubDate": "Sun, 05 Jul 2026 09:00:00 +0900",
                "originallink": "",
                "link": "https://news.naver.com/mnews/article/000/001",
            },
        ]
    }).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return body

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        return FakeResponse()

    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "csec")
    monkeypatch.delenv("ENABLE_NAVER_SEARCH", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    text, citations = LlmContentService()._naver_news_facts_and_citations("네이버 AI탭")

    assert "네이버 뉴스 검색 결과" in text
    assert len(citations) == 2
    # originallink가 있으면 그것을(언론사 원문), 없으면 link(네이버 미러)를 사용
    assert citations[0]["url"] == "https://press.example.com/naver-ai-tab"
    assert citations[1]["url"] == "https://news.naver.com/mnews/article/000/001"
    assert all(c["name"] for c in citations)


def test_exa_facts_and_citations_extracts_real_urls(monkeypatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "ekey")
    monkeypatch.delenv("ENABLE_EXA_SEARCH", raising=False)
    body = json.dumps({
        "results": [
            {"title": "Grok Imagine pricing update", "text": "New free tier limits announced.", "publishedDate": "2026-07-10", "url": "https://example.com/grok-pricing"},
        ]
    }).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return body

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    text, citations = LlmContentService()._exa_facts_and_citations("Grok Imagine pricing")

    assert "웹 문서 발췌" in text
    assert citations == [{"name": "Grok Imagine pricing update", "url": "https://example.com/grok-pricing"}]


def test_gather_facts_with_citations_merges_naver_and_exa_sources(monkeypatch) -> None:
    svc = LlmContentService()
    monkeypatch.setattr(
        svc,
        "_naver_news_facts_and_citations",
        lambda topic: ("[네이버 뉴스 검색 결과]\n- a", [{"name": "a", "url": "https://a.example.com"}]),
    )
    monkeypatch.setattr(
        svc,
        "_exa_facts_and_citations",
        lambda topic: ("[웹 문서 발췌 (Exa)]\n- b", [{"name": "b", "url": "https://b.example.com"}]),
    )

    facts, citations = svc.gather_facts_with_citations("주제")

    assert "네이버 뉴스 검색 결과" in facts
    assert "웹 문서 발췌" in facts
    assert citations == [
        {"name": "a", "url": "https://a.example.com"},
        {"name": "b", "url": "https://b.example.com"},
    ]


def test_gather_facts_merges_naver_and_exa(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_GOOGLE_CUSTOM_SEARCH", raising=False)
    svc = LlmContentService()
    monkeypatch.setattr(svc, "_naver_news_facts", lambda topic: "[네이버 뉴스 검색 결과]\n- a")
    monkeypatch.setattr(svc, "_exa_facts", lambda topic: "[웹 문서 발췌 (Exa)]\n- b")
    monkeypatch.setattr(svc, "_google_news_rss_facts", lambda topic: "RSS-SHOULD-NOT-BE-USED")

    facts = svc._gather_facts("주제")

    assert "네이버 뉴스 검색 결과" in facts
    assert "웹 문서 발췌" in facts
    assert "RSS-SHOULD-NOT-BE-USED" not in facts


def test_gather_facts_falls_back_to_rss_when_all_sources_empty(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_GOOGLE_CUSTOM_SEARCH", raising=False)
    svc = LlmContentService()
    monkeypatch.setattr(svc, "_naver_news_facts", lambda topic: "")
    monkeypatch.setattr(svc, "_exa_facts", lambda topic: "")
    monkeypatch.setattr(svc, "_google_news_rss_facts", lambda topic: "[최근 관련 뉴스 헤드라인]\n- rss")

    facts = svc._gather_facts("주제")

    assert "rss" in facts


def test_exa_facts_respects_per_run_call_cap(monkeypatch) -> None:
    # Exa는 크레딧 과금 — 재시도 루프에서 무제한 호출 방지 상한 검증
    monkeypatch.setenv("EXA_API_KEY", "ekey")
    monkeypatch.delenv("ENABLE_EXA_SEARCH", raising=False)
    svc = LlmContentService()
    svc._exa_facts_max_calls = 2
    calls = {"n": 0}

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        calls["n"] += 1
        raise RuntimeError("network blocked in test")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    for _ in range(5):
        svc._exa_facts("주제")

    assert calls["n"] == 2


def test_openai_primary_uses_official_url_and_current_default_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>generated html</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._call_provider(
        next(provider for provider in module._PROVIDERS if provider["name"] == "openai_api_fallback"),
        "test-key",
        "Write a post",
        "System prompt",
    )

    assert result == "<p>generated html</p>"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    # 유료 최종 폴백은 긴 본문 생성이 45초를 상시 초과해 read timeout으로 죽었다
    # (2026-07-19~20 발행 0건 원인) — provider별 timeout 300초.
    assert captured["timeout"] == 300
    assert captured["payload"]["model"] == "gpt-5-mini"
    assert captured["payload"]["max_completion_tokens"] == 12000
    assert "max_tokens" not in captured["payload"]
    assert "temperature" not in captured["payload"]


def test_openrouter_primary_uses_openrouter_url_and_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>openrouter generated html</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService()._call_provider(
        next(provider for provider in module._PROVIDERS if provider["name"] == "openrouter_primary"),
        "test-key",
        "Write a post",
        "System prompt",
    )

    assert result == "<p>openrouter generated html</p>"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["timeout"] == 45
    assert captured["payload"]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert captured["payload"]["max_tokens"] == 12000
    assert captured["payload"]["temperature"] == 0.7
    assert captured["headers"]["Http-referer"] == "https://holyyomiai.blogspot.com/"
    assert captured["headers"]["X-title"] == "holyyomi AI"


def test_call_with_fallback_uses_openai_when_both_free_models_fail(monkeypatch) -> None:
    calls: list[str] = []

    class FakeOpenAIResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>" + ("openai fallback " * 30) + "</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        del timeout
        calls.append(req.full_url)
        if "openrouter.ai" in req.full_url:
            raise RuntimeError("free model rate limited")
        return FakeOpenAIResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)

    result = LlmContentService().call_with_fallback("Write a post", "System prompt", min_chars=20)

    assert result and "openai fallback" in result
    # 무료는 혼잡 대비 provider당 2회씩 시도: 무료1×2 → 무료2×2 → 유료 = 5회
    assert calls == [
        "https://openrouter.ai/api/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
        "https://api.openai.com/v1/chat/completions",
    ]


_VALID_CONTENT = (
    "<p>구글 제미나이로 반복 작업을 줄이는 방법을 정리한다. 결론부터 말하면 검토 기준이 명확한 작업부터 맡기는 것이 가장 안정적이다.</p>"
    "<h2>무엇부터 시작해야 하나요?</h2><p>처음에는 범위를 좁히는 것이 중요하다. 매일 반복되는 정리 작업이 첫 후보가 된다.</p>"
    '<div class="quick-decision-table"><table><thead><tr><th>기준</th><th>작업</th></tr></thead>'
    "<tbody><tr><td>반복 빈도</td><td>정리·변환</td></tr></tbody></table></div>"
    '<div class="faq-section"><article class="faq-item"><h3 class="faq-q">무료로도 되나요?</h3>'
    '<p class="faq-a">가능한 범위가 있으나 요금제 조건은 공식 페이지 확인이 필요하다.</p></article></div>'
    '<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">'
    '<div class="confirmed-section"><h3>확인된 것</h3><ul><li>검토 기준이 핵심이라는 점</li></ul></div>'
    '<div class="check-needed-section"><h3>확인할 것</h3><ul><li>사용 도구의 요금제 조건</li></ul></div></section>'
)


def test_validate_generated_content_accepts_clean_article() -> None:
    # 정상 출력은 통과해야 무료 우선 정책(비용 0)이 유지된다.
    module._validate_generated_content(_VALID_CONTENT)  # no raise


def test_validate_generated_content_rejects_common_free_model_defects() -> None:
    import pytest

    # 1) 빈 응답
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content("")
    # 2) 중간 절단 — 닫는 태그로 끝나지 않음 (2026-07-08 라이브 사고 유형)
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content("<p>중간에 잘린 문장인데 태그가 안 닫히고 여기서 제미나이 3")
    # 3) 구조 태그 불균형 — 조립기가 못 살려 스크램블되는 유형
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content("<div><p>닫히지 않은 div가 있는 본문이다.</p>")
    # 4) 영어 설명 문장 혼입 (어제 영어 도입부 유형)
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content(
            "<p>Developer communities reported multiple production rollbacks after adoption last year.</p>"
        )
    # 5) 문장 반복 — 반복 루프 (도입부 문장이 뒤에서 재등장)
    dup = "제미나이로 반복 작업을 줄이는 방법을 처음부터 끝까지 정리한다."
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content(f"<p>{dup}</p><h2>소제목</h2><p>{dup}</p>")
    # 6) FAQ 답 미완성/빈 답
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content(
            '<div class="faq-section"><article class="faq-item">'
            '<h3 class="faq-q">질문?</h3><p class="faq-a"></p></article></div>'
        )
    # 7) AI 상투 문구 (2026-07-16) — 프롬프트 금지를 무시한 저품질 생성 신호
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content(
            "<p>이 기능은 업무 자동화의 게임 체인저가 될 것으로 보인다.</p>"
        )
    with pytest.raises(module._ContentValidationError):
        module._validate_generated_content(
            "<p>빠르게 변화하는 디지털 시대에 이 도구의 활용법을 정리했다.</p>"
        )


def test_broken_free_output_falls_back_to_paid(monkeypatch) -> None:
    # 무료가 '중간 절단' 응답을 주면 validator가 걸러 유료로 폴백해야 한다.
    calls: list[str] = []
    truncated = "<p>" + ("잘린 본문 " * 40)  # 닫는 태그 없이 끝남 → validator 실패

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self._content = content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": self._content}}]}).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        del timeout
        calls.append(req.full_url)
        if "openrouter.ai" in req.full_url:
            return FakeResponse(truncated)
        return FakeResponse(_VALID_CONTENT)

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)

    result = LlmContentService().call_with_fallback(
        "Write a post",
        system_prompt=None,
        min_chars=200,
        validator=module._validate_generated_content,
    )

    assert result == _VALID_CONTENT
    # 무료 1차·2차가 validator에 걸려(각 1회, 재시도 아님) 유료까지 내려감
    assert calls[-1] == "https://api.openai.com/v1/chat/completions"
    assert any("openrouter.ai" in c for c in calls)


def test_call_with_fallback_stops_at_free_primary_when_it_succeeds(monkeypatch) -> None:
    calls: list[str] = []

    class FakeOpenRouterResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "<p>" + ("free primary " * 30) + "</p>"}}],
            }).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        del timeout
        calls.append(req.full_url)
        return FakeOpenRouterResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = LlmContentService().call_with_fallback("Write a post", "System prompt", min_chars=20)

    assert result and "free primary" in result
    # 무료 1차 성공 → 유료로 내려가지 않음 (비용 0)
    assert calls == ["https://openrouter.ai/api/v1/chat/completions"]


def test_asset_rich_directive_triggers_on_productivity_evergreen_topics() -> None:
    # 2026-07-16: "직장인 생산성/시간 절약"류 evergreen(ai_work_tip)이 무기(계산기·
    # 비교표·체크리스트) 지시 트리거에 안 걸려 밋밋하게 나가던 갭 회귀 테스트
    # (2026-07-11 사용자 피드백 — 게이트는 통과하는데 저장할 정보 밀도 부족).
    directive = module._asset_rich_directive(
        title="무료 ChatGPT로도 업무 시간 줄이는 3가지 패턴",
        topic="직장인이 ChatGPT로 업무 시간을 줄이는 방법",
        category="AI활용",
        raw={},
    )
    assert directive, "생산성/시간 절약 evergreen 주제에 asset-rich 지시가 켜져야 함"


def test_asset_rich_directive_stays_off_for_unrelated_news() -> None:
    directive = module._asset_rich_directive(
        title="오픈AI 이사회 구성 변경 발표",
        topic="오픈AI 지배구조 개편",
        category="AI뉴스",
        raw={},
    )
    assert directive == ""


def test_claude_code_cli_never_uses_bare_mode(monkeypatch) -> None:
    # --bare는 "OAuth and keychain are never read"라 구독 인증이 아예 안 먹는다
    # (2026-07-20 gh CLI --help 실측으로 확인) — 회귀 방지.
    captured: dict[str, object] = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"result": "<p>generated</p>"})
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        return FakeResult()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    provider = next(p for p in module._PROVIDERS if p["name"] == "claude_code_cli")
    result = LlmContentService()._call_claude_code_cli(
        provider, "test-oauth-token", "Write a post", "System prompt"
    )

    assert result == "<p>generated</p>"
    args = captured["args"]
    assert "--bare" not in args
    assert args[0:2] == ["claude", "-p"]
    assert "--tools" in args
    assert args[args.index("--tools") + 1] == ""
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert "--system-prompt" in args
    assert args[args.index("--system-prompt") + 1] == "System prompt"
    assert args[-1] == "Write a post"
    assert captured["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "test-oauth-token"
    assert "ANTHROPIC_API_KEY" not in captured["env"]


def test_claude_code_cli_no_model_flag_when_model_none(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"result": "<p>ok</p>"})
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.delenv("CLAUDE_CODE_CLI_MODEL", raising=False)

    provider = next(p for p in module._PROVIDERS if p["name"] == "claude_code_cli")
    LlmContentService()._call_claude_code_cli(provider, "tok", "prompt", None)

    assert "--model" not in captured["args"]


def test_claude_code_cli_raises_on_nonzero_exit(monkeypatch) -> None:
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "auth expired"

    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: FakeResult())

    provider = next(p for p in module._PROVIDERS if p["name"] == "claude_code_cli")
    try:
        LlmContentService()._call_claude_code_cli(provider, "tok", "prompt", None)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "auth expired" in str(exc)


def test_claude_code_cli_raises_on_empty_result_field(monkeypatch) -> None:
    class FakeResult:
        returncode = 0
        stdout = json.dumps({"result": ""})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: FakeResult())

    provider = next(p for p in module._PROVIDERS if p["name"] == "claude_code_cli")
    try:
        LlmContentService()._call_claude_code_cli(provider, "tok", "prompt", None)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "result" in str(exc)


def test_system_prompt_carries_depth_contract_and_cliche_ban() -> None:
    # 프롬프트 계약 회귀 가드: 깊이 장치(독자 계약·판단 기준·4분할)와 상투 문구
    # 금지가 이후 프롬프트 수정에서 실수로 삭제되지 않게 고정한다.
    assert "독자 계약" in module._SYSTEM_PROMPT
    assert "판단 기준 의무" in module._SYSTEM_PROMPT
    assert "게임 체인저" in module._SYSTEM_PROMPT
    assert "바뀌지 않은 것" in module._USER_PROMPT_TMPL
    assert "본문이 다루지 않은 실제 검색 질문" in module._USER_PROMPT_TMPL
