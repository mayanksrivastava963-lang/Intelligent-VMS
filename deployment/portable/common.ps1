$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root
$Docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (!$Docker -and $env:LOCALAPPDATA) { $Docker = "$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe" }
if (!$Docker -or !(Test-Path $Docker)) { throw 'Install/start Docker Desktop (Linux containers) or Docker Engine with Compose first.' }
$env:PATH = "$(Split-Path $Docker)$([IO.Path]::PathSeparator)$env:PATH"
function D { & $Docker @args; if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." } }
function C { D compose --env-file .env.production -f compose.production.yml -f compose.bundled-db.yml @args }
function Guard {
    D info --format '{{.OSType}}' | Out-Null
    if ($env:OS -eq 'Windows_NT') {
        $os = Get-CimInstance Win32_OperatingSystem
        $used = 100 * (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize)
    } else {
        $mem = Get-Content /proc/meminfo
        $total = [double](($mem | Select-String '^MemTotal:').ToString() -replace '\D','')
        $available = [double](($mem | Select-String '^MemAvailable:').ToString() -replace '\D','')
        $used = 100 * (1 - $available / $total)
    }
    if ($used -ge 85) { throw "Host RAM $([math]::Round($used,1))%: 85% safety guard blocks startup/import." }
}
function Verify-Files {
    foreach ($line in Get-Content SHA256SUMS) {
        $hash,$relative = $line -split '  ',2
        if (!$relative -or !(Test-Path -LiteralPath $relative) -or (Get-FileHash -LiteralPath $relative -Algorithm SHA256).Hash -ne $hash) { throw "Checksum failed: $relative" }
    }
}
