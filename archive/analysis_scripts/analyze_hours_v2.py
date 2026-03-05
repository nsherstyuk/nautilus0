"""Analyze hour/weekday matrices: keep only slots with WR >= 68% AND positive PnL."""
import csv

RESULT_DIR = r"c:\nautilus0\backtest_results\MTF_V2_ENTRY_CONFIRMED_20260209_144652"
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def read_matrix(fn):
    m = {}
    with open(RESULT_DIR + "\\" + fn) as f:
        for row in csv.DictReader(f):
            h = int(row["hour_EST"])
            m[h] = {d: float(row[d]) for d in days}
    return m

pnl = read_matrix("hour_weekday_pnl_matrix_20260209_144652.csv")
trades = read_matrix("hour_weekday_trades_matrix_20260209_144652.csv")
wr = read_matrix("hour_weekday_winrate_matrix_20260209_144652.csv")

exclude = {d: [] for d in days}
keep = {d: [] for d in days}
kept_pnl = 0.0
exc_pnl = 0.0
kept_trades = 0
exc_trades = 0

print("KEPT SLOTS (WR >= 68% AND PnL > 0):")
print(f"{'Hour':>4} | {'Day':>10} | {'Trades':>6} | {'PnL':>8} | {'WR':>6}")
print("-" * 45)
for h in range(24):
    for d in days:
        t = int(trades[h][d])
        p = pnl[h][d]
        w = wr[h][d]
        if t == 0:
            continue
        if w >= 68 and p > 0:
            keep[d].append(h)
            kept_pnl += p
            kept_trades += t
            print(f"{h:>4} | {d:>10} | {t:>6} | ${p:>6.1f} | {w:>5.1f}%")
        else:
            exclude[d].append(h)
            exc_pnl += p
            exc_trades += t

print()
print("EXCLUDED SLOTS (WR < 68% OR PnL <= 0):")
print(f"{'Hour':>4} | {'Day':>10} | {'Trades':>6} | {'PnL':>8} | {'WR':>6}")
print("-" * 45)
for h in range(24):
    for d in days:
        t = int(trades[h][d])
        p = pnl[h][d]
        w = wr[h][d]
        if t == 0:
            continue
        if not (w >= 68 and p > 0):
            print(f"{h:>4} | {d:>10} | {t:>6} | ${p:>6.1f} | {w:>5.1f}%")

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Kept:     {kept_trades} trades, PnL=${kept_pnl:.2f}")
print(f"Excluded: {exc_trades} trades, PnL=${exc_pnl:.2f}")
print(f"Projected improvement: ${-exc_pnl:.2f}")
print()

print("EXCLUSIONS PER WEEKDAY:")
for d in days:
    exc = sorted(exclude[d])
    kept = sorted(keep[d])
    all_hours = set(range(24))
    active = set(exc + kept)
    no_trade = sorted(all_hours - active)
    full_exc = sorted(set(exc + no_trade))
    if d == "Saturday":
        full_exc = list(range(24))
    print(f"  {d}: KEEP {kept} | EXCLUDE hours with trades that fail criteria: {exc}")

print()
print("=" * 60)
print("ENV FORMAT (copy to .env.mtf_v2)")
print("=" * 60)
for d in days:
    exc = sorted(exclude[d])
    kept = sorted(keep[d])
    all_hours = set(range(24))
    active = set(exc + kept)
    no_trade = sorted(all_hours - active)
    full_exc = sorted(set(exc + no_trade))
    if d == "Saturday":
        full_exc = list(range(24))
    var = "MTF2_EXCLUDED_HOURS_" + d.upper()
    val = ",".join(str(h) for h in full_exc)
    print(f"{var}={val}")
