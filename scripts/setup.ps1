param([string]$TlsDirectory, [switch]$BundledDb)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$target = Join-Path $root '.env.production'
if (Test-Path -LiteralPath $target) { throw 'Existing configuration preserved. Review it explicitly before changing an installation.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is required; start Docker Desktop or install the supported Docker Engine.' }
& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is not reachable.' }
if (-not $TlsDirectory) { $TlsDirectory = Read-Host 'Directory containing trusted fullchain.pem and privkey.pem' }
$TlsDirectory = (Resolve-Path -LiteralPath $TlsDirectory).Path
foreach ($name in @('fullchain.pem','privkey.pem')) {
    if (-not (Test-Path -LiteralPath (Join-Path $TlsDirectory $name))) { throw "TLS file missing: $name" }
}
function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}
function Read-Private([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
$media = New-Secret
if ($BundledDb) {
    $pgHost = 'postgres'
    $pgDb = 'intelligent_vms'
    $pgUser = 'vms_admin'
    $pgPass = New-Secret
} else {
    $pgHost = Read-Host 'Existing PostgreSQL host (host.docker.internal for Windows host)'
    $pgDb = Read-Host 'Database name (must already exist; never reset)'
    $pgUser = Read-Host 'Dedicated database user'
    $pgPass = Read-Private 'Database password'
}
$values = [ordered]@{
    COMPOSE_PROJECT_NAME = 'intelligent-vms'
    VMS_BUILD_VERSION = '0.1.0-rc3'
    POSTGRES_HOST = $pgHost
    POSTGRES_PORT = '5432'
    POSTGRES_DB = $pgDb
    POSTGRES_USER = $pgUser
    POSTGRES_PASSWORD = $pgPass
    VMS_OPERATOR_USERNAME = (Read-Host 'Initial administrator username')
    VMS_OPERATOR_PASSWORD = (Read-Private 'Initial administrator password (12+ characters)')
    VMS_SESSION_SECRET = (New-Secret)
    MEDIAMTX_API_PASSWORD = (New-Secret)
    MEDIAMTX_MEDIA_PASSWORD = $media
    VMS_MEDIA_AUTH = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("vms-media:$media"))
    VMS_CAMERA_NETWORKS = (Read-Host 'Approved camera CIDRs, comma separated')
    VMS_TLS_DIRECTORY = $TlsDirectory.Replace('\','/')
    VMS_PUBLIC_HOST = (Read-Host 'HTTPS hostname covered by the certificate')
    VMS_BIND_ADDRESS = '127.0.0.1'
    VMS_HTTPS_PORT = '8443'
    RECORDING_SEGMENT_SECONDS = '1800'
    RECORDING_RETENTION_DAYS = '30'
}
if ($values.VMS_OPERATOR_PASSWORD.Length -lt 12) { throw 'Administrator password must contain at least 12 characters.' }
$lines = foreach ($entry in $values.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace($entry.Value) -or $entry.Value -match "[`r`n]") { throw "Invalid configuration field: $($entry.Key)" }
    "{0}='{1}'" -f $entry.Key, $entry.Value.Replace("'", "\'")
}
[IO.File]::WriteAllLines($target, $lines, [Text.UTF8Encoding]::new($false))
if ($env:OS -eq 'Windows_NT') {
    & icacls $target /inheritance:r /grant:r "${env:USERNAME}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Configuration written, but restricting file permissions failed. Secure the file before deployment.' }
}
if ($BundledDb) {
    Write-Host 'Configuration created with bundled PostgreSQL (compose.bundled-db.yml will load automatically).'
} else {
    Write-Host 'Configuration created without changing existing external database/data.'
}
Write-Host 'Back up .env.production securely; losing VMS_SESSION_SECRET prevents camera credential recovery.'
Write-Host 'Next: ./scripts/start.ps1 -Build. Startup checks migrations/database and service health. External access stays loopback-only until you configure a trusted network.'
