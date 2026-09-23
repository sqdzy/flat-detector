param(
    [Parameter(Mandatory = $true)]
    [string]$SearchUrl,
    [ValidateSet("msedge", "chrome", "chromium")]
    [string]$Channel = "msedge"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$Venv = Join-Path $RepoRoot ".venv-avito-probe"
$Python = Join-Path $Venv "Scripts\python.exe"
$Profile = Join-Path $env:LOCALAPPDATA "FlatDetector\AvitoProfile"

if (-not (Test-Path $Python)) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $Launcher) { & py -3 -m venv $Venv } else { & python -m venv $Venv }
}

& $Python -m pip install --disable-pip-version-check --quiet "playwright==1.59.0"
if ($Channel -eq "chromium") { & $Python -m playwright install chromium }

Write-Host "Launching one local read-only Avito probe."
Write-Host "Profile: $Profile"
Write-Host "Channel: $Channel"
Write-Host "No database or Telegram credentials are used."

& $Python -m flat_detector.avito_browser --url $SearchUrl --profile-dir $Profile --channel $Channel --headed --manual-wait --limit 20
exit $LASTEXITCODE
