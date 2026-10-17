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
python -m pytest tests/test_recommendation.py -m slow
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

It prints only the answering provider, model, latency, and attempt count.

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
