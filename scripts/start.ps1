param(
    [switch]$Build,
    [switch]$Validation,
    [switch]$HostMonitor,
    [switch]$BundledDb,
    [switch]$Ai,
    [switch]$AiGpu,
    [switch]$Valkey,
    [switch]$DistributedRecorders,
    [ValidateSet('development','small','medium','enterprise')][string]$Profile = 'small',
    [ValidateRange(1,100)][double]$StartupBlockPercent = 85,
    [ValidateRange(1,1024)][double]$MinBuildFreeGB = 6
)
. "$PSScriptRoot/deployment-common.ps1"
if ($env:OS -eq 'Windows_NT') {
    $osInfo = Get-CimInstance Win32_OperatingSystem
    $ramPercent = 100 * (1 - $osInfo.FreePhysicalMemory / $osInfo.TotalVisibleMemorySize)
    $freeGB = $osInfo.FreePhysicalMemory / 1MB
    $cpuPercent = (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
    if ($ramPercent -ge $StartupBlockPercent -or $cpuPercent -ge $StartupBlockPercent) {
        throw ('Startup/build admission paused: host RAM {0:N1}%, CPU {1:N1}%. Existing services and recordings are unchanged.' -f $ramPercent,$cpuPercent)
    }
}
Initialize-VmsDeployment -Validation:$Validation -Profile $Profile -HostMonitor:$HostMonitor -BundledDb:$BundledDb -Ai:$Ai -AiGpu:$AiGpu -Valkey:$Valkey -DistributedRecorders:$DistributedRecorders
foreach ($image in @('intelligent-vms-api:0.1.0','intelligent-vms-web:0.1.0')) {
    & docker image inspect $image --format '{{.Id}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $Build = $true }
}
if ($env:OS -eq 'Windows_NT' -and $Build -and $freeGB -lt $MinBuildFreeGB) {
    throw ('Build admission paused: {0:N2} GiB RAM free; require {1:N2} GiB of build headroom. Existing services and recordings are unchanged.' -f $freeGB,$MinBuildFreeGB)
}
if (-not $env:VMS_BUILD_VERSION) { $env:VMS_BUILD_VERSION = '0.1.0-rc3' }
if (-not $env:VMS_BUILD_TIMESTAMP) { $env:VMS_BUILD_TIMESTAMP = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
if (-not $env:VMS_BUILD_SHA) {
    $gitSha = ''
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $gitSha = (& git -C $script:VmsRoot rev-parse --short HEAD 2>$null)
    }
    $env:VMS_BUILD_SHA = if ($gitSha) { $gitSha.Trim() } else { 'release-archive' }
}
$arguments = @('up','-d','--wait','--wait-timeout','180')
if ($Build) { $arguments += '--build' }
Invoke-VmsCompose $arguments
Invoke-VmsCompose @('ps')
Write-Host 'Intelligent-VMS started. Default local URL: https://localhost:8443 (use your configured host/HTTPS port if changed).'
Write-Host 'Health checks cover service availability; verify /api/version, camera recording status, and completed playback separately.'
