#!/bin/bash
# =============================================================
# ProspectOS — Deploy / Update Script
# Run on your VPS whenever you push new code
# Usage: bash scripts/deploy.sh [--no-build] [--rollback]
# =============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()    { echo -e "\n${BOLD}==> $1${NC}"; }

APP_DIR="${APP_DIR:-/opt/prospectOS}"
COMPOSE="docker compose -f $APP_DIR/infra/docker-compose.yml"
NO_BUILD=false
ROLLBACK=false

for arg in "$@"; do
  case $arg in
    --no-build) NO_BUILD=true ;;
    --rollback) ROLLBACK=true ;;
  esac
done

cd "$APP_DIR"

# ── Rollback mode ─────────────────────────────────────────────
if [ "$ROLLBACK" = true ]; then
  step "Rolling back to previous version"
  PREV=$(git log --oneline -2 | tail -1 | awk '{print $1}')
  if [ -z "$PREV" ]; then
    error "No previous commit to roll back to"
  fi
  warn "Rolling back to: $(git log --oneline -2 | tail -1)"
  git checkout "$PREV"
  $COMPOSE up -d --build api worker web
  success "Rolled back"
  exit 0
fi

# ── Pre-deploy checks ─────────────────────────────────────────
step "Pre-deploy checks"

if [ ! -f "$APP_DIR/.env" ]; then
  error ".env file missing. Copy .env.example and fill in secrets."
fi

# Verify API key is set
if grep -q "your-google-api-key-here" "$APP_DIR/.env"; then
  error "GOOGLE_API_KEY not set in .env. Please add it before deploying."
fi

success "Pre-deploy checks passed"

# ── Pull latest code ─────────────────────────────────────────
step "Pulling latest code"
CURRENT_SHA=$(git rev-parse HEAD)
git fetch origin
git pull origin "$(git rev-parse --abbrev-ref HEAD)"
NEW_SHA=$(git rev-parse HEAD)

if [ "$CURRENT_SHA" = "$NEW_SHA" ]; then
  warn "No new commits. Re-deploying current version."
fi

success "Code: $(git log --oneline -1)"

# ── Build images ─────────────────────────────────────────────
if [ "$NO_BUILD" = false ]; then
  step "Building Docker images"
  $COMPOSE build --parallel api worker web
  success "Images built"
fi

# ── DB migrations ─────────────────────────────────────────────
step "Running database migrations"
# Migrations run automatically on API start (golang-migrate)
# If you want to run them manually:
# $COMPOSE run --rm api /app/server migrate-only
info "Migrations run automatically on API startup"

# ── Rolling restart ───────────────────────────────────────────
step "Restarting services (zero-downtime rolling restart)"

# Restart infra services only if compose files changed
if git diff "$CURRENT_SHA" HEAD -- infra/docker-compose.yml | grep -q postgres; then
  warn "docker-compose.yml changed, restarting all services"
  $COMPOSE up -d
else
  # Restart app services one at a time
  info "Restarting API..."
  $COMPOSE up -d --no-deps api
  sleep 3

  info "Restarting worker..."
  $COMPOSE up -d --no-deps worker

  info "Restarting web..."
  $COMPOSE up -d --no-deps web
fi

success "Services restarted"

# ── Health check ─────────────────────────────────────────────
step "Health check"
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/health" || echo "000")
  if [ "$STATUS" = "200" ]; then
    success "API is healthy (status 200)"
    break
  fi
  if [ "$i" = "$MAX_WAIT" ]; then
    warn "API health check timed out (status: $STATUS)"
    echo ""
    info "Last 50 API log lines:"
    $COMPOSE logs --tail=50 api
  fi
  echo "  Waiting for API... ($i/$MAX_WAIT)"
  sleep 2
done

# ── Prune old images ─────────────────────────────────────────
step "Cleaning up old Docker images"
docker image prune -f --filter "until=48h" > /dev/null 2>&1 || true
success "Cleanup done"

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}=====================================${NC}"
echo -e "${GREEN}${BOLD}  Deploy complete!${NC}"
echo -e "${GREEN}${BOLD}=====================================${NC}"
echo ""
echo -e "  Commit:  $(git log --oneline -1)"
echo -e "  Time:    $(date)"
echo ""
echo -e "  Logs:    $COMPOSE logs -f"
echo -e "  Rollback: bash $APP_DIR/scripts/deploy.sh --rollback"
echo ""
