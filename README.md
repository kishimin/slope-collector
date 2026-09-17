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

## Run the API

Start the API directly:

```powershell
uv run uvicorn app.main:app --reload
```

Start the API and MySQL 9.7.2 with Docker Compose:

```powershell
docker compose --env-file .env.development up --build
```

The API is available on port `8080`. Docker publishes MySQL on port `3307` so
it does not conflict with a host MySQL service on the default port.

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
