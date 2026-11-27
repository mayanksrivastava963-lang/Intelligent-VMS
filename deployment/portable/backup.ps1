param([Parameter(Mandatory=$true)][string]$Destination, [string]$SourceEnvironment)
. "$PSScriptRoot/common.ps1"
Guard
if (Test-Path $Destination) { throw 'Choose a new private backup directory.' }
New-Item -ItemType Directory $Destination | Out-Null
$dest = (Resolve-Path $Destination).Path
if ($env:OS -eq 'Windows_NT') {
    & icacls $dest /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict private backup permissions.' }
} else { & chmod 700 $dest; if ($LASTEXITCODE -ne 0) { throw 'Cannot secure backup directory.' } }
Write-Host 'Stopping application writers for a consistent database + recordings backup. Services stay stopped; restart explicitly afterwards.'
if ($SourceEnvironment) {
    $config = (Resolve-Path $SourceEnvironment).Path
    $projectLine = Get-Content $config | Where-Object {$_ -match '^COMPOSE_PROJECT_NAME='}
    $project = ($projectLine -split '=',2)[1].Trim().Trim("'",'"')
    if (!$project -or $project -notmatch '^[a-z0-9_-]+$') { throw 'Invalid source project.' }
    $writers = @(D ps -q --filter "label=com.docker.compose.project=$project" | ForEach-Object {
        $metadata = @(D inspect $_ | ConvertFrom-Json)[0]
        $service = $metadata.Config.Labels.'com.docker.compose.service'
        if ($service -notin @('postgres','validation-db','redis','mediamtx','synthetic-source')) { $_ }
    })
    if ($writers.Count) { D stop --time 60 @writers }
    $pg = D ps -q --filter "label=com.docker.compose.project=$project" --filter 'ancestor=postgres:18-alpine'
    $api = D ps -aq --filter "label=com.docker.compose.project=$project" --filter 'label=com.docker.compose.service=recording-api'
    if (@($pg).Count -ne 1 -or @($api).Count -ne 1 -or !$api -or !$pg) { throw 'Expected exactly one source API and PostgreSQL 18 container.' }
    $mounts = D inspect $api --format '{{json .Mounts}}' | ConvertFrom-Json
    $volume = @($mounts | Where-Object {$_.Destination -eq '/app/storage' -and $_.Type -eq 'volume'})
    if ($volume.Count -ne 1) { throw 'Source recording volume not found.' }
} else {
    $config = Join-Path $Root '.env.production'
    C stop --timeout 60 nginx recording-api rtsp-recorder storage-retention
    $pg = C ps -q postgres
}
if (!$pg) { throw 'Bundled PostgreSQL must be running.' }
D exec $pg sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/vms-transfer.dump'
D cp "${pg}:/tmp/vms-transfer.dump" "$dest/database.dump"
D exec $pg rm -f /tmp/vms-transfer.dump
if ($SourceEnvironment) {
    D run --rm --pull never --network none --memory 256m --user 0 --mount "type=volume,source=$($volume[0].Name),target=/app/storage,readonly" --mount "type=bind,source=$dest,target=/backup" intelligent-vms-portable/api:0.1.0-rc3 tar -czf /backup/recordings.tar.gz -C /app/storage .
} else {
    C run --rm --no-deps --pull never --user 0 -v "${dest}:/backup" --entrypoint tar recording-init -czf /backup/recordings.tar.gz -C /app/storage .
}
Copy-Item $config "$dest/private.env"
$records = Get-ChildItem $dest -File | ForEach-Object { @{name=$_.Name;sha256=(Get-FileHash $_.FullName).Hash} }
ConvertTo-Json -InputObject @($records) | Set-Content "$dest/backup-manifest.json"
Write-Host 'PRIVATE backup includes passwords, encryption secret, account data and recordings. Encrypt/protect the transfer media. TLS keys are not copied. Run start.ps1 to resume.'
