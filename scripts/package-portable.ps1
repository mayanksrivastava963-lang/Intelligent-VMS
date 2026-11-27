param([string]$Destination = 'releases/Intelligent-VMS-0.1.0-rc3-portable')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (!$docker) { $docker = "$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe" }
function D { & $docker @args; if ($LASTEXITCODE -ne 0) { throw "Docker failed: $LASTEXITCODE" } }
function Write-Utf8($path,$content) { [IO.File]::WriteAllText($path,$content,[Text.UTF8Encoding]::new($false)) }
$os = Get-CimInstance Win32_OperatingSystem
if ((1-$os.FreePhysicalMemory/$os.TotalVisibleMemorySize)*100 -ge 85) { throw '85% host memory guard blocks packaging.' }
if (Test-Path $Destination) { throw 'Output exists; choose a new destination.' }
New-Item -ItemType Directory $Destination | Out-Null
$out = (Resolve-Path $Destination).Path
$mapping = [ordered]@{
    'intelligent-vms-api:0.1.0'='intelligent-vms-portable/api:0.1.0-rc3'
    'intelligent-vms-web:0.1.0'='intelligent-vms-portable/web:0.1.0-rc3'
    'postgres:18-alpine'='intelligent-vms-portable/postgres:18'
    'redis:7-alpine'='intelligent-vms-portable/redis:7'
    'bluenviron/mediamtx:1.21.4'='intelligent-vms-portable/mediamtx:1.21.4'
}
$version = curl.exe -skf https://127.0.0.1:8443/api/version | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $version.version -ne '0.1.0-rc3') { throw 'Running API did not confirm RC3.' }
$inspection = Join-Path $env:TEMP ('vms-parity-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $inspection | Out-Null
foreach ($check in @(
    @('intelligent-vms-validation-recording-api-1','intelligent-vms-api:0.1.0','/app/backend','backend'),
    @('intelligent-vms-validation-recording-api-1','intelligent-vms-api:0.1.0','/app/services/recording_engine','services/recording_engine'),
    @('intelligent-vms-validation-nginx-1','intelligent-vms-web:0.1.0','/usr/share/nginx/html','frontend/dist')
)) {
    if ((D inspect $check[0] --format '{{.Image}}') -ne (D image inspect $check[1] --format '{{.Id}}')) { throw 'Running image/tag mismatch.' }
    $copy = Join-Path $inspection ([guid]::NewGuid().ToString('N'))
    D cp "$($check[0]):$($check[2])" $copy
    $local = (Resolve-Path $check[3]).Path
    foreach ($file in Get-ChildItem $local -Recurse -File | Where-Object {$_.FullName -notmatch '[\\/](tests|__pycache__)[\\/]|\.pyc$'}) {
        $relative = $file.FullName.Substring($local.Length+1)
        $imageFile = Join-Path $copy $relative
        if (!(Test-Path $imageFile) -or (Get-FileHash $file.FullName).Hash -ne (Get-FileHash $imageFile).Hash) { throw "Runtime source differs: $relative" }
    }
}
$manifest = @()
foreach ($source in $mapping.Keys) {
    $meta = @(D image inspect $source | ConvertFrom-Json)[0]
    if ($meta.Os -ne 'linux' -or $meta.Architecture -ne 'amd64') { throw "Unsupported platform: $source" }
    D tag $meta.Id $mapping[$source]
    $manifest += @{tag=$mapping[$source];source=$source;id=$meta.Id;created=$meta.Created;platform='linux/amd64';size=$meta.Size}
}
Copy-Item deployment/portable/* $out
Copy-Item scripts/setup.ps1 "$out/configure.ps1"
$setup = Get-Content "$out/configure.ps1" -Raw
$setup = $setup.Replace('$root = Split-Path $PSScriptRoot -Parent','$root = $PSScriptRoot')
$setup = $setup.Replace('./scripts/start.ps1 -Build','./start.ps1')
Write-Utf8 "$out/configure.ps1" $setup
$compose = Get-Content compose.production.yml -Raw
$compose = [regex]::Replace($compose,'(?ms)^  ai-worker:\r?\n.*?(?=^  redis:)','')
$compose = [regex]::Replace($compose,'(?ms)^    build:\r?\n.*?(?=^    image:)','')
$compose = [regex]::Replace($compose,'(?m)^    build: \{[^\r\n]+\}\r?\n','')
foreach ($source in $mapping.Keys) { $compose = [regex]::Replace($compose,[regex]::Escape($source)+'(?:@sha256:[a-f0-9]+)?',$mapping[$source]) }
$compose = $compose.Replace('${VMS_MAX_RECORDERS:-16}','${VMS_MAX_RECORDERS:-60}')
Write-Utf8 "$out/compose.production.yml" $compose
$bundled = (Get-Content compose.bundled-db.yml -Raw).Replace('postgres:18-alpine',$mapping['postgres:18-alpine']).Replace('/var/lib/postgresql/data','/var/lib/postgresql')
Write-Utf8 "$out/compose.bundled-db.yml" $bundled
New-Item -ItemType Directory "$out/infrastructure/mediamtx","$out/licenses","$out/docs" -Force | Out-Null
Copy-Item infrastructure/mediamtx/production.yml "$out/infrastructure/mediamtx/production.yml"
foreach($name in @('HARDWARE_SIZING_GUIDE.md','COMMERCIAL_LICENSING.md','RELEASE_CHECKLIST.md')) { Copy-Item "docs/$name" "$out/docs/$name" }
Copy-Item backend/requirements.lock.txt "$out/licenses/python-requirements.lock.txt"
Copy-Item frontend/package-lock.json "$out/licenses/javascript-package-lock.json"
$notices = (Get-Content THIRD_PARTY_NOTICES.md -Raw).Replace('No prebuilt binaries, AI model weights, or customer secrets are included in the source release archive.','This internal portable package includes prebuilt container binaries. No AI weights or customer secrets are included. Redistribution/source-offer and commercial licensing approvals remain outstanding.')
Write-Utf8 "$out/THIRD_PARTY_NOTICES.md" $notices
Write-Utf8 "$out/images.json" (ConvertTo-Json -InputObject $manifest -Depth 5)
Write-Utf8 "$out/build-version.json" ($version | ConvertTo-Json)
# Include license materials shipped with the actual API distribution.
D exec intelligent-vms-validation-recording-api-1 sh -c 'tar -czf /tmp/vms-license-materials.tar.gz /usr/share/doc /usr/share/common-licenses /usr/local/lib/python3.12/site-packages/*.dist-info 2>/dev/null'
D cp intelligent-vms-validation-recording-api-1:/tmp/vms-license-materials.tar.gz "$out/licenses/api-license-materials.tar.gz"
D exec intelligent-vms-validation-recording-api-1 rm -f /tmp/vms-license-materials.tar.gz
D cp intelligent-vms-validation-nginx-1:/usr/share/licenses "$out/licenses/nginx"
D cp intelligent-vms-validation-mediamtx-1:/LICENSE "$out/licenses/mediamtx-LICENSE"
curl.exe -fLsS https://www.postgresql.org/about/licence/ -o "$out/licenses/postgresql-license.html"
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL license download failed.' }
curl.exe -fLsS https://download.redis.io/releases/redis-7.4.12.tar.gz -o "$inspection/redis-source.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'Redis license source download failed.' }
tar -xzf "$inspection/redis-source.tar.gz" -C "$out/licenses" redis-7.4.12/LICENSE.txt redis-7.4.12/deps/fpconv/LICENSE.txt redis-7.4.12/deps/hdr_histogram/COPYING.txt redis-7.4.12/deps/hiredis/COPYING redis-7.4.12/deps/jemalloc/COPYING
if ($LASTEXITCODE -ne 0) { throw 'Redis license extraction failed.' }
foreach($package in @('react','react-dom','scheduler','hls.js')) {
    $dir = "frontend/node_modules/$package"
    if (Test-Path $dir) {
        New-Item -ItemType Directory -Force "$out/licenses/$package" | Out-Null
        Get-ChildItem $dir -File | Where-Object {$_.Name -match '^(LICENSE|COPYING|NOTICE)'} | Copy-Item -Destination "$out/licenses/$package"
    }
}
D save --output "$out/images.tar" @($mapping.Values)
Write-Host "Portable staging created: $out . Complete validation and generate SHA256SUMS before transfer."
