<div id="top"></div>

# slope-collector

Collect and expose normalized public records through a local FastAPI service and a separate collection process.

## Tech Stack

<p style="display: inline">
  <img src="https://img.shields.io/badge/-Python-3776AB.svg?logo=python&style=for-the-badge&logoColor=white">
  <img src="https://img.shields.io/badge/-FastAPI-009688.svg?logo=fastapi&style=for-the-badge&logoColor=white">
  <img src="https://img.shields.io/badge/-MySQL-4479A1.svg?logo=mysql&style=for-the-badge&logoColor=white">
  <img src="https://img.shields.io/badge/-pytest-0A9EDC.svg?logo=pytest&style=for-the-badge&logoColor=white">
  <img src="https://img.shields.io/badge/-Docker-2496ED.svg?logo=docker&style=for-the-badge&logoColor=white">
  <img src="https://img.shields.io/badge/-Ruff-D7FF64.svg?logo=ruff&style=for-the-badge&logoColor=black">
</p>

## Table of Contents

1. [About the Project](#about-the-project)
2. [Environment](#environment)
3. [Directory Structure](#directory-structure)
4. [Getting Started](#getting-started)
5. [Usage](#usage)
6. [API Endpoints](#api-endpoints)
7. [Available Commands](#available-commands)
8. [Troubleshooting](#troubleshooting)
9. [License](#license)

## About the Project

slope-collector provides these concepts:

- **Source**: A configured public collection source represented by a safe name.
- **Entity**: A source-owned author-like identity that groups records.
- **Record**: A normalized public article with a title, body, source path, and publication time.
- **Asset**: An approved image reference attached to a record.
- **Backfill**: A manual collection mode that follows historical pages.
- **Daily collection**: An incremental mode that stops at an existing persistence checkpoint.

The repository separates collection from the read-only development API. FastAPI exposes locally stored records, while the collector uses HTTP bounds, pacing, retries, and persistence checkpoints. Source URLs, selectors, credentials, and collected data stay outside committed files; the committed environment examples contain placeholders only.

The development API is bound to localhost by the Compose configuration. Production deployment details are represented by systemd unit files, but runtime timer execution and journald inspection require a Linux deployment environment.

<p align="right">(<a href="#top">back to top</a>)</p>

## Environment

| Language / Framework | Version |
| -------------------- | ------- |
| Python | 3.14.7 |
| uv | 0.12.15 |
| FastAPI | >=0.100,<1 |
| MySQL | 9.7.2 (Compose image) |

See `pyproject.toml`, `uv.lock`, and the `*.env.example` files for dependency and environment metadata.

<p align="right">(<a href="#top">back to top</a>)</p>

## Directory Structure

```text
.
├── .github/workflows
├── acceptance
├── alembic/versions
├── app
│   ├── api
│   ├── db
│   ├── models
│   ├── repositories
│   ├── scraping
│   └── services
├── branch-plans
├── deploy/systemd
├── docs
├── tests
│   ├── small
│   ├── medium
│   └── large
├── Dockerfile
├── compose.yaml
├── LICENSE
├── pyproject.toml
├── README.md
└── uv.lock
```

### Main Directories

| Directory | Description |
| --------- | ----------- |
| `app/api` | FastAPI health and development read-only endpoints. |
| `app/scraping` | HTTP bounds, source adapters, parsing, and preview support. |
| `app/services` | Collection workflows, retry handling, and notifications. |
| `app/repositories` | Persistence checkpoint implementation. |
| `app/models` and `app/db` | SQLAlchemy models and database session infrastructure. |
| `alembic` | Database migration environment and revisions. |
| `deploy/systemd` | Daily and manual collection service/timer definitions. |
| `acceptance` and `tests` | Acceptance contracts and size-marked automated tests. |
| `.github/workflows` | Quality, test, container, and Linux systemd verification jobs. |

<p align="right">(<a href="#top">back to top</a>)</p>

## Getting Started

### Prerequisites

Install Python 3.14.7, uv 0.12.15, and Docker Desktop. The local Compose environment uses MySQL 9.7.2 and publishes the database on `127.0.0.1:3307`.

### Clone the Repository

```powershell
git clone https://github.com/kishimin/slope-collector.git
cd slope-collector
```

### Install Dependencies

```powershell
uv sync --all-groups
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

Create local environment files from the committed examples without overwriting existing files:

```powershell
$environmentFiles = @(
    @{ Source = ".env.example"; Destination = ".env" },
    @{ Source = ".env.development.example"; Destination = ".env.development" }
)

foreach ($environmentFile in $environmentFiles) {
    if (-not (Test-Path -LiteralPath $environmentFile.Destination)) {
        Copy-Item -LiteralPath $environmentFile.Source -Destination $environmentFile.Destination
    }
}
```

Fill in only deployment-specific local values. Never commit `.env`, `.env.development`, `.env.test`, credentials, target URLs, selectors, or collected data.

The tracked `.env.example` defaults to `ENVIRONMENT=production`. Before the direct API command below, edit `.env` for local development and use a host-reachable MySQL URL, for example:

```text
ENVIRONMENT=development
DATABASE_URL=mysql+pymysql://collector:replace-with-local-password@127.0.0.1:3307/collector
```

The `.env.development` example keeps the Compose hostname `db:3306`; use it with the Compose command rather than with a host-launched Uvicorn process.

### Run Tests

```powershell
uv run pytest -m "small or medium"
uv run pytest acceptance tests --cov=app --cov-report=term-missing -q
```

### Start the API

Run the development API directly:

```powershell
uv run uvicorn app.main:app --reload --port 8080
```

Or start the API and MySQL together:

```powershell
docker compose --env-file .env.development up --build
```

Open `http://127.0.0.1:8080/health` and expect `{"status":"ok"}`.

### Run the Production Container

```powershell
docker build --tag slope-collector:local .
docker compose --env-file .env.development up --build
```

The image exposes port `8080`. Compose binds the API to `127.0.0.1:8080` and MySQL to `127.0.0.1:3307`.

<p align="right">(<a href="#top">back to top</a>)</p>

## Usage

### Read the local API

```python
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
    print(response.read().decode())
```

### Initialize and collect records

```powershell
uv run alembic upgrade head
uv run python -m app.collector collect-backfill
uv run python -m app.collector collect-daily
```

Run collection only against an intentionally configured local or deployment database. `collect-backfill` and `collect-daily` are separate processes from FastAPI.

To backfill one source-owned member, pass its source identity key to the manual
backfill command. This is the source key stored in `entities.external_key`, not
the database-generated `entities.id`:

```powershell
uv run python -m app.collector collect-backfill --source source_a --source-entity-key 40
```

The targeted backfill adds the requested source entity key to the configured
list path and follows only that member's pagination. Existing record keys are
checked before detail requests, so already persisted articles are not fetched
again.

<p align="right">(<a href="#top">back to top</a>)</p>

## API Endpoints

Development record routes are enabled only when `ENVIRONMENT=development`. Production exposes the health route but does not publish the development record browser.

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Return service availability. |
| `GET` | `/sources` | List configured source names. |
| `GET` | `/entities` | List entities; optionally filter with `source_id`. |
| `GET` | `/entities/{entity_id}` | Return one entity or `404`. |
| `GET` | `/entities/{entity_id}/records` | Return all titles and bodies for one entity, or `404`. |
| `GET` | `/records` | List records with entity, date, and pagination filters. |
| `GET` | `/records/{record_id}` | Return one record with body and assets, or `404`. |

### Record List Query Parameters

| Field | Required | Default | Description |
| ----- | -------- | ------- | ----------- |
| `entity_id` | No | - | Filter by entity ID. |
| `from` | No | - | Inclusive publication date lower bound. |
| `to` | No | - | Inclusive publication date upper bound. |
| `limit` | No | `20` | Page size from `1` to `100`. |
| `offset` | No | `0` | Number of records to skip; must be non-negative. |

### Entity Record Query

`GET /entities/{entity_id}/records` returns all records for one entity with
their `id`, `title`, and `body`. The response is not paginated; use the
general `/records` endpoint when bounded pages are required.

Responses use JSON and UTC ISO 8601 timestamps. Invalid parameters return `422` with `code=VALIDATION_ERROR`; invalid date ranges return `400`; missing resources return `404` with `code=NOT_FOUND`.

<p align="right">(<a href="#top">back to top</a>)</p>

## Available Commands

| Command | Description |
| ------- | ----------- |
| `uv sync --all-groups` | Install the locked development environment. |
| `uv run uvicorn app.main:app --reload --port 8080` | Start the development API. |
| `uv run alembic upgrade head` | Apply database migrations. |
| `uv run python -m app.collector collect-backfill` | Run manual historical collection. |
| `uv run python -m app.collector collect-daily` | Run incremental collection. |
| `uv run pytest -m small` | Run small tests. |
| `uv run pytest -m "small or medium"` | Run small and medium tests. |
| `uv run pytest acceptance tests --cov=app --cov-report=term-missing -q` | Run the full local test and coverage command. |
| `uv run ruff format --check .` | Check formatting. |
| `uv run ruff check .` | Run Ruff lint checks. |
| `uv run mypy app tests` | Run strict type checks. |
| `docker compose --env-file .env.development config --quiet` | Validate Compose configuration. |
| `docker build --tag slope-collector:local .` | Build the application image. |

<p align="right">(<a href="#top">back to top</a>)</p>

## Troubleshooting

### `uv: The term 'uv' is not recognized`

The uv executable is not installed or is not available on the PowerShell `PATH`. Install uv 0.12.15, reopen PowerShell so the PATH is refreshed, and confirm with `uv --version` before running the commands above.

### `DATABASE_URL` validation fails

The application requires a MySQL URL using the `mysql+pymysql` driver. Check the untracked `.env` or `.env.development` file and ensure the database is reachable before running migrations or collection.

<p align="right">(<a href="#top">back to top</a>)</p>

## License

This project is licensed under the MIT License. See `LICENSE` for the full text.

<p align="right">(<a href="#top">back to top</a>)</p>
