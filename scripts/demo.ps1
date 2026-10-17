$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"
& $python -m app.cli seed-demo
& $python -m app.cli export-demo
$env:DEMO_MODE = "true"
$env:DATABASE_URL = ".\out\demo\sim.db"
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
