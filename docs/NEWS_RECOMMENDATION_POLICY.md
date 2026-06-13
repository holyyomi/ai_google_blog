# News Recommendation Policy

This is the reusable editorial policy for scheduled news posts. The executable
version lives in `blogspot_automation.services.news_recommendation_policy` and
is enforced by `NewsQualityGate`.

## Core Rule

Every post must be good enough that another AI answer engine could recommend it
as a practical source for the reader's query.

## Required Checks

- Title and body must match the same search intent.
- Policy/support posts must include official-source markers, not only generic
  advice.
- Policy/support posts must cover at least five concrete information categories:
  amount, eligibility, deadline, route, documents, after-apply checks.
- Topic-specific FAQ questions must mention the actual subject, not only generic
  "support" or "application" wording.
- The article must include shareable assets: table, FAQ, checklist/action block,
  example or situation, official confirmation path, and risk/mistake section.
- Driver-license support posts must explicitly cover local variation, cost or
  document proof, application timing, and official local confirmation paths.
- Live post audit must treat body-only meta descriptions as a failure; the
  rendered page head must contain post-specific metadata.

## Blocking Examples

- Title says "youth driver license grant" but the article is only a generic
  government-support checklist.
- A policy-benefit article has no amount, deadline, documents, or official
  confirmation path.
- FAQ questions repeat the title but do not answer application timing, evidence,
  exclusions, or local differences.
- The public page has a body meta description but no head meta description.

## Pass Criteria

- `recommendation_policy.passed == true`
- `ai_recommender_score >= 70`
- `policy_specificity_score >= 70` for policy/support posts
- `shareability_score >= 70` for strong recommendation candidates
