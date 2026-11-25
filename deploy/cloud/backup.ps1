[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = 'Stop'
$composeFile = Join-Path $PSScriptRoot 'compose.yaml'
$composePrefix = @('compose', '-f', $composeFile)

function Invoke-Docker {
    param([string[]]$DockerArguments)

    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

$dbContainer = (Invoke-Docker -DockerArguments ($composePrefix + @('ps', '-q', 'db')) | Select-Object -First 1)
$odooContainer = (Invoke-Docker -DockerArguments ($composePrefix + @('ps', '-aq', 'odoo')) | Select-Object -First 1)
$odooWasRunning = [bool](Invoke-Docker -DockerArguments ($composePrefix + @('ps', '--status', 'running', '-q', 'odoo')) | Select-Object -First 1)
if (-not $dbContainer -or -not $odooContainer) {
    throw 'Start the cloud database and Odoo services before creating a backup.'
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
$backupName = 'sunnyside-cloud-{0}' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
$backupPath = Join-Path $destinationPath $backupName
if (Test-Path -LiteralPath $backupPath) {
    throw "Backup directory already exists: $backupPath"
}
New-Item -ItemType Directory -Path $backupPath | Out-Null

$dumpName = 'sunnyside_cloud.dump'
$dumpInContainer = '/tmp/{0}-{1}' -f $backupName, $dumpName
$odooStopped = $false
try {
    if ($odooWasRunning) {
        Invoke-Docker -DockerArguments ($composePrefix + @('stop', 'odoo')) | Out-Null
        $odooStopped = $true
    }

    Invoke-Docker -DockerArguments @(
        'exec', $dbContainer, 'pg_dump', '-U', 'odoo', '-d', 'sunnyside_cloud',
        '--format=custom', "--file=$dumpInContainer"
    ) | Out-Null
    Invoke-Docker -DockerArguments @(
        'cp', "${dbContainer}:$dumpInContainer", (Join-Path $backupPath $dumpName)
    ) | Out-Null
    Invoke-Docker -DockerArguments @(
        'exec', $dbContainer, 'rm', '-f', $dumpInContainer
    ) | Out-Null
    Invoke-Docker -DockerArguments @(
        'cp', "${odooContainer}:/var/lib/odoo/filestore/sunnyside_cloud", $backupPath
    ) | Out-Null

    @{
        created_at = (Get-Date).ToString('o')
        database = 'sunnyside_cloud'
        database_dump = $dumpName
        filestore = 'sunnyside_cloud'
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupPath 'manifest.json') -Encoding UTF8
}
catch {
    $backupError = $_
    try {
        Remove-Item -LiteralPath $backupPath -Recurse -Force -ErrorAction Stop
    }
    catch {
        Write-Warning "Could not remove incomplete backup directory: $backupPath"
    }
    throw $backupError
}
finally {
    if ($odooStopped) {
        Invoke-Docker -DockerArguments ($composePrefix + @('start', 'odoo')) | Out-Null
    }
}

Write-Output "Backup created at $backupPath"
