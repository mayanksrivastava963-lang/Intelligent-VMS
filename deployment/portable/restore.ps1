param([Parameter(Mandatory=$true)][string]$Source)
. "$PSScriptRoot/common.ps1"
Guard
$src = (Resolve-Path $Source).Path
foreach ($entry in (Get-Content "$src/backup-manifest.json" -Raw | ConvertFrom-Json)) {
    if ($entry.name -notin @('database.dump','recordings.tar.gz','private.env')) { throw 'Unexpected backup file.' }
    if ((Get-FileHash (Join-Path $src $entry.name)).Hash -ne $entry.sha256) { throw "Backup checksum mismatch: $($entry.name)" }
}
foreach ($name in @('database.dump','recordings.tar.gz','private.env')) { if (!(Test-Path "$src/$name")) { throw "Missing $name" } }
if (@(C ps -aq).Count) { throw 'Restore requires a freshly configured installation, before its first start. Existing containers preserved.' }
if ((Read-Host 'Type RESTORE to import private data into this fresh installation') -cne 'RESTORE') { throw 'Cancelled.' }
# Preserve fresh destination DB/TLS/network settings, but restore the source encryption key.
$secretLine = Get-Content "$src/private.env" | Where-Object { $_ -match '^VMS_SESSION_SECRET=' }
if (@($secretLine).Count -ne 1) { throw 'Source encryption key missing or ambiguous.' }
$lines = Get-Content .env.production | ForEach-Object { if ($_ -match '^VMS_SESSION_SECRET=') { $secretLine } else { $_ } }
[IO.File]::WriteAllLines((Join-Path $Root '.env.production'),$lines,[Text.UTF8Encoding]::new($false))
C up -d --no-build --pull never --wait postgres
$pg = C ps -q postgres
# Refuse pre-existing database contents even if containers were previously removed.
$query = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"))
$tables = D exec $pg sh -c "echo $query | base64 -d | psql -U `$POSTGRES_USER -d `$POSTGRES_DB -At -v ON_ERROR_STOP=1"
if ($tables -notmatch '^0$') { throw 'Destination database is not empty or could not be verified. Restore refused.' }
$files = C run --rm --no-deps --pull never --user 0 --entrypoint find recording-init /app/storage -type f -print -quit
if ($files) { throw 'Destination recording storage is not empty.' }
D cp "$src/database.dump" "${pg}:/tmp/vms-transfer.dump"
D exec $pg sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --no-owner --no-acl --exit-on-error /tmp/vms-transfer.dump'
D exec $pg rm -f /tmp/vms-transfer.dump
C run --rm --no-deps --pull never --user 0 -v "${src}:/backup:ro" --entrypoint tar recording-init -xzf /backup/recordings.tar.gz -C /app/storage
Write-Host 'Restored. Run start.ps1. Existing account passwords apply; installer password does not override restored accounts. Review restored camera addresses before starting.'
