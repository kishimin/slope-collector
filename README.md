# slope-collector

Collect and expose normalized public records without committing target-specific
configuration or secrets.

## Requirements

- Python 3.14.7
- uv 0.12.15
- Docker Desktop for the local MySQL environment

## Setup

Install the locked development environment:

```powershell
uv sync --all-groups
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

The local `.env`, `.env.development`, and `.env.test` files are intentionally
excluded from Git. Their committed `*.example` counterparts document the
required variable names without real collection targets or credentials.

Create the files used by the local API and Docker Compose. This script keeps an
existing destination file instead of overwriting it:

```powershell
$environmentFiles = @(
    @{ Source = ".env.example"; Destination = ".env" },
    @{ Source = ".env.development.example"; Destination = ".env.development" }
)

foreach ($environmentFile in $environmentFiles) {
    if (Test-Path -LiteralPath $environmentFile.Destination) {
        Write-Host "Keeping existing $($environmentFile.Destination)"
        continue
    }

    Copy-Item -LiteralPath $environmentFile.Source -Destination $environmentFile.Destination
}
```

Before starting either environment, replace the placeholder local passwords in
`.env.development`. Also set `.env`'s `DATABASE_URL` to a database reachable
from the host. When using the Compose database published by this project, use
port `3307` and the same database name, user, and password configured in
`.env.development`.

The application automatically loads `.env`; it does not automatically load
`.env.test`. The committed `.env.test.example` is reserved for commands that
explicitly load a separate test environment. The current test suite supplies
its required settings through the test runner and does not require a local
`.env.test` file.

## Run the API

Start the API directly:

```powershell
uv run uvicorn app.main:app --reload --port 8080
```

Start the API and MySQL 9.7.2 with Docker Compose:

```powershell
docker compose --env-file .env.development up --build
```

The API is available on port `8080`. Docker publishes MySQL on port `3307` so
it does not conflict with a host MySQL service on the default port.

## Verify source adapters locally

Private source URLs, paths, selectors, identifier patterns, and approved asset
hosts belong only in the untracked `.env` file. Their committed example values
must remain empty.

Fetch and parse one article from each configured source into a local Markdown
preview:

```powershell
uv run python -m app.scraping.preview --output scrape-preview.md
```

The preview intentionally omits source hosts, source URLs, selectors, and image
URLs. `scrape-preview.md` is not ignored automatically; inspect it locally and
do not stage or commit it.

## Verification

| Purpose | Command |
| --- | --- |
| Format | `uv run ruff format .` |
| Format check | `uv run ruff format --check .` |
| Lint | `uv run ruff check .` |
| Type check | `uv run mypy app tests` |
| Small tests | `uv run pytest -m small` |
| Small and Medium tests | `uv run pytest -m "small or medium"` |
| All tests with coverage | `uv run pytest --cov=app --cov-report=term-missing` |
| Validate Compose | `docker compose --env-file .env.development config --quiet` |
| Build container | `docker build --tag slope-collector:local .` |

Coverage fails when Coverage.py's branch-aware total falls below 80%.

## Project structure

```text
app/
├── api/          # FastAPI endpoints
├── db/           # Database infrastructure
├── models/       # SQLAlchemy models
├── repositories/ # Persistence boundaries
├── scraping/     # HTTP fetching and parsing
└── services/     # Application workflows
```

Alembic is initialized under `alembic/`, but the initial migration is deferred
until the SQLAlchemy models exist. The units under `deploy/systemd/` are also
templates: the service remains inactive until `app.collector` is implemented.
