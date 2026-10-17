$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDirectory = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDirectory "daily-ingest-$timestamp.log"
$lockPath = Join-Path $root "data\daily-ingest.lock"

$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-Error "Another daily ingestion run is already in progress."
    exit 2
}

try {
    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        throw "Project virtual environment not found at $python"
    }
    $env:PYTHONPATH = $root

    & $python scripts\sync_sources.py 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) { throw "Source sync failed with exit code $LASTEXITCODE" }
    & $python scripts\run_ingestion.py --no-snapshot 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Ingestion failed with exit code $LASTEXITCODE" }
    & $python scripts\embed_articles.py 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Embedding backfill failed with exit code $LASTEXITCODE" }
    & $python scripts\create_snapshot.py 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Archive snapshot failed with exit code $LASTEXITCODE" }
    Add-Content -Path $logPath -Value "Daily ingestion completed at $(Get-Date -Format o)"
} catch {
    Add-Content -Path $logPath -Value "Daily ingestion failed: $($_.Exception.Message)"
    Write-Error "Daily ingestion failed. See $logPath"
    exit 1
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
    if (Test-Path $lockPath) {
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}
