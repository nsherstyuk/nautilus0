"""Grid search over SL ATR multiplier values using the current backtest config."""
import os
import sys
import subprocess
import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# SL values to test - higher values (1.2 baseline = $161.72)
SL_VALUES = [1.3, 1.4, 1.5]

def run_backtest_with_sl(sl_value):
    """Run a backtest with a specific SL value by setting env var override."""
    env = os.environ.copy()
    env["MTF2_SL_ATR_MULT"] = str(sl_value)
    
    print(f"\n{'='*60}")
    print(f"  Running backtest with SL = {sl_value}x ATR")
    print(f"{'='*60}")
    
    result = subprocess.run(
        [sys.executable, "run_backtest_mtf_v2_entry_confirmed.py"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    
    # Extract result directory from output
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode != 0:
        print(f"  WARNING: backtest exited with code {result.returncode}")
        if stderr:
            print(f"  STDERR (last 500 chars): {stderr[-500:]}")
    
    for line in stdout.split("\n"):
        if "Results saved to:" in line or "Output Directory:" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                return parts[1].strip()
    
    # Fallback: find most recent result dir
    results_dir = PROJECT_ROOT / "backtest_results"
    dirs = sorted(results_dir.glob("MTF_V2_ENTRY_CONFIRMED_*"), key=lambda d: d.name)
    if dirs:
        return str(dirs[-1])
    return None


def analyze_result(result_dir, sl_value):
    """Analyze a backtest result directory."""
    result_dir = Path(result_dir)
    
    # Read summary
    summary_files = list(result_dir.glob("summary_*.txt"))
    if not summary_files:
        return None
    
    summary = summary_files[0].read_text()
    
    # Read trades
    trades_files = list(result_dir.glob("trades_*.csv"))
    if not trades_files:
        return None
    
    with open(trades_files[0]) as f:
        rows = list(csv.DictReader(f))
    
    total_trades = len(rows)
    if total_trades == 0:
        return {"sl": sl_value, "trades": 0, "pnl": 0, "wr": 0}
    
    total_pnl = sum(float(r["pnl"]) for r in rows)
    wins = sum(1 for r in rows if float(r["pnl"]) > 0)
    wr = wins / total_trades * 100
    
    longs = [r for r in rows if r["side"] == "LONG"]
    shorts = [r for r in rows if r["side"] == "SHORT"]
    
    long_pnl = sum(float(r["pnl"]) for r in longs)
    short_pnl = sum(float(r["pnl"]) for r in shorts)
    long_wins = sum(1 for r in longs if float(r["pnl"]) > 0)
    short_wins = sum(1 for r in shorts if float(r["pnl"]) > 0)
    
    # Extract max drawdown from summary
    max_dd = "N/A"
    for line in summary.split("\n"):
        if "Max Drawdown:" in line:
            max_dd = line.split("Max Drawdown:")[1].strip()
            break
    
    return {
        "sl": sl_value,
        "trades": total_trades,
        "pnl": round(total_pnl, 2),
        "wr": round(wr, 1),
        "long_trades": len(longs),
        "long_pnl": round(long_pnl, 2),
        "long_wr": round(long_wins / max(len(longs), 1) * 100, 1),
        "short_trades": len(shorts),
        "short_pnl": round(short_pnl, 2),
        "short_wr": round(short_wins / max(len(shorts), 1) * 100, 1),
        "max_dd": max_dd,
        "result_dir": str(result_dir),
    }


def main():
    results = []
    
    for sl in SL_VALUES:
        result_dir = run_backtest_with_sl(sl)
        if result_dir:
            info = analyze_result(result_dir, sl)
            if info:
                results.append(info)
                print(f"\n  SL={sl}: {info['trades']} trades, PnL=${info['pnl']}, WR={info['wr']}%")
                print(f"    LONG:  {info['long_trades']} trades, PnL=${info['long_pnl']}, WR={info['long_wr']}%")
                print(f"    SHORT: {info['short_trades']} trades, PnL=${info['short_pnl']}, WR={info['short_wr']}%")
                print(f"    Max DD: {info['max_dd']}")
    
    # Print comparison table
    print(f"\n\n{'='*80}")
    print("SL GRID SEARCH RESULTS")
    print(f"{'='*80}")
    print(f"{'SL':>5} | {'Trades':>6} | {'P&L':>10} | {'WR%':>6} | {'L_Trades':>8} | {'L_PnL':>8} | {'S_Trades':>8} | {'S_PnL':>8} | {'MaxDD':>15}")
    print("-" * 100)
    for r in results:
        print(f"{r['sl']:>5} | {r['trades']:>6} | ${r['pnl']:>8} | {r['wr']:>5}% | {r['long_trades']:>8} | ${r['long_pnl']:>7} | {r['short_trades']:>8} | ${r['short_pnl']:>7} | {r['max_dd']:>15}")
    
    # Save results
    out_file = PROJECT_ROOT / "sl_grid_search_results.txt"
    with open(out_file, "w") as f:
        f.write("SL Grid Search Results\n")
        f.write(f"{'='*80}\n")
        for r in results:
            f.write(f"SL={r['sl']}: {r['trades']} trades, PnL=${r['pnl']}, WR={r['wr']}%, MaxDD={r['max_dd']}\n")
            f.write(f"  LONG:  {r['long_trades']} trades, PnL=${r['long_pnl']}, WR={r['long_wr']}%\n")
            f.write(f"  SHORT: {r['short_trades']} trades, PnL=${r['short_pnl']}, WR={r['short_wr']}%\n")
    print(f"\nResults saved to: {out_file}")


if __name__ == "__main__":
    main()
