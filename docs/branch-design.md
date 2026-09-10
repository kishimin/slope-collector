# Git Branch Design

This document defines the branch structure and merge flow for slope-collector.

## Principles

- One change purpose is implemented in one branch and delivered by one pull request.
- `main` always represents the latest integrated state.
- Changes to `main` are made only by merging pull requests. Direct pushes and force pushes are prohibited.
- A work branch is deleted after its pull request is merged and is not reused for another purpose.
- Secrets, `.env` files, target URLs, selectors, IDs, class names, and target-specific fixtures are never committed.

## Branch Names

Branch names use `{type}/{issue-number}-{short-description}`.

The description uses lowercase kebab-case and describes the intended outcome rather than an implementation detail.

| Type | Purpose |
| --- | --- |
| `feature/` | User-facing or domain behavior |
| `fix/` | Defect correction |
| `refactor/` | Structural improvement without behavior changes |
| `docs/` | Documentation-only changes |
| `test/` | Test-only changes |
| `chore/` | Tooling, dependencies, migrations, and other maintenance |

`feat/` is not used as a branch type. It is reserved for Conventional Commits that add behavior.

Examples:

- `feature/4-add-read-only-api`
- `fix/12-prevent-duplicate-assets`
- `docs/define-git-branch-strategy`

## Branch and Pull Request Flow

1. Confirm that all dependency issues have been merged into `main`.
2. Update the local `main` from `origin/main`.
3. Create a new work branch from the updated `main`.
4. Implement only the selected issue's acceptance criteria.
5. Run every verification command defined by the repository for formatting, compilation or type checking, lint or static analysis, tests, and coverage.
6. Open a pull request targeting `main` and link the issue.
7. Merge only after required checks and review succeed.
8. Delete the merged work branch.

Dependent work starts after its prerequisite pull requests have been merged. Long-lived stacked branches are not used, so each pull request is reviewable against the current `main`.

## MVP Branch Plan

| Order | Issue | Branch | Start condition |
| --- | --- | --- | --- |
| 1 | #1 Set up database connection foundation | `chore/1-set-up-database-connection` | Start from `main` |
| 2 | #2 Implement SQLAlchemy models | `feature/2-add-sqlalchemy-models` | #1 merged |
| 3 | #3 Set up Alembic and initial migration | `chore/3-add-initial-migration` | #1 and #2 merged |
| 4A | #4 Implement read-only API | `feature/4-add-read-only-api` | #1, #2, and #3 merged |
| 4B | #5 Implement scraper and collection workflow | `feature/5-add-collection-workflow` | #1, #2, and #3 merged |
| 5 | #6 Implement retry, logging, and failure notifications | `feature/6-add-collector-reliability` | #5 merged |
| 6 | #7 Set up daily collection with systemd timer | `feature/7-schedule-daily-collection` | #5 and #6 merged |
| 7 | #8 Add end-to-end MVP tests and deployment verification | `test/8-verify-mvp` | #4, #5, #6, and #7 merged |

Branches #4 and #5 may be developed in parallel after #3 is merged because neither issue depends on the other. Issue #8 begins only after both paths and all of its other dependencies are merged.

## Commit Design

Commit messages use Conventional Commits and have an English summary followed by a body that explains why the change is needed.

- `test:` records a test that defines behavior.
- `feat:` implements new behavior.
- `fix:` corrects defective behavior.
- `refactor:` improves structure without changing behavior.
- `docs:` changes documentation only.
- `chore:` changes maintenance concerns such as dependencies or tooling.

For code changes, Red, Green, and Refactor commits remain on the same `feature/` or `fix/` branch. Branch types and commit types serve different purposes and do not need to match.

## Main Branch Protection

GitHub must protect `main` with a repository Ruleset that:

- requires changes to be merged through pull requests;
- requires the repository's mandatory status checks after those checks are introduced;
- blocks force pushes and deletion;
- does not provide a routine bypass for maintainers or automation.

A local `pre-push` hook may reject accidental direct pushes earlier, but it is only an additional safeguard. Server-side protection is the enforcement boundary.

## Emergency Changes

Urgent fixes use a `fix/` branch and the normal pull request path. Urgency does not permit direct pushes to `main` or skipping available verification. If branch protection itself must be changed during an incident, a maintainer records the reason and restores the protection after recovery.

## Completion Criteria

A branch is complete only when:

- its issue acceptance criteria are satisfied;
- all repository-defined formatting, compilation or type-checking, lint or static-analysis, test, and coverage commands succeed;
- the coverage summary reports at least 80% for every metric it provides;
- no target-specific values, secrets, generated artifacts, or unrelated changes are included;
- the pull request has passed the required checks and review.
