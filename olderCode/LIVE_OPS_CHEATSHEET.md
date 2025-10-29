# Live Ops Cheat Sheet (IBKR Paper, strict config)

All paths refer to `MINIMAL_LIVE_IBKR_TRADER_before/`.

## Launch

- __Option A (no policy change)__
```powershell
# From: C:\Users\nsher\Dropbox\Nick\TradingSystem\NewStart\TradingSystem\Trading-System\MINIMAL_LIVE_IBKR_TRADER_before
$env:TRADER_ENV_FILE = "$PWD\env.strict_live.json"
python -u .\live_ibkr_trader.py
```

- __Option B (use launcher script)__
```powershell
# Enable only for this session
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Start live (orders enabled to IBKR Paper)
.\run_live_strict_live.ps1

# Start with order submission DISABLED (dry run)
.\run_live_strict_paper.ps1
```

## Runtime controls (in the live console)
- S — start/stop trade loop
- P — status snapshot
- C — show current config
- R — reload config from TRADER_CONFIG file
- F — flatten (close all)
- buy — manual test buy
- sell — manual test sell
- Q — quit

Tip: Use P/R liberally when iterating; R re-reads `TRADER_CONFIG` without restart.

## Safety and configuration

- __Primary env files__:
  - Live orders: `env.strict_live.json` (has `"ORDER_EXEC_ENABLED": "1"`)
  - Dry run: `env.strict_paper.json` (has `"ORDER_EXEC_ENABLED": "0"`)
- __Strategy config__: `Nick3_timegated_strict_tp180_k04_ms08.json`
  - TP=180 micropips
  - ATR trailing: period=14, k=0.4, min_step=0.8
  - Time gating exclude_hours=[0, 11, 14, 16, 19, 20]
  - position_size=100000
- __IBKR connection__ (Paper TWS):
  - `IB_HOST=127.0.0.1`, `IB_PORT=7497`, `IB_CLIENT_ID=101`

## Monitoring

- __Console__: look for “Connected to IB TWS …” and “First tick received; streaming started”
- __IBKR TWS__: Orders and Trades tabs should populate when signals occur
- __Logs__: `C:\Users\nsher\Dropbox\Nick\TradingSystem\TradeLogs`
```powershell
Get-Content "C:\Users\nsher\Dropbox\Nick\TradingSystem\TradeLogs\*.log" -Tail 200 -Wait
```
- __State__: `C:\Users\nsher\Dropbox\Nick\TradingSystem\State`

## Best ET hours to prioritize
From `logs/sweeps/per_hour_4mo_crossmonth_tp180_k04_ms08_strict.csv`:
- Strong: 08, 09, 10, 12, 04, 06 ET
- Excluded by config: 0, 11, 14, 16, 19, 20 ET
- Optional: Pause with S during weaker hours (1, 21, 23, 17–18 ET)

## Stop / Restart

- __Normal stop__: press Q in console
- __Emergency stop (from another shell)__:
```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match '^python(\.exe)?$' -and 
  $_.CommandLine -match 'live_ibkr_trader\.py' -and 
  $_.CommandLine -match 'MINIMAL_LIVE_IBKR_TRADER_before'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
- __Restart with updated config__:
  - Edit `Nick3_timegated_strict_tp180_k04_ms08.json`
  - Press R in console to reload, or stop (Q) and relaunch

## Quick troubleshooting

- __Script won’t run__:
  - Use Option A launch (env var + python), or `Set-ExecutionPolicy -Scope Process Bypass`
- __No connection__:
  - Ensure TWS Paper is running; API enabled; port 7497; clientId not colliding
- __No ticks__:
  - Confirm market data subscriptions for EURUSD in TWS
- __Orders not appearing__:
  - Verify `ORDER_EXEC_ENABLED` = "1" in the active env file
  - Confirm env in current shell: `echo $env:TRADER_ENV_FILE`

## File references
- Runner: `MINIMAL_LIVE_IBKR_TRADER_before/live_ibkr_trader.py`
- Launchers: `run_live_strict_live.ps1`, `run_live_strict_paper.ps1`
- Envs: `env.strict_live.json`, `env.strict_paper.json`
- Strategy config: `Nick3_timegated_strict_tp180_k04_ms08.json`
