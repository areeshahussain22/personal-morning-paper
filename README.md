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
- A configurable RSS ingestion pipeline backed by SQLite.
- A shared article pool with canonical URL deduplication and 48-hour eligibility.
- Database-backed daily snapshots for later edition replay.

Authentication, recommendations, AI calls, frontend pages, and PDF generation
are intentionally not implemented yet.

## Planned architecture

- `app/core/` - configuration and cross-cutting application concerns.
- `app/api/` - HTTP routes and API dependencies.
- `app/models/` - article representations.
- `app/schemas/` - request and response schemas.
- `app/services/` - source registry, RSS ingestion, and archive logic.
- `app/repositories/` - SQLite persistence.
- `tests/` - automated tests.
- `scripts/` - development and maintenance scripts.
- `docs/` - project documentation.

SQLite is used for the initial shared article pool, and the project targets
free-tier compatible infrastructure.

## Requirements

- Python 3.11 or newer in the supported FastAPI range.
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

## RSS ingestion

The source registry is in
[`app/services/source_registry.py`](app/services/source_registry.py). Each
source has an ID, display name, feed URL, topic, starting reliability estimate,
paywall indicator, and enabled flag. Reliability is metadata for future
ranking, not an objective credibility claim. Add or disable sources there
without changing ingestion logic.

The service fetches enabled feeds concurrently with bounded concurrency,
timeouts, and limited exponential-backoff retries. It parses RSS/Atom metadata
only; it does not scrape article pages or execute feed content. Titles and URLs
are required. URLs are canonicalized by removing common tracking parameters
while preserving meaningful query parameters.

Articles with a missing or invalid publication date are archived but excluded
from the eligible article pool until their date can be validated. Eligible
articles have a UTC publication timestamp between now and the configurable
`FRESHNESS_HOURS` cutoff (48 hours by default). Future timestamps beyond a
small clock-skew allowance are logged as suspicious and excluded by the same
eligibility query.

The default database is `data/personal_morning_paper.db`. The `data/` directory
and database files are ignored by Git. Daily snapshots are stored in the
`archive_snapshots` SQLite table as one JSON payload containing the article
metadata needed for replay; snapshots are not committed to Git.

Run ingestion and create a snapshot from PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\run_ingestion.py
```

The API can run ingestion and inspect the pool:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/ingestion/run
Invoke-RestMethod http://127.0.0.1:8000/api/ingestion/articles?limit=20
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/ingestion/snapshots
```

Platform-independent Python equivalents:

```python
import httpx

httpx.post("http://127.0.0.1:8000/api/ingestion/run")
httpx.get("http://127.0.0.1:8000/api/ingestion/articles", params={"limit": 20})
```

Endpoints:

- `POST /api/ingestion/run` fetches enabled feeds and returns feed, parse,
  rejection, persistence, and duration counts. It returns `502` if every feed
  fails.
- `GET /api/ingestion/articles?limit=50&offset=0` returns recent eligible
  articles, capped at 100 per request.
- `POST /api/ingestion/snapshots` archives the current eligible pool.
- `GET /api/ingestion/snapshots/{snapshot_id}` replays a stored snapshot.

Known limitations: feed availability and publisher schemas can change, the
initial registry contains starting reliability estimates, and no full article
text is fetched. Live websites are not used by the automated tests.

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
