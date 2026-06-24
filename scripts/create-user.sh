#!/bin/bash
# =============================================================
# ProspectOS — Create First Admin User
# Usage: bash scripts/create-user.sh
# =============================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/prospectOS}"
COMPOSE="docker compose -f $APP_DIR/infra/docker-compose.yml"

echo "Create ProspectOS Admin User"
echo "============================"
read -rp "Organization name: " ORG_NAME
read -rp "Your full name:    " FULL_NAME
read -rp "Email:             " EMAIL
read -rsp "Password:          " PASSWORD
echo ""

# Generate org slug
SLUG=$(echo "$ORG_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd '[:alnum:]-')

# Hash password using the API container (has bcrypt available)
PASS_HASH=$($COMPOSE exec -T api /bin/sh -c "echo -n '$PASSWORD' | htpasswd -nBi admin 2>/dev/null | cut -d: -f2" 2>/dev/null || echo "")

# Fallback: insert via psql with plain SQL (API handles hashing internally via /auth/register endpoint)
$COMPOSE exec -T postgres psql -U prospectOS -d prospectOS <<EOF
DO \$\$
DECLARE
  v_org_id UUID := gen_random_uuid();
  v_user_id UUID := gen_random_uuid();
BEGIN
  -- Create organization
  INSERT INTO organizations (id, name, slug, plan)
  VALUES (v_org_id, '$ORG_NAME', '$SLUG', 'free')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_org_id;

  SELECT id INTO v_org_id FROM organizations WHERE slug = '$SLUG';

  -- Create admin user (password is stored as plain here — API login endpoint handles bcrypt)
  -- We call the register endpoint instead:
  RAISE NOTICE 'org_id=%', v_org_id;
END;
\$\$;
EOF

# Use the API's register endpoint for proper bcrypt hashing
RESPONSE=$(curl -s -X POST "http://localhost:8080/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"email\": \"$EMAIL\",
    \"password\": \"$PASSWORD\",
    \"full_name\": \"$FULL_NAME\",
    \"org_name\": \"$ORG_NAME\"
  }")

echo ""
if echo "$RESPONSE" | grep -q '"id"'; then
  echo -e "\e[32m[OK]\e[0m User created successfully!"
  echo ""
  echo "  Email:    $EMAIL"
  echo "  Org:      $ORG_NAME"
  echo ""
  echo "Login at: http://localhost:3000/login (dev) or your domain"
else
  echo -e "\e[31m[ERROR]\e[0m Registration failed:"
  echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
  echo ""
  echo "Make sure the API is running: docker compose -f $APP_DIR/infra/docker-compose.yml ps"
fi
