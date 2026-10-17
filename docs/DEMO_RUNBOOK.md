# Demo recording runbook

The demo uses only the isolated SQLite database at `out/demo/sim.db`. It does
not modify the development database. Demo routes return `404` unless
`DEMO_MODE=true`.

## Pre-flight

1. Install the project requirements and, optionally, Playwright.
2. Confirm that the source database contains the article pool and archived
   snapshots. The simulator uses cycle mode when fewer than 14 archive days are
   available.
3. Confirm that no live API keys are required for the recording. The default
   code-layout simulation is offline; only an explicitly requested live LLM
   onboarding scene needs keys.
4. Remove `out/demo` if a completely fresh recording is required.

## Build and start

PowerShell:

```powershell
.\scripts\demo.ps1
```

Linux/macOS:

```bash
./scripts/demo.sh
```

The commands seed the demo, export CSV/SVG files, enable demo mode, and start
Uvicorn on `http://127.0.0.1:8000`.

## Recording checklist

1. Open `/`, then sign in as a demo persona at
   `/demo/login/featured`, `/demo/login/health_science`, or
   `/demo/login/markets_world`.
2. Capture an edition, the archive, and the profile.
3. Capture the charts and statistics pages:
   `/demo/charts` and `/demo/stats`.
4. Capture a preparation/progress state when generating an uncached edition.
5. Run `scripts/capture_screens.py` for 1920x1080 screenshots when Playwright
   is installed.

Generated screenshots are written to `out/demo/screens/`. CSV and SVG exports
are written to `out/demo/`.

## Expected outputs

- `out/demo/sim.db`: isolated demo database.
- `out/demo/summary.json`: deterministic simulation summary.
- `out/demo/learning.csv`: learning snapshots for all personas and days.
- `out/demo/*.svg`: exported metric charts.
- `out/demo/pdfs/`: key-day PDF editions when a local PDF renderer is
  available.

To reproduce the default demo numbers, use seed `42`, all three personas, 14
days, and cycle mode. The simulation prints the number of LLM calls used and
does not perform network requests in its default configuration.
