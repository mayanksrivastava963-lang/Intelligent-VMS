<#
.SYNOPSIS
    Backup and restore Intelligent-VMS PostgreSQL database and private configuration.
.DESCRIPTION
    Reads PostgreSQL connection settings from .env.production (or validation.env),
    creates a timestamped backup directory with a PostgreSQL dump, configuration,
    TLS materials, and SHA-256 checksums. Supports restoring into PostgreSQL.
.PARAMETER Action
    'backup' or 'restore'
.PARAMETER BackupPath
    Path to a backup directory created by -Action backup (required for restore)
.PARAMETER Validation
    Target the isolated validation environment (storage/deployment-validation/validation.env)
.EXAMPLE
    .\scripts\backup_restore.ps1 -Action backup
    .\scripts\backup_restore.ps1 -Action backup -Validation
    .\scripts\backup_restore.ps1 -Action restore -BackupPath .\backups\vms-backup-20261127-120000
#>
param(
    [ValidateSet("backup", "restore")]
    [string]$Action = "backup",
    [string]$BackupPath = "",
    [switch]$Validation
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$envFile = if ($Validation) { Join-Path $root "storage\deployment-validation\validation.env" } else { Join-Path $root ".env.production" }
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Environment file not found: $envFile"
}

function Read-DotEnv([string]$Path) {
    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $idx = $trimmed.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $val = $trimmed.Substring($idx + 1).Trim()
        if (($val.StartsWith("'") -and $val.EndsWith("'")) -or ($val.StartsWith('"') -and $val.EndsWith('"'))) {
            $val = $val.Substring(1, $val.Length - 2).Replace("\'", "'")
        }
        $map[$key] = $val
    }
    return $map
}

$cfg = Read-DotEnv $envFile
$projectName = if ($cfg["COMPOSE_PROJECT_NAME"]) { $cfg["COMPOSE_PROJECT_NAME"] } else { "intelligent-vms" }
$pgUser = $cfg["POSTGRES_USER"]
$pgDb = $cfg["POSTGRES_DB"]
$pgHost = $cfg["POSTGRES_HOST"]
$pgPass = $cfg["POSTGRES_PASSWORD"]

function Find-PostgresContainer {
    foreach ($candidate in @("postgres", "validation-db")) {
        $id = docker ps --filter "label=com.docker.compose.project=$projectName" --filter "label=com.docker.compose.service=$candidate" --format "{{.ID}}" 2>$null
        if ($id) { return $id.Trim() }
    }
    return $null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $root "backups"

if ($Action -eq "backup") {
    Write-Host "=== Intelligent-VMS Backup ($projectName) ===" -ForegroundColor Cyan
    $targetDir = Join-Path $backupRoot "vms-backup-$timestamp"
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    Write-Host "[1/4] Backing up PostgreSQL database '$pgDb'..."
    $pgContainer = Find-PostgresContainer
    $sqlOut = Join-Path $targetDir "database.sql"
    if ($pgContainer) {
        docker exec -e "PGPASSWORD=$pgPass" $pgContainer pg_dump -U $pgUser -d $pgDb --clean --if-exists > $sqlOut
        if ($LASTEXITCODE -ne 0 -or (Get-Item $sqlOut).Length -lt 32) {
            throw "pg_dump inside PostgreSQL container failed or produced empty output"
        }
        Write-Host "  Container pg_dump completed: database.sql"
    } elseif ($pgHost) {
        $pgTools = Get-Command pg_dump -ErrorAction SilentlyContinue
        if ($pgTools) {
            $env:PGPASSWORD = $pgPass
            try {
                & pg_dump -h $pgHost -p ($cfg["POSTGRES_PORT"] ?? "5432") -U $pgUser -d $pgDb --clean --if-exists -f $sqlOut
                if ($LASTEXITCODE -ne 0) { throw "pg_dump failed against external PostgreSQL host $pgHost" }
            } finally {
                Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
            }
            Write-Host "  External host pg_dump completed: database.sql"
        } else {
            Write-Host "  WARNING: External PostgreSQL host '$pgHost' and local pg_dump not installed. Run pg_dump on your DB server." -ForegroundColor Yellow
        }
    }

    Write-Host "[2/4] Backing up configuration..."
    Copy-Item -LiteralPath $envFile (Join-Path $targetDir (Split-Path $envFile -Leaf))

    Write-Host "[3/4] Backing up TLS certificates..."
    $tlsDir = $cfg["VMS_TLS_DIRECTORY"]
    if (-not $tlsDir) { $tlsDir = Join-Path $root "infrastructure\nginx\tls" }
    if (Test-Path -LiteralPath $tlsDir) {
        $tlsTarget = Join-Path $targetDir "tls"
        New-Item -ItemType Directory -Path $tlsTarget -Force | Out-Null
        Copy-Item "$tlsDir\*.pem" $tlsTarget -ErrorAction SilentlyContinue
        Copy-Item "$tlsDir\*.crt" $tlsTarget -ErrorAction SilentlyContinue
        Copy-Item "$tlsDir\*.key" $tlsTarget -ErrorAction SilentlyContinue
    }

    Write-Host "[4/4] Recording manifest and SHA-256 checksums..."
    $files = Get-ChildItem -LiteralPath $targetDir -Recurse -File | ForEach-Object {
        @{
            path = $_.FullName.Substring($targetDir.Length + 1).Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $_.Length
        }
    }
    @{
        timestamp = $timestamp
        version = "0.1.0-rc3"
        project = $projectName
        database = $pgDb
        files = $files
    } | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $targetDir "backup-manifest.json")

    Write-Host "`n=== Backup Complete ===" -ForegroundColor Green
    Write-Host "Location: $targetDir"
}
elseif ($Action -eq "restore") {
    if (-not $BackupPath) { throw "Specify -BackupPath for restore" }
    if (-not (Test-Path -LiteralPath $BackupPath)) { throw "Backup directory not found: $BackupPath" }

    Write-Host "=== Intelligent-VMS Restore ($projectName) ===" -ForegroundColor Cyan
    Write-Host "Source: $BackupPath"
    $confirm = Read-Host "Type 'RESTORE' to overwrite database '$pgDb'"
    if ($confirm -ne "RESTORE") {
        Write-Host "Restore cancelled."
        return
    }

    $sqlFile = Join-Path $BackupPath "database.sql"
    if (Test-Path -LiteralPath $sqlFile) {
        $pgContainer = Find-PostgresContainer
        if ($pgContainer) {
            Get-Content -Raw -LiteralPath $sqlFile | docker exec -i -e "PGPASSWORD=$pgPass" $pgContainer psql -v ON_ERROR_STOP=1 -U $pgUser -d $pgDb
            if ($LASTEXITCODE -ne 0) { throw "Database restore inside container failed" }
            Write-Host "  Container database restored." -ForegroundColor Green
        } elseif ((Get-Command psql -ErrorAction SilentlyContinue) -and $pgHost) {
            $env:PGPASSWORD = $pgPass
            try {
                & psql -v ON_ERROR_STOP=1 -h $pgHost -p ($cfg["POSTGRES_PORT"] ?? "5432") -U $pgUser -d $pgDb -f $sqlFile
                if ($LASTEXITCODE -ne 0) { throw "External database restore failed" }
            } finally {
                Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
            }
            Write-Host "  External database restored." -ForegroundColor Green
        } else {
            throw "Neither PostgreSQL container nor local psql CLI is available to restore $sqlFile"
        }
    }
    Write-Host "`nRestore complete. Run scripts/start.ps1 (with matching flags) to verify migrations and service health." -ForegroundColor Green
}
