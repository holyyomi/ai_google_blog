# Runbook

## Current News Pipeline Quick Path

The active news automation uses this provider order:

```text
gemini_free -> openai_api_fallback
```

Required operator-owned secrets:

- `GOOGLE_AI_API_KEY`
- `OPENAI_API_KEY`

Optional search secrets:

- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_CX`

Recommended model env:

- `GEMINI_MODEL=gemini-2.5-flash-lite`
- `OPENAI_MODEL=gpt-5-mini`
- `ENABLE_GOOGLE_CUSTOM_SEARCH=false`

Do not use `OPENROUTER_API_KEY`.

Keep `ENABLE_GOOGLE_CUSTOM_SEARCH=false` when Programmable Search cannot enable "entire web" access. The pipeline will use Google News RSS and practical issue queries instead.

## Scheduled News Publishing

Production news publishing is configured in `.github/workflows/news_blog.yml`.

- GitHub Actions wakes twice per hour: `28,58 * * * *`.
- `tools/should_run_news_schedule.py` is the fixed-slot gate.
- Publish slot is `08:58` KST for one AI post per day.
- The gate ignores dry-run, deleted, 404, and unverified failed post-audit records when deciding whether a slot already succeeded.
- Live-verified records (`url_verified_status_code=200` or `live_url_verified=true`) count as real publishes even when older posts fail the newer audit checklist.
- `data/publish_history.json` is committed after each publish-mode run and acts as the editorial feedback log.

Keep these workflow values for automatic upload:

```yaml
cron: "28,58 * * * *"
NEWS_SCHEDULE_SLOTS: "08:58"
NEWS_PUBLISH_MODE: publish
AUTO_PUBLISH: true
PUBLISH_HOLD_PHASE2: "false"
ENABLE_GOOGLE_CUSTOM_SEARCH: "false"
```

Each history record stores the selected topic, title, source type, quality gate result, reader value score, focus score, topic engine score, title/golden pattern result, auto-publish blocking reasons, post-publish audit issues, and `learning_signals`. Topic selection uses recent history for rotation and duplicate avoidance, so repeated weak topics are pushed down over time.

If the committed feedback log drifts from the actual Blogger publish log, run the repair tool with a dry run first:

```powershell
python tools/sync_publish_history.py --dry-run --verify-live-urls
python tools/sync_publish_history.py --verify-live-urls
```

The repair writes a timestamped backup under `data/backups/`, backfills `state/news_published_history.json` into `data/publish_history.json`, and never revives records marked deleted, 404, or dereferenced.

Before a dry run:

```powershell
python scripts/validate_news_env.py
```

Before live publish:

```powershell
python scripts/validate_news_env.py --strict
```

Run `python scripts/validate_news_env.py --live-search` only when you intentionally enable `ENABLE_GOOGLE_CUSTOM_SEARCH=true`.

Safe dry run:

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

## 가장 쉬운 실행 방법

```powershell
$env:PYTHONPATH='src'
streamlit run src/blogspot_automation/ui/app.py
```

화면에서 `지금 자동 발행 시작` 버튼만 누르면 됩니다.

## Real-World Operating Sequence

Use this exact order for a real topic.

## 1. Init

```powershell
python -m venv .venv
.venv\Scripts\activate
copy .env.example .env
$env:PYTHONPATH='src'
python -m blogspot_automation.cli.main state init
```

Fill `.env` with:

- `OPENAI_API_KEY`
- `BLOGGER_BLOG_ID`
- and either:
  - `BLOGGER_ACCESS_TOKEN`
  - or `BLOGGER_CLIENT_ID`, `BLOGGER_CLIENT_SECRET`, `BLOGGER_REFRESH_TOKEN`

## 2. Discover Topics

```powershell
python -m blogspot_automation.cli.main discover-topics
python -m blogspot_automation.cli.main list-planned-topics
```

## 3. Select Topic

Choose one `topic_id` from `list-planned-topics`.

Optional detail check:

```powershell
python -m blogspot_automation.cli.main show-topic --topic-id <TOPIC_ID>
```

## 4. Build Fact Pack

```powershell
python -m blogspot_automation.cli.main build-fact-pack --topic-id <TOPIC_ID>
```

Check:

- `contents/<TOPIC_ID>/fact_pack.json`
- `contents/<TOPIC_ID>/source_pack.json`

## 5. Build Blog Package

```powershell
python -m blogspot_automation.cli.main build-blog-package --topic-id <TOPIC_ID>
```

Check:

- `contents/<TOPIC_ID>/brief.json`
- `contents/<TOPIC_ID>/blog_package.json`
- `contents/<TOPIC_ID>/article.html`
- `contents/<TOPIC_ID>/article.md`
- `contents/<TOPIC_ID>/metadata.json`

## 6. QA Review

```powershell
python -m blogspot_automation.cli.main qa-review --topic-id <TOPIC_ID>
python -m blogspot_automation.cli.main qa-status --topic-id <TOPIC_ID>
```

Check:

- `contents/<TOPIC_ID>/qa/qa_report.json`

## 7. Refine If Needed

Run only when `qa_result` is `FIX_REQUIRED`.

```powershell
python -m blogspot_automation.cli.main refine-content --topic-id <TOPIC_ID>
python -m blogspot_automation.cli.main qa-review --topic-id <TOPIC_ID>
python -m blogspot_automation.cli.main qa-status --topic-id <TOPIC_ID>
```

Check:

- `contents/<TOPIC_ID>/qa/revision_payload.json`
- updated `contents/<TOPIC_ID>/blog_package.json`

## 8. Generate Image Metadata

```powershell
python -m blogspot_automation.cli.main generate-cover-image --topic-id <TOPIC_ID>
python -m blogspot_automation.cli.main show-image-meta --topic-id <TOPIC_ID>
```

Check:

- `images/<TOPIC_ID>/prompt.txt`
- `images/<TOPIC_ID>/image_meta.json`
- `images/<TOPIC_ID>/cover.png` if generation succeeded

## 9. Approve Final Package

Run only after `qa_result=PASS`.

```powershell
python -m blogspot_automation.cli.main qa-approve --topic-id <TOPIC_ID> --reviewer-notes "Local review completed"
```

Check:

- `contents/<TOPIC_ID>/final_ready_package.json`

## 10. Publish Dry-Run

```powershell
python -m blogspot_automation.cli.main publish-topic --topic-id <TOPIC_ID> --dry-run
python -m blogspot_automation.cli.main publish-status --topic-id <TOPIC_ID>
```

Check:

- `contents/<TOPIC_ID>/publish/publish_ready.html`
- `contents/<TOPIC_ID>/publish/publish_ready_metadata.json`
- `contents/<TOPIC_ID>/publish/publish_request.json`
- `contents/<TOPIC_ID>/publish/publish_response.json`
- `contents/<TOPIC_ID>/publish/publish_log.jsonl`

## 11. Publish Live

Only after inspecting the dry-run artifacts.

```powershell
python -m blogspot_automation.cli.main publish-topic --topic-id <TOPIC_ID>
python -m blogspot_automation.cli.main publish-status --topic-id <TOPIC_ID>
```

Check:

- `contents/<TOPIC_ID>/publish/published_post.json`
- `contents/<TOPIC_ID>/publish/history/`

## 12. Recovery / Resume

- Re-run discovery safely
- Rebuild fact pack if sources change
- Re-run QA after refinement
- Re-run dry-run publish any time
- Live publish is blocked when already published unless `--force` is passed

## Single Integrated Run

For one-command execution:

```powershell
$env:PYTHONPATH='src'
python -m blogspot_automation.cli.main run-full --topic-id <TOPIC_ID> --auto-approve --dry-run-only
python -m blogspot_automation.cli.main run-full --topic-id <TOPIC_ID> --auto-approve
```

Useful options:

- `--dry-run-only`
- `--skip-image`
- `--auto-approve`
- `--force`

After `run-full`, inspect:

- `runs/run-full-<TOPIC_ID>-<TIMESTAMP>.json`
- `contents/<TOPIC_ID>/publish/publish_ready.html`
- `contents/<TOPIC_ID>/publish/publish_ready_metadata.json`

## Streamlit Run

```powershell
$env:PYTHONPATH='src'
streamlit run src/blogspot_automation/ui/app.py
```

원클릭 발행 화면 특징:

- 제목: `AI 블로그 자동 발행기`
- 큰 버튼 하나만 표시
- 최신 AI 주제를 자동 탐색
- 최고 점수 주제 1개 자동 선택
- 글, 메타 설명, 이미지, 발행까지 자동 실행
- 기본 화면에서는 내부 JSON과 경로를 숨김
- 옵션은 expander 안에서만 노출

## Changed Files

- `src/blogspot_automation/config/settings.py`
- `src/blogspot_automation/content_generation/renderers.py`
- `src/blogspot_automation/content_generation/service.py`
- `src/blogspot_automation/content_generation/validators.py`
- `src/blogspot_automation/publishing/client.py`
- `src/blogspot_automation/publishing/service.py`
- `src/blogspot_automation/storage/state_store.py`
- `tests/test_content_generation.py`
- `tests/test_publishing.py`
- `README.md`
- `RUNBOOK.md`
- `ARCHITECTURE.md`

## Verification Method

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m blogspot_automation.cli.main publish-topic --topic-id <TOPIC_ID> --dry-run
python -m blogspot_automation.cli.main publish-status --topic-id <TOPIC_ID>
```

Check:

- `publish_ready.html`
- `publish_ready_metadata.json`
- `publish_request.json`
- `publish_response.json`
- `publish_log.jsonl`

For live publish, also check:

- `published_post.json`
- `response_status`
- `published`
- `verified_status_code = 200`
- `runs/run-full-*.json` step logs

## Failure Checkpoints

- `OPENAI_BASE_URL` must end at `/v1`
- `qa_result` must be `PASS`
- Blogger credentials must be complete
- Blogger API response must include `id`, `url`, `title`, `status`, `published`
- live publish fails intentionally when the public URL GET check does not return `200`
- if `run-full` stops before publish, inspect the last failed step in the run log JSON
- if Streamlit UI is unavailable, install `streamlit` in the active environment
