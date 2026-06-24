# ProspectOS — shorthand commands
# Usage: make <target>

.PHONY: dev stop logs reset deploy setup

# ── Local dev (Windows) ───────────────────────────────────────
dev:
	powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

stop:
	powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Stop

logs:
	docker compose -f infra/docker-compose.yml logs -f $(svc)

reset:
	powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Reset

# ── VPS deployment ────────────────────────────────────────────
deploy:
	bash scripts/deploy.sh

deploy-no-build:
	bash scripts/deploy.sh --no-build

rollback:
	bash scripts/deploy.sh --rollback

# ── Railway deployment ────────────────────────────────────────
railway-deploy:
	bash scripts/deploy-railway.sh

railway-update:
	bash scripts/deploy-railway.sh --update

railway-logs:
	railway logs --service $(svc)

railway-open:
	railway open

# ── Utilities ─────────────────────────────────────────────────
ps:
	docker compose -f infra/docker-compose.yml ps

build:
	docker compose -f infra/docker-compose.yml build --parallel

migrate:
	docker compose -f infra/docker-compose.yml exec api /app/server migrate

create-user:
	bash scripts/create-user.sh
