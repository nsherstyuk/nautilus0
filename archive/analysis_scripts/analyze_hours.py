"""Analyze hour/weekday P&L matrix to determine optimal exclusions for XGBoost V3."""
import csv
import sys

RESULT_DIR = r"c:\nautilus0\backtest_results\MTF_V2_ENTRY_CONFIRMED_20260209_144652"

days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def read_matrix(filename):
    m = {}
    with open(f"{RESULT_DIR}\\{filename}") as f:
        for row in csv.DictReader(f):
            h = int(row["hour_EST"])
            m[h] = {d: float(row[d]) for d in days}
    return m

pnl = read_matrix("hour_weekday_pnl_matrix_20260209_144652.csv")
trades = read_matrix("hour_weekday_trades_matrix_20260209_144652.csv")
wr = read_matrix("hour_weekday_winrate_matrix_20260209_144652.csv")

exclude = {d: [] for d in days}
kept_pnl = 0.0
exc_pnl = 0.0
kept_trades = 0
exc_trades = 0

for h in range(24):
    for d in days:
        t = int(trades[h][d])
        p = pnl[h][d]
        w = wr[h][d]
        if t == 0:
            continue
        # Exclude if: negative P&L > $5 loss, or low win rate with enough sample
        if p < -5 or (t >= 2 and w < 55):
            exclude[d].append(h)
            exc_pnl += p
            exc_trades += t
        else:
            kept_pnl += p
            kept_trades += t

print("=" * 60)
print("HOUR EXCLUSION ANALYSIS - XGBoost V3 (no exclusions baseline)")
print("=" * 60)
print(f"Kept slots:     PnL = ${kept_pnl:.2f}  ({kept_trades} trades)")
print(f"Excluded slots: PnL = ${exc_pnl:.2f}  ({exc_trades} trades)")
print(f"Improvement:    ${-exc_pnl:.2f}")
print(f"Projected PnL:  ${kept_pnl:.2f}")
print()

for d in days:
    exc = sorted(exclude[d])
    if d == "Saturday":
        exc = list(range(24))
    if exc:
        print(f"  {d}: EXCLUDE {exc}")
    else:
        print(f"  {d}: No exclusions")

print()
print("=" * 60)
print("ENV FORMAT (copy to .env.mtf_v2)")
print("=" * 60)
for d in days:
    exc = sorted(exclude[d])
    if d == "Saturday":
        exc = list(range(24))
    var = f"MTF2_EXCLUDED_HOURS_{d.upper()}"
    val = ",".join(str(h) for h in exc) if exc else ""
    print(f"{var}={val}")

# Also show the detailed bad slots
print()
print("=" * 60)
print("DETAILED BAD SLOTS")
print("=" * 60)
for h in range(24):
    for d in days:
        t = int(trades[h][d])
        p = pnl[h][d]
        w = wr[h][d]
        if t > 0 and (p < -5 or (t >= 2 and w < 55)):
            print(f"  {d} {h:02d}:00 EST  ->  PnL=${p:.1f}  trades={t}  WR={w:.0f}%")
