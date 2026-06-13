from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.image_generation.service import generate_cover_image, show_image_meta
from blogspot_automation.storage import StateStore


_ONE_PIXEL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2p6YQAAAAASUVORK5CYII="
)


class FakeImageClient:
    def generate_image(self, *, prompt: str, size: str = "1536x1024") -> dict[str, object]:
        del prompt, size
        return {
            "created": 1234567890,
            "data": [{"b64_json": _ONE_PIXEL_PNG_BASE64}],
        }


class FailingImageClient:
    def generate_image(self, *, prompt: str, size: str = "1536x1024") -> dict[str, object]:
        del prompt, size
        raise RuntimeError("Image API unavailable in current environment.")


class ImageGenerationTests(unittest.TestCase):
    def test_generate_cover_image_writes_files_and_updates_blog_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db")
            store = StateStore(settings)
            _seed_topic_assets(store, "topic-001")

            result = generate_cover_image(
                topic_id="topic-001",
                store=store,
                settings=settings,
                client=FakeImageClient(),
            )

            image_dir = root / "images" / "topic-001"
            self.assertEqual(result.status, "generated")
            self.assertTrue((image_dir / "cover.png").exists())
            self.assertTrue((image_dir / "image_meta.json").exists())
            self.assertTrue((image_dir / "prompt.txt").exists())
            self.assertTrue((image_dir / "image_raw_response.json").exists())

            payload = store.load_blog_package("topic-001")
            self.assertEqual(payload["blog_package"]["image_assets"]["status"], "generated")
            self.assertTrue(payload["blog_package"]["image_assets"]["image_path"].endswith("cover.png"))

    def test_generate_cover_image_saves_placeholder_when_api_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, sqlite_path="state/test.db")
            store = StateStore(settings)
            _seed_topic_assets(store, "topic-002")

            result = generate_cover_image(
                topic_id="topic-002",
                store=store,
                settings=settings,
                client=FailingImageClient(),
            )

            image_dir = root / "images" / "topic-002"
            self.assertEqual(result.status, "placeholder_pending")
            self.assertFalse((image_dir / "cover.png").exists())
            meta = show_image_meta(topic_id="topic-002", store=store)
            self.assertEqual(meta["status"], "placeholder_pending")
            self.assertIsNone(meta["image_path"])
            self.assertIn("todo", meta)


def _seed_topic_assets(store: StateStore, topic_id: str) -> None:
    output_dir = store.topic_output_dir(topic_id)
    brief_payload = {
        "topic_data": {"topic_id": topic_id},
        "brief": {"run_id": "brief-1", "topic_id": topic_id},
    }
    metadata_payload = {
        "cover_image_prompt": "Editorial, modern AI automation cover, clean shapes, no text",
    }
    blog_package_payload = {
        "topic_data": {"topic_id": topic_id},
        "brief": {"run_id": "brief-1", "topic_id": topic_id},
        "blog_package": {
            "topic_id": topic_id,
            "cover_image_prompt": "Editorial, modern AI automation cover, clean shapes, no text",
            "image_assets": {},
        },
    }
    (output_dir / "brief.json").write_text(json.dumps(brief_payload, ensure_ascii=False), encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata_payload, ensure_ascii=False), encoding="utf-8")
    (output_dir / "blog_package.json").write_text(
        json.dumps(blog_package_payload, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
