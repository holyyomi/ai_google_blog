from __future__ import annotations

import re
from html import escape, unescape


def extract_meta_description(html: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html or "", flags=re.IGNORECASE):
        name = _attr(tag, "name").lower()
        if name == "description":
            return unescape(_attr(tag, "content")).strip()
    return ""


def upsert_meta_description(html: str, description: str) -> str:
    """Ensure the publish HTML carries a standard search description tag."""
    clean_description = " ".join((description or "").split()).strip()
    if not clean_description:
        raise ValueError("Search description is required.")

    escaped = escape(clean_description, quote=True)
    meta_tag = f'<meta name="description" content="{escaped}">'
    content = html or ""
    pattern = r'<meta\b(?=[^>]*\bname\s*=\s*["\']description["\'])[^>]*>'
    if re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, meta_tag, content, count=1, flags=re.IGNORECASE | re.DOTALL)

    if re.search(r"<head\b[^>]*>", content, flags=re.IGNORECASE):
        return re.sub(
            r"(<head\b[^>]*>)",
            lambda match: f"{match.group(1)}\n{meta_tag}",
            content,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"{meta_tag}\n{content}".strip()


def _attr(tag: str, name: str) -> str:
    match = re.search(
        rf"\b{name}\s*=\s*([\"'])(.*?)\1",
        tag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(2) if match else ""
