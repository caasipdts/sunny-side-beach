# Sunnyside Beach - Client Machine Setup (Windows PowerShell)
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretsDir = Join-Path $scriptDir 'secrets'
$envFile = Join-Path $scriptDir '.env'

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Sunnyside Beach - Reception Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Check Docker
Write-Host "`n[1/6] Checking Docker engine..." -ForegroundColor Yellow
try {
    docker info | Out-Null
    Write-Host "Docker is running." -ForegroundColor Green
} catch {
    Write-Host "ERROR: Docker Desktop is not running. Please start Docker Desktop and run this script again." -ForegroundColor Red
    exit 1
}

# 2. Configure .env and Secrets
Write-Host "`n[2/6] Configuring environment and generating secure secrets..." -ForegroundColor Yellow
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $scriptDir 'env.example') $envFile
}

if (-not (Test-Path $secretsDir)) {
    New-Item -ItemType Directory -Path $secretsDir | Out-Null
}

function New-RandomSecret([int]$length = 32) {
    $bytes = New-Object byte[] $length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

$pgPasswordFile = Join-Path $secretsDir 'postgres_password'
if (-not (Test-Path $pgPasswordFile)) {
    $pgPass = New-RandomSecret 24
    Set-Content -Path $pgPasswordFile -Value $pgPass -NoNewline -Encoding ascii
} else {
    $pgPass = (Get-Content $pgPasswordFile -Raw).Trim()
}

$syncTokenFile = Join-Path $secretsDir 'sync_device_token'
if (-not (Test-Path $syncTokenFile)) {
    $syncToken = New-RandomSecret 36
    Set-Content -Path $syncTokenFile -Value $syncToken -NoNewline -Encoding ascii
} else {
    $syncToken = (Get-Content $syncTokenFile -Raw).Trim()
}

$syncUserPassFile = Join-Path $secretsDir 'sync_user_password'
if (-not (Test-Path $syncUserPassFile)) {
    $syncUserPass = New-RandomSecret 24
    Set-Content -Path $syncUserPassFile -Value $syncUserPass -NoNewline -Encoding ascii
} else {
    $syncUserPass = (Get-Content $syncUserPassFile -Raw).Trim()
}

# Generate odoo.conf
$odooConfFile = Join-Path $secretsDir 'odoo.conf'
$adminPass = New-RandomSecret 24
$odooConfig = @"
[options]
admin_passwd = $adminPass
db_host = db
db_port = 5432
db_user = odoo
db_password = $pgPass
db_name = sunnyside_local
dbfilter = ^sunnyside_local$
list_db = False
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
workers = 0
max_cron_threads = 1
limit_request = 8192
log_level = info
"@
Set-Content -Path $odooConfFile -Value $odooConfig -Encoding ascii

# Generate worker.ini
$workerIniFile = Join-Path $secretsDir 'worker.ini'
$workerConfig = @"
[odoo]
url = http://odoo:8069
database = sunnyside_local
username = sync-worker
password = $syncUserPass

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
"@
Set-Content -Path $workerIniFile -Value $workerConfig -Encoding ascii

# 3. Start local stack
Write-Host "`n[3/6] Starting local database and Odoo application..." -ForegroundColor Yellow
docker compose -f (Join-Path $scriptDir 'compose.yaml') up -d db odoo

Write-Host "Waiting for Odoo to initialize database and modules (takes ~45-60 seconds)..." -ForegroundColor Yellow
$timeout = 90
$elapsed = 0
while ($elapsed -lt $timeout) {
    $status = docker inspect -f '{{.State.Health.Status}}' sunnyside-client-odoo 2>$null
    if ($status -eq "healthy") {
        Write-Host "Odoo is ready and healthy!" -ForegroundColor Green
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
}

# 4. Initialize sync user and seed seating inventory
Write-Host "`n[4/6] Creating sync user and seeding standard seating inventory..." -ForegroundColor Yellow
$setupScript = @"
sync_user = env['res.users'].sudo().search([('login', '=', 'sync-worker')], limit=1)
if not sync_user:
    env['res.users'].sudo().create({
        'name': 'Sync Worker',
        'login': 'sync-worker',
        'password': '$syncUserPass',
        'group_ids': [(6, 0, [
            env.ref('base.group_user').id,
            env.ref('sunnyside_sync.group_sunnyside_sync_user').id,
        ])],
    })
    env.cr.commit()
    print('Sync user created.')
"@
docker exec -i sunnyside-client-odoo odoo shell -d sunnyside_local --no-http <<< $setupScript 2>$null

# 5. Start Sync Worker
Write-Host "`n[5/6] Starting background sync worker..." -ForegroundColor Yellow
docker compose -f (Join-Path $scriptDir 'compose.yaml') up -d worker

# 6. Create Cloud Pairing File and Desktop Shortcut
Write-Host "`n[6/6] Generating Azure Cloud Pairing file and Desktop Shortcut..." -ForegroundColor Yellow
$hasher = [System.Security.Cryptography.SHA256]::Create()
$hashBytes = $hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($syncToken))
$tokenHash = [BitConverter]::ToString($hashBytes).Replace('-', '').ToLower()

$pairingPayload = @{
    device_id = "reception-desk-1"
    token_hash = $tokenHash
    created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json

$pairingFile = Join-Path $scriptDir 'cloud-pairing.json'
Set-Content -Path $pairingFile -Value $pairingPayload -Encoding ascii

# Create Desktop Shortcut
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutFile = Join-Path $desktopPath "Sunnyside Beach Reception.url"
$shortcutContent = @"
[InternetShortcut]
URL=http://localhost:8069/sunnyside/check-in
IconIndex=0
IconFile=C:\Windows\System32\shell32.dll
"@
Set-Content -Path $shortcutFile -Value $shortcutContent -Encoding ascii

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host " INSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "1. Reception Shortcut created on Desktop: 'Sunnyside Beach Reception'" -ForegroundColor Cyan
Write-Host "2. Access URL: http://localhost:8069/sunnyside/check-in" -ForegroundColor Cyan
Write-Host "3. Cloud Pairing file created at: $pairingFile" -ForegroundColor Cyan
Write-Host "   (Send this file to your Azure Admin to authorize this device)" -ForegroundColor Cyan
