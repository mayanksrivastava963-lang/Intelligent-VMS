param(
    [switch]$Check,
    [switch]$Verify,
    [ValidateSet('development','small','medium','enterprise')][string]$Profile = 'development'
)

. "$PSScriptRoot/deployment-common.ps1"
Initialize-VmsDeployment -Validation -Profile $Profile
if ($Check -and $Verify) { throw 'Choose either -Check or -Verify.' }
$action = if ($Check) { 'check' } elseif ($Verify) { 'verify' } else { 'reset' }
$recoveryScript = Join-Path $script:VmsRoot 'backend/app/services/admin_recovery.py'
Invoke-VmsCompose @('run','--no-deps','--rm','-v',"${recoveryScript}:/tmp/admin_recovery.py:ro",'-e','PYTHONPATH=/app','recording-api','python','/tmp/admin_recovery.py',$action)
