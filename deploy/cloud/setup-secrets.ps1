$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$secrets = Join-Path $root 'secrets'
$envFile = Join-Path $root '.env'

if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root 'env.example') $envFile
}
if (Test-Path $secrets) {
    throw "Secrets already exist at '$secrets'; refusing to overwrite them."
}
New-Item -ItemType Directory -Path $secrets | Out-Null

function New-RandomSecret {
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

$postgresPassword = New-RandomSecret
$masterPassword = New-RandomSecret
$deviceToken = New-RandomSecret

Set-Content -Path (Join-Path $secrets 'postgres_password') -Value $postgresPassword -NoNewline -Encoding ascii
Set-Content -Path (Join-Path $secrets 'sync_device_token') -Value $deviceToken -NoNewline -Encoding ascii
Set-Content -Path (Join-Path $secrets 'cloud_local_ca.crt') -Value 'Replace this placeholder with Caddy root.crt using make cloud-worker-up.' -Encoding ascii

$odooConfig = @"
[options]
admin_passwd = $masterPassword
db_host = db
db_port = 5432
db_user = odoo
db_password = $postgresPassword
db_name = sunnyside_cloud
dbfilter = ^sunnyside_cloud$
list_db = False
proxy_mode = True
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
workers = 0
max_cron_threads = 1
limit_request = 8192
log_level = info
"@
Set-Content -Path (Join-Path $secrets 'odoo.conf') -Value $odooConfig -Encoding ascii
@"
[odoo]
url = http://host.docker.internal:8069
database = odoo
username = REPLACE_WITH_LOCAL_SYNC_USER
password = REPLACE_WITH_LOCAL_SYNC_PASSWORD

[cloud]
url = https://caddy
device_id = reception-laptop
token_file = /run/secrets/sync_device_token
verify_tls = true
ca_file = /run/secrets/cloud_local_ca

[worker]
online_interval = 15
retry_min = 5
retry_max = 60
reconcile_interval = 3600
"@ | Set-Content -Path (Join-Path $secrets 'worker.ini') -Encoding ascii
Write-Output 'Cloud Odoo secrets created. Keep deploy/cloud/secrets private and back it up securely.'
Write-Output 'The sync device token is mounted into the optional Docker worker as a secret.'
Write-Output 'Before starting the Docker worker, edit secrets/worker.ini with local Odoo credentials.'
Write-Output 'The cloud worker CA file will be exported from Caddy by make cloud-worker-up.'
