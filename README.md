# Personal Morning Paper

Personal Morning Paper is an AI-powered personalized digital newspaper. It will
eventually combine a user's interests with RSS news sources, article
deduplication, clustering, reliability scoring, personalized ranking, and
AI-generated newspaper editions.

The learning loop is the primary engineering focus: article clicks and reader
feedback will improve future recommendations over time.

## Current foundation

This initial project foundation contains:

- A minimal FastAPI application.
- Root and health-check endpoints.
- A smoke test for the health-check endpoint.
- A lightweight package layout ready for later application layers.

Application features such as authentication, database tables, RSS ingestion,
AI calls, frontend pages, and PDF generation are intentionally not implemented
yet.

## Planned architecture

- `app/core/` - configuration and cross-cutting application concerns.
- `app/api/` - HTTP routes and API dependencies.
- `app/models/` - database models.
- `app/schemas/` - request and response schemas.
- `app/services/` - application and learning-loop logic.
- `app/repositories/` - persistence access.
- `tests/` - automated tests.
- `scripts/` - development and maintenance scripts.
- `docs/` - project documentation.

SQLite will be the initial database, and the project will target free-tier
compatible infrastructure.

## Requirements

- Python 3.12 or newer in the supported FastAPI range.
- `pip`.

## Local setup

From the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `py` is unavailable, use the installed Python 3.12 executable directly:

```powershell
python -m venv .venv
```

Copy `.env.example` to `.env` when local environment configuration is needed.
The example file contains placeholders only; never commit real secrets.

## Run the application

```powershell
python -m uvicorn app.main:app --reload
```

The application is then available at <http://127.0.0.1:8000>.

- Root endpoint: <http://127.0.0.1:8000/>
- Health check: <http://127.0.0.1:8000/health>
- OpenAPI docs: <http://127.0.0.1:8000/docs>

## Run tests

```powershell
python -m pytest
```
