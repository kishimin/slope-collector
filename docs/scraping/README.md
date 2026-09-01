# Scraping Design

Scraping and collection design for slope-collector.

## Responsibilities

The implementation uses simple responsibility separation rather than a full Clean Architecture.

```text
app/
├── api/          # FastAPI endpoints
├── models/       # SQLAlchemy models
├── services/     # Collection workflows
├── scraping/     # HTTP fetching and HTML parsing
├── repositories/ # Database operations
└── db/           # Database connection
```

Important boundaries:

- Fetching/parsing is separated from database persistence.
- API handlers do not contain direct database operation logic.
- Target-specific HTML structure and URLs are configuration, not application logic.

## Collection Modes

### Backfill

The initial collection is executed manually and collects all available records for all entities.

```text
manual backfill
  ↓
all entities
  ↓
traverse all available pages
  ↓
fetch and parse all records
  ↓
save record + assets
```

Each record and its assets are persisted in a single database transaction.

### Daily Collection

Normal collection runs once per day.

```text
systemd timer
  ↓
active entities
  ↓
traverse records from newest to oldest
  ↓
fetch and save unseen records
  ↓
stop when an existing external_key is reached
```

The collector must not assume that checking only the newest page is sufficient. It continues pagination until previously collected data is reached so that multiple records published between runs are not missed.

## Scheduling

Daily collection is started by a `systemd timer` on the application server.

The collector runs as an independent process rather than embedding a scheduler inside FastAPI.

The initial backfill is started manually.

The same systemd service is not run concurrently. This prevents overlapping daily collection processes.

## Retry Policy

Transient failures such as network errors, `5xx` responses, and `429 Too Many Requests` are retried up to three times with backoff.

A failure that succeeds during retry is treated as successful. Only failures remaining after all retry attempts are included in the final failure report.

Parsing failures are logged and the collector continues processing other records when possible.

## Recovery

Successfully collected records are persisted immediately rather than waiting for the entire collection run to complete.

The database acts as the collection checkpoint. On a later run, existing records are detected using their identifiers and skipped, allowing collection to resume without a dedicated job-management table for the MVP.

## Error Notification

All errors that remain unresolved after retries are collected during the run.

If at least one failure remains when the run finishes, one summary email is sent containing the failures rather than sending one email per error.

The notification should include enough information to investigate the failure, such as:

- occurrence time
- entity or record context when available
- processing stage
- exception type
- error message

Mail configuration and recipient information are provided through environment variables and are not committed to the repository.

## Logging

The collector logs the complete processing flow using appropriate log levels.

- `INFO`: run start/end, entity processing, record fetch/save/skip, and summary counts
- `WARNING`: retryable failures, retries, and rate-limit responses
- `ERROR`: failures that remain unresolved and exceptions that prevent a processing step from completing

Article bodies and complete HTTP response bodies are not written to logs.

## Target Configuration

Information that can identify or reveal the collection target is not committed to the public repository.

Target URLs, URL patterns, selectors, class names, IDs, pagination configuration, and similar target-specific values are stored only in local environment configuration.

`.env` is excluded from Git. `.env.example` exposes only generic environment-variable names and does not contain real target values.

Example:

```dotenv
TARGET_BASE_URL=
TARGET_LIST_PATH=
TARGET_DETAIL_PATH=

LIST_ITEM_SELECTOR=
TITLE_SELECTOR=
BODY_SELECTOR=
DATE_SELECTOR=
ASSET_SELECTOR=
NEXT_PAGE_SELECTOR=
```

Application code and public documentation use generic terminology and must not contain target-specific values.