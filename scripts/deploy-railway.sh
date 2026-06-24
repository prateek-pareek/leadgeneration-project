#!/bin/bash
# =============================================================
# ProspectOS — Railway Deployment Script
# Deploys all services to Railway with one command.
#
# Prerequisites:
#   1. Install Railway CLI:  npm i -g @railway/cli
#   2. Have your .env file ready with GOOGLE_API_KEY set
#
# Usage:
#   bash scripts/deploy-railway.sh           # full deploy
#   bash scripts/deploy-railway.sh --update  # redeploy after code changes
# =============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()    { echo -e "\n${BOLD}==> $1${NC}"; }

UPDATE_MODE=false
for arg in "$@"; do
  [ "$arg" = "--update" ] && UPDATE_MODE=true
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

# ── Prereq checks ─────────────────────────────────────────────
step "Checking prerequisites"

if ! command -v railway &>/dev/null; then
  error "Railway CLI not found. Install it with:\n  npm install -g @railway/cli\n  Then re-run this script."
fi
success "Railway CLI: $(railway --version 2>/dev/null || echo 'found')"

if ! command -v git &>/dev/null; then
  error "git not found"
fi

if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  error ".env file created from template. Please fill in GOOGLE_API_KEY and other required values, then re-run."
fi

if grep -q "your-google-api-key-here" "$ENV_FILE"; then
  error "GOOGLE_API_KEY is not set in .env. Please add it before deploying."
fi

# Load .env values (for variable injection)
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

success "Prerequisites OK"

# ── Login ─────────────────────────────────────────────────────
step "Railway login"
if ! railway whoami &>/dev/null; then
  info "Not logged in — opening browser login..."
  railway login
fi
success "Logged in as: $(railway whoami)"

# ── Project init or link ──────────────────────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Creating Railway project"
  info "This will create a new Railway project called 'prospectOS'."
  info "If you already have one, press Ctrl+C and run with --update instead."
  echo ""
  railway init --name "prospectOS"
  success "Project created"
fi

# Helper: deploy one service from a subdirectory
deploy_service() {
  local name="$1"
  local dir="$2"

  step "Deploying service: $name"
  cd "$ROOT_DIR/$dir"
  railway up --service "$name" --detach
  success "$name deployed"
  cd "$ROOT_DIR"
}

# ── Database (PostgreSQL with pgvector) ───────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Adding PostgreSQL database"
  info "Railway will provision a managed Postgres instance."
  railway add --plugin postgresql
  success "PostgreSQL added"

  # Enable pgvector extension (needed for embeddings)
  info "Enabling pgvector extension..."
  sleep 5  # wait for DB to be ready
  railway run --service "postgres" psql -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || \
    warn "Could not auto-enable pgvector — enable it manually:\n  railway run psql -c 'CREATE EXTENSION IF NOT EXISTS vector;'"

  # ── Redis ──────────────────────────────────────────────────
  step "Adding Redis"
  railway add --plugin redis
  success "Redis added"
fi

# ── LiteLLM service ──────────────────────────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Creating LiteLLM service"
  railway service create --name "litellm"

  info "Setting LiteLLM environment variables..."
  railway variables --service litellm --set \
    "GOOGLE_API_KEY=${GOOGLE_API_KEY}" \
    "LITELLM_MASTER_KEY=${LITELLM_API_KEY:-$(openssl rand -hex 16)}" \
    "PORT=4000"

  info "Linking LiteLLM Docker image..."
  # LiteLLM deployed via their public Docker image
  # You need to set the source in the Railway dashboard:
  # Service → Settings → Source → Docker Image → ghcr.io/berriai/litellm:main-latest
  warn "ACTION REQUIRED: In the Railway dashboard, set the LiteLLM service source to:"
  warn "  Docker Image: ghcr.io/berriai/litellm:main-latest"
  warn "  Start command: --config /app/config.yaml --port 4000"
  warn "  Mount: infra/litellm/config.yaml → /app/config.yaml"
  echo ""
  read -rp "Press Enter once you've configured LiteLLM in the dashboard..."

  success "LiteLLM service created"
fi

# Get LiteLLM internal URL
LITELLM_INTERNAL_URL="http://litellm.railway.internal:4000"

# ── Meilisearch service ───────────────────────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Creating Meilisearch service"
  railway service create --name "meilisearch"
  railway variables --service meilisearch --set \
    "MEILI_MASTER_KEY=${MEILISEARCH_MASTER_KEY:-$(openssl rand -hex 16)}" \
    "PORT=7700"

  warn "ACTION REQUIRED: In the Railway dashboard, set the Meilisearch service source to:"
  warn "  Docker Image: getmeili/meilisearch:v1.7"
  echo ""
  read -rp "Press Enter once you've configured Meilisearch in the dashboard..."
  success "Meilisearch service created"
fi

MEILI_INTERNAL_URL="http://meilisearch.railway.internal:7700"

# ── Generate secrets if not in .env ───────────────────────────
APP_SECRET="${APP_SECRET:-$(openssl rand -hex 32)}"
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
ENCRYPTION_KEY="${ENCRYPTION_KEY:-$(openssl rand -hex 32)}"
LITELLM_API_KEY="${LITELLM_API_KEY:-$(openssl rand -hex 16)}"
MEILISEARCH_MASTER_KEY="${MEILISEARCH_MASTER_KEY:-$(openssl rand -hex 16)}"

# ── API service ───────────────────────────────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Creating API service"
  railway service create --name "api"
fi

step "Setting API environment variables"
railway variables --service api --set \
  "APP_ENV=production" \
  "APP_SECRET=${APP_SECRET}" \
  "JWT_SECRET=${JWT_SECRET}" \
  "ENCRYPTION_KEY=${ENCRYPTION_KEY}" \
  "LITELLM_BASE_URL=${LITELLM_INTERNAL_URL}" \
  "LITELLM_API_KEY=${LITELLM_API_KEY}" \
  "MEILISEARCH_URL=${MEILI_INTERNAL_URL}" \
  "MEILISEARCH_MASTER_KEY=${MEILISEARCH_MASTER_KEY}" \
  "DNS_RESOLVER=8.8.8.8:53"
# DATABASE_URL and REDIS_URL are injected automatically by Railway plugins

success "API environment variables set"

step "Deploying API"
cd "$ROOT_DIR/apps/api"
railway up --service api --detach
cd "$ROOT_DIR"
success "API deployed"

# ── Worker service ────────────────────────────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Creating Worker service"
  railway service create --name "worker"
fi

step "Setting Worker environment variables"
railway variables --service worker --set \
  "APP_ENV=production" \
  "GOOGLE_API_KEY=${GOOGLE_API_KEY}" \
  "LITELLM_BASE_URL=${LITELLM_INTERNAL_URL}" \
  "LITELLM_API_KEY=${LITELLM_API_KEY}" \
  "ENCRYPTION_KEY=${ENCRYPTION_KEY}"
# DATABASE_URL and REDIS_URL injected automatically

success "Worker environment variables set"

step "Deploying Worker"
cd "$ROOT_DIR/apps/worker"
railway up --service worker --detach
cd "$ROOT_DIR"
success "Worker deployed"

# ── Web (Next.js) service ─────────────────────────────────────
if [ "$UPDATE_MODE" = false ]; then
  step "Creating Web service"
  railway service create --name "web"
fi

# Get API public URL to wire into the Next.js app
API_URL=$(railway domain --service api 2>/dev/null || echo "")
if [ -z "$API_URL" ]; then
  warn "Could not auto-detect API URL. You can set NEXT_PUBLIC_API_URL manually after deploy."
  API_URL="https://your-api-url.up.railway.app"
fi

step "Setting Web environment variables"
railway variables --service web --set \
  "NEXT_PUBLIC_API_URL=https://${API_URL}/api/v1" \
  "NODE_ENV=production"

success "Web environment variables set"

step "Deploying Web"
cd "$ROOT_DIR/apps/web"
railway up --service web --detach
cd "$ROOT_DIR"
success "Web deployed"

# ── Print summary ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}================================================${NC}"
echo -e "${GREEN}${BOLD}  ProspectOS deployed to Railway!${NC}"
echo -e "${GREEN}${BOLD}================================================${NC}"
echo ""
echo "Opening Railway dashboard..."
railway open

echo ""
echo -e "${YELLOW}Post-deploy checklist:${NC}"
echo "  1. In dashboard → API service → Settings → Add a public domain"
echo "  2. In dashboard → Web service → Settings → Add a public domain"
echo "  3. Update NEXT_PUBLIC_API_URL on the web service to point to the API domain"
echo "  4. Create your first user: visit https://your-web-domain/login → register"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "  Logs:     railway logs --service api"
echo "  Redeploy: bash scripts/deploy-railway.sh --update"
echo "  Open:     railway open"
echo ""
