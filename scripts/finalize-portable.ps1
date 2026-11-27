param([string]$Package = 'releases/Intelligent-VMS-0.1.0-rc3-portable')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $Package).Path
if (!(Test-Path "$root/VALIDATION.md") -or !(Test-Path "$root/images.tar")) { throw 'Validation evidence and exported images required.' }
foreach ($file in Get-ChildItem $root -Recurse -File) {
    if ($file.Name -in @('.env.production','validation.env','private.env','privkey.pem') -or $file.Extension -in @('.mp4','.dump','.key')) { throw "Private file in package: $($file.Name)" }
}
$sums = Get-ChildItem $root -Recurse -File | Where-Object {$_.Name -ne 'SHA256SUMS'} | Sort-Object FullName | ForEach-Object {
    (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $_.FullName.Substring($root.Length+1).Replace('\','/')
}
[IO.File]::WriteAllLines("$root/SHA256SUMS",$sums,[Text.UTF8Encoding]::new($false))
$archive = "$root.tar"
if (Test-Path $archive) { throw 'Archive exists; preserve it and choose a new output.' }
tar -cf $archive -C (Split-Path $root -Parent) (Split-Path $root -Leaf)
if ($LASTEXITCODE -ne 0) { throw 'Outer archive creation failed.' }
$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$archive.sha256",$hash+'  '+(Split-Path $archive -Leaf)+"`n",[Text.UTF8Encoding]::new($false))
[pscustomobject]@{Path=$archive;Bytes=(Get-Item $archive).Length;SHA256=$hash} | ConvertTo-Json
