# Product Requirements Document

## Overview
This project will replace the current AI-news Blogger automation flow with a monetization-focused Korean blog automation engine.

The new system targets practical publishing for the following top-level content clusters:

1. Daily side hustle breakdowns
2. Korean stock explainers based on Korean news
3. AI side hustle and online monetization
4. Side hustle tax and multi-income tax in Korea
5. Korean stock beginner guides

## Product Goals
- Run as a local-first Python and Streamlit application.
- Remove Google Sheets dependency completely.
- Use SQLite as the default operational store.
- Use Blogger HTML upload as the primary publish path.
- Support imgbb upload only when a public image URL is required.
- Split the pipeline into 4 clear stages:
  - topic selection
  - content generation
  - QA
  - publishing

## Non-Goals For This Phase
- Full implementation of every pipeline service
- External workflow tools such as n8n
- Complex multi-user auth
- CMS other than Blogger

## User Types
- Solo Korean blog operator
- Small media operator
- Niche affiliate or ad-monetized content operator

## Core User Outcomes
- Pick high-potential monetizable topics quickly
- Generate high-quality Korean blog drafts
- Reject weak articles before publish
- Publish clean Blogger-ready HTML with minimal manual work

## Functional Requirements
- Topic planner for monetization-driven categories
- Structured article package generation
- QA gate with PASS / FAIL style decisions
- Blogger publish-ready artifact generation
- Local run history and state tracking
- Streamlit control panel for operations

## Quality Requirements
- Korean writing must be readable, explicit, and translation-friendly
- Avoid generic filler and unsupported claims
- Prioritize reusable templates and deterministic outputs
- Prefer source-grounded content for news and finance-sensitive topics

## State Model
- `planned`
- `generated`
- `qa_failed`
- `published`
- `failed`

## Storage Requirements
- SQLite first
- JSON artifact fallback and debug output when needed
- Deterministic per-topic output folders

## Migration Direction
- Reuse useful local storage, Blogger publish, logging, and Streamlit foundations
- Remove or phase out AI-news-specific topic discovery, fact-pack logic, and AI-only prompt assumptions
