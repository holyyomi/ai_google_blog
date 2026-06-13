# News External Search Stack

Scheduled publishing now uses a layered discovery/verification stack.

Provider order:

1. Naver Search (`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`)
   - Primary Korean candidate discovery.
   - Default search types: `news,webkr`.
   - Request cap: `NEWS_NAVER_MAX_REQUESTS=18`.
2. Google News RSS
   - Free fallback and diversity source.
   - Google Custom Search remains disabled unless `ENABLE_GOOGLE_CUSTOM_SEARCH=true`.
3. Naver DataLab
   - Adds `naver_datalab_score` to candidates.
   - Request cap: `NEWS_NAVER_DATALAB_MAX_REQUESTS=5`.
4. Tavily
   - Verifies only top candidates with `search_depth=basic`.
   - Request cap: `NEWS_TAVILY_MAX_REQUESTS=3`.
5. Exa
   - Semantic web/news corroboration for a very small finalist set.
   - Request cap: `NEWS_EXA_MAX_REQUESTS=1`.
6. Firecrawl
   - Final source evidence extraction/search only.
   - Request cap: `NEWS_FIRECRAWL_MAX_REQUESTS=1`.

Scoring inputs added to candidate `raw`:

- `external_search_providers`
- `naver_datalab_score`
- `verified_source_count`
- `source_diversity_score`
- `official_source_found`
- `web_verification`

`NewsScoringService` converts these signals into `external_evidence_bonus`, capped at 8 points. The bonus is disabled for stale, risky, fallback, and evergreen fallback candidates.
