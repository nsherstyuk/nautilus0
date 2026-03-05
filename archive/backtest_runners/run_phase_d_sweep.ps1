# Phase D Sequential Sweep - Ultra-selective configurations
Write-Host "Starting Phase D Sweep - Testing ultra-selective configurations" -ForegroundColor Cyan
Write-Host "Expected runtime: ~2 hours (20-30 min per config)" -ForegroundColor Yellow
Write-Host ""

$configs = @(
    @{Name='D1'; Threshold='0.00050'; SL='2.0'; TP='1.2'},
    @{Name='D2'; Threshold='0.00060'; SL='2.0'; TP='1.5'},
    @{Name='D3'; Threshold='0.00060'; SL='2.5'; TP='1.5'},
    @{Name='D4'; Threshold='0.00070'; SL='2.5'; TP='2.0'},
    @{Name='D5'; Threshold='0.00080'; SL='3.0'; TP='2.0'}
)

$envFile = '.env.mtf_v2'
$backup = '.env.mtf_v2.backup_phased'

# Backup original config
Copy-Item $envFile $backup -Force
Write-Host "Backed up original .env.mtf_v2 -> $backup" -ForegroundColor Green

foreach ($cfg in $configs) {
    $startTime = Get-Date
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "Running $($cfg.Name): XPair Threshold=$($cfg.Threshold), SL=$($cfg.SL)x ATR, TP=$($cfg.TP)x ATR" -ForegroundColor Yellow
    Write-Host "Started: $($startTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Gray
    Write-Host "========================================`n" -ForegroundColor Cyan
    
    # Modify .env.mtf_v2 with current config
    $content = Get-Content $envFile
    $content = $content -replace 'MTF2_XPAIR_STRENGTH_THRESHOLD=.*', "MTF2_XPAIR_STRENGTH_THRESHOLD=$($cfg.Threshold)"
    $content = $content -replace 'MTF2_SL_ATR_MULT=.*', "MTF2_SL_ATR_MULT=$($cfg.SL)"
    $content = $content -replace 'MTF2_POS1_TP_ATR_MULT=.*', "MTF2_POS1_TP_ATR_MULT=$($cfg.TP)"
    $content | Set-Content $envFile -Force
    
    # Run backtest
    python run_backtest_mtf_v2_entry_confirmed_adaptive.py
    
    $endTime = Get-Date
    $elapsed = $endTime - $startTime
    Write-Host "`n$($cfg.Name) completed in $([math]::Round($elapsed.TotalMinutes, 1)) minutes" -ForegroundColor Green
}

# Restore original config
Copy-Item $backup $envFile -Force
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "All Phase D runs complete!" -ForegroundColor Green
Write-Host "Original .env.mtf_v2 restored from backup" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
