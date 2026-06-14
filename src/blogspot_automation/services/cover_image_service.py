"""CoverImageService — 커버 이미지 자동 생성 + 영구 호스팅.

흐름: 무료 이미지 생성 (1순위 Cloudflare Workers AI flux-1-schnell — 일 10k 뉴런
      무료·카드 불필요, 2순위 Gemini — 무과금 키는 쿼터 0이라 보통 429)
      → imgbb 업로드(영구 직링크, 엑박 방지) → URL 반환.

실패는 전부 비치명 — URL을 못 만들면 빈 문자열을 반환하고 발행은 이미지 없이 진행한다.
환경변수:
  ENABLE_COVER_IMAGE_AUTOGEN (기본 true)
  CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN — Cloudflare Workers AI (무료 1순위)
  GOOGLE_AI_API_KEY  — Gemini 이미지 생성 (2순위)
  AI_IMAGE_UPLOAD_KEY / IMGBB_API_KEY      — imgbb 업로드 (필수)
  COVER_IMAGE_MODEL  — Gemini 모델, 기본 gemini-2.5-flash-image
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_COVER_IMAGE_MODEL = "gemini-2.5-flash-image"
CLOUDFLARE_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_CLOUDFLARE_BASE = "https://api.cloudflare.com/client/v4/accounts"
_IMGBB_ENDPOINT = "https://api.imgbb.com/1/upload"

# 인물 초상권·텍스트 깨짐을 피하는 스타일 고정 지시.
# flux-schnell은 "no text"를 자주 무시하고 깨진 글자를 그린다(실사례: "BALSING").
# 부정 지시만으론 부족 → 글자가 그려질 소재(간판/라벨/문서) 자체를 배제하고
# "wordless/textless"를 긍정 서술로 반복한다.
_STYLE_SUFFIX = (
    "Minimal abstract flat vector illustration, modern soft color palette, "
    "clean simple geometric shapes only, subtle gradient background, 16:9 wide composition, "
    "generous empty margins, nothing important near the bottom edge. "
    "Completely wordless and textless artwork: no text, no letters, no numbers, "
    "no signs, no labels, no captions, no typography, no writing of any kind, "
    "no watermark, no logos. "
    # 글자가 그려지기 쉬운 소재 자체를 배제 (화면/문서/키보드/책/간판 등)
    "Do not draw screens, monitors, phones with UI, documents, papers, books, "
    "keyboards, charts with axis labels, or any object that would contain readable text. "
    "No realistic human faces, no real person likeness."
)


class CoverImageService:
    def __init__(self) -> None:
        self.gemini_key = os.getenv("GOOGLE_AI_API_KEY", "").strip()
        self.imgbb_key = (
            os.getenv("AI_IMAGE_UPLOAD_KEY", "").strip()
            or os.getenv("IMGBB_API_KEY", "").strip()
        )
        self.model = os.getenv("COVER_IMAGE_MODEL", DEFAULT_COVER_IMAGE_MODEL).strip()
        self.cf_account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.cf_api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()

    def enabled(self) -> bool:
        flag = os.getenv("ENABLE_COVER_IMAGE_AUTOGEN", "true").strip().lower()
        if flag in {"false", "0", "no", "off"}:
            return False
        has_generator = bool(self.cf_account_id and self.cf_api_token) or bool(self.gemini_key)
        return has_generator and bool(self.imgbb_key)

    def _generator_candidates(self) -> list[tuple[str, Any]]:
        """무료 확정(Cloudflare)을 1순위로, Gemini는 2순위 (무과금 키는 보통 429)."""
        candidates: list[tuple[str, Any]] = []
        if self.cf_account_id and self.cf_api_token:
            candidates.append(("cloudflare_flux", self._generate_image_cloudflare))
        if self.gemini_key:
            candidates.append((f"gemini:{self.model}", self._generate_image_gemini))
        return candidates

    def build_cover_image_url(
        self, *, title: str, topic: str = "", slug: str = "", image_concept: str = ""
    ) -> str:
        """주제 기반 커버 이미지 생성 → imgbb 영구 URL. 실패 시 ""(비치명)."""
        prompt = self._build_prompt(
            title=title, topic=topic, slug=slug, image_concept=image_concept,
        )
        image_bytes: bytes = b""
        last_error: Exception | None = None
        for name, generate in self._generator_candidates():
            for attempt in range(2):
                try:
                    image_bytes = generate(prompt)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning(
                        "cover image 생성 실패 (provider=%s attempt %d/2): %s",
                        name, attempt + 1, exc,
                    )
                    if "429" in str(exc):
                        # plan quota 소진(분당이 아님)이면 재시도 무의미 → 다음 provider
                        break
                    if attempt == 0:
                        time.sleep(5)
            if image_bytes:
                break
        if not image_bytes:
            logger.warning("cover image 생성 최종 실패 → 이미지 없이 진행: %s", last_error)
            return ""
        try:
            url = self._upload_imgbb(image_bytes, name=slug or "yomi-cover")
        except Exception as exc:  # noqa: BLE001
            logger.warning("imgbb 업로드 실패 → 이미지 없이 진행: %s", exc)
            return ""
        logger.info("cover image 준비 완료: %s", url)
        return url

    # ── 내부 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(*, title: str, topic: str, slug: str, image_concept: str = "") -> str:
        # 1순위: 본문을 쓴 LLM이 만든 영어 장면 묘사(image_concept) — 주제 일치도 최고.
        # flux 등 이미지 모델은 한국어 이해가 약하므로 영어 묘사가 핵심이다.
        concept = " ".join((image_concept or "").split())
        if concept:
            return f"Editorial cover illustration: {concept}. {_STYLE_SUFFIX}"
        # 폴백: 영문 slug + 한국어 토픽 병기
        subject_en = ""
        if slug:
            subject_en = " ".join(t for t in slug.split("-") if t and not t.isdigit())
        subject_kr = " ".join((topic or title or "").split())[:80]
        subject = " / ".join(p for p in (subject_en, subject_kr) if p) or "korean daily news issue"
        return (
            f"Editorial cover illustration for a Korean news blog article. "
            f"Article topic: {subject}. "
            f"Depict the topic's core subject matter symbolically and recognizably "
            f"(objects, scenery, metaphor related to the topic). "
            f"{_STYLE_SUFFIX}"
        )

    def _generate_image_cloudflare(self, prompt: str) -> bytes:
        """Cloudflare Workers AI flux-1-schnell — 무료 일 10k 뉴런 (~230장)."""
        url = f"{_CLOUDFLARE_BASE}/{self.cf_account_id}/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
        req = urllib.request.Request(
            url,
            data=json.dumps({"prompt": prompt, "steps": 8}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.cf_api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise ValueError(f"HTTP {exc.code} (cloudflare_flux): {detail or exc.reason}") from exc
        if not body.get("success"):
            raise ValueError(f"cloudflare ai rejected: {str(body.get('errors'))[:200]}")
        data = (body.get("result") or {}).get("image")
        if not data:
            raise ValueError("cloudflare response contains no image data")
        raw = base64.b64decode(data)
        if not _looks_like_image(raw):
            raise ValueError("cloudflare payload is not a valid image")
        if len(raw) < 15_000:
            raise ValueError(f"cloudflare image too small ({len(raw)} bytes)")
        return raw

    def _generate_image_gemini(self, prompt: str) -> bytes:
        use_model = self.model
        url = f"{_GEMINI_BASE}/models/{use_model}:generateContent?key={self.gemini_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 429/4xx 응답 본문에 정확한 quota 사유가 담겨 있음 — 진단을 위해 노출.
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise ValueError(f"HTTP {exc.code} ({use_model}): {detail or exc.reason}") from exc
        for candidate in body.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data") or {}
                data = inline.get("data")
                if data:
                    raw = base64.b64decode(data)
                    if not _looks_like_image(raw):
                        raise ValueError("generated payload is not a valid image")
                    if len(raw) < 15_000:
                        raise ValueError(f"generated image too small ({len(raw)} bytes)")
                    return raw
        raise ValueError("gemini response contains no inline image data")

    def _upload_imgbb(self, image_bytes: bytes, *, name: str = "") -> str:
        safe_name = re.sub(r"[^a-z0-9-]+", "-", (name or "cover").lower()).strip("-")[:60]
        form = urllib.parse.urlencode({
            "key": self.imgbb_key,
            "image": base64.b64encode(image_bytes).decode("ascii"),
            "name": safe_name or "yomi-cover",
        }).encode("utf-8")
        req = urllib.request.Request(
            _IMGBB_ENDPOINT,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("success"):
            raise ValueError(f"imgbb upload rejected: {str(body)[:200]}")
        data = body.get("data") or {}
        url = str(data.get("url") or data.get("display_url") or "").strip()
        if not url.startswith("http"):
            raise ValueError("imgbb response missing image url")
        return url


def _looks_like_image(raw: bytes) -> bool:
    return (
        raw[:3] == b"\xff\xd8\xff"  # JPEG
        or raw[:8] == b"\x89PNG\r\n\x1a\n"  # PNG
        or raw[:6] in (b"GIF87a", b"GIF89a")  # GIF
        or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")  # WebP
    )
