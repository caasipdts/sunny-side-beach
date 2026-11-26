#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${SCRIPT_DIR}/secrets"
ENV_FILE="${SCRIPT_DIR}/.env"

echo "=========================================="
echo " Sunnyside Beach - Reception Setup"
echo "=========================================="

# 1. Check Docker
echo -e "\n[1/6] Checking Docker engine..."
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running. Please start Docker and run this script again." >&2
    exit 1
fi
echo "Docker is running."

# 2. Configure .env and Secrets
echo -e "\n[2/6] Configuring environment and generating secure secrets..."
if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${SCRIPT_DIR}/env.example" "${ENV_FILE}"
fi
mkdir -p "${SECRETS_DIR}"

gen_secret() {
    openssl rand -base64 "${1:-32}" | tr -d '\n\r'
}

PG_PASS_FILE="${SECRETS_DIR}/postgres_password"
if [[ ! -f "${PG_PASS_FILE}" ]]; then
    gen_secret 24 > "${PG_PASS_FILE}"
fi
PG_PASS="$(cat "${PG_PASS_FILE}")"

SYNC_TOKEN_FILE="${SECRETS_DIR}/sync_device_token"
if [[ ! -f "${SYNC_TOKEN_FILE}" ]]; then
    gen_secret 36 > "${SYNC_TOKEN_FILE}"
fi
SYNC_TOKEN="$(cat "${SYNC_TOKEN_FILE}")"

SYNC_USER_PASS_FILE="${SECRETS_DIR}/sync_user_password"
if [[ ! -f "${SYNC_USER_PASS_FILE}" ]]; then
    gen_secret 24 > "${SYNC_USER_PASS_FILE}"
fi
SYNC_USER_PASS="$(cat "${SYNC_USER_PASS_FILE}")"

# Generate odoo.conf
ODOO_CONF_FILE="${SECRETS_DIR}/odoo.conf"
ADMIN_PASS="$(gen_secret 24)"
cat <<EOF > "${ODOO_CONF_FILE}"
[options]
admin_passwd = ${ADMIN_PASS}
db_host = db
db_port = 5432
db_user = odoo
db_password = ${PG_PASS}
db_name = sunnyside_local
dbfilter = ^sunnyside_local$
list_db = False
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
workers = 0
max_cron_threads = 1
limit_request = 8192
log_level = info
EOF

# Generate worker.ini
WORKER_INI_FILE="${SECRETS_DIR}/worker.ini"
cat <<EOF > "${WORKER_INI_FILE}"
[odoo]
url = http://odoo:8069
database = sunnyside_local
username = sync-worker
password = ${SYNC_USER_PASS}

[cloud]
url = https://your-cloud-domain.example
device_id = reception-desk-1
token_file = /run/secrets/sync_device_token
verify_tls = true

[worker]
online_interval = 15
max_idle_interval = 300
retry_min = 5
retry_max = 60
reconcile_interval = 3600
vacuum_interval = 86400
EOF

# 3. Start local stack
echo -e "\n[3/6] Starting local database and Odoo application..."
docker compose -f "${SCRIPT_DIR}/compose.yaml" up -d db odoo

echo "Waiting for Odoo to initialize database and modules (takes ~45-60 seconds)..."
timeout=90
elapsed=0
while [[ $elapsed -lt $timeout ]]; do
    status="$(docker inspect -f '{{.State.Health.Status}}' sunnyside-client-odoo 2>/dev/null || true)"
    if [[ "$status" == "healthy" ]]; then
        echo "Odoo is ready and healthy!"
        break
    fi
    sleep 5
    elapsed=$((elapsed + 5))
done

# 4. Initialize sync user
echo -e "\n[4/6] Creating sync worker user..."
SETUP_PY="
sync_user = env['res.users'].sudo().search([('login', '=', 'sync-worker')], limit=1)
if not sync_user:
    env['res.users'].sudo().create({
        'name': 'Sync Worker',
        'login': 'sync-worker',
        'password': '${SYNC_USER_PASS}',
        'group_ids': [(6, 0, [
            env.ref('base.group_user').id,
            env.ref('sunnyside_sync.group_sunnyside_sync_user').id,
        ])],
    })
    env.cr.commit()
    print('Sync user created.')
"
echo "${SETUP_PY}" | docker exec -i sunnyside-client-odoo odoo shell -d sunnyside_local --no-http 2>/dev/null || true

# 5. Start Sync Worker
echo -e "\n[5/6] Starting background sync worker..."
docker compose -f "${SCRIPT_DIR}/compose.yaml" up -d worker

# 6. Create Cloud Pairing File
echo -e "\n[6/6] Generating Azure Cloud Pairing file..."
TOKEN_HASH="$(echo -n "${SYNC_TOKEN}" | openssl dgst -sha256 | awk '{print $NF}')"
PAIRING_FILE="${SCRIPT_DIR}/cloud-pairing.json"
cat <<EOF > "${PAIRING_FILE}"
{
  "device_id": "reception-desk-1",
  "token_hash": "${TOKEN_HASH}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "========================================================"
echo " INSTALLATION COMPLETED SUCCESSFULLY!"
echo "========================================================"
echo "1. Access URL: http://localhost:8069/sunnyside/check-in"
echo "2. Cloud Pairing file: ${PAIRING_FILE}"
echo "   (Send this file to your Azure Admin to authorize this device)"
