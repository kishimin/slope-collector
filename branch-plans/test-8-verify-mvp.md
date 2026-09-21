# Branch Work Plan: MVP End-to-End Verification

- Branch: `test/8-verify-mvp`
- Source plan: [`docs/branch-design.md`](../docs/branch-design.md)
- Specification: GitHub Issue #8, “Add end-to-end MVP tests and deployment verification”
- Start point: `origin/main` at `ca14ad7bd1478a9962d5b160e64195a97c51b288`
- Prerequisites: Issues #4, #5, #6, and #7 are merged into `main`.
- Dependencies: the read-only API, collection workflow, reliability handling, systemd units, local-only configuration boundary, and ADR-0068.

## Owned scope

This branch verifies the complete MVP across persistence, API, collection, notifications, and scheduling. It adds automated coverage for critical paths and documents deployment verification without committing secrets, target-specific configuration, or collected data.

The following Issue #8 requirements are in scope:

- Integration tests for database-backed API behavior.
- Backfill and incremental collection flows with mocked HTTP responses.
- Duplicate prevention and transaction rollback for record and asset persistence.
- Retry and failure-summary behavior.
- Ruff and mypy checks.
- Alembic migration from an empty MySQL database.
- API startup and collector execution in the deployment environment.
- systemd daily execution and log inspection.
- Repository scan proving `.env`, secrets, target URLs, selectors, IDs/classes, and target-specific fixtures are absent.

## Ordered work items

- [ ] Create acceptance coverage for the Issue #8 MVP verification contract without modifying existing acceptance tests. **Skipped by explicit user decision to not use ATDD.**
- [x] Verify database-backed API integration coverage for list/detail behavior and error boundaries. Existing acceptance and medium tests exercise a real SQLAlchemy database through the HTTP boundary; no redundant test was added.
- [x] Add mocked-HTTP incremental collection coverage, including duplicate prevention. Backfill coverage already exists in acceptance and medium tests.
- [x] Add persistence rollback coverage for records and assets. A duplicate asset position is rejected without leaving partial rows.
- [x] Add retry and failure-summary integration coverage across the collector boundary. Mocked HTTP verifies transient retries; a permanent record failure is delivered as one sanitized summary.
- [ ] Add an empty-MySQL Alembic migration verification that uses only test/deployment fixtures.
- [ ] Add API startup and collector execution verification for the supported deployment environment.
- [ ] Add systemd timer/service execution and journald inspection verification where the host environment permits it.
- [ ] Add a deterministic repository scan for secrets, `.env`, target-specific values, and fixtures.
- [x] Run formatting, type checking, lint/static analysis, tests, coverage, and `git diff --check`.

## Progress evidence

- `python -m pytest acceptance/test_read_only_api.py tests/small/test_records.py tests/medium/test_collection_repository.py -q` — 10 passed.
- `python -m pytest tests/medium/test_collection_incremental.py -q` — 1 passed.
- `python -m pytest tests/medium/test_collection_repository.py -q` — 5 passed.
- Full repository verification — 71 passed, total coverage 86.20%, Ruff format/check and mypy passed, `git diff --check` passed.
- `python -m pytest tests/medium/test_collection_reliability_integration.py -q` — 2 passed.

## Non-goals

- No live scraping against external targets.
- No production deployment or production database mutation.
- No target-specific URLs, selectors, identifiers, fixtures, secrets, or collected data.
- No API contract redesign or database schema redesign.
- No changes to the existing retry, pacing, scheduling, or local-only data-boundary decisions unless a separate decision is approved.
- No direct changes to `main`; delivery is through a pull request.

## Completion criteria

- Automated tests cover the critical MVP paths listed in Issue #8.
- Migration, API, collector, notification, and scheduling flows have verifiable test or deployment evidence.
- Ruff and mypy pass.
- Coverage remains at least 80% for every reported metric.
- Repository scans confirm that secrets, `.env`, target-specific configuration, and target-specific fixtures are not committed.
- Acceptance tests pass and remain unchanged after their baseline commit.
- Repository-defined verification succeeds:
  - `python -m ruff format --check app tests acceptance`
  - `python -m ruff check app tests acceptance`
  - `python -m mypy app tests acceptance`
  - `python -m pytest acceptance tests --cov=app --cov-report=term-missing -q`
  - `git diff --check`

## Unresolved decisions and blockers

- The supported MySQL test host and credentials must be supplied through test-only environment configuration; no real credentials may enter Git.
- Linux-only API startup, systemd execution, journald inspection, and `systemd-analyze verify` require a deployment-capable environment; this Windows machine cannot prove them directly.
- The exact boundary between deterministic repository scans and deployment-only checks must be fixed before acceptance tests are committed.
- Whether Issue #8 should include a real Docker-based MySQL integration job or only a deployment verification procedure is not specified by the issue and requires confirmation.
