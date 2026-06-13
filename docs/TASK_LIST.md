# Task List

## Phase 1: Design Freeze
- Finalize PRD
- Finalize target architecture
- Finalize SQLite schema
- Finalize config spec
- Finalize publish artifact contract

## Phase 2: Storage Refactor
- Introduce new SQLite repositories
- Define migration-safe schema bootstrap
- Add JSON fallback artifact writer
- Add run and job history tables

## Phase 3: Topic Pipeline Refactor
- Replace AI-news topic discovery strategy
- Add category-aware topic planner
- Add long-tail intent scoring
- Add Korean finance/news source adapters

## Phase 4: Content Pipeline Refactor
- Add new content briefs per niche
- Add reusable article templates by cluster
- Add Blogger-ready HTML renderers
- Add metadata and schema generation

## Phase 5: QA Pipeline Refactor
- Build operator-grade QA checklist
- Add niche-specific validation rules
- Add finance/tax caution rules
- Add publish-blocking decisions

## Phase 6: Publish Pipeline Refactor
- Keep Blogger HTML upload path
- Add optional imgbb upload flow
- Improve publish verification and history

## Phase 7: Streamlit App Refactor
- Replace developer-facing controls
- Build operator dashboard by 4 stages
- Add queue and run history views
- Add retry and republish actions

## Phase 8: Cleanup
- Remove dead AI-news modules
- Remove Google Sheets assumptions
- Rewrite README and workflow docs
- Expand tests
