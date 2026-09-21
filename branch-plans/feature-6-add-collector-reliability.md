# Collector reliability

- Branch: `feature/6-add-collector-reliability`
- Source plan: [`docs/branch-design.md`](../docs/branch-design.md)
- Specification: [`docs/scraping/README.md`](../docs/scraping/README.md)
- Issue: GitHub #6
- Start point: `origin/main` after PRs #13 and #14 were merged
- Prerequisite: Issue #5 collection workflow

## Scope

- [ ] Retry temporary network, 5xx, and 429 failures up to three times with backoff.
- [ ] Preserve successful retry outcomes and report only unresolved failures.
- [ ] Capture sanitized failure context for one summary notification per run.
- [ ] Emit collection progress at INFO, retryable failures at WARNING, and unresolved failures at ERROR.
- [ ] Keep article bodies, complete response bodies, target-specific values, and secrets out of logs and notifications.
- [ ] Add acceptance and regression tests for retry, failure aggregation, logging, and notification behavior.

## Non-goals

- Daily systemd scheduling (Issue #7).
- End-to-end deployment verification (Issue #8).
- Live scraping or committing source-specific configuration.

## Completion criteria

- All Issue #6 acceptance criteria are covered by tests.
- Formatting, Ruff, mypy, pytest, and coverage commands defined by `pyproject.toml` pass.
- Coverage remains at least 80%.
- The branch contains no `.env`, secrets, target-specific values, or generated artifacts.

## Unresolved decisions

- The retry backoff default and whether it should be configurable must be confirmed from the existing settings boundary before implementation.
