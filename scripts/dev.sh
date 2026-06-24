#!/usr/bin/env bash
# ProspectOS — local development without Docker (macOS/Linux)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
LOG_DIR="${TMPDIR:-/tmp}/prospectos-logs"
mkdir -p "$LOG_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
step()  { echo -e "\n${CYAN}==> $*${NC}"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERR]${NC} $*"; exit 1; }

if [[ "${1:-}" == "stop" ]]; then
  step "Stopping ProspectOS services"
  for f in api worker web litellm; do
    pidfile="$LOG_DIR/$f.pid"
    if [[ -f "$pidfile" ]]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
      rm -f "$pidfile"
    fi
  done
  pkill -f "$LOG_DIR/prospectos-api" 2>/dev/null || true
  pkill -f "apps/worker/main.py" 2>/dev/null || true
  pkill -f "next dev" 2>/dev/null || true
  pkill -f "litellm --config" 2>/dev/null || true
  ok "Stopped app processes (postgres/redis left running)"
  exit 0
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  warn "Created .env from .env.example — review before continuing"
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

step "Checking prerequisites"
command -v go >/dev/null || fail "Go not found"
command -v node >/dev/null || fail "Node not found"
command -v npm >/dev/null || fail "npm not found"
command -v redis-cli >/dev/null || fail "redis-cli not found — install Redis"
redis-cli ping >/dev/null 2>&1 || fail "Redis is not running (brew services start redis)"
ok "Redis is running"

PSQL=""
for candidate in psql /opt/homebrew/opt/postgresql@16/bin/psql /opt/homebrew/opt/postgresql@17/bin/psql; do
  if command -v "$candidate" >/dev/null 2>&1; then PSQL="$candidate"; break; fi
done
[[ -n "$PSQL" ]] || fail "psql not found — install PostgreSQL"

step "Preparing worker virtualenv"
WORKER_VENV="$ROOT/apps/worker/.venv"
if [[ ! -d "$WORKER_VENV" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    python3.11 -m venv "$WORKER_VENV"
  elif [[ -x /opt/anaconda3/bin/python3.11 ]]; then
    /opt/anaconda3/bin/python3.11 -m venv "$WORKER_VENV"
  else
    fail "Python 3.11 required for worker (asyncpg does not support 3.13 yet)"
  fi
fi
# shellcheck disable=SC1091
source "$WORKER_VENV/bin/activate"
pip install -q -r "$ROOT/apps/worker/requirements.txt"
pip install -q 'litellm[proxy]' prisma
ln -sf "$ENV_FILE" "$ROOT/apps/worker/.env"

step "Installing web dependencies"
(cd "$ROOT/apps/web" && npm install --silent)

start_bg() {
  local name="$1"
  shift
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" >"$LOG_DIR/$name.log" 2>&1 < /dev/null &
  else
    nohup "$@" >"$LOG_DIR/$name.log" 2>&1 < /dev/null &
    disown
  fi
  echo $! >"$LOG_DIR/$name.pid"
}

step "Starting LiteLLM"
# Run from /tmp and clear DATABASE_URL so LiteLLM does not attach to the app Postgres DB.
start_bg litellm bash -c "cd /tmp && unset DATABASE_URL && exec litellm --config '$ROOT/infra/litellm/config.yaml' --port 4000"

step "Starting API"
(cd "$ROOT/apps/api" && go build -o "$LOG_DIR/prospectos-api" ./cmd/server/main.go)
start_bg api bash -c "cd '$ROOT/apps/api' && exec '$LOG_DIR/prospectos-api'"

step "Starting worker"
start_bg worker bash -c "cd '$ROOT/apps/worker' && exec '$WORKER_VENV/bin/python' main.py"

step "Starting web"
start_bg web npm run dev --prefix "$ROOT/apps/web"

step "Waiting for services"
for i in {1..30}; do
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then ok "API healthy"; break; fi
  [[ $i -eq 30 ]] && warn "API health check timed out — see $LOG_DIR/api.log"
  sleep 1
done

for i in {1..30}; do
  if curl -sf http://localhost:3000/login >/dev/null 2>&1; then ok "Web healthy"; break; fi
  [[ $i -eq 30 ]] && warn "Web health check timed out — see $LOG_DIR/web.log"
  sleep 1
done

echo ""
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  ProspectOS is running (no Docker)${NC}"
echo -e "${GREEN}=====================================${NC}"
echo ""
echo -e "  App:     ${CYAN}http://localhost:3000${NC}"
echo -e "  API:     ${CYAN}http://localhost:8080/health${NC}"
echo -e "  LiteLLM: ${CYAN}http://localhost:4000${NC}"
echo ""
echo "Logs: $LOG_DIR/"
echo "Stop: bash scripts/dev.sh stop"
echo ""
