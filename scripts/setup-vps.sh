#!/bin/bash
# =============================================================
# ProspectOS — First-time VPS Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 / Debian 12 VPS
# Usage: curl -fsSL https://yourrepo/scripts/setup-vps.sh | bash
#   OR:  bash setup-vps.sh
# =============================================================

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()    { echo -e "\n${BOLD}==> $1${NC}"; }

# ── Config ────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-}"          # set via env or prompted below
APP_DIR="${APP_DIR:-/opt/prospectOS}"
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"                # for Let's Encrypt

# ── Checks ───────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  error "Please run as root: sudo bash setup-vps.sh"
fi

step "ProspectOS VPS Setup"
echo "This will install Docker, clone your repo, and start all services."
echo ""

# Prompt for missing config
if [ -z "$REPO_URL" ]; then
  read -rp "Git repo URL (e.g. git@github.com:you/prospectOS.git): " REPO_URL
fi
if [ -z "$DOMAIN" ]; then
  read -rp "Your domain (e.g. app.yourdomain.com, or press Enter to skip SSL): " DOMAIN
fi
if [ -n "$DOMAIN" ] && [ -z "$EMAIL" ]; then
  read -rp "Email for Let's Encrypt SSL: " EMAIL
fi

# ── System packages ──────────────────────────────────────────
step "Updating system packages"
apt-get update -qq
apt-get install -y -qq \
  curl git unzip wget gnupg2 lsb-release \
  ca-certificates apt-transport-https \
  ufw fail2ban htop
success "System packages installed"

# ── Docker ───────────────────────────────────────────────────
step "Installing Docker"
if command -v docker &>/dev/null; then
  warn "Docker already installed: $(docker --version)"
else
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
  success "Docker installed: $(docker --version)"
fi

if ! command -v docker compose &>/dev/null; then
  info "Installing Docker Compose plugin"
  apt-get install -y docker-compose-plugin
fi
success "Docker Compose: $(docker compose version)"

# ── Firewall ─────────────────────────────────────────────────
step "Configuring firewall (UFW)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
success "Firewall configured"

# ── Fail2ban ─────────────────────────────────────────────────
step "Enabling Fail2ban"
systemctl enable --now fail2ban
success "Fail2ban active"

# ── App directory ────────────────────────────────────────────
step "Setting up app directory: $APP_DIR"
mkdir -p "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  warn "Repo already cloned. Pulling latest..."
  git -C "$APP_DIR" pull
else
  git clone "$REPO_URL" "$APP_DIR"
  success "Repo cloned to $APP_DIR"
fi

# ── Environment file ─────────────────────────────────────────
step "Setting up .env file"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"

  # Generate random secrets
  APP_SECRET=$(openssl rand -hex 32)
  JWT_SECRET=$(openssl rand -hex 32)
  ENC_KEY=$(openssl rand -hex 32)
  MEILI_KEY=$(openssl rand -hex 16)
  LITELLM_KEY=$(openssl rand -hex 16)

  sed -i "s|change-me-to-a-random-32-char-secret|$APP_SECRET|g" "$APP_DIR/.env"
  sed -i "s|change-me-to-a-different-random-secret|$JWT_SECRET|g" "$APP_DIR/.env"
  sed -i "s|0000000000000000000000000000000000000000000000000000000000000000|$ENC_KEY|g" "$APP_DIR/.env"
  sed -i "s|MEILISEARCH_MASTER_KEY=change-me|MEILISEARCH_MASTER_KEY=$MEILI_KEY|g" "$APP_DIR/.env"
  sed -i "s|LITELLM_API_KEY=change-me|LITELLM_API_KEY=$LITELLM_KEY|g" "$APP_DIR/.env"

  if [ -n "$DOMAIN" ]; then
    sed -i "s|NEXT_PUBLIC_APP_URL=http://localhost:3000|NEXT_PUBLIC_APP_URL=https://$DOMAIN|g" "$APP_DIR/.env"
    sed -i "s|NEXT_PUBLIC_API_URL=http://localhost:8080/api/v1|NEXT_PUBLIC_API_URL=https://$DOMAIN/api/v1|g" "$APP_DIR/.env"
  fi

  warn "IMPORTANT: Edit $APP_DIR/.env and add your GOOGLE_API_KEY before continuing."
  echo ""
  read -rp "Press Enter after adding your API key to .env to continue..."
fi
success ".env ready"

# ── SSL Certificate ──────────────────────────────────────────
if [ -n "$DOMAIN" ] && [ -n "$EMAIL" ]; then
  step "Setting up SSL with Let's Encrypt (Certbot)"
  apt-get install -y certbot
  certbot certonly --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN" || warn "Certbot failed — continuing without SSL. Add certs manually."

  CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
  if [ -d "$CERT_DIR" ]; then
    mkdir -p "$APP_DIR/infra/nginx/certs"
    ln -sf "$CERT_DIR/fullchain.pem" "$APP_DIR/infra/nginx/certs/fullchain.pem"
    ln -sf "$CERT_DIR/privkey.pem"   "$APP_DIR/infra/nginx/certs/privkey.pem"

    # Auto-renew via cron
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && docker compose -f $APP_DIR/infra/docker-compose.yml restart nginx") | crontab -
    success "SSL certificate installed and auto-renew configured"
  fi
fi

# ── Update nginx config with real domain ─────────────────────
if [ -n "$DOMAIN" ]; then
  sed -i "s|prospectOS.yourdomain.com|$DOMAIN|g" "$APP_DIR/infra/nginx/nginx.conf"
fi

# ── Build and start services ─────────────────────────────────
step "Building Docker images (this takes a few minutes)"
cd "$APP_DIR"
docker compose -f infra/docker-compose.yml build --parallel
success "Images built"

step "Starting all services"
docker compose -f infra/docker-compose.yml up -d
success "Services started"

# Wait for postgres
step "Waiting for PostgreSQL to be ready"
for i in $(seq 1 30); do
  if docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U prospectOS &>/dev/null; then
    success "PostgreSQL is ready"
    break
  fi
  echo "  Waiting... ($i/30)"
  sleep 2
done

# ── Systemd service for auto-restart ─────────────────────────
step "Creating systemd service for auto-restart on reboot"
cat > /etc/systemd/system/prospectOS.service << EOF
[Unit]
Description=ProspectOS
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=docker compose -f infra/docker-compose.yml up -d
ExecStop=docker compose -f infra/docker-compose.yml down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable prospectOS
success "Systemd service enabled (auto-starts on reboot)"

# ── Health check ─────────────────────────────────────────────
step "Running health check"
sleep 5
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/health" || echo "000")
if [ "$HTTP_STATUS" = "200" ]; then
  success "API health check passed"
else
  warn "API not responding yet (status: $HTTP_STATUS) — may still be starting up"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}============================================${NC}"
echo -e "${GREEN}${BOLD}  ProspectOS setup complete!${NC}"
echo -e "${GREEN}${BOLD}============================================${NC}"
echo ""
if [ -n "$DOMAIN" ]; then
  echo -e "  App URL:    ${BLUE}https://$DOMAIN${NC}"
  echo -e "  API URL:    ${BLUE}https://$DOMAIN/api/v1/health${NC}"
else
  SERVER_IP=$(curl -s ifconfig.me || echo "your-server-ip")
  echo -e "  App URL:    ${BLUE}http://$SERVER_IP${NC}"
  echo -e "  API URL:    ${BLUE}http://$SERVER_IP/api/v1/health${NC}"
fi
echo ""
echo -e "  App dir:    $APP_DIR"
echo -e "  Logs:       docker compose -f $APP_DIR/infra/docker-compose.yml logs -f"
echo -e "  Update:     bash $APP_DIR/scripts/deploy.sh"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Point your DNS A record to this server's IP"
echo "  2. Create your first user: bash $APP_DIR/scripts/create-user.sh"
echo ""
