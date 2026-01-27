# Restart Live Entry Confirmed with FAIL-SAFE Trading
# This script stops the current fail-safe live runner, toggles debug off, and restarts it

Write-Host "Restarting Live Entry Confirmed with FAIL-SAFE..." -ForegroundColor Cyan

# Stop any running live runner processes
Write-Host "Stopping running live processes..." -ForegroundColor Yellow
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*run_live_mtf_v2_entry_confirmed_v2_failsafe*" -or
    $_.CommandLine -like "*run_live_mtf_v2_entry_confirmed_v2_supervisor_failsafe*"
} | ForEach-Object {
    Write-Host "  Stopping PID $($_.Id)..." -ForegroundColor Yellow
    Stop-Process -Id $_.Id -Force
}

Start-Sleep -Seconds 2

# Toggle debug off to ensure clean console logging
Write-Host "Setting console log level to INFO..." -ForegroundColor Yellow
python scripts\toggle_debug.py off

Start-Sleep -Seconds 1

# Start the fail-safe supervisor
Write-Host "Starting fail-safe live runner with supervisor..." -ForegroundColor Green
Start-Process python -ArgumentList "live\run_live_mtf_v2_entry_confirmed_v2_supervisor_failsafe.py" -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "FAIL-SAFE Live runner restarted!" -ForegroundColor Green
Write-Host "Features enabled:" -ForegroundColor Cyan
Write-Host "  - Entry confirmation using 1m bars" -ForegroundColor White
Write-Host "  - 30-second grace period after order submission" -ForegroundColor White
Write-Host "  - 3 consecutive failed protection checks required" -ForegroundColor White
Write-Host "  - Periodic health monitoring every 15m bar" -ForegroundColor White
Write-Host "  - Emergency flatten if SL/TP orders missing" -ForegroundColor White
Write-Host ""
Write-Host "Check logs in: logs\live_mtf\application.log" -ForegroundColor Yellow
