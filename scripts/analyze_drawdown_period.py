"""Analyze the drawdown period (Jul 20 - Oct 28, 2025) from xpair soft backtest."""
import pandas as pd
import sys

trades_file = r"c:\nautilus0\backtest_results\MTF_V2_ENTRY_CONFIRMED_ADAPTIVE_20260211_210015\trades_20260211_210015.csv"

df = pd.read_csv(trades_file, parse_dates=["entry_time", "exit_time", "signal_time"])

# Split into drawdown period vs rest
dd_start = pd.Timestamp("2025-07-20", tz="UTC")
dd_end = pd.Timestamp("2025-10-28", tz="UTC")

dd = df[(df["entry_time"] >= dd_start) & (df["entry_time"] <= dd_end)]
rest = df[(df["entry_time"] < dd_start) | (df["entry_time"] > dd_end)]

print("=" * 70)
print("DRAWDOWN PERIOD ANALYSIS: Jul 20 - Oct 28, 2025")
print("=" * 70)

print(f"\n--- Overall Comparison ---")
print(f"{'Metric':<25} {'Drawdown Period':>18} {'Rest of Year':>18}")
print(f"{'-'*25} {'-'*18} {'-'*18}")
print(f"{'Trades':<25} {len(dd):>18} {len(rest):>18}")
print(f"{'Total PnL':<25} {'${:.2f}'.format(dd['pnl'].sum()):>18} {'${:.2f}'.format(rest['pnl'].sum()):>18}")
print(f"{'Win Rate':<25} {'{:.1f}%'.format(100*len(dd[dd['pnl']>0])/len(dd)):>18} {'{:.1f}%'.format(100*len(rest[rest['pnl']>0])/len(rest)):>18}")
print(f"{'Avg PnL/Trade':<25} {'${:.2f}'.format(dd['pnl'].mean()):>18} {'${:.2f}'.format(rest['pnl'].mean()):>18}")
print(f"{'Avg Win':<25} {'${:.2f}'.format(dd[dd['pnl']>0]['pnl'].mean()):>18} {'${:.2f}'.format(rest[rest['pnl']>0]['pnl'].mean()):>18}")
print(f"{'Avg Loss':<25} {'${:.2f}'.format(dd[dd['pnl']<0]['pnl'].mean()):>18} {'${:.2f}'.format(rest[rest['pnl']<0]['pnl'].mean()):>18}")

# Exit reason breakdown
print(f"\n--- Exit Reasons (Drawdown Period) ---")
for reason, grp in dd.groupby("exit_reason"):
    wr = 100 * len(grp[grp["pnl"] > 0]) / len(grp)
    print(f"  {reason}: {len(grp)} trades, PnL=${grp['pnl'].sum():.2f}, WR={wr:.1f}%")

print(f"\n--- Exit Reasons (Rest of Year) ---")
for reason, grp in rest.groupby("exit_reason"):
    wr = 100 * len(grp[grp["pnl"] > 0]) / len(grp)
    print(f"  {reason}: {len(grp)} trades, PnL=${grp['pnl'].sum():.2f}, WR={wr:.1f}%")

# Side breakdown
print(f"\n--- Side Breakdown (Drawdown Period) ---")
for side, grp in dd.groupby("side"):
    wr = 100 * len(grp[grp["pnl"] > 0]) / len(grp)
    print(f"  {side}: {len(grp)} trades, PnL=${grp['pnl'].sum():.2f}, WR={wr:.1f}%")

print(f"\n--- Side Breakdown (Rest of Year) ---")
for side, grp in rest.groupby("side"):
    wr = 100 * len(grp[grp["pnl"] > 0]) / len(grp)
    print(f"  {side}: {len(grp)} trades, PnL=${grp['pnl'].sum():.2f}, WR={wr:.1f}%")

# Hour breakdown during drawdown
print(f"\n--- Hourly Performance (Drawdown Period, UTC) ---")
dd_hourly = dd.groupby("signal_hour").agg(
    trades=("pnl", "count"),
    pnl=("pnl", "sum"),
    wr=("pnl", lambda x: 100 * (x > 0).sum() / len(x))
).sort_values("pnl")
print(f"{'Hour':>6} {'Trades':>8} {'PnL':>10} {'WR':>8}")
for h, row in dd_hourly.iterrows():
    print(f"{h:>6} {int(row['trades']):>8} ${row['pnl']:>8.2f} {row['wr']:>7.1f}%")

# Weekday breakdown during drawdown
print(f"\n--- Weekday Performance (Drawdown Period) ---")
day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
dd_weekday = dd.groupby("signal_weekday").agg(
    trades=("pnl", "count"),
    pnl=("pnl", "sum"),
    wr=("pnl", lambda x: 100 * (x > 0).sum() / len(x))
).sort_values("pnl")
print(f"{'Day':>6} {'Trades':>8} {'PnL':>10} {'WR':>8}")
for d, row in dd_weekday.iterrows():
    print(f"{day_names.get(d, d):>6} {int(row['trades']):>8} ${row['pnl']:>8.2f} {row['wr']:>7.1f}%")

# Weekly P&L during drawdown to see the pattern
print(f"\n--- Weekly P&L During Drawdown ---")
dd_copy = dd.copy()
dd_copy["week"] = dd_copy["entry_time"].dt.isocalendar().week.astype(int)
dd_copy["year_week"] = dd_copy["entry_time"].dt.strftime("%Y-W%U")
weekly = dd_copy.groupby("year_week").agg(
    trades=("pnl", "count"),
    pnl=("pnl", "sum"),
    wr=("pnl", lambda x: 100 * (x > 0).sum() / len(x))
)
print(f"{'Week':>10} {'Trades':>8} {'PnL':>10} {'WR':>8}")
cum_pnl = 0
for w, row in weekly.iterrows():
    cum_pnl += row["pnl"]
    print(f"{w:>10} {int(row['trades']):>8} ${row['pnl']:>8.2f} {row['wr']:>7.1f}%  (cum: ${cum_pnl:.2f})")

# Individual losing trades during drawdown (sorted by loss)
print(f"\n--- Biggest Losses During Drawdown ---")
losers = dd[dd["pnl"] < 0].sort_values("pnl")
print(f"{'Date':>22} {'Side':>6} {'PnL':>10} {'Exit':>6} {'Hour':>6} {'Day':>5}")
for _, t in losers.head(15).iterrows():
    print(f"{str(t['entry_time'])[:19]:>22} {t['side']:>6} ${t['pnl']:>8.2f} {t['exit_reason']:>6} {t['signal_hour']:>6} {day_names.get(t['signal_weekday'], '?'):>5}")

# Price range analysis - was it trending or ranging?
print(f"\n--- Price Context ---")
print(f"  Entry prices during DD: min={dd['entry'].min():.5f}, max={dd['entry'].max():.5f}, range={dd['entry'].max()-dd['entry'].min():.5f}")
print(f"  Entry prices rest:      min={rest['entry'].min():.5f}, max={rest['entry'].max():.5f}, range={rest['entry'].max()-rest['entry'].min():.5f}")

# Consecutive loss streaks
print(f"\n--- Loss Streaks During Drawdown ---")
streak = 0
max_streak = 0
streak_pnl = 0
max_streak_pnl = 0
for _, t in dd.iterrows():
    if t["pnl"] < 0:
        streak += 1
        streak_pnl += t["pnl"]
        if streak > max_streak:
            max_streak = streak
            max_streak_pnl = streak_pnl
    else:
        streak = 0
        streak_pnl = 0
print(f"  Max consecutive losses: {max_streak} (total: ${max_streak_pnl:.2f})")

# Monthly breakdown (already have this but show it again for context)
print(f"\n--- Monthly Summary (Full Year) ---")
monthly = df.groupby("entry_month").agg(
    trades=("pnl", "count"),
    pnl=("pnl", "sum"),
    wr=("pnl", lambda x: 100 * (x > 0).sum() / len(x))
)
print(f"{'Month':>10} {'Trades':>8} {'PnL':>10} {'WR':>8}")
for m, row in monthly.iterrows():
    marker = " <<< DD" if m in ["2025-08", "2025-09", "2025-10"] else ""
    print(f"{m:>10} {int(row['trades']):>8} ${row['pnl']:>8.2f} {row['wr']:>7.1f}%{marker}")
