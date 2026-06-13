# Project Structure

## Target Top-Level Layout

```text
config/
app/
services/
pipelines/
storage/
templates/
utils/
contents/
  artifacts/
  drafts/
  published/
images/
logs/
runs/
tests/
```

## Python Package Layout

```text
src/blogspot_automation/
  app/
    streamlit_app.py
    view_models.py
    state_handlers.py
  services/
    topic_service.py
    content_service.py
    qa_service.py
    publish_service.py
    image_service.py
    asset_service.py
  pipelines/
    topic_pipeline.py
    content_pipeline.py
    qa_pipeline.py
    publish_pipeline.py
    full_pipeline.py
  storage/
    sqlite_store.py
    artifact_store.py
    repositories/
  templates/
    prompts/
    html/
    qa/
  utils/
    logging.py
    retry.py
    slug.py
    html.py
    time.py
    validation.py
  config/
    settings.py
    loader.py
```

## Reuse Strategy From Current Codebase

Keep and adapt:
- local SQLite state handling
- Blogger publishing integration
- image generation integration
- Streamlit runtime shell
- retry and logging utilities

Phase out or replace:
- AI-news-specific topic discovery
- current fact-pack structure as a global default
- cluster logic centered on AI launches only
- old one-click assumptions tied to AI topic cards

## Folder Intent
- `app`: Streamlit UI and app coordination
- `services`: domain services used by UI and CLI
- `pipelines`: orchestration only
- `storage`: SQLite and file persistence
- `templates`: content, HTML, QA, and prompt templates
- `utils`: shared helper code
