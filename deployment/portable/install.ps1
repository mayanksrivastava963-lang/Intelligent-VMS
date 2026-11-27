param([string]$TlsDirectory, [switch]$SelfSigned)
. "$PSScriptRoot/common.ps1"
if (Test-Path .env.production) { throw 'Existing installation preserved. Use start.ps1.' }
Guard
& "$Root/import-images.ps1"
if ($SelfSigned) {
    if (Test-Path tls/privkey.pem) { throw 'Existing TLS key preserved.' }
    New-Item -ItemType Directory -Force tls | Out-Null
    $TlsDirectory = (Resolve-Path tls).Path
    D run --rm --pull never --network none --user 0 --memory 128m --mount "type=bind,source=$TlsDirectory,target=/tls" intelligent-vms-portable/api:0.1.0-rc3 openssl req -x509 -nodes -newkey rsa:3072 -days 365 -keyout /tls/privkey.pem -out /tls/fullchain.pem -subj /CN=localhost -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
    Write-Host 'New local-only certificate generated. Browser trust warning expected; use trusted TLS for remote access.'
}
& "$Root/configure.ps1" -BundledDb -TlsDirectory $TlsDirectory
Write-Host 'Installation configured. Run ./start.ps1 (no build). Keep .env.production and TLS keys private.'
