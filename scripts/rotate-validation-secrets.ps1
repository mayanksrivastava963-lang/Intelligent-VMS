param([switch]$Check)
. "$PSScriptRoot/deployment-common.ps1"
Initialize-VmsDeployment -Validation -Profile development
if (-not $Check) {
    $active = & docker @script:ComposeArgs ps --status running --services
    if ($active -match 'recording-api|rtsp-recorder|storage-retention|ai-worker') {
        throw 'Stop application services before rotating validation secrets; database may remain running.'
    }
}
$rotator = Join-Path $script:VmsRoot 'scripts/rotate_validation_secrets.py'
$secureDir = Join-Path $script:VmsRoot 'storage/deployment-validation'
$mode = if ($Check) { '--check' } else { '/secure/validation.env' }
Invoke-VmsCompose @('run','--no-deps','--rm','-v',"${rotator}:/tmp/rotate_validation_secrets.py:ro",'-v',"${secureDir}:/secure",'-e','PYTHONPATH=/app','recording-api','python','/tmp/rotate_validation_secrets.py',$mode)
