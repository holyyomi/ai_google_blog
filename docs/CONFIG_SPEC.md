# Config Spec

## Principles
- `.env` driven local configuration
- explicit, minimal, operator-friendly
- no Google Sheets credentials
- SQLite default, JSON fallback automatic

## Required Settings
- `APP_ENV`
- `DATA_DIR`
- `SQLITE_PATH`
- `BLOGGER_BLOG_ID`

## Candidate Discovery Settings
- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_CX`
- `ENABLE_GOOGLE_CUSTOM_SEARCH=false`

`GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_CX` are optional. The news pipeline works without Programmable Search "entire web" access. By default it uses Google News RSS and prioritized practical queries. Set `ENABLE_GOOGLE_CUSTOM_SEARCH=true` only after the live search diagnostic succeeds.

## LLM Settings
- `GOOGLE_AI_API_KEY`
- `GEMINI_MODEL=gemini-2.5-flash-lite`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL=gpt-5-mini`
- `OPENAI_IMAGE_MODEL`

Provider order is fixed:

```text
gemini_free -> openai_api_fallback
```

`OPENROUTER_API_KEY` is not used.

## Blogger Settings
- `BLOGGER_ACCESS_TOKEN`
- or:
  - `BLOGGER_CLIENT_ID`
  - `BLOGGER_CLIENT_SECRET`
  - `BLOGGER_REFRESH_TOKEN`

## Optional Image Hosting
- `IMGBB_API_KEY`
- `ENABLE_IMGBB_UPLOAD=true|false`

## App Settings
- `LOG_LEVEL`
- `DEFAULT_DRY_RUN=true|false`
- `DEFAULT_QA_BLOCK=true|false`
- `DEFAULT_IMAGE_UPLOAD=true|false`

## Config Validation Rules
- SQLite path must always resolve under local workspace
- Blogger credentials must be complete before live publish
- imgbb remains optional and disabled by default
- `OPENAI_BASE_URL` must normalize to `/v1`
- run `python scripts/validate_news_env.py --strict` before live publish
