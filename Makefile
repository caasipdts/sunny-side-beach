# Sunnyside Beach Odoo project commands
# Override values on the command line when needed, for example:
#   make run DB_NAME=staging
#   make db-backup DB_NAME=odoo BACKUP=backups/odoo.dump

.DEFAULT_GOAL := help
.PHONY: help \
	py-info py-install py-worker-run run-worker \
	docker-up docker-down docker-restart docker-ps docker-logs docker-pull docker-build docker-clean \
	db-up db-down db-logs db-ps db-wait db-list db-create db-drop db-backup db-restore \
	run run-shell run-init run-update run-upgrade run-stop-after-init run-scaffold \
	cloud-config cloud-up cloud-down cloud-restart cloud-ps cloud-logs cloud-pull cloud-backup cloud-restore \
	cloud-worker-up cloud-worker-down cloud-worker-restart cloud-worker-ps cloud-worker-logs

# Local workstation defaults. The existing PostgreSQL service hosts the Odoo DB on 5432.
PY              ?= py
DOCKER          ?= docker
COMPOSE         ?= $(DOCKER) compose
DB_SERVICE      ?= db
DB_HOST         ?= 127.0.0.1
DB_PORT         ?= 5432
DB_USER         ?= odoo
DB_PASSWORD     ?= odoo
DB_NAME         ?= odoo
ODOO_ADDONS     ?= custom-addons
ODOO_CONFIG     ?= debian/odoo.conf
ODOO_EXTRA_ARGS ?=
MODULES         ?= sunnyside_visitor_management,sunnyside_sync
WORKER_CONFIG   ?= deploy/cloud/secrets/worker.ini
BACKUP          ?= backups/$(DB_NAME).dump
CLOUD_COMPOSE   ?= deploy/cloud/compose.yaml
CLOUD_BACKUP_DIR ?= backups

help: ## Show available commands
	@$(PY) -c "print('Sunnyside Beach project commands:'); print(''); print('Docker / local database:'); print('  docker-up, docker-down, docker-restart, docker-ps, docker-logs, docker-pull, docker-build, docker-clean'); print('  db-up, db-down, db-logs, db-ps, db-wait, db-list, db-create, db-drop, db-backup, db-restore'); print(''); print('Odoo / Python:'); print('  py-info, py-install, run, run-shell, run-init, run-update, run-upgrade, run-stop-after-init, run-scaffold'); print('  py-worker-run'); print(''); print('Cloud Compose:'); print('  cloud-config, cloud-up, cloud-down, cloud-restart, cloud-ps, cloud-logs, cloud-pull, cloud-backup, cloud-restore'); print('  cloud-worker-up, cloud-worker-down, cloud-worker-restart, cloud-worker-ps, cloud-worker-logs'); print(''); print('Common overrides: DB_NAME=odoo MODULES=sunnyside_sync BACKUP=backups/db.dump PY=python')"

# Python and dependency management
py-info: ## Print Python and pip versions
	$(PY) --version
	$(PY) -m pip --version

py-install: ## Install Odoo's Python dependencies from requirements.txt
	$(PY) -m pip install -r requirements.txt

py-worker-run: ## Run the sync worker in the foreground (WORKER_CONFIG=...)
	$(PY) custom-addons/sunnyside_sync/worker.py --config "$(WORKER_CONFIG)"

run-worker: py-worker-run ## Alias for py-worker-run

# Development PostgreSQL container from docker-compose.yml
docker-up: ## Start the local Docker Compose stack
	$(COMPOSE) up -d

docker-down: ## Stop and remove local Compose containers (keeps database volume)
	$(COMPOSE) down

docker-restart: ## Restart local Compose containers
	$(COMPOSE) restart

docker-ps: ## Show local Compose container status
	$(COMPOSE) ps

docker-logs: ## Follow local Compose logs (SERVICE=db to select one service)
	$(COMPOSE) logs -f $(SERVICE)

docker-pull: ## Pull images for the local Compose stack
	$(COMPOSE) pull

docker-build: ## Build services in the local Compose stack
	$(COMPOSE) build

docker-clean: ## Remove local Compose containers and networks, preserving volumes
	$(COMPOSE) down --remove-orphans

db-up: ## Start PostgreSQL for local Odoo development
	$(COMPOSE) up -d --wait $(DB_SERVICE)

db-down: ## Stop the local PostgreSQL container (keeps its volume)
	$(COMPOSE) stop $(DB_SERVICE)

db-logs: ## Follow PostgreSQL logs
	$(COMPOSE) logs -f $(DB_SERVICE)

db-ps: ## Show PostgreSQL container status
	$(COMPOSE) ps $(DB_SERVICE)

db-wait: ## Wait until PostgreSQL is ready
	$(COMPOSE) exec -T $(DB_SERVICE) pg_isready -U $(DB_USER) -d postgres

db-list: ## List databases in the local PostgreSQL container
	$(COMPOSE) exec -T $(DB_SERVICE) psql -U $(DB_USER) -d postgres -c "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"

db-create: ## Create DB_NAME in the local PostgreSQL container
	$(COMPOSE) exec -T $(DB_SERVICE) createdb -U $(DB_USER) "$(DB_NAME)"

db-drop: ## Drop DB_NAME in the local PostgreSQL container (destructive)
	$(COMPOSE) exec -T $(DB_SERVICE) dropdb --if-exists --force -U $(DB_USER) "$(DB_NAME)"

db-backup: ## Dump DB_NAME to BACKUP in custom PostgreSQL format
	$(PY) -c "from pathlib import Path; Path(r'$(BACKUP)').parent.mkdir(parents=True, exist_ok=True)"
	$(COMPOSE) exec -T $(DB_SERVICE) pg_dump -U $(DB_USER) -d "$(DB_NAME)" -Fc > "$(BACKUP)"

db-restore: ## Restore BACKUP into DB_NAME (replaces objects in that database)
	$(COMPOSE) exec -T $(DB_SERVICE) pg_restore -U $(DB_USER) -d "$(DB_NAME)" --clean --if-exists --no-owner < "$(BACKUP)"

# Local Odoo runs on the host and connects to the Compose PostgreSQL port.
run: ## Run Odoo with the local development database
	$(PY) odoo-bin --addons-path=addons,$(ODOO_ADDONS) --db_host=$(DB_HOST) --db_port=$(DB_PORT) --db_user=$(DB_USER) --db_password=$(DB_PASSWORD) --http-interface=0.0.0.0 -d "$(DB_NAME)" $(ODOO_EXTRA_ARGS)

run-shell: ## Open an Odoo shell for DB_NAME
	$(PY) odoo-bin shell --addons-path=addons,$(ODOO_ADDONS) --db_host=$(DB_HOST) --db_port=$(DB_PORT) --db_user=$(DB_USER) --db_password=$(DB_PASSWORD) -d "$(DB_NAME)"

run-init: ## Initialize MODULES in DB_NAME and exit
	$(PY) odoo-bin --addons-path=addons,$(ODOO_ADDONS) --db_host=$(DB_HOST) --db_port=$(DB_PORT) --db_user=$(DB_USER) --db_password=$(DB_PASSWORD) -d "$(DB_NAME)" --init="$(MODULES)" --stop-after-init $(ODOO_EXTRA_ARGS)

run-update: ## Update MODULES in DB_NAME and exit
	$(PY) odoo-bin --addons-path=addons,$(ODOO_ADDONS) --db_host=$(DB_HOST) --db_port=$(DB_PORT) --db_user=$(DB_USER) --db_password=$(DB_PASSWORD) -d "$(DB_NAME)" --update="$(MODULES)" --stop-after-init $(ODOO_EXTRA_ARGS)

run-upgrade: run-update ## Alias for run-update

run-stop-after-init: ## Run Odoo once and exit (set ODOO_EXTRA_ARGS for a task)
	$(PY) odoo-bin --addons-path=addons,$(ODOO_ADDONS) --db_host=$(DB_HOST) --db_port=$(DB_PORT) --db_user=$(DB_USER) --db_password=$(DB_PASSWORD) -d "$(DB_NAME)" --stop-after-init $(ODOO_EXTRA_ARGS)

run-scaffold: ## Create an addon skeleton (NAME=my_module)
	$(PY) odoo-bin scaffold "$(NAME)" "$(ODOO_ADDONS)"

# Production/cloud Compose stack. Cloud backup and restore use the maintained
# PowerShell scripts, which also preserve the matching Odoo filestore.
cloud-config: ## Validate and display the cloud Compose configuration
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" config

cloud-up: ## Start the cloud Odoo, PostgreSQL, and Caddy stack
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" up -d

cloud-down: ## Stop the cloud stack (preserves named volumes)
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" down

cloud-restart: ## Restart the cloud stack
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" restart

cloud-ps: ## Show cloud stack status
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" ps

cloud-logs: ## Follow cloud stack logs (SERVICE=odoo, db, or caddy)
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" logs -f $(SERVICE)

cloud-pull: ## Pull cloud stack images
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" pull

cloud-worker-up: ## Build and start the Docker sync worker with the cloud stack
	$(PY) -c "import configparser,pathlib,sys; p=pathlib.Path('deploy/cloud/secrets/worker.ini'); c=configparser.ConfigParser(); ok=p.is_file() and c.read(p) and c.has_section('odoo') and c.has_section('cloud') and not c.get('odoo','username',fallback='').startswith('REPLACE_') and not c.get('odoo','password',fallback='').startswith('REPLACE_'); print('Worker config is ready.' if ok else 'Edit deploy/cloud/secrets/worker.ini with local Odoo sync user credentials.'); sys.exit(0 if ok else 1)"
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" up -d db odoo caddy
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" cp caddy:/data/caddy/pki/authorities/local/root.crt deploy/cloud/secrets/cloud_local_ca.crt
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" --profile worker up -d --build worker

cloud-worker-down: ## Stop the Docker sync worker without stopping Odoo
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" --profile worker stop worker

cloud-worker-restart: ## Restart the Docker sync worker
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" --profile worker restart worker

cloud-worker-ps: ## Show sync worker container status
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" --profile worker ps worker

cloud-worker-logs: ## Follow sync worker logs
	$(COMPOSE) -f "$(CLOUD_COMPOSE)" --profile worker logs -f worker

cloud-backup: ## Back up cloud database and filestore (DESTINATION=...)
	powershell -NoProfile -ExecutionPolicy Bypass -File deploy/cloud/backup.ps1 -Destination "$(if $(DESTINATION),$(DESTINATION),$(CLOUD_BACKUP_DIR))"

cloud-restore: ## Restore cloud database and filestore (BACKUP_DIR=... FORCE=1)
	powershell -NoProfile -ExecutionPolicy Bypass -File deploy/cloud/restore.ps1 -BackupDirectory "$(BACKUP_DIR)" $(if $(FORCE),-Force,)
