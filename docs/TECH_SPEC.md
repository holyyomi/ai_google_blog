# Tech Spec

## Runtime
- Python 3.11+
- Streamlit for local operator UI
- SQLite as primary store
- JSON files for artifact snapshots and fallback visibility

## Primary Integrations
- OpenAI-compatible API for content and image generation
- Blogger API for publishing
- imgbb API for optional public image URLs

## Publishing Model
- Final output is Blogger-safe HTML
- Publish request and response artifacts are always stored locally
- Public URL verification remains required after publish

## Data Contracts

### Topic Record
- `topic_id`
- `topic_group`
- `topic_cluster`
- `title_seed`
- `main_keyword`
- `supporting_keywords`
- `user_intent`
- `status`
- `created_at`

### Content Package
- `topic_id`
- `brief`
- `article_title`
- `slug`
- `meta_description`
- `article_html`
- `article_markdown`
- `faq_items`
- `schema_payload`
- `image_prompt`
- `image_alt`
- `status`

### QA Record
- `topic_id`
- `qa_result`
- `qa_score`
- `issues`
- `fixes`
- `reviewed_at`

### Publish Record
- `topic_id`
- `blogger_post_id`
- `blogger_post_url`
- `published_at`
- `status`
- `request_artifact_path`
- `response_artifact_path`

## SQLite Schema Draft

### `topics`
- `topic_id` TEXT PRIMARY KEY
- `topic_group` TEXT NOT NULL
- `topic_cluster` TEXT NOT NULL
- `title_seed` TEXT NOT NULL
- `main_keyword` TEXT NOT NULL
- `supporting_keywords_json` TEXT NOT NULL
- `user_intent` TEXT
- `status` TEXT NOT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

### `content_packages`
- `topic_id` TEXT PRIMARY KEY
- `brief_json` TEXT NOT NULL
- `article_title` TEXT
- `slug` TEXT
- `meta_description` TEXT
- `article_html_path` TEXT
- `article_markdown_path` TEXT
- `package_json_path` TEXT
- `status` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

### `qa_reviews`
- `topic_id` TEXT PRIMARY KEY
- `qa_result` TEXT NOT NULL
- `qa_score` REAL
- `issues_json` TEXT NOT NULL
- `fixes_json` TEXT NOT NULL
- `reviewed_at` TEXT NOT NULL

### `publish_jobs`
- `publish_id` TEXT PRIMARY KEY
- `topic_id` TEXT NOT NULL
- `blogger_post_id` TEXT
- `blogger_post_url` TEXT
- `published_at` TEXT
- `status` TEXT NOT NULL
- `request_path` TEXT
- `response_path` TEXT
- `verify_status_code` INTEGER
- `created_at` TEXT NOT NULL

### `run_logs`
- `run_id` TEXT PRIMARY KEY
- `pipeline_name` TEXT NOT NULL
- `topic_id` TEXT
- `status` TEXT NOT NULL
- `step_logs_json` TEXT NOT NULL
- `created_at` TEXT NOT NULL

## JSON Fallback Policy
- Every major stage writes an artifact JSON under `contents/artifacts/{topic_id}/`
- SQLite remains the source of truth
- JSON is for inspection, portability, and recovery
