# Ops script: common day-to-day commands in one place.
# (Kept ASCII-only on purpose: Windows PowerShell 5.1 misreads UTF-8 Chinese in .ps1)
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\ops.ps1 <command> [args]
#
# Commands:
#   api                      Start API server (with reload, for dev)
#   worker                   Start background worker (parses & ingests uploads)
#   migrate                  Upgrade DB schema to latest
#   makemigration "<msg>"    Generate a migration script
#   ingest <folder> [type]   Batch-ingest a folder of docs (type default: tongyong)
#   health                   Check API + DB
#   help                     Show this help

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"   # so Python prints Chinese without garbling

$cmd = $args[0]
switch ($cmd) {
    "api" {
        Write-Host "API: http://127.0.0.1:8000/docs"
        uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    }
    "worker" {
        Write-Host "Worker started (Ctrl+C to stop)"
        uv run procrastinate --app=app.workers.queue.app worker
    }
    "migrate" {
        uv run alembic upgrade head
    }
    "makemigration" {
        $msg = $args[1]
        if (-not $msg) { Write-Host 'Usage: ops.ps1 makemigration "message"'; break }
        uv run alembic revision --autogenerate -m $msg
        Write-Host "Generated. Review alembic/versions/ then run: ops.ps1 migrate"
    }
    "ingest" {
        $folder = $args[1]
        if (-not $folder) { Write-Host "Usage: ops.ps1 ingest <folder> [doc-type]"; break }
        Write-Host "Ingesting: $folder"
        # No doc-type given -> let batch_ingest.py use its own default
        if ($args[2]) {
            uv run python scripts/batch_ingest.py $folder --doc-type $args[2]
        } else {
            uv run python scripts/batch_ingest.py $folder
        }
    }
    "health" {
        Write-Host "=== API ==="
        try { (Invoke-WebRequest "http://127.0.0.1:8000/api/v1/health" -UseBasicParsing).Content }
        catch { "API not running? try: ops.ps1 api" }
        Write-Host "`n=== DB ==="
        try { (Invoke-WebRequest "http://127.0.0.1:8000/api/v1/health/db" -UseBasicParsing).Content }
        catch { "DB unreachable, check .env / PG" }
    }
    default {
        Write-Host "ops.ps1 commands: api | worker | migrate | makemigration | ingest | health"
        Write-Host "  api                     start API (dev, reload)"
        Write-Host "  worker                  start background worker"
        Write-Host "  migrate                 upgrade DB to latest"
        Write-Host '  makemigration "msg"     generate a migration'
        Write-Host "  ingest <folder> [type]  batch ingest docs"
        Write-Host "  health                  check API + DB"
        Write-Host "Note: uploading new docs needs api + worker both running (or use ingest, no worker needed)."
    }
}
