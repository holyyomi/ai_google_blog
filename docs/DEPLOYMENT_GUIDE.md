# News Automation Deployment Guide

## GitHub Secrets

Register only these API secrets for the current news pipeline.

| Name | Required | Purpose |
| --- | --- | --- |
| `GOOGLE_SEARCH_API_KEY` | Optional | Google Custom Search candidate discovery, only when explicitly enabled |
| `GOOGLE_SEARCH_CX` | Optional | Programmable Search Engine ID, only when explicitly enabled |
| `GOOGLE_AI_API_KEY` | Yes | Gemini API first-pass generation |
| `OPENAI_API_KEY` | Yes | OpenAI fallback generation |
| `BLOGGER_CLIENT_ID` | Publish only | Blogger OAuth client |
| `BLOGGER_CLIENT_SECRET` | Publish only | Blogger OAuth secret |
| `BLOGGER_REFRESH_TOKEN` | Publish only | Blogger refresh token |
| `BLOGGER_BLOG_ID` | Publish only | Target Blogspot blog |
| `NEWS_COVER_IMAGE_URL` | Optional | Reusable cover image URL |

Do not set `OPENROUTER_API_KEY`. OpenRouter is no longer used.

`ENABLE_GOOGLE_CUSTOM_SEARCH` defaults to `false`. This keeps the pipeline independent from Programmable Search "entire web" access and uses Google News RSS first. Turn it on only after `python scripts/validate_news_env.py --live-search` succeeds.

## Workflow Defaults

The GitHub Actions workflow sets:

```yaml
schedule: 17,47 * * * *
schedule_kst: 08:13
NEWS_PUBLISH_MODE: publish
AUTO_PUBLISH: true
GEMINI_MODEL: gemini-2.5-flash
OPENAI_MODEL: gpt-5-mini
ENABLE_GOOGLE_CUSTOM_SEARCH: false
AI_BLOG_MODE: true
NEWS_EXCLUDED_QUERY_GROUPS: ""
ALLOW_AI_NEWS_TOPICS: true
```

The workflow wakes twice per hour, then `tools/should_run_news_schedule.py` allows publish attempts only for the fixed KST slots. This gives catch-up chances when GitHub schedule events are delayed. The schedule gate does not count dry-run, deleted, 404, or unverified failed post-audit records as successful publishes. Live-verified records still count as real publishes, even if older posts fail the newer audit checklist. After each publish-mode run, `data/publish_history.json` is committed back to the branch. That file is the feedback memory for topic rotation, duplicate avoidance, quality warnings, and post-publish audit issues.

If the feedback log needs repair, run `python tools/sync_publish_history.py --dry-run --verify-live-urls` first, then rerun without `--dry-run`. The tool creates `data/backups/` snapshots before writing.

## Local Validation

Run the non-secret diagnostics before a dry run:

```powershell
python scripts/validate_news_env.py
```

Use strict mode in CI or before live publish:

```powershell
python scripts/validate_news_env.py --strict
```

Validate the actual Custom Search key/CX with one live request only if you plan to set `ENABLE_GOOGLE_CUSTOM_SEARCH=true`:

```powershell
python scripts/validate_news_env.py --live-search
```

The output masks keys and only reports whether each required value is present.

## Dry Run

```powershell
$env:DRY_RUN='true'
$env:NEWS_PUBLISH_MODE='dry_run'
$env:AUTO_PUBLISH='false'
$env:NEWS_MODE='news'
$env:AI_BLOG_MODE='true'
$env:NEWS_EXCLUDED_QUERY_GROUPS=''
$env:ALLOW_AI_NEWS_TOPICS='true'
$env:BLOGSPOT_HOME_URL='https://holyyomiai.blogspot.com/'
$env:DISABLE_IMAGE_GENERATION='true'
$env:DISABLE_IMAGE_UPLOAD='true'
$env:RUNS_DIR='runs'
python src/blogspot_automation/cli_news.py
```

Expected LLM order:

```text
gemini_free -> openai_api_fallback
```

Expected safe outcomes:

- `dry_run_saved`: article candidate passed review gates but was not published.
- `blocked_by_quality_gate`: article generated but failed final quality checks.
- `held_no_fresh_or_fallback_candidate`: no safe fresh candidate, so nothing is published.

## Live Publish Gate

Only use publish mode after diagnostics and dry-run artifacts are clean:

```powershell
$env:DRY_RUN='false'
$env:NEWS_PUBLISH_MODE='publish'
$env:AUTO_PUBLISH='true'
python src/blogspot_automation/cli_news.py
```

Live publish still requires Blogger credentials and quality gates to pass. It does not require Google Custom Search while `ENABLE_GOOGLE_CUSTOM_SEARCH=false`.

For scheduled live publishing, keep the workflow defaults above. A scheduled run still publishes only when all of these are true:

- a real Google News RSS candidate is selected, not a fallback candidate
- Gemini or OpenAI content generation succeeds
- the golden article candidate is generated
- `publish_quality_gate.passed=true`
- `publish_ready=true`, `geo_ready=true`, and `sge_ready=true`
- Blogger credentials are present and valid
