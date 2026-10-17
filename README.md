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

### Daily ingestion on Windows

The repository includes [`scripts/daily_ingest.ps1`](scripts/daily_ingest.ps1).
It synchronizes the enabled source registry, ingests feeds, runs embedding
backfill (including topic assignment and clustering), and creates the daily
archive snapshot. Each run writes a timestamped log under `data/logs/`.
That directory and the lock file are ignored by Git. A same-day rerun reuses
the existing calendar-day snapshot instead of creating a duplicate.

Run it manually from the repository root:

```powershell
Set-Location C:\path\to\personal-morning-paper
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\daily_ingest.ps1
```

The script uses `.venv\Scripts\python.exe`, exits non-zero on failure, and
holds an exclusive lock so overlapping runs are rejected.

To schedule it twice daily in Windows Task Scheduler, review and run these
commands as your own logged-in user. They do not run when you are logged off:

```powershell
schtasks /Create /TN "Personal Morning Paper - Daily Ingest 08" /TR "PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File C:\path\to\personal-morning-paper\scripts\daily_ingest.ps1" /SC DAILY /ST 08:00 /RU "$env:USERNAME" /RP * /F
schtasks /Create /TN "Personal Morning Paper - Daily Ingest 20" /TR "PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File C:\path\to\personal-morning-paper\scripts\daily_ingest.ps1" /SC DAILY /ST 20:00 /RU "$env:USERNAME" /RP * /F
```

Replace `C:\path\to\personal-morning-paper` with the absolute project path.

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

## Profiles and recommendations

Profiles are stored separately from global article data. A user has topic
weights, source weights, muted topics, and an edition-read count. Onboarding
weights are represented as selected topic `3`, selected sub-interest `2`,
user-entered tag `2`, and unselected topics `0`. Preferences can be changed
through the API without changing the schema.

The local recommendation service uses deterministic hashed word vectors rather
than a downloaded model. This keeps tests offline and installation lightweight;
it is an extensible baseline, not a replacement for a future higher-quality
embedding model. Article vectors and up to two deterministic topic assignments
are cached in SQLite. Topic assignment uses configurable keyword descriptions
and a confidence threshold.

For each eligible article, the default score is:

```text
T = tanh(topic_weight / 4)
E = 0.6 * cosine(U_long, article_embedding) + 0.4 * cosine(U_short, article_embedding)
S = clamp(tanh(source_weight / 4), -0.3, 0.3)
C = min(1, log2(cluster_size) / 3)
F = exp(-age_hours / 18)
score = (0.40*T + 0.35*E + 0.10*S + 0.15*C) * F * (0.5 + 0.5*reliability)
```

Missing vectors and weights safely contribute zero. Scores expose all
components for debugging. Before scoring, recommendations exclude articles
older than 48 hours, sources below reliability `0.3`, articles in the user's
last seven editions, muted topics, and invalid publication records.

Selection returns up to two must-know stories, a deterministic exploration
slice using `epsilon = max(0.15, 0.40 - 0.05 * editions_read)`, and regular
MMR-ranked stories. MMR subtracts `0.3 * max_similarity` from relevance, and a
40% topic cap is applied when the candidate pool allows it. Exploration is a
deterministic fallback until real click/view events exist; Thompson sampling is
intentionally deferred to the learning-loop phase.

Create a demo profile and preview recommendations:

```powershell
$user = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/users `
  -ContentType 'application/json' `
  -Body '{"name":"Demo Reader","selected_topics":["technology_ai"],"selected_sub_interests":["science_research"],"interest_tags":["robotics"]}'
$userId = $user.user_id
Invoke-RestMethod http://127.0.0.1:8000/api/users/$userId/preferences
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/users/$userId/recommendations/preview?edition_size=10"
Invoke-RestMethod http://127.0.0.1:8000/api/users/$userId/recommendations
```

Recommendation endpoints:

- `GET /api/topics` lists topic names and descriptions.
- `POST /api/users` creates a profile with onboarding preferences.
- `GET /api/users/{user_id}/preferences` reads preferences.
- `PUT /api/users/{user_id}/preferences` updates weights and muted topics.
- `POST /api/users/{user_id}/recommendations/preview` generates and persists an
  explainable edition.
- `GET /api/users/{user_id}/recommendations` retrieves the latest persisted
  edition.

The schema is initialized safely on application access using `CREATE TABLE IF
NOT EXISTS`; it does not delete existing article data. Future migrations can
replace this initializer if schema evolution becomes more complex.

## Embedding backends and enrichment

The `Embedder` interface in
[`app/services/embeddings.py`](app/services/embeddings.py) supports:

- `sentence_transformer` (the normal-run default): lazy
  `all-MiniLM-L6-v2` local semantic embeddings, normalized and encoded in CPU
  batches. The first use downloads approximately 80 MB of model weights. The
  Hugging Face cache is outside the repository (normally
  `%USERPROFILE%\.cache\huggingface`) and is not committed.
- `hashed`: deterministic, lightweight offline vectors used by the test suite
  and as an explicit fallback. They are not semantic model embeddings.

Install the real backend with the project requirements:

```powershell
python -m pip install -r requirements.txt
$env:EMBEDDING_BACKEND = "sentence_transformer"
$env:EMBEDDING_ALLOW_FALLBACK = "false"
python scripts/embed_articles.py
```

`sentence-transformers` installs the PyTorch stack and is substantially
heavier than the base project. If model download or dependency installation is
not practical, use the explicit offline backend:

```powershell
$env:EMBEDDING_BACKEND = "hashed"
python scripts/embed_articles.py
```

`EMBEDDING_ALLOW_FALLBACK=true` opts into a visible warning and hashed fallback
when the sentence-transformer backend cannot load. There is no silent fallback.
Every stored article and user vector records its embedder name and dimension;
vectors from different backends cannot be compared. Use `--reembed` when
switching backends:

```powershell
python scripts/embed_articles.py --reembed
```

Embedding and clustering are enrichment operations, not recommendation request
work. The command stores article vectors, deterministic topic assignments, and
36-hour-window story clusters. Cluster size is the number of distinct source
outlets in a cluster. Topic and cluster thresholds are configurable separately:
the initial hashed baselines are `0.12` and `0.45`; the initial
sentence-transformer values are `0.45` and `0.72`. These were chosen from
small reviewable examples covering exact topical headlines, semantically
related wording, and unrelated sports/world headlines; they are starting
calibration values and should be rechecked against production feeds.

The slow semantic integration test is skipped by default because it downloads
model weights. Run it explicitly after installation with:

```powershell
python -m pytest -m slow tests/test_recommendation.py

The real-model test is registered as `slow` and excluded from the default
suite by `pytest.ini`; run it explicitly with the command above.

For the current `all-MiniLM-L6-v2` calibration, semantic topic assignment
uses `REAL_TOPIC_MATCH_THRESHOLD=0.10` and permits a second topic only when it
is within `TOPIC_SECONDARY_MARGIN=0.04` of the best score. These values are
per-embedder settings and should be recalibrated when the model changes.
```

## LLM client layer

The single LLM entry point is
[`app/services/llm.py`](app/services/llm.py). Later features should call
`LLMClient.generate_structured(...)`; they should not call a provider directly.
The client wraps untrusted article text in delimited blocks, sends a guardrail
system instruction, requests JSON/schema output where supported, and validates
the response with Pydantic before returning it.

Configured provider order defaults to:

```text
gemini,groq,openrouter,ollama
```

The implementation uses `httpx` only:

- Gemini uses its native `generateContent` REST endpoint and JSON response
  schema.
- Groq and OpenRouter use their OpenAI-compatible `/chat/completions`
  endpoints.
- Ollama uses its local `/api/chat` endpoint and `format` JSON schema.

The current documented model defaults are configurable and not hard-coded into
the service logic:

- Gemini: `gemini-2.5-flash` (Google AI Studio structured-output capable).
- Groq: `llama-3.1-8b-instant` (Groq hosted low-latency model).
- OpenRouter: `meta-llama/llama-3.3-8b-instruct:free` (free-model suffix).
- Ollama: `llama3.2` (local model; install it with `ollama pull llama3.2`).

Provider free tiers, model availability, quotas, and data-retention policies
change. Check the current provider dashboard and official documentation before
using a key. Create keys through Google AI Studio, the Groq console, and
OpenRouter's account settings; Ollama does not require an API key when running
locally. Review each provider's data policy before sending article text. The
client never sends user names, email addresses, or user IDs.

Copy the placeholders from `.env.example` into a local `.env` or configure
PowerShell environment variables:

```powershell
$env:LLM_PROVIDER_ORDER = "gemini,groq,openrouter,ollama"
$env:GEMINI_API_KEY = "<Google AI Studio key>"
$env:GROQ_API_KEY = "<Groq key>"
$env:OPENROUTER_API_KEY = "<OpenRouter key>"
$env:GEMINI_MODEL = "gemini-2.5-flash"
$env:GROQ_MODEL = "llama-3.1-8b-instant"
$env:OPENROUTER_MODEL = "meta-llama/llama-3.3-8b-instruct:free"
$env:OLLAMA_MODEL = "llama3.2"
```

Providers without a key are skipped, except local Ollama. Timeout, retry,
global concurrency, and per-provider minimum interval settings are available
through `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`,
`LLM_CONCURRENCY_LIMIT`, and `LLM_MIN_PROVIDER_INTERVAL`. Timeouts, 429s, and
5xx responses retry with backoff and jitter before the client moves to the
next provider. A validation failure gets one repair attempt before fallback.
If every configured provider fails, the client raises `LLMUnavailable`; it
never fabricates output.

The supported schemas are defined in
[`app/models/llm.py`](app/models/llm.py): `ArticleSummary`, `EditorOutput`,
`InterestSummary`, and `OnboardingTags`. They enforce length limits, topic
enums, no HTML/URLs in text, and supplied-ID constraints.

Calls are recorded in the SQLite `llm_calls` table with provider, model,
purpose, success, error type, latency, input size, and UTC date. Identical
requests use the local `llm_cache` table. The daily call summary is available
through `Database.llm_calls_per_day()` for a future budget display.

Run the diagnostic command without printing secrets or generated content:

```powershell
python -m app.cli llm-check
```

Use `--provider gemini`, `--provider groq`, `--provider openrouter`, or
`--provider ollama` to diagnose one provider. The command prints only whether
a key is configured, the model, HTTP status, and a short redacted error.

## Edition generation

Edition generation turns one recommendation selection into a persisted
newspaper. `EditionService` first runs the existing must-know, exploration,
and regular selection, then summarizes only selected articles whose `summary`
column is empty. Summaries are cached on the article by canonical URL through
the article row: LLM summaries record `summary_source=llm` plus provider and
model metadata, while the deterministic fallback stores sanitized RSS
sentences with `summary_source=snippet`.

The editor receives only the selected article IDs, headlines, summaries,
scores, selection flags, and code-generated reason codes. Its output is
validated so every selected story appears exactly once and the lead is among
the five highest-scoring stories. Invalid or unavailable LLM output uses the
code layout: the highest-score story is the lead, sections are topic groups
ordered by total score, and original headlines and reason text are retained.
The saved edition includes `layout_source` (`llm` or `code`), provider/model
metadata, stage timings, score components, reason codes, and reading
positions starting at 1.

Generate an edition without any network or API key:

```powershell
python -m app.cli generate-edition --user-id <USER_ID> --no-llm
```

With configured providers, omit `--no-llm`. Use `--date YYYY-MM-DD` and
`--force` to regenerate an existing date. The HTTP API equivalents are:

```text
POST /api/users/{user_id}/editions/generate?use_llm=false
GET  /api/users/{user_id}/editions
GET  /api/users/{user_id}/editions/{YYYY-MM-DD}
```

`generate-all` iterates over every stored user and supports `--no-llm` and
`--force`. Edition generation is idempotent for a user/date unless forced.

## Onboarding and identity

The local web UI uses Jinja2 templates, vanilla JavaScript, and local static
assets only; there is no frontend build step or CDN dependency. Open `/` to
walk through:

1. Welcome
2. Topic and sub-interest selection
3. Specific-interest tags, generated with `OnboardingTags` or a deterministic
   lowercase stop-word fallback
4. Reading preferences: depth, 10-20 stories, surprise level, timezone,
   delivery time, and optional display name

Headline reactions are intentionally left as a marked future extension point.
Completing onboarding creates the user, stores the initial weighted baseline
(topic 3, sub-interest 2, tag 2), initializes long/short vectors with the
configured embedder, maps surprise to exploration floors (low `0.10`, medium
`0.15`, high `0.25`), and starts the first edition in the background.

The browser receives a signed, HttpOnly, SameSite=Lax session cookie containing
only the user identity. `GET /api/me` resolves the current reader. In
development a local fallback session secret is used; set `SESSION_SECRET` and
use `ENVIRONMENT=production` so startup fails if a secret is missing outside
development. This identity model has no passwords or account recovery and is
intended for the local/demo phase.

The preparing page polls
`GET /api/users/{user_id}/editions/{YYYY-MM-DD}/status` and displays queued,
running stage names, ready, or failed with a retry path. Profile settings are
stored in `user_settings` and the recommendation engine applies each user's
edition size and exploration floor.

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
### PDF editions

Each saved edition can be downloaded from `/edition/YYYY-MM-DD/pdf` or the
**Download PDF** button. PDFs are stored in `data/pdfs/<user>/<date>.pdf`
(and are ignored by Git). Rendering uses WeasyPrint by default:

```text
PDF_RENDERER=auto       # auto, weasyprint, or playwright
PUBLIC_BASE_URL=http://localhost:8000
```

`auto` selects WeasyPrint when it imports and falls back to Playwright if a
WeasyPrint runtime error occurs. Playwright is optional; install it with
`pip install playwright` followed by `playwright install chromium` (the
Chromium download is roughly 150 MB and varies by release). PDF links use
the public base URL and only record clicks while the application is reachable.

On Windows, WeasyPrint may need the GTK3 runtime. In PowerShell, download
`https://github.com/nickvidal/winlibs/blob/master/gtk3-runtime.zip`, extract
it, and add its `bin` directory to the current user's PATH, then restart
PowerShell and retry. On Ubuntu/Debian:

```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libcairo2
```

On macOS:

```bash
brew install pango libffi
```

### Reader events and privacy

The reader UI records raw interaction facts through `POST /api/events`:
`impression_seen` means a story was visible for about one second,
`expand_summary` means its explanation was opened, `save`, `like`, `dislike`,
and `less_topic` are explicit reader actions, `return` records seconds away
after following an article, and `pdf_download` records a PDF download.
Outbound article clicks are recorded asynchronously by `/out/{token}`.

Events store the session user, optional article and edition, position, source,
raw value, small JSON extras, and timestamp. They are not converted into
profile signals in this phase. Events can be deleted directly from the
`events` table by user and are retained in the local SQLite database until
that deletion or database cleanup. Bot, prefetch, and repeated clicks inside
the configured deduplication window are ignored.
## Profile and interest summary

Open `/profile` while signed in to review the topics and sources currently shaping
your paper. The interest summary uses topic weights, recent clicked and disliked
headlines, and onboarding tags. It is sent to the configured LLM without your
name, email, user ID, or other identifiers; if no provider is available, a local
template is used.

```powershell
.venv\Scripts\python.exe -m app.cli generate-summary --user-id USER_ID
```

The profile page supports editing or regenerating the summary, resetting learned
preferences to the onboarding baseline, and deleting account data. Deletion
removes the user and its cascaded editions, events, tokens, and profile records.

## Scheduler and jobs

Install dependencies, then run the long-lived scheduler from the repository root:

```powershell
.venv\Scripts\python.exe -m app.cli scheduler
```

On Linux or macOS, use `.venv/bin/python -m app.cli scheduler`. The scheduler
ingests and enriches the article pool every three hours by default, processes
pending events before due reader editions, refreshes summaries weekly, and
creates the nightly archive snapshot. Configure `SCHEDULER_INTERVAL_HOURS` and
`SCHEDULER_LEAD_MINUTES` (default 60) in `.env`. Free hosts may sleep, so
startup catch-up and first-visit generation recover missed editions.

Useful one-shot commands:

```powershell
.venv\Scripts\python.exe -m app.cli generate-all --date 2026-10-17 --no-llm
.venv\Scripts\python.exe -m app.cli status
```

Each run is recorded in the `job_runs` table with its key, status, timestamps,
error, and JSON statistics. Jobs coalesce missed intervals, allow one instance
at a time, and isolate reader failures. The development-only `/api/admin/jobs`
endpoint requires the configured `ADMIN_TOKEN`.

## Demo mode

Demo routes are available only when `DEMO_MODE=true`. Build the isolated demo
database and local SVG/CSV exports with:

```powershell
.venv\Scripts\python.exe -m app.cli seed-demo
.venv\Scripts\python.exe -m app.cli export-demo
$env:DEMO_MODE="true"; $env:DATABASE_URL="out\demo\sim.db"
.venv\Scripts\python.exe -m uvicorn app.main:app
```

Then open `/demo/charts`, `/demo/stats`, or `/demo/login/featured`.
`scripts/demo.ps1` and `scripts/demo.sh` automate the setup and server start.
The demo uses server-rendered SVG charts and simulated data only; generated
files are under ignored `out/demo/`. `scripts/capture_screens.py` optionally
captures the chart and stats pages at 1920x1080 when Playwright is installed.
