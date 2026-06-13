# Architecture

## Architecture Summary

The project will move from an AI-news automation stack to a monetization-focused Blogger publishing platform.

The new architecture is local-first and built around:
- Streamlit operator app
- service layer
- pipeline orchestrators
- SQLite-first persistence
- Blogger HTML publishing

## Architectural Principles
- SQLite is the operational source of truth
- JSON artifacts are secondary but always available for inspection
- UI calls services, not raw CLI logic
- pipelines orchestrate services but do not own business rules
- publishing is Blogger HTML first
- optional public image hosting is modular

## Target Layers

### App Layer
- Streamlit dashboard
- operator workflow actions
- run history and publish status

### Service Layer
- topic planning
- article generation
- QA
- publish preparation
- Blogger publish
- image hosting

### Pipeline Layer
- orchestrated stage-by-stage execution
- no duplicate business logic
- status transitions and resumability

### Storage Layer
- repository pattern over SQLite
- JSON artifact writer
- local file structure for drafts and publish outputs

### Template Layer
- reusable prompts
- reusable HTML blocks
- reusable QA checklists

## Status Flow
- `planned`
- `generated`
- `qa_failed`
- `published`
- `failed`

## Publish Artifact Layout

```text
contents/
  drafts/{topic_id}/
  artifacts/{topic_id}/
  published/{topic_id}/
images/{topic_id}/
logs/
runs/
```

## Blogger Publishing Contract
- clean title
- slug
- publish-ready HTML
- meta description
- labels
- schema JSON-LD
- image URL if required
- stored request and response

## Migration Notes
- preserve reusable local state and Blogger integration logic
- replace AI-news strategy modules with business-topic planning modules
- move Streamlit into operator-first workflow screens
