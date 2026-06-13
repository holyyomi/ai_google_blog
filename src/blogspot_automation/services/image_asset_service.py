from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
from typing import Protocol
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from blogspot_automation.config import Settings
from blogspot_automation.image_generation.client import OpenAIImageClient
from blogspot_automation.storage import BlogWorkItemRepository, ContentPackageRepository
from blogspot_automation.utils.network import post_json_with_retry


logger = logging.getLogger(__name__)

FALLBACK_BRANDING_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#e0f2fe"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="60" y="60" width="1080" height="510" rx="28" fill="#ffffff" stroke="#cbd5e1" stroke-width="4"/>
  <text x="100" y="170" fill="#0f172a" font-size="34" font-family="Segoe UI, Arial, sans-serif" font-weight="700">Daily Insight &amp; Tips</text>
  <text x="100" y="240" fill="#0f172a" font-size="54" font-family="Segoe UI, Arial, sans-serif" font-weight="700">{title}</text>
  <text x="100" y="320" fill="#334155" font-size="28" font-family="Segoe UI, Arial, sans-serif">{pillar}</text>
  <text x="100" y="500" fill="#0ea5e9" font-size="28" font-family="Segoe UI, Arial, sans-serif" font-weight="600">오늘의 핵심 포인트를 확인하세요 🚀</text>
</svg>
""".strip()


class ImageGenerationProvider(Protocol):
    def generate(self, *, prompt: str) -> "GeneratedImageAsset":
        ...


class ImageHostingProvider(Protocol):
    def upload(self, *, image_bytes: bytes, filename: str) -> str:
        ...


class URLValidator(Protocol):
    def validate(self, url: str) -> bool:
        ...


@dataclass(slots=True)
class GeneratedImageAsset:
    image_bytes: bytes | None
    mime_type: str
    source_format: str
    raw_response: dict[str, object]
    remote_url: str | None = None


@dataclass(slots=True)
class ImagePipelineResult:
    work_item_id: str
    status: str
    image_url: str | None
    final_image_url: str | None
    image_prompt: str
    article_html: str
    fallback_used: bool
    error_message: str
    raw_response: dict[str, object]


class OpenAIImageGenerationProvider:
    def __init__(self, settings: Settings) -> None:
        self.client = OpenAIImageClient(settings)

    def generate(self, *, prompt: str) -> GeneratedImageAsset:
        raw_response = self.client.generate_image(prompt=prompt)
        if not isinstance(raw_response, dict) or not isinstance(raw_response.get("data"), list) or not raw_response["data"]:
            raise RuntimeError("Image generation response did not include a data array.")
        first_item = raw_response["data"][0]
        if not isinstance(first_item, dict):
            raise RuntimeError("Image generation response first item is not an object.")
        if first_item.get("b64_json"):
            decoded = base64.b64decode(str(first_item["b64_json"]))
            if not decoded:
                raise RuntimeError("Image generation response contained an empty base64 payload.")
            return GeneratedImageAsset(
                image_bytes=decoded,
                mime_type="image/png",
                source_format="base64",
                raw_response=raw_response,
            )
        if first_item.get("url"):
            remote_url = str(first_item["url"]).strip()
            if not remote_url:
                raise RuntimeError("Image generation response contained an empty url.")
            return GeneratedImageAsset(
                image_bytes=None,
                mime_type="image/png",
                source_format="url",
                raw_response=raw_response,
                remote_url=remote_url,
            )
        raise RuntimeError("Image generation response did not include b64_json or url.")


class ImgBBHostingProvider:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.imgbb_api_key
        if not self.api_key:
            raise RuntimeError("AI_IMAGE_UPLOAD_KEY or IMGBB_API_KEY is required for imgbb upload.")

    def upload(self, *, image_bytes: bytes, filename: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        response = post_json_with_retry(
            url=f"https://api.imgbb.com/1/upload?key={self.api_key}",
            headers={"Content-Type": "application/json"},
            payload={"image": encoded, "name": filename},
            operation_name="imgbb_upload",
            logger=logger,
            connect_timeout=20,
            read_timeout=180,
        )
        parsed = json.loads(response)
        if not isinstance(parsed, dict) or not parsed.get("data"):
            raise RuntimeError("imgbb upload response missing data payload.")
        data = parsed.get("data", {})
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            raise RuntimeError("imgbb upload response missing public URL.")
        return url.strip()


class DefaultImageURLValidator:
    def validate(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        try:
            request = Request(url=url, method="GET")
            with urlopen(request, timeout=20) as response:
                return 200 <= int(response.status) < 400
        except Exception:
            return False


class ImageAssetPipelineService:
    def __init__(
        self,
        *,
        work_item_repository: BlogWorkItemRepository,
        content_package_repository: ContentPackageRepository,
        settings: Settings,
    ) -> None:
        self.work_item_repository = work_item_repository
        self.content_package_repository = content_package_repository
        self.settings = settings

    def process_cover_image(
        self,
        *,
        work_item_id: str,
        generation_provider: ImageGenerationProvider | None = None,
        hosting_provider: ImageHostingProvider | None = None,
        url_validator: URLValidator | None = None,
        allow_publish_without_image: bool = True,
    ) -> ImagePipelineResult:
        work_item = self.work_item_repository.get_by_id(work_item_id)
        package = self.content_package_repository.get_by_work_item_id(work_item_id)
        if work_item is None:
            raise ValueError(f"Work item not found: {work_item_id}")
        if package is None:
            raise ValueError(f"Content package not found: {work_item_id}")

        image_prompt = (
            package.image_prompt
            or work_item.image_prompt
            or self._build_cover_image_prompt(work_item.final_title or work_item.topic_title, work_item.content_pillar)
        )
        generation_provider = generation_provider or OpenAIImageGenerationProvider(self.settings)
        url_validator = url_validator or DefaultImageURLValidator()

        raw_response: dict[str, object] = {}
        image_url: str | None = None
        final_image_url: str | None = None
        error_message = ""
        status = "not_started"
        fallback_used = False

        try:
            generated = generation_provider.generate(prompt=image_prompt)
            raw_response = generated.raw_response
            _validate_generation_payload(generated)
            logger.info("image generation succeeded: work_item_id=%s source_format=%s", work_item_id, generated.source_format)

            if generated.remote_url:
                image_url = generated.remote_url
                logger.info("image generation returned remote url: work_item_id=%s", work_item_id)
            else:
                chosen_hosting_provider = hosting_provider
                if chosen_hosting_provider is None and self.settings.enable_imgbb_upload:
                    chosen_hosting_provider = ImgBBHostingProvider(self.settings)
                if chosen_hosting_provider is None:
                    raise RuntimeError("Image bytes were generated but no hosting provider is available.")
                image_url = chosen_hosting_provider.upload(
                    image_bytes=generated.image_bytes or b"",
                    filename=f"{work_item_id}-cover",
                )
                logger.info("image upload succeeded: work_item_id=%s", work_item_id)

            if not image_url or not validate_public_image_url(image_url, validator=url_validator):
                raise RuntimeError(f"Final image URL is not publicly accessible: {image_url}")

            final_image_url = image_url
            status = "generated"
        except Exception as exc:  # noqa: BLE001
            error_message = f"{type(exc).__name__}: {exc}"
            logger.warning("image pipeline failed: work_item_id=%s error=%s", work_item_id, error_message)
            if not allow_publish_without_image:
                raise
            fallback_used = True
            status = "fallback_branding_image"
            final_image_url = ""
            image_url = None
            raw_response = raw_response or {"error": error_message}

        article_html = _inject_cover_image(
            article_html=work_item.article_html,
            image_url=final_image_url or None,
            fallback_svg_data_url=_build_fallback_data_url(work_item.final_title or work_item.topic_title, work_item.content_pillar)
            if fallback_used
            else None,
            alt_text=work_item.final_title or work_item.topic_title,
        )
        work_item.image_prompt = image_prompt
        work_item.image_url = final_image_url or ""
        work_item.generated_image_status = status
        work_item.image_error_message = error_message
        work_item.final_image_url = final_image_url or ""
        work_item.article_html = article_html
        if fallback_used:
            work_item.notes = _append_note(work_item.notes, f"image fallback used: {error_message}")
        else:
            work_item.notes = _append_note(work_item.notes, f"image generated: {final_image_url}")
        self.work_item_repository.upsert(work_item)

        return ImagePipelineResult(
            work_item_id=work_item_id,
            status=status,
            image_url=image_url,
            final_image_url=final_image_url,
            image_prompt=image_prompt,
            article_html=article_html,
            fallback_used=fallback_used,
            error_message=error_message,
            raw_response=raw_response,
        )

    @staticmethod
    def _build_cover_image_prompt(final_title: str, pillar: str) -> str:
        return (
            f"Premium editorial blog cover, trustworthy Korean business blog style, "
            f"mobile friendly composition, clear focal point, topic={pillar}, title={final_title}"
        )


def validate_public_image_url(url: str, *, validator: URLValidator | None = None) -> bool:
    if not url or not url.strip():
        return False
    return (validator or DefaultImageURLValidator()).validate(url.strip())


def _validate_generation_payload(generated: GeneratedImageAsset) -> None:
    if generated.source_format == "base64":
        if not generated.image_bytes:
            raise RuntimeError("Image generation reported base64 output but image_bytes is empty.")
    elif generated.source_format == "url":
        if not generated.remote_url:
            raise RuntimeError("Image generation reported url output but remote_url is empty.")
    else:
        raise RuntimeError(f"Unsupported image source format: {generated.source_format}")


def _inject_cover_image(
    article_html: str,
    image_url: str | None,
    fallback_svg_data_url: str | None,
    alt_text: str = "",
) -> str:
    src = image_url or fallback_svg_data_url
    if not src:
        return article_html
    if "{{IMG_1}}" in article_html:
        return article_html.replace("{{IMG_1}}", src)
    safe_alt = html_escape_for_svg(" ".join((alt_text or "AI cover image").split()))
    image_block = (
        "<section style=\"margin:0 0 20px 0;\">"
        f"<img src=\"{src}\" alt=\"{safe_alt}\" "
        "style=\"width:100%;height:auto;border-radius:8px;display:block;border:1px solid #dbe3ee;\" />"
        "</section>"
    )
    if "<article" in article_html:
        insertion_point = article_html.find(">", article_html.find("<article"))
        if insertion_point != -1:
            return article_html[: insertion_point + 1] + image_block + article_html[insertion_point + 1 :]
    return image_block + article_html


def _build_fallback_data_url(title: str, pillar: str) -> str:
    safe_title = html_escape_for_svg(title[:42] or "Fallback cover")
    safe_pillar = html_escape_for_svg(pillar[:48] or "Blogger post")
    svg = FALLBACK_BRANDING_SVG.format(title=safe_title, pillar=safe_pillar)
    return f"data:image/svg+xml;charset=utf-8,{quote(svg)}"


def html_escape_for_svg(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _append_note(existing: str, new_note: str) -> str:
    return new_note if not existing else f"{existing}\n{new_note}"
