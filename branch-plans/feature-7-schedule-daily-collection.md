# Branch Work Plan: Daily Collection Scheduling

- Branch: `feature/7-schedule-daily-collection`
- Source plan: [`docs/branch-design.md`](../docs/branch-design.md)
- Specification: GitHub Issue #7, “Set up daily collection with systemd timer”
- Start point: `origin/main` at `976e61df39ef434593c22701e52cf8f386461157`
- Prerequisites: Issues #5 and #6 are merged into `main`.
- Dependencies: existing daily collection command, collector reliability behavior, and local-only target configuration.

## Owned scope

This branch adds production scheduling for the existing daily incremental collection workflow. It keeps the initial full backfill as a manual operation and keeps deployment-specific secrets and target configuration outside the repository.

The following Issue #7 requirements are in scope:

- Provide a collector command for daily incremental collection.
- Provide a separate command for manual backfill.
- Add a systemd service definition for the collector.
- Add a systemd timer definition that runs once per day.
- Prevent overlapping executions of the same collector service.
- Document installation, enable/start, status, logs, and manual execution procedures.

## Ordered work items

- [ ] Add or complete the daily incremental collection command while preserving the separate manual backfill command.
- [ ] Define a systemd service that invokes the daily command with deployment-specific configuration supplied outside Git.
- [ ] Define a once-per-day systemd timer and document its schedule semantics.
- [ ] Enforce single-process execution for the service and add a test or configuration-level verification for overlap prevention.
- [ ] Add operational documentation for installation, enable/start, status, logs, and manual execution.
- [ ] Add or update acceptance tests for the Issue #7 command and scheduling contract without modifying existing acceptance tests.
- [ ] Run formatting, type checking, lint/static analysis, tests, coverage, and `git diff --check`.

## Non-goals

- No initial full-history backfill from the systemd timer.
- No target-specific URLs, selectors, IDs, fixtures, secrets, or collected data in the repository.
- No database schema or API redesign.
- No deployment to a production host.
- No change to the retry policy introduced by Issue #6 except where the daily command must invoke it.
- No changes to `main` directly; delivery is through a pull request.

## Completion criteria

- The daily command performs incremental collection and the backfill command remains manual and separate.
- The service and timer definitions are present, generic, and free of deployment secrets.
- The timer runs once per day and overlapping service executions are prevented.
- The documented operational commands match the committed unit files and collector entry points.
- Issue #7 acceptance criteria are covered by tests or deterministic configuration checks.
- Repository-defined verification succeeds:
  - `python -m ruff format --check app tests acceptance`
  - `python -m ruff check app tests acceptance`
  - `python -m mypy app tests acceptance`
  - `python -m pytest acceptance tests --cov=app --cov-report=term-missing -q`
  - `git diff --check`
- Coverage remains at least 80% for every reported metric.

## Unresolved decisions and blockers

- The exact daily timer time and timezone are not specified by Issue #7 and must be decided before writing the unit file.
- The systemd deployment user, working directory, environment-file path, and service restart policy are deployment-specific and must remain placeholders or documented inputs.
- The concrete inter-process lock mechanism must be selected and tested without introducing a second scheduler.
- The ADR-0068 policy requires serial target processing and checkpoint-based resumption; implementation details must preserve that boundary.
