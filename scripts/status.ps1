param(
    [switch]$Validation,
    [switch]$HostMonitor,
    [switch]$BundledDb,
    [switch]$Ai,
    [switch]$AiGpu,
    [switch]$Valkey,
    [switch]$DistributedRecorders,
    [ValidateSet('development','small','medium','enterprise')][string]$Profile = 'small'
)
. "$PSScriptRoot/deployment-common.ps1"
Initialize-VmsDeployment -Validation:$Validation -Profile $Profile -HostMonitor:$HostMonitor -BundledDb:$BundledDb -Ai:$Ai -AiGpu:$AiGpu -Valkey:$Valkey -DistributedRecorders:$DistributedRecorders
Invoke-VmsCompose @('ps','--all')
Write-Host 'For bounded resource readings: docker stats --no-stream'
