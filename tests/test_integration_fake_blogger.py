"""Fake Blogger 서버로 발행 파이프라인을 끝까지 통과시키는 통합 테스트.

배경(2026-07-08 구조 감사): 이 프로젝트의 실전 사고 5건 중 3건(PR #29 최종 계약
크래시, 수동 리허설=라이브 발행, 초안 자멸)은 전부 "외부 경계"(Blogger API의
실제 응답 형태, 발행 후 라이브 fetch)에서 났고, 유닛테스트 1000+개는 그 경계를
목킹으로 덮고 있어 전부 통과했다. 이 테스트는 그 공백을 메운다:

- 프로덕션 코드는 전부 실물로 돈다: cli_news.run_news_cycle() → NewsPipeline →
  NewsPublishService → BloggerClient → post_publish_audit까지 실제 코드 경로.
- 가짜인 것은 HTTP transport 딱 3곳: utils.network의 HTTPSConnection(모든
  post_json_with_retry 트래픽), OAuth의 urllib.request.urlopen, 감사의
  post_publish_audit_service.urlopen. 로컬 fake 서버가 **실측된 Blogger 응답
  형태**를 재현한다 — 특히 "초안 insert의 url 필드 = 블로그 홈 URL"(run
  28916401142에서 실측, 초안 자멸 버그의 원인)을 그대로 흉내낸다.
- 그 외 모든 외부 호출(검색/LLM/RSS)은 오프라인처럼 실패해 폴백 경로를 탄다 —
  뉴스가 약한 날의 실제 운영 형태와 같다(FORCE_EVERGREEN_FALLBACK).

이 파일이 지키는 회귀:
1. publish_draft 리허설이 초안을 만들고 스스로 지우지 않는다 (초안 자멸 버그).
2. 라이브 발행이 발행 후 감사(자기 글 fetch)까지 통과한다 (PR #29 유형).
3. PUBLISH_HOLD_PHASE2 env 누락 시 발행이 홀드된다 (PR #23 유형 — env 계약).
4. 라이브 감사 치명 이슈 시에만 글을 삭제한다 (초안은 절대 삭제 금지).
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import urllib.error
import urllib.request
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

HOME_URL = "https://holyyomiai.blogspot.com/"


def _run_news_cycle():
    """cli_news를 지연 import해서 실행.

    모듈 최상단에서 import하면 pytest 수집 시점에 load_dotenv가 실행돼 로컬
    .env의 발행 스위치(PUBLISH_HOLD_PHASE2 등)가 프로세스 전체 os.environ을
    오염시키고, 같은 세션의 다른 테스트들이 깨진다(실측: test_ai_pipeline_quality
    6건 오염 실패). 지연 import + _isolated_environ 스냅샷 복원이 그 격리막이다.
    """
    from blogspot_automation.cli_news import run_news_cycle

    return run_news_cycle()


def _canned_llm_article(title: str, topic: str) -> str:
    """실제 LLM(서술형 프롬프트)의 정상 출력 형태를 흉내낸 결정적 기사.

    fake 서버의 /chat/completions가 요청 프롬프트에서 제목·주제를 뽑아 이 템플릿을
    채운다 — 어떤 주제가 로테이션돼도 제목·주제 문자열이 본문에 그대로 들어가
    title↔body 정합 게이트를 구조적으로 만족한다. 내용은 팩트-세이프티 규칙
    (단정 금지·금지 문구·개인 경험담 금지)을 지키는 안전 서술로 구성.
    """
    return f"""
<p>{title} — 이 질문을 검색해 들어온 분들이 가장 먼저 확인해야 할 것부터 정리한다.
{topic} 문제는 도구를 몇 개 쓰느냐가 아니라, 어떤 작업을 어떤 순서로 맡기느냐에서 갈린다.
결론부터 말하면, 반복 빈도가 높고 검토 기준이 명확한 작업부터 맡기고, 판단이 필요한 작업은
사람이 마지막에 확인하는 구조를 만드는 것이 가장 안정적이다.</p>
<h2>{topic}, 무엇부터 시작해야 하나요?</h2>
<p>처음에는 범위를 좁히는 것이 중요하다. {topic} 관점에서 보면, 매일 같은 형식으로 반복되는
작업 — 예를 들어 자료 정리, 형식 변환, 초안 작성 — 이 첫 후보가 된다. 이런 작업은 결과를
검토하는 기준이 명확해서, 사람 확인을 마지막에 한 번 두는 것만으로 품질을 유지할 수 있다.
반대로 숫자 판단이나 대외 커뮤니케이션처럼 맥락이 중요한 작업은 도구 출력의 초안 역할까지만
맡기는 편이 안전하다. 계정과 요금제에 따라 제공 기능이 다를 수 있으므로, 실제 적용 전에
공식 도움말에서 최신 조건을 확인하는 것이 좋다.</p>
<h2>어떤 기준으로 작업을 나눠야 하나요?</h2>
<p>기준은 세 가지다. 첫째, 반복 빈도 — 주 3회 이상 반복되면 자동화 가치가 있다. 둘째,
오류 비용 — 틀렸을 때 되돌리기 쉬운 작업부터 시작한다. 셋째, 검토 난이도 — 결과를 30초
안에 확인할 수 있는 작업이 우선이다. 아래 표에 이 기준을 적용한 구분을 정리했다.</p>
<table><thead><tr><th>구분 기준</th><th>먼저 맡길 작업</th><th>사람이 확인할 작업</th></tr></thead>
<tbody><tr><td>반복 빈도</td><td>매일 반복되는 정리·변환</td><td>비정기 판단 업무</td></tr>
<tr><td>오류 비용</td><td>내부 초안·요약</td><td>대외 발송·확정 문서</td></tr>
<tr><td>검토 난이도</td><td>형식이 정해진 결과물</td><td>맥락 판단이 필요한 결과물</td></tr></tbody></table>
<p>표의 기준을 적용할 때 흔한 실수는 처음부터 전 과정을 자동화하려는 것이다. 검토 단계를
생략하면 오류가 누적된 뒤에야 발견되기 때문에, 초기에는 단계마다 사람 확인을 끼워 넣고
안정된 뒤에 확인 주기를 늘리는 순서가 실패 비용을 줄인다. 아는 사람만 아는 팁 하나 —
결과물을 저장하는 폴더를 날짜별로 나눠 두면, 품질이 흔들리기 시작한 시점을 되짚기 쉽다.</p>
<h2>자주 묻는 질문</h2>
<div class="faq-section">
<article class="faq-item"><h3 class="faq-q">{topic}은 무료 도구로도 가능한가요?</h3>
<p class="faq-a">가능한 범위가 있다. 무료 요금제는 사용량 제한이 있어 반복 작업 일부에
적합하고, 제한과 데이터 처리 방침은 서비스 정책에 따라 달라질 수 있어 공식 페이지 확인이 필요하다.</p></article>
<article class="faq-item"><h3 class="faq-q">결과물 검토는 얼마나 자주 해야 하나요?</h3>
<p class="faq-a">초기에는 매 결과물을 확인하고, 오류율이 안정되면 표본 확인으로 줄이는
방식이 일반적이다. 검토 기준을 문서로 남겨두면 확인 시간이 줄어든다.</p></article>
<article class="faq-item"><h3 class="faq-q">어떤 작업은 자동화하면 안 되나요?</h3>
<p class="faq-a">개인정보·회사 기밀이 들어가는 작업, 되돌리기 어려운 확정 처리 작업은
도구 출력의 초안 역할까지만 쓰고 최종 판단은 사람이 하는 것이 안전하다.</p></article>
</div>
<p>정리하면, 무엇을 맡기고 무엇을 직접 확인할지 기준을 먼저 세우는 것이 {topic}의
시작점이다. 요금과 제공 범위처럼 자주 바뀌는 조건은 아래 항목에서 직접 확인하자.</p>
<section id="CONFIRMED_VS_CHECK_NEEDED_BLOCK" class="confirmed-needed-box">
<div class="confirmed-section"><h3>지금까지 확인된 것</h3><ul>
<li>반복 빈도·오류 비용·검토 난이도가 작업 구분의 핵심 기준이라는 점</li>
<li>초기에는 매 결과물 검토가 필요하다는 점</li>
<li>개인정보가 들어가는 작업은 사람 최종 확인이 필요하다는 점</li></ul></div>
<div class="check-needed-section"><h3>직접 확인할 것</h3><ul>
<li>사용 중인 도구의 무료 한도와 요금제 조건 (공식 페이지 기준)</li>
<li>회사 보안 정책상 입력 가능한 자료 범위</li>
<li>계정·지역·버전에 따른 기능 제공 여부</li></ul></div>
</section>
""".strip()


# ─── Fake Blogger 서버 ────────────────────────────────────────────────────────


class FakeBloggerState:
    """Blogger API 상태 + 호출 기록. 응답 형태는 실측 기준."""

    def __init__(self) -> None:
        self.posts: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []  # (method, path)
        self._next_id = 1000
        # 사보타주 노브: 이 post_id의 라이브 페이지를 엉뚱한 제목으로 서빙
        self.serve_wrong_title_for: str | None = None

    def new_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def method_calls(self, method: str, path_part: str = "") -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] == method and path_part in c[1]]

    @staticmethod
    def _extract_description(payload: dict[str, Any]) -> str:
        raw = payload.get("customMetaData") or ""
        try:
            return str(json.loads(raw).get("description") or "")
        except Exception:  # noqa: BLE001
            return ""

    def insert_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        post_id = self.new_id()
        self.posts[post_id] = {
            "id": post_id,
            "title": str(payload.get("title") or ""),
            "content": str(payload.get("content") or ""),
            "labels": list(payload.get("labels") or []),
            "search_description": self._extract_description(payload),
            "status": "DRAFT",
            # 실측: 초안 insert의 url은 개별 미리보기 링크가 아니라 블로그 홈 URL.
            # (2026-07-08 run 28916401142 — 초안 자멸 버그의 원인이 된 실제 형태)
            "url": HOME_URL,
            "deleted": False,
        }
        return {"kind": "blogger#post", **self.posts[post_id]}

    def publish_post(self, post_id: str) -> dict[str, Any]:
        post = self.posts[post_id]
        # Blogger처럼 발행 시점의 제목 단어로 영어 permalink를 만든다.
        slug_words = re.findall(r"[a-z0-9]+", post["title"].lower())
        slug = "-".join(slug_words) or f"post-{post_id}"
        post["status"] = "LIVE"
        post["url"] = f"{HOME_URL}2026/07/{slug}.html"
        return {"kind": "blogger#post", **post}

    def patch_post(self, post_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        post = self.posts[post_id]
        for key in ("title", "content", "labels"):
            if key in payload:
                post[key] = payload[key]
        if "customMetaData" in payload:
            post["search_description"] = self._extract_description(payload)
        return {"kind": "blogger#post", **post}

    def delete_post(self, post_id: str) -> None:
        if post_id in self.posts:
            self.posts[post_id]["deleted"] = True

    # ── 라이브 페이지 렌더 (감사 fetch 대상) ──
    def render_page(self, url: str) -> str | None:
        if url.rstrip("/") == HOME_URL.rstrip("/"):
            items = "".join(
                f'<article><h3 class="post-title"><a href="{p["url"]}">{p["title"]}</a></h3></article>'
                for p in self.posts.values()
                if p["status"] == "LIVE" and not p["deleted"]
            )
            return (
                f'<html><head><title>blog home</title><link rel="canonical" href="{HOME_URL}"/></head>'
                f"<body>{items}</body></html>"
            )
        for post in self.posts.values():
            if post["url"] == url and post["status"] == "LIVE" and not post["deleted"]:
                title = post["title"]
                if self.serve_wrong_title_for == post["id"]:
                    title = "전혀 다른 글 제목 (사보타주)"
                labels = "".join(f'<a rel="tag" href="#">{lb}</a>' for lb in post["labels"])
                desc = post["search_description"] or title
                return (
                    "<html><head>"
                    f"<title>{title}</title>"
                    f'<link rel="canonical" href="{url}"/>'
                    f'<meta name="description" content="{desc}"/>'
                    f'<meta property="og:description" content="{desc}"/>'
                    "</head><body>"
                    f'<h3 class="post-title">{title}</h3>'
                    f'<div class="post-body"><article class="yomi-clean-post">{post["content"]}</article></div>'
                    f"<div>{labels}</div>"
                    "</body></html>"
                )
        return None


def _make_handler(state: FakeBloggerState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # 테스트 출력 소음 제거
            pass

        def _read_payload(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:  # noqa: BLE001
                return {}

        def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self, method: str) -> None:
            state.calls.append((method, self.path))
            path = self.path.split("?", 1)[0].rstrip("/")
            payload = self._read_payload() if method in {"POST", "PATCH"} else {}

            if method == "POST" and path.endswith("/token"):
                self._send_json({"access_token": "fake-token"})
                return
            if method == "POST" and path.endswith("/chat/completions"):
                # OpenAI 호환 fake LLM (HTTPSConnection 리다이렉트로 도착하는 경우)
                self._send_json(_completion_for_payload(payload))
                return
            publish_match = re.search(r"/posts/(\d+)/publish$", path)
            if method == "POST" and publish_match:
                self._send_json(state.publish_post(publish_match.group(1)))
                return
            if method == "POST" and path.endswith("/posts"):
                self._send_json(state.insert_post(payload))
                return
            post_match = re.search(r"/posts/(\d+)$", path)
            if method == "PATCH" and post_match:
                self._send_json(state.patch_post(post_match.group(1), payload))
                return
            if method == "DELETE" and post_match:
                state.delete_post(post_match.group(1))
                self._send_json({})
                return
            # 그 외(LLM/검색 등 외부 API가 리다이렉트로 도착) → 404 즉시 실패
            # (5xx가 아니라서 post_json_with_retry가 재시도하지 않아 빠르다)
            self._send_json({"error": "not found in fake blogger"}, status=404)

        def do_POST(self) -> None:
            self._route("POST")

        def do_PATCH(self) -> None:
            self._route("PATCH")

        def do_DELETE(self) -> None:
            self._route("DELETE")

        def do_GET(self) -> None:
            self._route("GET")

    return Handler


class _FakeHTTPResponse(io.BytesIO):
    """urlopen 반환값 흉내 — with 문과 .read()만 지원하면 충분."""

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _completion_for_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """OpenAI 호환 fake LLM 응답 — 프롬프트에서 제목/주제를 뽑아 결정적 기사 생성."""
    user_text = ""
    for message in payload.get("messages", []):
        if message.get("role") == "user":
            user_text = str(message.get("content") or "")
    title_match = re.search(r"제목:\s*(.+)", user_text)
    topic_match = re.search(r"주제:\s*(.+)", user_text)
    article = _canned_llm_article(
        (title_match.group(1).strip() if title_match else "제목 없음"),
        (topic_match.group(1).strip() if topic_match else "주제 없음"),
    )
    return {"choices": [{"message": {"role": "assistant", "content": article}}]}


def _make_fake_urlopen(state: FakeBloggerState):
    def fake_urlopen(request: Any, timeout: float | None = None, **kwargs: Any):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/token" in url or "oauth2" in url:
            return _FakeHTTPResponse(json.dumps({"access_token": "fake-token"}).encode("utf-8"))
        if "chat/completions" in url:
            # LLM provider는 urlopen 경유(post_json_with_retry 아님) — 여기서 응답
            raw = getattr(request, "data", None) or b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:  # noqa: BLE001
                payload = {}
            return _FakeHTTPResponse(
                json.dumps(_completion_for_payload(payload)).encode("utf-8")
            )
        if url.startswith(HOME_URL):
            state.calls.append(("GET", url))
            page = state.render_page(url)
            if page is not None:
                return _FakeHTTPResponse(page.encode("utf-8"))
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        # 그 외 외부 세계(RSS/검색/트렌드) → 오프라인처럼 실패 → 폴백 경로
        raise urllib.error.URLError("offline (fake blogger integration test)")

    return fake_urlopen


# ─── 하네스 픽스처 ───────────────────────────────────────────────────────────


@pytest.fixture()
def _isolated_environ():
    """테스트 중 발생하는 모든 os.environ 변경(cli의 load_dotenv 포함)을 원복.

    monkeypatch는 자신이 바꾼 키만 복원한다 — 테스트 도중 load_dotenv가
    setdefault로 심는 키는 추적 밖이라 이 전체 스냅샷이 반드시 필요하다.
    """
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


@pytest.fixture()
def fake_blogger(_isolated_environ, monkeypatch: pytest.MonkeyPatch, tmp_path) -> FakeBloggerState:
    state = FakeBloggerState()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    class RedirectedHTTPSConnection(HTTPConnection):
        """모든 https post_json_with_retry 트래픽을 fake 서버로 보낸다(평문 HTTP)."""

        def __init__(self, host: str, port_: int | None = None, timeout: float = 10, **kw: Any) -> None:
            super().__init__("127.0.0.1", port, timeout=timeout)

    monkeypatch.setattr(
        "blogspot_automation.utils.network.HTTPSConnection", RedirectedHTTPSConnection
    )
    fake_urlopen = _make_fake_urlopen(state)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    # post_publish_audit_service는 urlopen을 모듈 최상단에서 바인딩 → 별도 패치 필수
    monkeypatch.setattr(
        "blogspot_automation.services.post_publish_audit_service.urlopen", fake_urlopen
    )

    # 작업 디렉토리 격리: 상대경로 원장(data/), dedup 상태(state/), runs/ 전부 tmp로
    (tmp_path / "data").mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.chdir(tmp_path)

    yield state

    server.shutdown()
    server.server_close()


@pytest.fixture()
def _env_publish_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """ai_blog.yml schedule 발행과 같은 env 형태 + 외부 의존 전부 차단."""
    env = {
        "DRY_RUN": "false",
        "AUTO_PUBLISH": "true",
        "NEWS_PUBLISH_MODE": "publish",
        "PUBLISH_HOLD_PHASE2": "false",
        # ai_blog.yml의 모드 키 — 누락 시 파이프라인이 "뉴스 블로그 모드"로 돌아
        # AI 주제가 ai_topic_leaked_to_news_blog 게이트에 막힌다. (처음 이 키들을
        # 빠뜨렸을 때 로컬 .env가 우연히 채워줘 첫 테스트만 통과하는 오염 실패가
        # 났다 — env 한 줄 누락이 사일런트 동작 변경이 되는 PR #23 유형의 재현)
        "NEWS_MODE": "news",
        "AI_BLOG_MODE": "true",
        "AI_BLOG_AUTO_PUBLISH": "true",
        "ALLOW_AI_NEWS_TOPICS": "true",
        "NEWS_EXCLUDED_QUERY_GROUPS": "",
        "MIN_TOPIC_SCORE": "75",
        "TITLE_CANDIDATE_COUNT": "10",
        "BLOG_BRAND_NAME": "holyyomi AI",
        "BLOG_AUTHOR_NAME": "holyyomi AI",
        "FORCE_EVERGREEN_FALLBACK": "true",  # 뉴스 수집(네트워크) 대신 결정적 evergreen 풀
        # 주제 선택 시드 고정 — 미설정 시 now+pid 기반 랜덤이라 실행마다 주제가 바뀐다.
        "NEWS_TOPIC_SELECTION_SEED": "fake-blogger-integration",
        # evergreen 풀은 날짜로 로테이션돼 세금/정책 주제가 먼저 뽑히는 날이 있다.
        # canned 기사는 범용(AI/업무)이라 세금 특화 게이트에 막힐 수 있는데, 그 경우
        # 재시도가 막힌 주제를 제외하고 다음 주제로 넘어간다(실제 운영과 동일 동작).
        "NEWS_MAX_PUBLISH_ATTEMPTS": "8",
        "RUNS_DIR": str(tmp_path / "runs"),
        "BLOGGER_CLIENT_ID": "fake-client",
        "BLOGGER_CLIENT_SECRET": "fake-secret",
        "BLOGGER_REFRESH_TOKEN": "fake-refresh",
        "BLOGGER_BLOG_ID": "1234567890",
        "BLOGSPOT_HOME_URL": HOME_URL,
        "AI_DEFAULT_COVER_IMAGE_URL": f"{HOME_URL}assets/cover.png",
        "REQUIRE_NEWS_COVER_IMAGE": "false",
        "DISABLE_IMAGE_GENERATION": "true",
        "DISABLE_IMAGE_UPLOAD": "true",
        "ENABLE_COVER_IMAGE_AUTOGEN": "false",
        "ENABLE_GOOGLE_CUSTOM_SEARCH": "false",
        "ENABLE_NAVER_SEARCH": "false",
        "ENABLE_NAVER_DATALAB": "false",
        "ENABLE_TAVILY_SEARCH": "false",
        "ENABLE_EXA_SEARCH": "false",
        "ENABLE_FIRECRAWL_SEARCH": "false",
        # fake LLM(정상 운영일 재현): 키가 있어야 폴백 체인이 provider를 시도하고,
        # HTTPSConnection 리다이렉트로 fake 서버의 /chat/completions에 도착한다.
        "ENABLE_AI_LLM_ENRICH": "true",
        "OPENROUTER_API_KEY": "fake-llm-key",
        "DEDUP_DAYS": "7",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # 로컬 .env(cli import 시 load_dotenv)에서 흘러든 실키 제거 — 결정성 보장
    for key in (
        "OPENAI_API_KEY", "GOOGLE_SEARCH_API_KEY",
        "GOOGLE_SEARCH_CX", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",
        "TAVILY_API_KEY", "EXA_API_KEY", "FIRECRAWL_API_KEY",
        "NAVER_INDEXNOW_KEY", "GITHUB_EVENT_NAME", "NEWS_MANUAL_DEDUP_BYPASS",
        "NEWS_PUBLISH_AS_DRAFT", "AI_FORCE_TOPIC", "AI_COVER_IMAGE_URL",
        "IMGBB_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def _load_history(tmp_path) -> list[dict[str, Any]]:
    path = tmp_path / "data" / "publish_history.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ─── 시나리오 ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_publish_draft_rehearsal_end_to_end(fake_blogger, _env_publish_mode, monkeypatch, tmp_path):
    """publish_draft 리허설: 초안이 만들어지고 절대 스스로 지워지지 않는다."""
    monkeypatch.setenv("NEWS_PUBLISH_AS_DRAFT", "true")

    result = _run_news_cycle()

    assert result.get("status") == "draft_saved_for_review", result.get("status")
    assert result.get("publish_succeeded") is False  # 초안은 발행 성공이 아니다(정직)
    # 초안이 생성됐고, 살아있고, 라이브 전환(/publish)이 없었다
    drafts = [p for p in fake_blogger.posts.values() if not p["deleted"]]
    assert len(drafts) == 1 and drafts[0]["status"] == "DRAFT"
    assert not fake_blogger.method_calls("POST", "/publish")
    assert not fake_blogger.method_calls("DELETE")
    # 사람이 열어볼 링크는 (신뢰 불가한 홈 URL이 아니라) 대시보드 편집 링크
    assert "blogger.com/blog/post/edit" in str(result.get("blogger_url"))
    # 이력에는 미발행으로 기록 → 이후 dedup이 실발행으로 오인하지 않는다
    records = [r for r in _load_history(tmp_path) if r.get("status") == "draft_saved_for_review"]
    assert records and records[-1].get("published") is False


@pytest.mark.integration
def test_publish_live_end_to_end_passes_own_audit(fake_blogger, _env_publish_mode, tmp_path):
    """라이브 발행: 우리가 보낸 HTML이 우리 자신의 발행 후 감사를 통과해야 한다.

    PR #29(파이프라인 단계 수정을 발행 서비스 재렌더가 무효화 → 실발행에서만
    크래시), PR #24(라이브 결함) 유형을 로컬에서 잡는 핵심 시나리오.
    """
    result = _run_news_cycle()

    assert result.get("status") == "published", (
        f"status={result.get('status')} hold={result.get('publish_hold_reason')} "
        f"blocking={result.get('blocking_issues')}"
    )
    live = [p for p in fake_blogger.posts.values() if p["status"] == "LIVE" and not p["deleted"]]
    assert len(live) == 1
    assert not fake_blogger.method_calls("DELETE")
    # 발행 후 감사가 실제로 라이브 페이지를 fetch했다
    assert any(url == live[0]["url"] for _m, url in fake_blogger.method_calls("GET"))
    # 원장에 발행 성공 기록 → 엔티티 쿨다운/dedup의 근거가 된다
    records = [r for r in _load_history(tmp_path) if r.get("status") == "published"]
    assert records and records[-1].get("published") is True
    assert records[-1].get("url") == live[0]["url"]


@pytest.mark.integration
def test_missing_publish_hold_env_blocks_publish(fake_blogger, _env_publish_mode, monkeypatch):
    """PR #23 회귀: PUBLISH_HOLD_PHASE2 누락 → 기본값 true → 발행 홀드.

    (2026-07-03~06 5일 미발행 사건의 결정타 — env 한 줄 누락이 사일런트하게
    모든 발행을 막았다. 이 테스트가 그 동작을 명시적 계약으로 고정한다.)
    """
    monkeypatch.delenv("PUBLISH_HOLD_PHASE2", raising=False)
    # 재시도를 끄고 단일 시도로 고정 — 홀드가 재시도로 가려지지 않게
    monkeypatch.setenv("NEWS_MAX_PUBLISH_ATTEMPTS", "1")

    result = _run_news_cycle()

    assert result.get("status") == "held_for_review"
    assert not fake_blogger.method_calls("POST", "/posts")  # Blogger 근처에도 못 간다


@pytest.mark.integration
def test_live_audit_fatal_deletes_live_post_only(fake_blogger, _env_publish_mode, monkeypatch):
    """라이브 감사 치명 이슈(제목 불일치) → 그 라이브 글만 삭제. 초안 규칙과 대비."""
    # 발행되는 순간 그 글의 라이브 페이지를 엉뚱한 제목으로 서빙하게 만든다
    original_publish = fake_blogger.publish_post

    def sabotaged_publish(post_id: str) -> dict[str, Any]:
        fake_blogger.serve_wrong_title_for = post_id
        return original_publish(post_id)

    monkeypatch.setattr(fake_blogger, "publish_post", sabotaged_publish)

    result = _run_news_cycle()

    # 치명 감사 실패 → 삭제 후 차단 상태(재시도 소진 시 최종 상태는 구현에 따라
    # blocked_by_post_publish_audit 또는 재시도 요약) — 발행 성공만 아니면 된다
    assert result.get("publish_succeeded") is not True
    assert fake_blogger.method_calls("DELETE"), "치명 감사 실패면 라이브 글을 삭제해야 한다"
    live_alive = [
        p for p in fake_blogger.posts.values() if p["status"] == "LIVE" and not p["deleted"]
    ]
    assert not live_alive, "사보타주된 라이브 글이 살아남으면 안 된다"
