# Automation Engine Structure

## Pipeline Model

The system will be explicitly divided into 4 stages.

1. Topic Selection
2. Content Generation
3. QA
4. Publishing

## Stage 1: Topic Selection

### Responsibilities
- generate candidate topics by niche
- rank by search demand, monetization fit, and explainability
- save operator-selectable planned topics

### Outputs
- `topic_id`
- topic brief seed
- target cluster
- keyword package
- operator-facing rationale

## Stage 2: Content Generation

### Responsibilities
- create article brief
- create Korean article package
- render Blogger HTML
- generate metadata and schema
- generate image prompt

### Outputs
- HTML
- markdown
- meta description
- labels
- FAQ
- JSON-LD
- image prompt and alt text

## Stage 3: QA

### Responsibilities
- validate readability
- validate factual safety
- validate finance/tax caution rules
- validate publish completeness

### Outputs
- PASS or FAIL style decision
- fix list
- operator notes

## Stage 4: Publishing

### Responsibilities
- upload image if public URL required
- build final Blogger payload
- publish HTML
- verify public URL
- store publish artifacts and history

### Outputs
- publish request
- publish response
- published post record
- publish log

## Reuse Mapping From Existing Code
- current `publishing` module -> future `services/publish_service.py`
- current `storage` module -> future `storage/sqlite_store.py`
- current `ui` module -> future `app/streamlit_app.py`
- current retry/logging helpers -> future `utils/`

## Removal Mapping
- current AI-news topic discovery -> replace
- current AI-launch fact-pack defaults -> replace
- current one-click AI topic recommendation UI -> replace
