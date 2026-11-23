$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Run-Npm([string[]]$Arguments) {
    & npm.cmd @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'npm dependency installation failed.' }
}
function Run-Wrangler([string[]]$Arguments) {
    & node.exe "$PSScriptRoot\node_modules\wrangler\bin\wrangler.js" @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Cloudflare command failed. Stop and review its error.' }
}
try {
    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) { throw 'Install Node.js LTS from https://nodejs.org/ then reopen PowerShell.' }
    $NodeVersion = (& node.exe --version | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0 -or $NodeVersion -notmatch '^v(\d+)\.') { throw 'Cannot read Node.js version.' }
    $Major = [int]$Matches[1]
    if ($Major -lt 22) { throw 'Node.js 22 or newer is required. Install the current LTS.' }
    Write-Host 'This updates your existing anima Worker and creates its SQLite Durable Object.'
    Write-Host 'It does not upgrade plans. Stop unless this account is Workers Free.'
    if ((Read-Host 'Type FREE to confirm Workers Free') -cne 'FREE') { throw 'Free plan not confirmed.' }
    $Account = (Read-Host 'Paste the Cloudflare Account ID (32 hexadecimal characters, NOT a token)').Trim()
    if ($Account -notmatch '^[0-9a-fA-F]{32}$') { throw 'Invalid Account ID.' }
    $Config = Get-Content -Raw wrangler.jsonc | ConvertFrom-Json
    $Config | Add-Member -NotePropertyName account_id -NotePropertyValue $Account -Force
    $Config | ConvertTo-Json -Depth 12 | Set-Content -Encoding ASCII wrangler.jsonc
    Run-Npm -Arguments @('ci', '--ignore-scripts')
    Run-Wrangler -Arguments @('login')
    Run-Wrangler -Arguments @('whoami')
    Write-Host 'Check the displayed account matches the intended account.'
    if ((Read-Host 'Type anima to authorize replacing ONLY the anima Worker with this relay') -cne 'anima') { throw 'Deployment canceled.' }
    Run-Wrangler -Arguments @('deploy', '--dry-run', '--outdir', '.dry-run')
    Run-Wrangler -Arguments @('deploy')
    # Independent application credentials. Reuse on repeat execution; never print.
    $Private = Join-Path $PSScriptRoot '.private'
    New-Item -ItemType Directory -Force $Private | Out-Null
    & icacls.exe $Private /inheritance:r /grant:r "$($env:USERDOMAIN)\$($env:USERNAME):(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict credential directory permissions.' }
    $KeysFile = Join-Path $Private 'relay-keys.json'
    if (-not (Test-Path $KeysFile)) {
        $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $A = New-Object byte[] 32; $B = New-Object byte[] 32
            $Rng.GetBytes($A); $Rng.GetBytes($B)
            @{CLIENT_KEY=[Convert]::ToBase64String($A); AGENT_KEY=[Convert]::ToBase64String($B)} | ConvertTo-Json | Set-Content -Encoding ASCII $KeysFile
        } finally { $Rng.Dispose() }
    }
    Run-Wrangler -Arguments @('secret', 'bulk', $KeysFile)
    $Keys = Get-Content -Raw $KeysFile | ConvertFrom-Json
    [IO.File]::WriteAllText((Join-Path $Private 'client.key'), $Keys.CLIENT_KEY)
    [IO.File]::WriteAllText((Join-Path $Private 'agent.key'), $Keys.AGENT_KEY)
    $Url = (Read-Host 'Paste the workers.dev URL printed by deploy (example https://anima.yourname.workers.dev)').Trim().TrimEnd('/')
    if ($Url -notmatch '^https://anima\.[a-z0-9-]+\.workers\.dev$') { throw 'Unexpected Worker URL.' }
    $Response = Invoke-RestMethod -Uri "$Url/healthz" -Headers @{Authorization="Bearer $($Keys.CLIENT_KEY)"} -TimeoutSec 30
    if ($Response.relay -ne 'READY') { throw 'Relay did not report READY.' }
    $Rejected = $false
    try { Invoke-WebRequest -UseBasicParsing -Uri "$Url/healthz" -Headers @{Authorization='Bearer deliberately-invalid-verification-value'} -TimeoutSec 30 | Out-Null }
    catch { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) { $Rejected=$true } else { throw } }
    if (-not $Rejected) { throw 'Wrong-key authentication test failed.' }
    [IO.File]::WriteAllText((Join-Path $Private 'relay-url.txt'), $Url)
    Write-Host "PASS: relay health 200 and wrong key 401 at $Url"
    Write-Host 'The image VM is NOT connected yet. No generation success is claimed.'
    Write-Host 'Keep .private files on this PC. Never post agent.key, client.key or OAuth data in chat.'
} catch {
    Write-Host ('STOP: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
