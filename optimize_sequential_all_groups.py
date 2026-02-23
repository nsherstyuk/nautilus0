#!/usr/bin/env python3
"""
Sequential Multi-Group Parameter Optimizer for MTF V2 Strategy.

Groups run in order; best parameters from each group are fixed for all subsequent groups.

  Group 1 — SL / TP / MAMA            :  3 × 3 × 2 × 2 = 36 combos  (~4 h)
  Group 2 — ML prediction thresholds  :  4 × 4          = 16 combos  (~2 h)
  Group 3 — 1m entry confirmation     :  3 × 4 × 4      = 48 combos  (~6 h)
  Group 4 — ATR gate                  :  4 × 3          = 12 combos  (~1.5 h)

Run via:  python launch_sequential_optimization.py
"""

import os
import sys
import itertools
import shutil
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

# ── Trace file ────────────────────────────────────────────────────────────────
_TRACE_FILE = Path(__file__).parent / "seq_opt_trace.txt"

def _trace(msg: str) -> None:
    with _TRACE_FILE.open("a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

_trace("module_level_start")

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

_trace("before_backtest_import")
from run_backtest_mtf_v2_entry_confirmed_adaptive import run_v2_entry_confirmed_adaptive_backtest
_trace("after_backtest_import")

# ── Global config ─────────────────────────────────────────────────────────────
SYMBOL     = "EUR/USD"
VENUE      = "IDEALPRO"
START_DATE = "2025-01-01"
END_DATE   = "2026-02-08"
CLEANUP_RESULTS = True

DATE_TAG   = datetime.now().strftime("%Y%m%d")

# Logging suppression env vars applied to every run
_SUPPRESS_LOG_ENV = {
    "MTF2_DMI_PARITY_DEBUG":              "0",
    "NAUTILUS_LOG_LEVEL":                 "ERROR",
    "LOG_LEVEL":                          "ERROR",
    "NAUTILUS_BYPASS_LOGGING":            "1",
    "NAUTILUS_CORE_LOG_LEVEL":            "ERROR",
    "NAUTILUS_TRADER_LOG_LEVEL":          "ERROR",
    "NAUTILUS_LOG_COLOR":                 "0",
    "RUST_LOG":                           "error",
}

# ── Score formula (shared across all groups) ──────────────────────────────────
def _compute_score(total_pnl: float, win_rate: float, max_drawdown: float, total_trades: int = 1) -> float:
    """40% avg-trade yield, 30% WR above 50 %, 30% drawdown penalty."""
    avg_trade  = total_pnl / max(total_trades, 1)
    pnl_score  = avg_trade * 10
    wr_score   = (win_rate - 0.50) * 200
    dd_penalty = (abs(max_drawdown) / 1_000) * 100
    return pnl_score * 0.4 + wr_score * 0.3 - dd_penalty * 0.3


# ── Single backtest runner ────────────────────────────────────────────────────
def run_single_backtest(combo_env: dict, fixed_env: dict, label: str = ""):
    """
    Run one backtest.
    combo_env : {MTF2_ENV_VAR: value, ...}  — the parameters being swept
    fixed_env : {MTF2_ENV_VAR: value, ...}  — best params from previous groups
    Returns a metrics dict, or None on failure.
    """
    import logging
    import numpy as np

    start_ts = time.time()
    _trace(f"run_enter: {label} {combo_env}")

    # Build full env override (os.environ requires string values)
    env_vars = {}
    env_vars.update(_SUPPRESS_LOG_ENV)
    env_vars.update({k: str(v) for k, v in fixed_env.items()})
    env_vars.update({k: str(v) for k, v in combo_env.items()})
    _trace("env_built")

    # Suppress Python logging
    logging.getLogger().setLevel(logging.ERROR)
    for handler in logging.getLogger().handlers:
        handler.setLevel(logging.ERROR)
    for name in [
        "MLSignalStrategy_V2_EntryConfirmedAdaptive",
        "MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe",
        "BACKTESTER-001.MLSignalStrategyV2EntryConfirmedAdaptiveFailSafe",
        "BACKTESTER-001.Portfolio",
        "BACKTESTER-001.BacktestEngine",
    ]:
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        lg.propagate = False
    _trace("logging_suppressed")

    try:
        original_env = os.environ.copy()
        _trace("env_backup_done")
        os.environ.update(env_vars)
        _trace("env_applied")
    except Exception as _env_exc:
        _trace(f"env_update_error: {_env_exc!r}")
        raise

    try:
        _trace("before_run_backtest")
        result, results_dir = run_v2_entry_confirmed_adaptive_backtest(
            symbol=SYMBOL,
            venue=VENUE,
            start_date=START_DATE,
            end_date=END_DATE,
        )
        _trace(f"after_run_backtest: {results_dir}")

        results_path = Path(results_dir)
        trades_files  = list(results_path.glob("trades_*.csv"))
        if not trades_files:
            _trace(f"no_trades_csv: {results_dir}")
            return None

        trades_df = pd.read_csv(trades_files[0])
        total_trades = len(trades_df)
        if total_trades == 0:
            return None

        total_pnl   = float(trades_df["pnl"].sum())
        win_rate    = float((trades_df["pnl"] > 0).mean())
        avg_trade   = total_pnl / total_trades

        winning_pnl = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losing_pnl  = abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = (winning_pnl / losing_pnl) if losing_pnl > 0 else float("inf")

        cum_pnl     = trades_df["pnl"].cumsum()
        max_drawdown = float((cum_pnl - cum_pnl.cummax()).min())

        pnl_std     = trades_df["pnl"].std()
        sharpe      = avg_trade / pnl_std if pnl_std > 0 else 0.0

        score = _compute_score(total_pnl, win_rate, max_drawdown, total_trades)

        if CLEANUP_RESULTS:
            shutil.rmtree(results_dir, ignore_errors=True)

        metrics = {
            "total_pnl":     total_pnl,
            "win_rate":      win_rate,
            "total_trades":  total_trades,
            "profit_factor": profit_factor,
            "sharpe_ratio":  sharpe,
            "max_drawdown":  max_drawdown,
            "avg_trade":     avg_trade,
            "score":         score,
            "duration_s":    time.time() - start_ts,
        }
        metrics.update(combo_env)
        return metrics

    except Exception as exc:
        print(f"  ERROR: {exc}", flush=True)
        _trace(f"run_error: {exc}")
        return None
    finally:
        os.environ.clear()
        os.environ.update(original_env)


# ── Generic group runner ──────────────────────────────────────────────────────
def run_group(
    group_name: str,
    param_grid: dict,          # {env_var: [values, ...]}
    fixed_env:  dict,          # env vars fixed from previous groups
    output_file: str,
) -> dict:
    """
    Run a full sweep of param_grid, return the best env-var dict.
    Supports resume: existing output_file rows are skipped.
    """
    keys   = list(param_grid.keys())
    combos = [dict(zip(keys, v)) for v in itertools.product(*param_grid.values())]
    total  = len(combos)

    print(f"\n{'='*60}", flush=True)
    print(f"GROUP: {group_name}  ({total} combos)", flush=True)
    print(f"Fixed params: {fixed_env}", flush=True)
    print(f"Output: {output_file}", flush=True)
    print(f"{'='*60}", flush=True)

    # Resume: load completed keys
    results         = []
    completed_keys  = set()
    out_path        = Path(output_file)
    if out_path.exists():
        try:
            existing = pd.read_csv(out_path)
            results  = existing.to_dict("records")
            for row in results:
                completed_keys.add(tuple(row[k] for k in keys))
            print(f"  Resuming: {len(completed_keys)}/{total} already done.", flush=True)
        except Exception as ex:
            print(f"  Warning: could not load existing results ({ex}), starting fresh.", flush=True)

    for i, combo_env in enumerate(combos):
        key = tuple(combo_env[k] for k in keys)
        tag = f"[{i+1}/{total}]"

        if key in completed_keys:
            print(f"{tag} Skip (done): {combo_env}", flush=True)
            continue

        print(f"{tag} Testing: {combo_env}", flush=True)
        _trace(f"{group_name}_combo_{i+1}_start: {combo_env}")
        metrics = run_single_backtest(combo_env, fixed_env, label=f"{group_name}:{i+1}")
        _trace(f"{group_name}_combo_{i+1}_done")

        if metrics:
            print(
                f"  → PnL=${metrics['total_pnl']:.2f}  WR={metrics['win_rate']:.2%}  "
                f"Trades={metrics['total_trades']}  Score={metrics['score']:.3f}",
                flush=True,
            )
            results.append(metrics)
            pd.DataFrame(results).to_csv(out_path, index=False)
        else:
            print(f"  → FAILED (no metrics)", flush=True)

    if not results:
        print(f"  WARNING: {group_name} produced no results!", flush=True)
        return fixed_env  # pass through unchanged

    df      = pd.DataFrame(results).sort_values("score", ascending=False)
    best    = df.iloc[0]
    best_env = {k: best[k] for k in keys}

    print(f"\n  ✓ {group_name} complete — best combo:", flush=True)
    for k, v in best_env.items():
        print(f"    {k} = {v}", flush=True)
    print(f"  Score={best['score']:.3f}  PnL=${best['total_pnl']:.2f}  WR={best['win_rate']:.2%}", flush=True)

    # Merge best combo into fixed env for next group
    next_fixed = dict(fixed_env)
    next_fixed.update(best_env)
    return next_fixed


# ── Group definitions ─────────────────────────────────────────────────────────

GROUP1_GRID = {
    "MTF2_SL_ATR_MULT":              [1.5, 2.0, 2.5],
    "MTF2_POS1_TP_ATR_MULT":         [1.2, 1.5, 1.8],
    "MTF2_POS2_TP_ATR_MULT":         [2.0, 3.0],
    "MTF2_META_FILTER_MAMA_MIN_DIFF": [0.0001, 0.0002],
}

GROUP2_GRID = {
    "MTF2_PREDICTION_THRESHOLD_LONG":  [0.65, 0.70, 0.75, 0.80],
    "MTF2_PREDICTION_THRESHOLD_SHORT": [0.60, 0.65, 0.70, 0.75],
}

GROUP3_GRID = {
    "MTF2_ENTRY_CONFIRM_BARS":      [1, 2, 3],
    "MTF2_ENTRY_CONFIRM_THRESHOLD": [0.10, 0.15, 0.22, 0.30],
    # MTF2_ENTRY_CONFIRM_MAX_WAIT_BARS left at .env.mtf_v2 default (3×4=12 combos)
}

GROUP4_GRID = {
    "MTF2_MIN_ATR": [0.00018, 0.00022, 0.00025, 0.00030],
    "MTF2_MAX_ATR": [0.003,   0.004,   0.005],
}

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _trace("main_start")
    t0 = time.time()

    print(f"Sequential multi-group optimizer", flush=True)
    print(f"Period: {START_DATE} → {END_DATE}  |  Symbol: {SYMBOL}", flush=True)
    total_combos = (
        len(list(itertools.product(*GROUP1_GRID.values())))
        + len(list(itertools.product(*GROUP2_GRID.values())))
        + len(list(itertools.product(*GROUP3_GRID.values())))
        + len(list(itertools.product(*GROUP4_GRID.values())))
    )
    print(f"Total combos across all groups: {total_combos}", flush=True)

    # ── Group 1 ───────────────────────────────────────────────────────────────
    # Reuse existing Group-1 results if all 36 are present (optimization already done)
    g1_file  = f"opt_group1_sl_tp_mama_{DATE_TAG}.csv"
    legacy   = Path("optimization_results_fixed_20260221.csv")

    # Column rename map: legacy human-readable names → env-var names used by this script
    _G1_COL_RENAME = {
        "sl_atr_mult":   "MTF2_SL_ATR_MULT",
        "tp1_atr_mult":  "MTF2_POS1_TP_ATR_MULT",
        "tp2_atr_mult":  "MTF2_POS2_TP_ATR_MULT",
        "mama_min_diff": "MTF2_META_FILTER_MAMA_MIN_DIFF",
    }

    # If today's Group 1 file doesn't exist but the legacy one does, import it
    if not Path(g1_file).exists() and legacy.exists():
        try:
            existing_g1 = pd.read_csv(legacy)
            # Rename legacy columns to env-var names so resume logic works
            existing_g1 = existing_g1.rename(columns=_G1_COL_RENAME)
            existing_g1.to_csv(g1_file, index=False)
            n = len(existing_g1)
            expected_g1 = len(list(itertools.product(*GROUP1_GRID.values())))
            print(f"  Imported legacy Group 1 results: {n}/{expected_g1} rows → {g1_file}", flush=True)
        except Exception as ex:
            print(f"  Warning: could not import legacy results ({ex})", flush=True)

    # Check if Group 1 is already complete — if so, extract best and skip run_group
    g1_keys   = list(GROUP1_GRID.keys())
    expected_g1 = len(list(itertools.product(*GROUP1_GRID.values())))
    best_env  = {}
    if Path(g1_file).exists():
        try:
            g1_df = pd.read_csv(g1_file)
            if len(g1_df) >= expected_g1:
                best_row = g1_df.sort_values("score", ascending=False).iloc[0]
                best_env = {k: best_row[k] for k in g1_keys if k in best_row}
                print(f"\n{'='*60}", flush=True)
                print(f"GROUP: Group1_SL_TP_MAMA  — already complete ({len(g1_df)}/{expected_g1})", flush=True)
                print(f"  Best: {best_env}", flush=True)
                print(f"  Score={best_row['score']:.3f}  PnL=${best_row['total_pnl']:.2f}  WR={best_row['win_rate']:.2%}", flush=True)
            else:
                print(f"  Group 1 partial ({len(g1_df)}/{expected_g1}), resuming...", flush=True)
                best_env = run_group("Group1_SL_TP_MAMA", GROUP1_GRID, {}, g1_file)
        except Exception as ex:
            print(f"  Warning: could not read Group 1 file ({ex}), running from scratch.", flush=True)
            best_env = run_group("Group1_SL_TP_MAMA", GROUP1_GRID, {}, g1_file)
    else:
        best_env = run_group("Group1_SL_TP_MAMA", GROUP1_GRID, {}, g1_file)

    # ── Group 2 ───────────────────────────────────────────────────────────────
    g2_file  = f"opt_group2_pred_thresholds_{DATE_TAG}.csv"
    best_env = run_group("Group2_PredThresholds", GROUP2_GRID, best_env, g2_file)

    # ── Group 3 ───────────────────────────────────────────────────────────────
    g3_file  = f"opt_group3_entry_confirm_{DATE_TAG}.csv"
    best_env = run_group("Group3_EntryConfirm", GROUP3_GRID, best_env, g3_file)

    # ── Group 4 ───────────────────────────────────────────────────────────────
    g4_file  = f"opt_group4_atr_gate_{DATE_TAG}.csv"
    best_env = run_group("Group4_ATRGate", GROUP4_GRID, best_env, g4_file)

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed = (time.time() - t0) / 3600
    print(f"\n{'='*60}", flush=True)
    print(f"ALL GROUPS COMPLETE  (total time: {elapsed:.1f} h)", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"\nFinal best parameter set:", flush=True)
    for env_var, value in best_env.items():
        if env_var.startswith("MTF2_"):
            print(f"  {env_var}={value}", flush=True)

    # Map env vars back to .env.mtf_v2 names for easy copy-paste
    print(f"\n--- Suggested .env.mtf_v2 updates ---", flush=True)
    for env_var, value in best_env.items():
        if env_var.startswith("MTF2_"):
            print(f"{env_var}={value}", flush=True)

    # Write final params to a summary file
    summary_path = Path(f"opt_final_params_{DATE_TAG}.txt")
    with summary_path.open("w") as f:
        f.write(f"# Sequential optimization result — {datetime.now().isoformat()}\n")
        f.write(f"# Period: {START_DATE} to {END_DATE}\n\n")
        for env_var, value in best_env.items():
            if env_var.startswith("MTF2_"):
                f.write(f"{env_var}={value}\n")
    print(f"\nFinal params written to {summary_path}", flush=True)

    _trace("main_end")


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        import traceback
        _trace(f"FATAL: {_e!r}")
        _trace(traceback.format_exc().replace('\n', ' | '))
        raise
