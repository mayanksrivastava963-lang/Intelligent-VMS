. "$PSScriptRoot/common.ps1"
C ps --all
$ids = @(C ps -q)
if ($ids.Count) { D stats --no-stream @ids }
