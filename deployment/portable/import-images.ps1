. "$PSScriptRoot/common.ps1"
Guard
Verify-Files
D load --input images.tar
foreach ($entry in (Get-Content images.json -Raw | ConvertFrom-Json)) {
    $actual = D image inspect $entry.tag --format '{{.Id}}'
    if ($actual -ne $entry.id) { throw "Image identity mismatch: $($entry.tag)" }
}
Write-Host 'Images imported and exact identities verified. No rebuild required.'
