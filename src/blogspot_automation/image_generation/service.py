from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import base64
import json

from blogspot_automation.config.settings import Settings
from blogspot_automation.storage import StateStore


@dataclass(slots=True)
class ImageGenerationResult:
    topic_id: str
    status: str
    image_path: str | None
    meta_path: str


def generate_cover_image(
    *,
    topic_id: str,
    store: StateStore,
    settings: Settings,
    client: Any,
) -> ImageGenerationResult:
    del settings
    image_dir = store.topic_image_dir(topic_id)
    blog_package_payload = store.load_blog_package(topic_id)
    blog_package = dict(blog_package_payload.get("blog_package") or {})
    prompt = str(
        blog_package.get("cover_image_prompt")
        or blog_package.get("image_prompt")
        or "Editorial blog cover image, clean minimal, no text"
    )
    (image_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    try:
        response = client.generate_image(prompt=prompt)
        (image_dir / "image_raw_response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        b64_json = str(((response.get("data") or [{}])[0] or {}).get("b64_json") or "")
        if not b64_json:
            raise RuntimeError("image response missing b64_json")
        image_path = image_dir / "cover.png"
        image_path.write_bytes(base64.b64decode(b64_json))
        meta = {
            "topic_id": topic_id,
            "status": "generated",
            "image_path": str(image_path),
            "prompt": prompt,
        }
        status = "generated"
    except Exception as exc:  # noqa: BLE001
        image_path = None
        meta = {
            "topic_id": topic_id,
            "status": "placeholder_pending",
            "image_path": None,
            "prompt": prompt,
            "todo": "Generate or upload a cover image before live publishing.",
            "error": f"{type(exc).__name__}: {exc}",
        }
        status = "placeholder_pending"

    meta_path = image_dir / "image_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    blog_package["image_assets"] = {
        "status": status,
        "image_path": str(image_path) if image_path else None,
        "meta_path": str(meta_path),
    }
    blog_package_payload["blog_package"] = blog_package
    store.save_blog_package(topic_id, blog_package_payload)
    return ImageGenerationResult(
        topic_id=topic_id,
        status=status,
        image_path=str(image_path) if image_path else None,
        meta_path=str(meta_path),
    )


def show_image_meta(*, topic_id: str, store: StateStore) -> dict[str, Any]:
    meta = store.try_load_image_meta(topic_id)
    if meta is None:
        raise FileNotFoundError(f"image_meta.json not found for topic_id={topic_id}")
    return meta
