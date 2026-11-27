$ErrorActionPreference = 'Stop'
$script:VmsRoot = Split-Path $PSScriptRoot -Parent

function Initialize-VmsDeployment(
    [switch]$Validation,
    [string]$Profile = 'small',
    [switch]$HostMonitor,
    [switch]$BundledDb,
    [switch]$Ai,
    [switch]$AiGpu,
    [switch]$Valkey,
    [switch]$DistributedRecorders
) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $dockerBin = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin'
        if (Test-Path -LiteralPath (Join-Path $dockerBin 'docker.exe')) {
            $env:Path = "$dockerBin;$env:Path"
        } else {
            throw 'Docker CLI not found. Open Docker Desktop and add its resources/bin directory to PATH.'
        }
    }
    & docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is not reachable. Start Docker Desktop and inspect docker context ls.' }
    $envFile = Join-Path $script:VmsRoot '.env.production'
    if ($Validation) { $envFile = Join-Path $script:VmsRoot 'storage/deployment-validation/validation.env' }
    if (-not (Test-Path -LiteralPath $envFile)) { throw 'Configuration missing. Run scripts/setup.ps1 first.' }
    $profileFile = Join-Path $script:VmsRoot "deployment/profiles/$Profile.env"
    if (-not (Test-Path -LiteralPath $profileFile)) { throw 'Unknown deployment resource profile.' }

    if (-not $Validation -and -not $BundledDb) {
        $pgHostLine = Select-String -LiteralPath $envFile -Pattern "^POSTGRES_HOST=['""]?postgres['""]?\s*$" -Quiet
        if ($pgHostLine) { $BundledDb = $true }
    }

    $script:ComposeArgs = @('compose','--project-directory',$script:VmsRoot,'--env-file',$profileFile,'--env-file',$envFile,'-f',(Join-Path $script:VmsRoot 'compose.production.yml'))
    if ($Validation) { $script:ComposeArgs += @('-f',(Join-Path $script:VmsRoot 'compose.validation.yml')) }
    elseif ($BundledDb) { $script:ComposeArgs += @('-f',(Join-Path $script:VmsRoot 'compose.bundled-db.yml')) }
    if ($HostMonitor) { $script:ComposeArgs += @('-f',(Join-Path $script:VmsRoot 'compose.host-monitor.yml')) }
    if ($AiGpu) { $script:ComposeArgs += @('-f',(Join-Path $script:VmsRoot 'compose.ai-gpu.yml')) }
    if ($Valkey) { $script:ComposeArgs += @('-f',(Join-Path $script:VmsRoot 'compose.valkey.yml')) }
    if ($DistributedRecorders) { $script:ComposeArgs += @('-f',(Join-Path $script:VmsRoot 'compose.distributed-recorders.yml')) }
    if ($Ai -or $AiGpu) { $script:ComposeArgs += @('--profile','ai') }
    & docker @script:ComposeArgs config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Deployment configuration is invalid.' }
}

function Invoke-VmsCompose([string[]]$CommandArgs) {
    & docker @script:ComposeArgs @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed. Use scripts/status.ps1 and sanitized service logs to diagnose.' }
}
