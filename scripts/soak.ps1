param(
    [ValidateSet('smoke','integration','operational','day','stability')][string]$Profile = 'smoke',
    [ValidateRange(1,2147483647)][int]$Cameras = 4,
    [string]$Python = "$PSScriptRoot/../services/ai_engine/.venv/Scripts/python.exe"
)
$ErrorActionPreference = 'Stop'
$duration = @{smoke=1860; integration=7200; operational=28800; day=86400; stability=259200}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Supply the configured developer Python interpreter with -Python.' }
& $Python "$PSScriptRoot/validate_streams.py" --count $Cameras --duration $duration[$Profile]
if ($LASTEXITCODE -ne 0) { throw 'Soak did not pass. Inspect the preserved local validation report.' }
