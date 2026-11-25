[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not $Force) {
    throw 'Restore replaces the sunnyside_cloud database and filestore. Rerun with -Force only after verifying the backup.'
}

$composeFile = Join-Path $PSScriptRoot 'compose.yaml'
$composePrefix = @('compose', '-f', $composeFile)

function Invoke-Docker {
    param([string[]]$DockerArguments)

    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

$backupPath = (Resolve-Path -LiteralPath $BackupDirectory).Path
$manifestPath = Join-Path $backupPath 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw 'The backup manifest is missing.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if (
    $manifest.database -ne 'sunnyside_cloud' -or
    $manifest.database_dump -ne 'sunnyside_cloud.dump' -or
    $manifest.filestore -ne 'sunnyside_cloud'
) {
    throw 'The backup manifest does not describe a supported Sunnyside cloud backup.'
}

$dumpPath = Join-Path $backupPath $manifest.database_dump
$filestorePath = Join-Path $backupPath $manifest.filestore
if (-not (Test-Path -LiteralPath $dumpPath -PathType Leaf)) {
    throw 'The database dump is missing.'
}
if (-not (Test-Path -LiteralPath $filestorePath -PathType Container)) {
    throw 'The cloud filestore backup is missing.'
}

$dbContainer = (Invoke-Docker -DockerArguments ($composePrefix + @('ps', '-q', 'db')) | Select-Object -First 1)
$odooContainer = (Invoke-Docker -DockerArguments ($composePrefix + @('ps', '-aq', 'odoo')) | Select-Object -First 1)
if (-not $dbContainer -or -not $odooContainer) {
    throw 'The cloud database and Odoo containers must exist before restoring.'
}
$odooWasRunning = [bool](Invoke-Docker -DockerArguments ($composePrefix + @('ps', '--status', 'running', '-q', 'odoo')) | Select-Object -First 1)

$restoreName = 'sunnyside-restore-{0}.dump' -f ([guid]::NewGuid().ToString('N'))
$dumpInContainer = "/tmp/$restoreName"
$dumpCopied = $false
$odooStopped = $false
$restoreSucceeded = $false
try {
    if ($odooWasRunning) {
        Invoke-Docker -DockerArguments ($composePrefix + @('stop', 'odoo')) | Out-Null
        $odooStopped = $true
    }

    Invoke-Docker -DockerArguments @('cp', $dumpPath, "${dbContainer}:$dumpInContainer") | Out-Null
    $dumpCopied = $true
    Invoke-Docker -DockerArguments @('exec', $dbContainer, 'pg_restore', '--list', $dumpInContainer) | Out-Null
    Invoke-Docker -DockerArguments @('exec', $dbContainer, 'dropdb', '-U', 'odoo', '--if-exists', 'sunnyside_cloud') | Out-Null
    Invoke-Docker -DockerArguments @('exec', $dbContainer, 'createdb', '-U', 'odoo', '--owner=odoo', 'sunnyside_cloud') | Out-Null
    Invoke-Docker -DockerArguments @(
        'exec', $dbContainer, 'pg_restore', '-U', 'odoo', '-d', 'sunnyside_cloud',
        '--no-owner', '--role=odoo', '--exit-on-error', $dumpInContainer
    ) | Out-Null

    $filestoreMount = '{0}:/restore:ro' -f $filestorePath
    Invoke-Docker -DockerArguments ($composePrefix + @(
        'run', '--rm', '--no-deps', '-T', '--entrypoint', '/bin/sh',
        '--volume', $filestoreMount, 'odoo',
        '-c', 'set -eu; rm -rf /var/lib/odoo/filestore/sunnyside_cloud; mkdir -p /var/lib/odoo/filestore/sunnyside_cloud; cp -a /restore/. /var/lib/odoo/filestore/sunnyside_cloud/'
    )) | Out-Null
    $restoreSucceeded = $true
}
catch {
    if ($odooStopped -and -not $restoreSucceeded) {
        Write-Warning 'Restore did not complete; Odoo remains stopped to avoid serving an inconsistent database and filestore.'
    }
    throw
}
finally {
    if ($dumpCopied) {
        & docker exec $dbContainer rm -f $dumpInContainer
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Could not remove the temporary restore dump from the database container.'
        }
    }
    if ($odooStopped -and $restoreSucceeded) {
        Invoke-Docker -DockerArguments ($composePrefix + @('start', 'odoo')) | Out-Null
    }
}

Write-Output 'Cloud database and filestore restored successfully.'
