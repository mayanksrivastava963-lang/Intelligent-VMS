. "$PSScriptRoot/common.ps1"
Guard
C config --quiet
C up -d --no-build --pull never --wait --wait-timeout 180
C ps
Write-Host 'Default URL: https://localhost:8443/ . Sign in with the administrator configured during installation.'
