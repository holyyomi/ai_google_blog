from __future__ import annotations

import os
import re
from html import escape
from urllib.parse import urlparse


def cover_image_url_from_env(
    *,
    content_type: str = "",
    topic_group: str = "",
    include_default: bool = True,
) -> str:
    for key in _cover_image_env_keys(
        content_type=content_type,
        topic_group=topic_group,
        include_default=include_default,
    ):
        value = _clean_public_image_url(os.getenv(key, ""))
        if value:
            return value
    return ""


def cover_image_required_from_env() -> bool:
    return os.getenv("REQUIRE_NEWS_COVER_IMAGE", "false").strip().lower() in {"1", "true", "yes", "on"}


def _cover_image_env_keys(
    *,
    content_type: str = "",
    topic_group: str = "",
    include_default: bool = True,
) -> tuple[str, ...]:
    keys: list[str] = []
    for value in (content_type, topic_group):
        suffix = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_").upper()
        if suffix:
            keys.append(f"AI_COVER_IMAGE_URL_{suffix}")
            keys.append(f"NEWS_COVER_IMAGE_URL_{suffix}")
    keys.append("AI_COVER_IMAGE_URL")
    keys.append("NEWS_COVER_IMAGE_URL")
    if include_default:
        keys.append("AI_DEFAULT_COVER_IMAGE_URL")
        keys.append("DEFAULT_NEWS_COVER_IMAGE_URL")
    return tuple(dict.fromkeys(keys))


def ensure_cover_image_html(
    html: str,
    *,
    image_url: str = "",
    alt_text: str = "",
    title: str = "",
) -> str:
    content = html or ""
    if not content.strip() or _has_article_image(content):
        return content
    clean_url = _clean_public_image_url(image_url)
    if not clean_url:
        return content

    safe_alt = escape(" ".join((alt_text or title or "AI cover image").split()), quote=True)
    block = (
        '<figure class="news-cover-image" data-yomi-block="cover-image">'
        f'<img src="{escape(clean_url, quote=True)}" alt="{safe_alt}" '
        'loading="eager" decoding="async" width="1200" height="675" '
        "/>"
        "</figure>"
    )
    if re.search(r"</h1>", content, flags=re.IGNORECASE):
        return re.sub(r"</h1>", f"</h1>\n{block}", content, count=1, flags=re.IGNORECASE)
    if re.search(r"<article\b[^>]*>", content, flags=re.IGNORECASE):
        return re.sub(
            r"(<article\b[^>]*>)",
            lambda match: f"{match.group(1)}\n{block}",
            content,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"{block}\n{content}"


def cover_image_coverage(html: str) -> dict[str, object]:
    content = html or ""
    match = re.search(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", content, flags=re.IGNORECASE)
    src = match.group(1).strip() if match else ""
    return {
        "cover_image_present": bool(match),
        "cover_image_url": src,
        "cover_image_public_url": bool(_clean_public_image_url(src)),
        "cover_image_block_present": 'data-yomi-block="cover-image"' in content,
    }


def _has_article_image(html: str) -> bool:
    return bool(re.search(r"<img\b[^>]*\bsrc=[\"'][^\"']+[\"']", html or "", flags=re.IGNORECASE))


def _clean_public_image_url(value: str) -> str:
    url = " ".join((value or "").split()).strip()
    if not url or any(char in url for char in ('"', "'", "<", ">")):
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url
