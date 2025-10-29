# Launch minimal live IBKR trader with baseline config
# Safety: this will ENABLE order execution if ORDER_EXEC_ENABLED=1 in the env file.
# Toggle to paper/no-order by setting ORDER_EXEC_ENABLED to 0 in the env JSON.

$ErrorActionPreference = 'Stop'

# Resolve script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Choose the env file
$envFile = Join-Path $scriptDir 'env.minimal_baseline.json'

if (-not (Test-Path $envFile)) {
  Write-Host "Env file not found: $envFile" -ForegroundColor Red
  exit 1
}

# Point live_ibkr_trader.py to the env file
$env:TRADER_ENV_FILE = $envFile

Write-Host "Using TRADER_ENV_FILE=$envFile" -ForegroundColor Cyan

# Start the live trader (unbuffered output)
python -u (Join-Path $scriptDir 'live_ibkr_trader.py')
