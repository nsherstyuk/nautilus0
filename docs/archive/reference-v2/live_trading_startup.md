# Live Trading Startup - Ready for Sunday Evening

## Configuration Status: ✅ READY

Your live trading environment is now configured for parity diagnostics. When you start trading Sunday evening, it will:

1. **Capture Parity Snapshots** when live reaches `2026-02-20 05:15:00 UTC`
   - Features 15m DataFrame → `parity_snapshots/features_15m_live_20260220_051500.csv`
   - Features 30m DataFrame → `parity_snapshots/features_30m_live_20260220_051500.csv`
   - Bar delivery counts → `parity_snapshots/bar_delivery_live_20260220_051500.csv`

2. **Log DMI Parity Data** for comparison with backtest DMI+ values

## Quick Start (Sunday Evening)

### Option 1: Use the Startup Script (Recommended)
```powershell
cd c:\nautilus0
.\start_live_trading.ps1
```

The script will:
- ✅ Check IBKR Gateway/TWS connection
- ✅ Kill any existing live trading processes
- ✅ Verify parity diagnostics are configured
- ✅ Start the supervisor with live monitoring

### Option 2: Manual Start
```powershell
cd c:\nautilus0
python live/run_live_mtf_v2_entry_confirmed_adaptive_failsafe_supervisor.py
```

## Prerequisites

Before starting:
1. **IBKR Gateway/TWS must be running** and accepting API connections on port 4002
2. **Markets must be open** (Sunday 5 PM EST / 10 PM UTC onwards)

## What Happens Next

### Immediate (upon start)
- Supervisor starts child process
- Strategy connects to IBKR
- Strategy enters warmup period (needs 500+ 15m bars)

### When Live Reaches 2026-02-20 05:15 UTC
- **Automatic snapshot export** triggered
- Log message: `[PARITY_SNAPSHOT] Exported features_15m to ...`
- Three CSV files written to `parity_snapshots/` directory

### After Snapshot Capture
- Run parity comparison to identify divergence:
  ```powershell
  python scripts/compare_feature_snapshots.py
  ```
- This will compare live vs replay snapshots and report first diverging feature/timestamp

## Monitoring Live Trading

### Check if running:
```powershell
Get-Process python | Where-Object { $_.CommandLine -like '*run_live_mtf_v2*' }
```

### View recent logs:
```powershell
Get-ChildItem logs\live_mtf\*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 50
```

### Check for snapshot files:
```powershell
Get-ChildItem parity_snapshots\*_live_*.csv
```

## Troubleshooting

### IBKR Connection Refused
- Start IBKR Gateway or TWS
- Verify API settings:
  - Socket port: **4002**
  - Enable ActiveX and Socket Clients: **✓**
  - Read-Only API: **✗** (unchecked)
  - Master API Client ID: (leave blank or use 25)

### Snapshot Not Captured
- Check logs for `[PARITY_DEBUG] Snapshot export enabled at ...` message on startup
- Verify timestamp in `.env.mtf_v2`: `MTF2_PARITY_SNAPSHOT_TS=2026-02-20T05:15:00+00:00`
- Ensure live trading reaches that timestamp (wait ~6 hours after Sunday 10 PM UTC restart)

### Process Keeps Restarting
- Check child process logs in `logs/live_mtf/run_live_mtf_*.log`
- Common causes:
  - IBKR connection lost
  - Data feed issue
  - Model file missing

## Next Steps After Snapshot Capture

1. **Compare snapshots:**
   ```powershell
   python scripts/compare_feature_snapshots.py
   ```

2. **Review divergence report** - identifies first feature that differs between live and replay

3. **Implement idempotency fix** based on findings:
   - If bar double-delivery is confirmed as root cause
   - Skip already-processed bars in `on_bar()` method
   - Re-test parity improvement

## Files Modified

- **`.env.mtf_v2`**: Added parity diagnostic settings
  - `MTF2_PARITY_SNAPSHOT_TS=2026-02-20T05:15:00+00:00`
  - `MTF2_DMI_PARITY_DEBUG=1`

- **`start_live_trading.ps1`**: Created startup script with pre-flight checks

- **Strategy code**: Already updated with feature snapshot export logic
  - `strategies/ml_strategy_mtf_v2_entry_confirmed_adaptive_failsafe.py`

## Replay Snapshots (Already Generated)

For comparison reference, replay snapshots are ready:
- `parity_snapshots/features_15m_replay_20260220_051500.csv` (2113 rows, OHLC + hl2)
- `parity_snapshots/features_30m_replay_20260220_051500.csv` (50 rows, OHLC + adx/dmp/dmn)
- `parity_snapshots/bar_delivery_replay_20260220_051500.csv` (2113 bars, delivery counts)

---

**Status**: Ready to start Sunday evening when markets reopen 🚀
