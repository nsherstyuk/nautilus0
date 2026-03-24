# ============================================================
# Paper Trading Launch Script -- Updated 2026-03-23
#
# Process 1: V6 ORB -- XAUUSD no BE, skip Wed (client_id=60)
# Process 2: V8 Confirmed Rebreak -- XAUUSD pw=120 (client_id=70)
# Process 3: V8 Confirmed Rebreak -- EURUSD pw=120 (client_id=71)
# Process 4: V8 Confirmed Rebreak -- USDJPY pw=120 (client_id=72)
# Process 5: V8 Confirmed Rebreak -- GBPUSD pw=120 (client_id=73)
#
# Prerequisites:
#   - IB Gateway running on port 4002 (paper account)
#   - Python venv at .venv312 with all deps
# ============================================================

$ROOT = "C:\nautilus0"
$PYTHON = "$ROOT\.venv312\Scripts\python.exe"

Write-Host "=" * 65
Write-Host "  Paper Trading Launch"
Write-Host "  V6 XAUUSD + V8 XAUUSD + V8 EURUSD + V8 USDJPY + V8 GBPUSD"
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "=" * 65

# ── Process 1: V6 ORB on XAUUSD ──────────────────────────────
# Config from v5_xauusd_orb/config.yaml instruments.XAUUSD section
# be_hours=999 (disabled), skip Wed, velocity on
Write-Host "`n[1/5] Starting V6 ORB -- XAUUSD ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v6_orb_refactor.live.run_live --instrument XAUUSD" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Process 2: V8 Confirmed Rebreak on XAUUSD ────────────────
# pw=120 (walk-forward validated: IS picks pw=120 in 5/6 windows, OOS +3.08)
# min_ticks=50 (WF-validated config, IBKR gets ~60 ticks/bar)
Write-Host "[2/5] Starting V8 Rebreak -- XAUUSD pw=120 ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v8_confirmed_rebreak.live.run_live --client-id 70 --symbol XAUUSD --sec-type CMDTY --exchange SMART --pw 120 --min-ticks 50 --tick-size 0.01 --spread-cost 0.30" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Process 3: V8 Confirmed Rebreak on EURUSD ────────────────
# pw=120 (walk-forward validated: IS picks pw=120 in 4/6 windows, OOS +3.96)
# min_ticks=30 (WF-validated, IBKR gets ~60 ticks/bar)
# EURUSD on IBKR: symbol=EUR, secType=CASH, exchange=IDEALPRO
Write-Host "[3/5] Starting V8 Rebreak -- EURUSD pw=120 ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v8_confirmed_rebreak.live.run_live --client-id 71 --symbol EUR --sec-type CASH --exchange IDEALPRO --pw 120 --min-ticks 30 --tick-size 0.00005 --spread-cost 0.00010 --qty 20000" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Process 4: V8 Confirmed Rebreak on USDJPY ────────────────
# pw=120 (Claude research: Sharpe +2.91, strongest next pair)
# min_ticks=30 (WF-validated, spread=0.015)
# USDJPY on IBKR: symbol=USD, secType=CASH, exchange=IDEALPRO, currency=JPY
Write-Host "[4/5] Starting V8 Rebreak -- USDJPY pw=120 ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v8_confirmed_rebreak.live.run_live --client-id 72 --symbol USD --sec-type CASH --exchange IDEALPRO --currency JPY --pw 120 --min-ticks 30 --tick-size 0.005 --spread-cost 0.015 --qty 20000" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Process 5: V8 Confirmed Rebreak on GBPUSD ────────────────
# pw=120 (WF: avg OOS Sharpe +1.84, 6/6 positive, IS picks pw=120 in 5/6)
# min_ticks=30 (WF-validated, spread=0.00012)
# GBPUSD on IBKR: symbol=GBP, secType=CASH, exchange=IDEALPRO
Write-Host "[5/5] Starting V8 Rebreak -- GBPUSD pw=120 ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v8_confirmed_rebreak.live.run_live --client-id 73 --symbol GBP --sec-type CASH --exchange IDEALPRO --pw 120 --min-ticks 30 --tick-size 0.00005 --spread-cost 0.00012 --qty 20000" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Write-Host "`nAll 5 processes launched (LIVE mode -- paper account)."
Write-Host ""
Write-Host "To monitor:"
Write-Host "  V6 XAUUSD log: v6_orb_refactor\logs\orb_xauusd_live.log"
Write-Host "  V8 XAUUSD log: v8_confirmed_rebreak\live\logs\v8_live_xauusd_*.log"
Write-Host "  V8 EURUSD log: v8_confirmed_rebreak\live\logs\v8_live_eurusd_*.log"
Write-Host "  V8 USDJPY log: v8_confirmed_rebreak\live\logs\v8_live_usdjpy_*.log"
Write-Host "  V8 GBPUSD log: v8_confirmed_rebreak\live\logs\v8_live_gbpusd_*.log"
