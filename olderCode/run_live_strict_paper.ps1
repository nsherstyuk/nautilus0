# Launch strict config in PAPER mode (order behavior follows env.strict_paper.json; currently ENABLED)
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $scriptDir 'env.strict_paper.json'

if (-not (Test-Path $envFile)) {
  Write-Host "Env file not found: $envFile" -ForegroundColor Red
  exit 1
}

$env:TRADER_ENV_FILE = $envFile
Write-Host "Using TRADER_ENV_FILE=$envFile" -ForegroundColor Cyan

python -u (Join-Path $scriptDir 'live_ibkr_trader.py')
