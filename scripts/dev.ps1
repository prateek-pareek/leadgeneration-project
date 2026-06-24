# =============================================================
# ProspectOS — Local Development Startup (Windows)
# Usage: .\scripts\dev.ps1
#        .\scripts\dev.ps1 -Service api      # start one service
#        .\scripts\dev.ps1 -Stop             # stop everything
#        .\scripts\dev.ps1 -Logs api         # tail logs
# =============================================================

param(
  [string]$Service = "",
  [switch]$Stop,
  [string]$Logs = "",
  [switch]$Reset
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = "$ProjectRoot\infra\docker-compose.yml"
$EnvFile     = "$ProjectRoot\.env"

function Write-Step  { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[OK]  $msg" -ForegroundColor Green }
function Write-Info  { param($msg) Write-Host "[INF] $msg" -ForegroundColor Blue }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "[ERR] $msg" -ForegroundColor Red; exit 1 }

# ── .env check ───────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
  Write-Warn ".env not found — copying from .env.example"
  Copy-Item "$ProjectRoot\.env.example" $EnvFile
  Write-Warn "Please edit $EnvFile and add your GOOGLE_API_KEY, then re-run."
  exit 1
}
if (Select-String -Path $EnvFile -Pattern "your-google-api-key-here" -Quiet) {
  Write-Fail "GOOGLE_API_KEY not set in .env. Add it before starting."
}

# ── Stop ─────────────────────────────────────────────────────
if ($Stop) {
  Write-Step "Stopping all ProspectOS services"
  docker compose -f $ComposeFile down
  Write-Ok "All services stopped"
  exit 0
}

# ── Logs ─────────────────────────────────────────────────────
if ($Logs -ne "") {
  docker compose -f $ComposeFile logs -f $Logs
  exit 0
}

# ── Reset (nuclear option) ────────────────────────────────────
if ($Reset) {
  Write-Warn "This will DELETE all containers AND volumes (including the database)."
  $confirm = Read-Host "Type 'yes' to confirm"
  if ($confirm -ne "yes") { Write-Info "Cancelled."; exit 0 }
  docker compose -f $ComposeFile down -v --remove-orphans
  Write-Ok "Reset complete — all data wiped"
  exit 0
}

# ── Prereq checks ────────────────────────────────────────────
Write-Step "Checking prerequisites"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Fail "Docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
}

$dockerRunning = docker info 2>$null
if (-not $dockerRunning) {
  Write-Fail "Docker is not running. Please start Docker Desktop."
}

Write-Ok "Docker is running"

# ── Start specific service ────────────────────────────────────
if ($Service -ne "") {
  Write-Step "Starting service: $Service"
  docker compose -f $ComposeFile up -d $Service
  Write-Ok "$Service started"
  docker compose -f $ComposeFile logs -f $Service
  exit 0
}

# ── Full dev start ────────────────────────────────────────────
Write-Step "Starting ProspectOS (dev mode)"
Write-Info "Services: postgres, redis, litellm, meilisearch, api, worker, web, nginx"

# Start infrastructure first
Write-Step "Starting infrastructure (postgres + redis + litellm + meilisearch)"
docker compose -f $ComposeFile up -d postgres redis litellm meilisearch
Write-Info "Waiting for PostgreSQL..."
$ready = $false
for ($i = 1; $i -le 20; $i++) {
  $pg = docker compose -f $ComposeFile exec -T postgres pg_isready -U prospectOS 2>$null
  if ($LASTEXITCODE -eq 0) { $ready = $true; break }
  Write-Info "  Waiting ($i/20)..."
  Start-Sleep 2
}
if (-not $ready) { Write-Warn "PostgreSQL slow to start — continuing anyway" }
else { Write-Ok "PostgreSQL ready" }

# Build and start app services
Write-Step "Building and starting app services (api + worker + web)"
docker compose -f $ComposeFile up -d --build api worker web

# Start nginx
docker compose -f $ComposeFile up -d nginx

# Wait for API
Write-Step "Waiting for API to be healthy"
for ($i = 1; $i -le 30; $i++) {
  try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { Write-Ok "API is healthy"; break }
  } catch {}
  if ($i -eq 30) { Write-Warn "API health check timed out" }
  else { Write-Info "  Waiting for API ($i/30)..."; Start-Sleep 2 }
}

# ── Done ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "=====================================" -ForegroundColor Green
Write-Host "  ProspectOS is running!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Green
Write-Host ""
Write-Host "  App:       http://localhost:3000" -ForegroundColor Cyan
Write-Host "  API:       http://localhost:8080/api/v1/health" -ForegroundColor Cyan
Write-Host "  LiteLLM:   http://localhost:4000" -ForegroundColor Cyan
Write-Host "  Meilisearch: http://localhost:7700" -ForegroundColor Cyan
Write-Host ""
Write-Host "Commands:" -ForegroundColor Yellow
Write-Host "  Logs:    .\scripts\dev.ps1 -Logs api"
Write-Host "  Stop:    .\scripts\dev.ps1 -Stop"
Write-Host "  Reset:   .\scripts\dev.ps1 -Reset"
Write-Host ""
Write-Host "Tailing all logs (Ctrl+C to stop)..." -ForegroundColor Gray
docker compose -f $ComposeFile logs -f --tail=50
