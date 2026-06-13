from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from blogspot_automation.config import Settings, get_settings
from blogspot_automation.services import (
    BlogBriefGenerationService,
    BlogQualityAssuranceService,
    BloggerPackageService,
    BloggerPublishService,
    ImageAssetPipelineService,
)
from blogspot_automation.services.ai_content_service import AiContentService
from blogspot_automation.storage import (
    BlogWorkItemRepository,
    BriefRecordRepository,
    ContentPackageRepository,
    PublishRecordRepository,
    QAReviewRepository,
    SQLiteBlogStore,
)


@dataclass(slots=True)
class ServiceRuntime:
    settings: Settings
    store: SQLiteBlogStore
    work_repo: BlogWorkItemRepository
    brief_repo: BriefRecordRepository
    package_repo: ContentPackageRepository
    qa_repo: QAReviewRepository
    publish_repo: PublishRecordRepository
    brief_service: BlogBriefGenerationService
    ai_content_service: AiContentService | None
    package_service: BloggerPackageService
    image_service: ImageAssetPipelineService
    qa_service: BlogQualityAssuranceService
    publish_service: BloggerPublishService


def build_service_runtime(
    *,
    root_dir: Path,
    settings: Settings | None = None,
    publish_client=None,
) -> ServiceRuntime:
    resolved_settings = settings or get_settings()
    store = SQLiteBlogStore(root_dir)
    work_repo = BlogWorkItemRepository(store)
    brief_repo = BriefRecordRepository(store)
    package_repo = ContentPackageRepository(store)
    qa_repo = QAReviewRepository(store)
    publish_repo = PublishRecordRepository(store)

    # Try to initialize AiContentService; gracefully degrade if API key missing
    try:
        ai_content_svc: AiContentService | None = AiContentService(
            work_item_repository=work_repo,
            brief_repository=brief_repo,
            settings=resolved_settings,
        )
    except ValueError:
        ai_content_svc = None

    return ServiceRuntime(
        settings=resolved_settings,
        store=store,
        work_repo=work_repo,
        brief_repo=brief_repo,
        package_repo=package_repo,
        qa_repo=qa_repo,
        publish_repo=publish_repo,
        brief_service=BlogBriefGenerationService(
            work_item_repository=work_repo,
            brief_repository=brief_repo,
        ),
        ai_content_service=ai_content_svc,
        package_service=BloggerPackageService(
            work_item_repository=work_repo,
            brief_repository=brief_repo,
            content_package_repository=package_repo,
        ),
        image_service=ImageAssetPipelineService(
            work_item_repository=work_repo,
            content_package_repository=package_repo,
            settings=resolved_settings,
        ),
        qa_service=BlogQualityAssuranceService(
            work_item_repository=work_repo,
            brief_repository=brief_repo,
            content_package_repository=package_repo,
            qa_review_repository=qa_repo,
        ),
        publish_service=BloggerPublishService(
            work_item_repository=work_repo,
            content_package_repository=package_repo,
            qa_review_repository=qa_repo,
            publish_record_repository=publish_repo,
            settings=resolved_settings,
            blogger_client=publish_client,
        ),
    )

