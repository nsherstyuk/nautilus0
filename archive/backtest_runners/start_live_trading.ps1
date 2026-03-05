#!/usr/bin/env pwsh
# Start Live MTF V2 Trading with Parity Diagnostics
# Run this when markets reopen Sunday evening

Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "Starting Live MTF V2 Trading (Adaptive Entry Confirmed + Fail-Safe)" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# Check if IBKR Gateway/TWS is running
Write-Host "[1/4] Checking IBKR connection..." -ForegroundColor Yellow
$ibkrPort = 4002  # From .env.mtf_v2
try {
    $connection = Test-NetConnection -ComputerName 127.0.0.1 -Port $ibkrPort -WarningAction SilentlyContinue
    if ($connection.TcpTestSucceeded) {
        Write-Host "  ✓ IBKR Gateway/TWS is accessible on port $ibkrPort" -ForegroundColor Green
    } else {
        Write-Host "  ✗ IBKR Gateway/TWS is NOT accessible on port $ibkrPort" -ForegroundColor Red
        Write-Host "    Please start IBKR Gateway or TWS before running live trading" -ForegroundColor Red
        Write-Host ""
        $continue = Read-Host "Continue anyway? (y/N)"
        if ($continue -ne "y" -and $continue -ne "Y") {
            exit 1
        }
    }
} catch {
    Write-Host "  ⚠ Could not verify IBKR connection" -ForegroundColor Yellow
}
Write-Host ""

# Check for existing live trading processes
Write-Host "[2/4] Checking for existing live trading processes..." -ForegroundColor Yellow
$existingProcs = Get-CimInstance Win32_Process | Where-Object { 
    $_.Name -match '^python(\.exe)?$' -and 
    $_.CommandLine -match 'run_live_mtf_v2_entry_confirmed_adaptive_failsafe(_supervisor)?\.py' 
}

if ($existingProcs.Count -gt 0) {
    Write-Host "  ✗ Found $($existingProcs.Count) existing live trading process(es)" -ForegroundColor Red
    Write-Host "    PIDs: $($existingProcs.ProcessId -join ', ')" -ForegroundColor Red
    Write-Host ""
    $kill = Read-Host "Kill existing processes and start fresh? (y/N)"
    if ($kill -eq "y" -or $kill -eq "Y") {
        foreach ($p in $existingProcs) {
            Write-Host "  Stopping PID $($p.ProcessId)..." -ForegroundColor Yellow
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        Write-Host "  ✓ Existing processes stopped" -ForegroundColor Green
    } else {
        Write-Host "  Aborting - please stop existing processes manually" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  ✓ No existing live trading processes found" -ForegroundColor Green
}
Write-Host ""

# Verify parity diagnostics are configured
Write-Host "[3/4] Verifying parity diagnostics configuration..." -ForegroundColor Yellow
$envFile = "c:\nautilus0\.env.mtf_v2"
$snapshotTs = Select-String -Path $envFile -Pattern "MTF2_PARITY_SNAPSHOT_TS" -Quiet
$dmiDebug = Select-String -Path $envFile -Pattern "MTF2_DMI_PARITY_DEBUG" -Quiet

if ($snapshotTs -and $dmiDebug) {
    Write-Host "  ✓ Parity diagnostics enabled in .env.mtf_v2" -ForegroundColor Green
    $tsValue = (Select-String -Path $envFile -Pattern "MTF2_PARITY_SNAPSHOT_TS=(.+)" | 
                Select-Object -First 1).Matches.Groups[1].Value.Trim()
    Write-Host "    Snapshot timestamp: $tsValue" -ForegroundColor Cyan
    Write-Host "    When live reaches this timestamp, features will be exported to:" -ForegroundColor Cyan
    Write-Host "      - parity_snapshots/features_15m_live_*.csv" -ForegroundColor Cyan
    Write-Host "      - parity_snapshots/features_30m_live_*.csv" -ForegroundColor Cyan
    Write-Host "      - parity_snapshots/bar_delivery_live_*.csv" -ForegroundColor Cyan
} else {
    Write-Host "  ⚠ Parity diagnostics not fully configured" -ForegroundColor Yellow
    Write-Host "    (This is optional - trading will still work)" -ForegroundColor Yellow
}
Write-Host ""

# Start the supervisor
Write-Host "[4/4] Starting live trading supervisor..." -ForegroundColor Yellow
Write-Host "  Logs will be written to: logs/live_mtf/" -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop trading (will shut down gracefully)" -ForegroundColor Cyan
Write-Host ""
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "STARTING NOW" -ForegroundColor Green -BackgroundColor Black
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# Start the supervisor (foreground mode for user visibility)
python live/run_live_mtf_v2_entry_confirmed_adaptive_failsafe_supervisor.py
