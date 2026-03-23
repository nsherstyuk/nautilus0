# ============================================================
# Paper Trading Launch Script — Sunday Night 2026-03-22
#
# Process 1: V6 ORB — XAUUSD no BE, skip Wed (client_id=60)
# Process 2: V8 Confirmed Rebreak — XAUUSD pw=60 (client_id=70)
# Process 3: V8 Confirmed Rebreak — EURUSD pw=120 (client_id=71)
#
# Prerequisites:
#   - IB Gateway running on port 4002 (paper account)
#   - Python venv at .venv312 with all deps
# ============================================================

$ROOT = "C:\nautilus0"
$PYTHON = "$ROOT\.venv312\Scripts\python.exe"

Write-Host "=" * 65
Write-Host "  Paper Trading Launch"
Write-Host "  V6 XAUUSD + V8 XAUUSD + V8 EURUSD"
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "=" * 65

# ── Process 1: V6 ORB on XAUUSD ──────────────────────────────
# Config from v5_xauusd_orb/config.yaml instruments.XAUUSD section
# be_hours=999 (disabled), skip Wed, velocity on
Write-Host "`n[1/3] Starting V6 ORB — XAUUSD (dry-run) ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v6_orb_refactor.live.run_live --instrument XAUUSD" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Process 2: V8 Confirmed Rebreak on XAUUSD ────────────────
# pw=120 (walk-forward validated: IS picks pw=120 in 5/6 windows, OOS +3.08)
# min_ticks=15 (WF-validated config)
Write-Host "[2/3] Starting V8 Rebreak — XAUUSD pw=120 (dry-run) ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v8_confirmed_rebreak.live.run_live --client-id 70 --symbol XAUUSD --sec-type CMDTY --exchange SMART --pw 120 --min-ticks 15" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Process 3: V8 Confirmed Rebreak on EURUSD ────────────────
# pw=120 (walk-forward validated: IS picks pw=120 in 4/6 windows, OOS +3.96)
# min_ticks=75 (WF-validated: stricter quality filter for EUR)
# EURUSD on IBKR: symbol=EUR, secType=CASH, exchange=IDEALPRO
Write-Host "[3/3] Starting V8 Rebreak — EURUSD pw=120 (dry-run) ..."
Start-Process -FilePath $PYTHON `
    -ArgumentList "-m v8_confirmed_rebreak.live.run_live --client-id 71 --symbol EUR --sec-type CASH --exchange IDEALPRO --pw 120 --min-ticks 75 --qty 20000" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Write-Host "`nAll 3 processes launched (LIVE mode — paper account)."
Write-Host ""
Write-Host "To monitor:"
Write-Host "  V6 XAUUSD log: v6_orb_refactor\logs\orb_xauusd_live.log"
Write-Host "  V8 XAUUSD log: v8_confirmed_rebreak\live\logs\v8_live_*.log"
Write-Host "  V8 EURUSD log: v8_confirmed_rebreak\live\logs\v8_live_*.log"
