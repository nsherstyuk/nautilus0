# Phase E: Alternative Approaches
# Testing: 1) No cross-pair filter, 2) Time filtering, 3) Confidence zones

$envFile = '.env.mtf_v2'
$backup = '.env.mtf_v2.backup_phase_e'
Copy-Item $envFile $backup

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "PHASE E: ALTERNATIVE APPROACHES" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# E1: Classic V2 Pure (no cross-pair filter, $100k sizing)
Write-Host "`n=== E1: Classic V2 Pure (No Cross-Pair Filter) ===" -ForegroundColor Yellow
Write-Host "Config: Threshold=0.00030, SL=1.2x, TP=0.9x, Size=$100k, NO xpair filter" -ForegroundColor Gray
$env = Get-Content $envFile
$env = $env -replace 'MTF2_XPAIR_STRENGTH_THRESHOLD=.*', 'MTF2_XPAIR_STRENGTH_THRESHOLD=0.00030'
$env = $env -replace 'MTF2_SL_ATR_MULT=[ ]*[0-9.]+', 'MTF2_SL_ATR_MULT=1.2'
$env = $env -replace 'MTF2_POS1_TP_ATR_MULT=[ ]*[0-9.]+', 'MTF2_POS1_TP_ATR_MULT=0.9'
$env = $env -replace 'MTF2_TOTAL_POSITION_SIZE=[ ]*[0-9]+', 'MTF2_TOTAL_POSITION_SIZE=100000'
$env = $env -replace 'MTF2_ENABLE_XPAIR_USD_FILTER=.*', 'MTF2_ENABLE_XPAIR_USD_FILTER=False'
$env | Set-Content $envFile
$startTime = Get-Date
python run_backtest_mtf_v2_entry_confirmed_adaptive.py
$duration = ((Get-Date) - $startTime).TotalMinutes
Write-Host "E1 completed in $([math]::Round($duration, 1)) minutes`n" -ForegroundColor Green

# E2: Classic V2 + Time Filter (exclude worst hours)
Write-Host "`n=== E2: Classic V2 + Time Filter ===" -ForegroundColor Yellow
Write-Host "Config: Same as E1 but exclude hours: 21,22,23,01,03 EST" -ForegroundColor Gray
$env = Get-Content $envFile
$env = $env -replace 'MTF2_ENABLE_XPAIR_USD_FILTER=.*', 'MTF2_ENABLE_XPAIR_USD_FILTER=False'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_MODE=.*', 'MTF2_EXCLUDED_HOURS_MODE=weekday'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_MONDAY=.*', 'MTF2_EXCLUDED_HOURS_MONDAY=21,22,23,1,3'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_TUESDAY=.*', 'MTF2_EXCLUDED_HOURS_TUESDAY=21,22,23,1,3'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_WEDNESDAY=.*', 'MTF2_EXCLUDED_HOURS_WEDNESDAY=21,22,23,1,3'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_THURSDAY=.*', 'MTF2_EXCLUDED_HOURS_THURSDAY=21,22,23,1,3'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_FRIDAY=.*', 'MTF2_EXCLUDED_HOURS_FRIDAY=21,22,23,1,3'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_SATURDAY=.*', 'MTF2_EXCLUDED_HOURS_SATURDAY=21,22,23,1,3'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_SUNDAY=.*', 'MTF2_EXCLUDED_HOURS_SUNDAY=21,22,23,1,3'
$env | Set-Content $envFile
$startTime = Get-Date
python run_backtest_mtf_v2_entry_confirmed_adaptive.py
$duration = ((Get-Date) - $startTime).TotalMinutes
Write-Host "E2 completed in $([math]::Round($duration, 1)) minutes`n" -ForegroundColor Green

# E3: ML Confidence Zones (differential SL/TP based on confidence)
Write-Host "`n=== E3: ML Confidence Zones ===" -ForegroundColor Yellow
Write-Host "Config: High conf (>0.8) SL=2.0x/TP=1.5x, Low conf SL=1.2x/TP=0.6x (proven baseline)" -ForegroundColor Gray
$env = Get-Content $envFile
$env = $env -replace 'MTF2_ENABLE_XPAIR_USD_FILTER=.*', 'MTF2_ENABLE_XPAIR_USD_FILTER=False'
$env = $env -replace 'MTF2_EXCLUDED_HOURS_MODE=.*', 'MTF2_EXCLUDED_HOURS_MODE=disabled'
# High confidence: wider stops (trust the signal)
$env = $env -replace 'MTF2_CONF_HIGH_THRESH=.*', 'MTF2_CONF_HIGH_THRESH=0.80'
$env = $env -replace 'MTF2_CONF_HIGH_SL_MULT=.*', 'MTF2_CONF_HIGH_SL_MULT=2.0'
$env = $env -replace 'MTF2_CONF_HIGH_TP_MULT=.*', 'MTF2_CONF_HIGH_TP_MULT=1.5'
# Low confidence: proven baseline SL with quick TP
$env = $env -replace 'MTF2_CONF_LOW_THRESH=.*', 'MTF2_CONF_LOW_THRESH=0.65'
$env = $env -replace 'MTF2_CONF_LOW_SL_MULT=.*', 'MTF2_CONF_LOW_SL_MULT=1.2'
$env = $env -replace 'MTF2_CONF_LOW_TP_MULT=.*', 'MTF2_CONF_LOW_TP_MULT=0.6'
$env | Set-Content $envFile
$startTime = Get-Date
python run_backtest_mtf_v2_entry_confirmed_adaptive.py
$duration = ((Get-Date) - $startTime).TotalMinutes
Write-Host "E3 completed in $([math]::Round($duration, 1)) minutes`n" -ForegroundColor Green

# Restore original
Copy-Item $backup $envFile -Force
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "All Phase E experiments complete!" -ForegroundColor Green
Write-Host "Original .env.mtf_v2 restored" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green
