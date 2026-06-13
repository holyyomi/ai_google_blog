from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from blogspot_automation.config.settings import Settings
from blogspot_automation.services import (
    GeneratedImageAsset,
    ImageAssetPipelineService,
    validate_public_image_url,
)
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    ContentPackageRecord,
    ContentPackageRepository,
    ContentPillar,
    SQLiteBlogStore,
    create_sample_work_item,
)


class ImageAssetServiceTests(unittest.TestCase):
    def test_inserts_public_image_url_into_article_html(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            store = SQLiteBlogStore(Path(temp_dir))
            settings = Settings(data_dir=Path(temp_dir), sqlite_path="data/test.db")
            work_repo = BlogWorkItemRepository(store)
            package_repo = ContentPackageRepository(store)
            _seed_content_package(work_repo, package_repo, work_item_id="img-001")
            service = ImageAssetPipelineService(
                work_item_repository=work_repo,
                content_package_repository=package_repo,
                settings=settings,
            )

            result = service.process_cover_image(
                work_item_id="img-001",
                generation_provider=_FakeGenerationProvider(),
                hosting_provider=_FakeHostingProvider(),
                url_validator=_AlwaysValidURLValidator(),
            )

            self.assertEqual(result.status, "generated")
            self.assertEqual(result.final_image_url, "https://img.example.com/cover.png")
            self.assertIn("<img src=\"https://img.example.com/cover.png\"", result.article_html)
            loaded = work_repo.get_by_id("img-001")
            self.assertEqual(loaded.final_image_url, "https://img.example.com/cover.png")
            self.assertEqual(loaded.generated_image_status, "generated")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_uses_branding_fallback_when_upload_fails(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            store = SQLiteBlogStore(Path(temp_dir))
            settings = Settings(data_dir=Path(temp_dir), sqlite_path="data/test.db")
            work_repo = BlogWorkItemRepository(store)
            package_repo = ContentPackageRepository(store)
            _seed_content_package(work_repo, package_repo, work_item_id="img-002")
            service = ImageAssetPipelineService(
                work_item_repository=work_repo,
                content_package_repository=package_repo,
                settings=settings,
            )

            result = service.process_cover_image(
                work_item_id="img-002",
                generation_provider=_FakeGenerationProvider(),
                hosting_provider=_FailingHostingProvider(),
                allow_publish_without_image=True,
            )

            self.assertEqual(result.status, "fallback_branding_image")
            self.assertEqual(result.final_image_url, "")
            self.assertIn("<img src=\"data:image/svg+xml", result.article_html)
            self.assertIn("upload failed", result.error_message)
            loaded = work_repo.get_by_id("img-002")
            self.assertEqual(loaded.generated_image_status, "fallback_branding_image")
            self.assertTrue(loaded.image_error_message)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_public_image_url_checks_scheme_and_access(self) -> None:
        self.assertFalse(validate_public_image_url(""))
        self.assertFalse(validate_public_image_url("file:///tmp/x.png"))
        self.assertTrue(validate_public_image_url("https://img.example.com/x.png", validator=_AlwaysValidURLValidator()))


class _FakeGenerationProvider:
    def generate(self, *, prompt: str) -> GeneratedImageAsset:
        del prompt
        return GeneratedImageAsset(
            image_bytes=b"fake-image-bytes",
            mime_type="image/png",
            source_format="base64",
            raw_response={"data": [{"b64_json": "ZmFrZS1pbWFnZS1ieXRlcw=="}]},
        )


class _FakeHostingProvider:
    def upload(self, *, image_bytes: bytes, filename: str) -> str:
        del image_bytes, filename
        return "https://img.example.com/cover.png"


class _FailingHostingProvider:
    def upload(self, *, image_bytes: bytes, filename: str) -> str:
        del image_bytes, filename
        raise RuntimeError("upload failed")


class _AlwaysValidURLValidator:
    def validate(self, url: str) -> bool:
        return url.startswith("https://")


def _seed_content_package(
    work_repo: BlogWorkItemRepository,
    package_repo: ContentPackageRepository,
    *,
    work_item_id: str,
) -> None:
    work_item = create_sample_work_item(item_id=work_item_id, content_pillar=ContentPillar.AI_SIDE_HUSTLE)
    work_item.final_title = "AI 부업 자동화 실전 해설"
    work_item.article_html = "<article><h1>제목</h1><p>본문</p></article>"
    work_item.image_prompt = "Editorial cover"
    work_repo.upsert(work_item)
    package_repo.upsert(
        ContentPackageRecord(
            work_item_id=work_item_id,
            created_at="2026-03-17T00:00:00+00:00",
            updated_at="2026-03-17T00:00:00+00:00",
            title_candidates=["a", "b", "c", "d", "e"],
            final_title=work_item.final_title,
            meta_description="설명",
            labels=["AI"],
            hashtags=["#AI"],
            image_prompt="Editorial cover",
            article_html=work_item.article_html,
            article_preview_html="<!doctype html>",
            json_ld={},
        )
    )


if __name__ == "__main__":
    unittest.main()
