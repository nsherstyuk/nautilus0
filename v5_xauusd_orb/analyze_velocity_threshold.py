"""Analyze collected IBKR velocity data to set proper threshold for ORB."""
import pandas as pd
import numpy as np
from pathlib import Path

csv_path = Path("c:/nautilus0/v6_velocity_logs/velocity_realtime_XAUUSD_20260312_195234.csv")
df = pd.read_csv(csv_path)
print(f"Total rows: {len(df)}")
print(f"Time range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
print(f"Columns: {df.columns.tolist()}")

print("\n" + "=" * 70)
print("VELOCITY 3m STATS (ALL HOURS)")
print("=" * 70)
print(df["velocity_3m"].describe())

# London session (08:00-16:00 UTC) - when ORB trades
london = df[(df["hour_utc"] >= 8) & (df["hour_utc"] < 16)]
print(f"\n{'=' * 70}")
print(f"LONDON SESSION (08-16 UTC): {len(london)} rows")
print("=" * 70)
if len(london) > 0:
    print(london["velocity_3m"].describe())
    print("\nPercentiles (London vel_3m):")
    for p in [10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90]:
        val = london["velocity_3m"].quantile(p / 100)
        print(f"  P{p}: {val:.1f}")

# 08:00 UTC specifically (ORB entry time)
h8 = df[df["hour_utc"] == 8]
print(f"\n{'=' * 70}")
print(f"08:00 UTC HOUR: {len(h8)} rows")
print("=" * 70)
if len(h8) > 0:
    print(h8["velocity_3m"].describe())
    print("\nPercentiles (08:00 vel_3m):")
    for p in [25, 50, 75, 90]:
        val = h8["velocity_3m"].quantile(p / 100)
        print(f"  P{p}: {val:.1f}")

# Hourly breakdown
print(f"\n{'=' * 70}")
print("HOURLY VELOCITY 3m BREAKDOWN")
print("=" * 70)
hourly = df.groupby("hour_utc")["velocity_3m"].agg(["count", "mean", "median", "std"])
hourly.columns = ["count", "mean", "median", "std"]
for hour, row in hourly.iterrows():
    print(f"  {hour:02d}:00 UTC  n={row['count']:>5.0f}  mean={row['mean']:>6.1f}  median={row['median']:>6.1f}  std={row['std']:>6.1f}")

# Recommendation
print(f"\n{'=' * 70}")
print("THRESHOLD RECOMMENDATION")
print("=" * 70)
if len(london) > 0:
    p50 = london["velocity_3m"].quantile(0.50)
    p40 = london["velocity_3m"].quantile(0.40)
    p30 = london["velocity_3m"].quantile(0.30)
    print(f"  London P30: {p30:.0f} ticks/min (aggressive - more trades)")
    print(f"  London P40: {p40:.0f} ticks/min (balanced)")
    print(f"  London P50: {p50:.0f} ticks/min (conservative - fewer trades)")
    print(f"\n  Claude recommended IBKR P50 at 08:00 = ~188")
    if len(h8) > 0:
        p50_h8 = h8["velocity_3m"].quantile(0.50)
        print(f"  Our data P50 at 08:00 = {p50_h8:.0f}")
