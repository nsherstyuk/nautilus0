# Session Handover — Feb 22, 2026 (Optimization Monitor)

## Status: Optimization RUNNING — DO NOT INTERRUPT

**PIDs (as of ~11:30 UTC):**
- PID 72460: `launch_sequential_optimization.py` (monitor/launcher)
- PID 71568: `optimize_sequential_all_groups.py` (child console, doing the work)

**Current position:** Group 1, combo 1/36 — started 11:25 UTC  
**Trace file:** `seq_opt_trace.txt` (last line: `before_run_backtest`)  
**No group CSVs yet** — combo 1 not yet complete (~55 min per combo expected)

---

## What Was Fixed This Session

### Bug 1: `TypeError: str expected, not float`
- Root cause: parameter grids use floats (e.g., `1.5`) but `os.environ.update()` requires strings
- Fix in [optimize_sequential_all_groups.py](optimize_sequential_all_groups.py):
  ```python
  env_vars.update({k: str(v) for k, v in fixed_env.items()})
  env_vars.update({k: str(v) for k, v in combo_env.items()})
  ```
- Also added global `try/except` in `__main__` block and diagnostic trace points to catch future errors

### Bug 2: Previous sessions kept dying silently
- NautilusTrader BacktestEngine requires a real TTY — hangs at 0% CPU if stdout is redirected
- **ONLY working launch pattern:** `python launch_sequential_optimization.py`
  - This spawns `optimize_sequential_all_groups.py` with `CREATE_NEW_CONSOLE`
  - Do NOT use `> file.log`, `| Add-Content`, or VS Code background terminals

---

## Optimizer Configuration

| Setting | Value |
|---|---|
| Script | `optimize_sequential_all_groups.py` |
| Launcher | `launch_sequential_optimization.py` |
| START_DATE | 2025-01-01 |
| END_DATE | 2026-02-08 |
| Model | `models/ml_model_mtf_v3_xgb.pkl` (retrained today, SL/TP-aware labels) |
| Score formula | `avg_trade×10×0.4 + (WR-0.5)×200×0.3 - (abs_DD/1000)×100×0.3` |
| CLEANUP_RESULTS | True (backtest dirs deleted after each combo) |

### Groups
| # | Name | File | Combos | Grid |
|---|---|---|---|---|
| 1 | SL/TP/MAMA | `opt_group1_sl_tp_mama_20260222.csv` | 36 | SL×[1.5,2.0,2.5] × TP1×[1.2,1.5,1.8] × TP2×[2.0,3.0] × MAMA×[0.0001,0.0002] |
| 2 | Pred Thresholds | `opt_group2_pred_thresholds_20260222.csv` | 16 | LONG_TH×[0.65,0.70,0.75,0.80] × SHORT_TH×[0.60,0.65,0.70,0.75] |
| 3 | Entry Confirm | `opt_group3_entry_confirm_20260222.csv` | 12 | BARS×[1,2,3] × THRESHOLD×[0.10,0.15,0.22,0.30] |
| 4 | ATR Gate | `opt_group4_atr_gate_20260222.csv` | 12 | MIN_ATR×[0.00018,0.00022,0.00025,0.00030] × MAX_ATR×[0.003,0.004,0.005] |
| **Total** | | | **76** | **~70h total** |

Each group uses best params from all previous groups as fixed baseline.

---

## How to Monitor Progress

```powershell
# Quick status check
Get-Content seq_opt_trace.txt -Tail 5
Get-ChildItem opt_group*.csv -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name): $((Import-Csv $_.FullName | Measure-Object).Count) rows" }
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\.exe)?$' } | ForEach-Object { "PID $($_.ProcessId)" }
```

---

## If Optimizer Died — How to Restart (resume-safe)

```powershell
# Check if dead
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\.exe)?$' }

# Restart — resume logic is built in, will skip completed combos
python launch_sequential_optimization.py
```

The optimizer resumes automatically from existing CSV rows — do NOT delete group CSVs unless starting completely fresh.

---

## After ALL Groups Complete

1. Read `opt_final_params_20260222.txt` for the optimal parameter set
2. Apply to `.env.mtf_v2`:
   - `MTF2_SL_ATR_MULT`
   - `MTF2_POS1_TP_ATR_MULT`
   - `MTF2_POS2_TP_ATR_MULT`
   - `MTF2_META_FILTER_MAMA_MIN_DIFF`
   - `MTF2_PREDICTION_THRESHOLD_LONG`
   - `MTF2_PREDICTION_THRESHOLD_SHORT`
   - `MTF2_ENTRY_CONFIRM_BARS`
   - `MTF2_ENTRY_CONFIRM_THRESHOLD`
   - `MTF2_MIN_ATR`
   - `MTF2_MAX_ATR`
3. Run OOS validation backtest on held-out window `2026-02-08` → `2026-02-22`
4. Only then restart live trading via `python live/run_live_mtf_v2_entry_confirmed_adaptive_failsafe_supervisor.py`
