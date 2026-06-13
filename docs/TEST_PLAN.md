# Test Plan

## Objectives
- Ensure the new architecture supports operator workflows reliably
- Prevent silent publish failures
- Validate SQLite-first behavior
- Validate Blogger HTML artifacts before real publish

## Test Layers

### Unit Tests
- slug generation
- metadata normalization
- template rendering
- state transitions
- retry and timeout handling

### Service Tests
- topic planning service
- content packaging service
- QA scoring service
- Blogger publish artifact builder
- optional imgbb upload service

### Pipeline Tests
- planned to generated
- generated to qa_failed
- generated to published
- failure recovery from intermediate steps

### Storage Tests
- SQLite schema bootstrap
- repository CRUD
- JSON artifact fallback
- state idempotency

### UI Tests
- Streamlit view model logic
- operator actions call correct services
- failed runs show clear operator messages

## Critical Scenarios
- Blogger publish succeeds and URL is verified
- Blogger publish fails but artifacts remain recoverable
- content package exists even if image upload fails
- QA failure blocks live publish
- rerun after failure resumes correctly

## Acceptance Criteria
- No publish without valid HTML artifact
- No final state mutation without durable storage write
- Every pipeline run leaves inspectable local artifacts
