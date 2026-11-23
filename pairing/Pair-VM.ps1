$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& node.exe .\pair-vm.cjs
if ($LASTEXITCODE -ne 0) { exit 1 }
