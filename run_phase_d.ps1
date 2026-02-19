# Phase D Sequential Sweep - Simplified
$configs = @(
    @{Name='D1'; Threshold='0.00050'; SL='2.0'; TP='1.2'},
    @{Name='D2'; Threshold='0.00060'; SL='2.0'; TP='1.5'},
    @{Name='D3'; Threshold='0.00060'; SL='2.5'; TP='1.5'},
    @{Name='D4'; Threshold='0.00070'; SL='2.5'; TP='2.0'},
    @{Name='D5'; Threshold='0.00080'; SL='3.0'; TP='2.0'}
)

$envFile = '.env.mtf_v2'
$backup = '.env.mtf_v2.backup_phased'
Copy-Item $envFile $backup

Write-Host 'Starting Phase D Sweep - 5 configurations' -ForegroundColor Cyan
Write-Host 'This will take approximately 60-75 minutes total' -ForegroundColor Yellow
Write-Host ''

foreach ($cfg in $configs) {
    Write-Host "=== Running $($cfg.Name): Threshold=$($cfg.Threshold), SL=$($cfg.SL)x, TP=$($cfg.TP)x ===" -ForegroundColor Yellow
    
    $env = Get-Content $envFile
    $env = $env -replace 'MTF2_XPAIR_STRENGTH_THRESHOLD=.*', "MTF2_XPAIR_STRENGTH_THRESHOLD=$($cfg.Threshold)"
    $env = $env -replace 'MTF2_SL_ATR_MULT=[ ]*[0-9.]+', "MTF2_SL_ATR_MULT=$($cfg.SL)"
    $env = $env -replace 'MTF2_POS1_TP_ATR_MULT=[ ]*[0-9.]+', "MTF2_POS1_TP_ATR_MULT=$($cfg.TP)"
    $env | Set-Content $envFile
    
    $start = Get-Date
    python run_backtest_mtf_v2_entry_confirmed_adaptive.py
    $duration = ((Get-Date) - $start).TotalMinutes
    
    Write-Host "Completed $($cfg.Name) in $([math]::Round($duration, 1)) minutes" -ForegroundColor Green
    Write-Host ''
}

Copy-Item $backup $envFile -Force
Write-Host "All runs complete! Original .env restored" -ForegroundColor Green
