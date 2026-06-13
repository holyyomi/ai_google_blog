from __future__ import annotations

import base64
import json
import urllib.request

from blogspot_automation.services.cover_image_service import CoverImageService, _looks_like_image

# 유효한 최소 PNG 헤더 + 패딩 (크기 검증 통과용)
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20_000


def _service(monkeypatch) -> CoverImageService:
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "gemini-key")
    monkeypatch.setenv("IMGBB_API_KEY", "imgbb-key")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("ENABLE_COVER_IMAGE_AUTOGEN", raising=False)
    return CoverImageService()


def _service_with_cf(monkeypatch) -> CoverImageService:
    svc = _service(monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
    return CoverImageService()


def test_disabled_without_keys(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    monkeypatch.delenv("IMGBB_API_KEY", raising=False)
    assert CoverImageService().enabled() is False


def test_disabled_by_flag(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "k")
    monkeypatch.setenv("IMGBB_API_KEY", "k")
    monkeypatch.setenv("ENABLE_COVER_IMAGE_AUTOGEN", "false")
    assert CoverImageService().enabled() is False


def test_enabled_with_keys(monkeypatch) -> None:
    assert _service(monkeypatch).enabled() is True


def test_ai_image_upload_key_takes_priority(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "gemini-key")
    monkeypatch.setenv("AI_IMAGE_UPLOAD_KEY", "ai-upload-key")
    monkeypatch.setenv("IMGBB_API_KEY", "legacy-imgbb-key")

    svc = CoverImageService()

    assert svc.enabled() is True
    assert svc.imgbb_key == "ai-upload-key"


def test_build_cover_image_url_full_flow(monkeypatch) -> None:
    svc = _service(monkeypatch)
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        calls.append(req.full_url)
        if "generativelanguage" in req.full_url:
            return FakeResponse({
                "candidates": [{
                    "content": {"parts": [
                        {"text": "ok"},
                        {"inlineData": {"mimeType": "image/png",
                                        "data": base64.b64encode(_FAKE_PNG).decode("ascii")}},
                    ]},
                }],
            })
        return FakeResponse({
            "success": True,
            "data": {"url": "https://i.ibb.co/abc123/jangma-cover.png"},
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    url = svc.build_cover_image_url(
        title="비 안 와도 장마철?", topic="장마 정의 개편", slug="jangma-definition-change",
    )
    assert url == "https://i.ibb.co/abc123/jangma-cover.png"
    assert "generativelanguage" in calls[0]
    assert "imgbb" in calls[1]


def test_returns_empty_when_generation_fails(monkeypatch) -> None:
    svc = _service(monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr("blogspot_automation.services.cover_image_service.time.sleep", sleeps.append)

    def fake_urlopen(req, timeout):
        raise RuntimeError("api down")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert svc.build_cover_image_url(title="t", topic="x", slug="s") == ""
    # provider 1개(gemini) × 2회 시도, 첫 실패 후 대기 1회
    assert len(sleeps) == 1


def test_cloudflare_is_first_priority_and_429_skips_to_next_provider(monkeypatch) -> None:
    svc = _service_with_cf(monkeypatch)
    urls: list[str] = []
    monkeypatch.setattr("blogspot_automation.services.cover_image_service.time.sleep", lambda *_: None)

    def fake_urlopen(req, timeout):
        urls.append(req.full_url)
        raise RuntimeError("HTTP Error 429: quota exceeded")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert svc.build_cover_image_url(title="t", topic="x", slug="s") == ""
    # 429 = plan quota 소진 → 같은 provider 재시도 없이 즉시 다음 provider
    assert len(urls) == 2
    assert "cloudflare.com" in urls[0]  # 무료 확정인 Cloudflare가 1순위
    assert "generativelanguage" in urls[1]


def test_cloudflare_generation_success_uploads_to_imgbb(monkeypatch) -> None:
    svc = _service_with_cf(monkeypatch)
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self._p = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self._p).encode("utf-8")

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        if "cloudflare.com" in req.full_url:
            assert "flux-1-schnell" in req.full_url
            return FakeResponse({
                "success": True,
                "result": {"image": base64.b64encode(_FAKE_PNG).decode("ascii")},
            })
        return FakeResponse({
            "success": True,
            "data": {"url": "https://i.ibb.co/xyz789/cover.png"},
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    url = svc.build_cover_image_url(title="장마 정의 개편", topic="장마", slug="jangma-change")
    assert url == "https://i.ibb.co/xyz789/cover.png"
    assert len(calls) == 2  # cloudflare 생성 1회 + imgbb 업로드 1회 (gemini 호출 없음)


def test_returns_empty_when_imgbb_rejects(monkeypatch) -> None:
    svc = _service(monkeypatch)

    class FakeResponse:
        def __init__(self, payload):
            self._p = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self._p).encode("utf-8")

    def fake_urlopen(req, timeout):
        if "generativelanguage" in req.full_url:
            return FakeResponse({
                "candidates": [{"content": {"parts": [
                    {"inlineData": {"data": base64.b64encode(_FAKE_PNG).decode("ascii")}},
                ]}}],
            })
        return FakeResponse({"success": False, "error": {"message": "bad key"}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert svc.build_cover_image_url(title="t", topic="x", slug="s") == ""


def test_prompt_uses_slug_and_blocks_faces(monkeypatch) -> None:
    svc = _service(monkeypatch)
    prompt = svc._build_prompt(title="손흥민 이적설", topic="손흥민 이적설", slug="son-heungmin-transfer")
    assert "son heungmin transfer" in prompt
    assert "no real person likeness" in prompt
    assert "no text" in prompt  # wordless 스타일 지시 포함


def test_looks_like_image_magic_bytes() -> None:
    assert _looks_like_image(_FAKE_PNG) is True
    assert _looks_like_image(b"\xff\xd8\xff" + b"\x00" * 100) is True
    assert _looks_like_image(b"<html>error</html>") is False


def test_prompt_prefers_llm_image_concept(monkeypatch) -> None:
    svc = _service(monkeypatch)
    prompt = svc._build_prompt(
        title="장마 정의 개편",
        topic="장마 정의 개편",
        slug="jangma-definition-change",
        image_concept="rain clouds parting over a Korean weather observatory with dry cracked ground",
    )
    # 본문 LLM의 영어 장면 묘사가 1순위 (flux는 한국어 이해가 약함)
    assert "rain clouds parting over a Korean weather observatory" in prompt
    assert "jangma definition change" not in prompt
    assert "no text" in prompt  # wordless 스타일 지시 포함
