"""Trace the exact pandas resampling behavior to understand HTF alignment."""
import pandas as pd
import numpy as np

# Simulate 15m bars around 08:00 UTC boundary
times = pd.date_range("2024-01-02 06:00", "2024-01-02 12:00", freq="15min", tz="UTC")
prices = [1.1000 + i * 0.0001 for i in range(len(times))]
df = pd.DataFrame({"close": prices}, index=times)
df["open"] = df["close"] - 0.0001
df["high"] = df["close"] + 0.0002
df["low"] = df["open"] - 0.0002
df["volume"] = 100

print("=== 15m bars ===")
for ts, row in df.iterrows():
    print(f"  {ts}  close={row['close']:.4f}")

# ── BATCH: label='left', closed='left' (pandas default, PRODUCTION) ──
print("\n=== BATCH: label=left, closed=left (CURRENT PRODUCTION) ===")
r_left = df.resample("1h").agg(
    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
).dropna()

print("\n1h bars created:")
for ts, row in r_left.iterrows():
    print(f"  1h label={ts}  close={row['close']:.4f}")

# Which 15m bars went into each 1h bar?
print("\n  Which 15m bars are in [08:00, 09:00) with left/left?")
for ts in times:
    if ts.hour == 8:
        print(f"    {ts} close={df.loc[ts, 'close']:.4f}")

# ffill to 15m
feat = pd.DataFrame({"close_1h": r_left["close"]})
feat_ff = feat.reindex(df.index, method="ffill")
print("\nAfter ffill to 15m (label=left):")
for ts in df.index:
    val = feat_ff.loc[ts, "close_1h"]
    c15 = df.loc[ts, "close"]
    if pd.notna(val):
        marker = " *** LOOKAHEAD" if val > c15 + 0.0003 else ""
        print(f"  {ts}  1h_close={val:.4f}  15m_close={c15:.4f}{marker}")

# ── BATCH: label='right', closed='right' (CLEAN) ──
print("\n=== BATCH: label=right, closed=right (CLEAN) ===")
r_right = df.resample("1h", label="right", closed="right").agg(
    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
).dropna()

print("\n1h bars created:")
for ts, row in r_right.iterrows():
    print(f"  1h label={ts}  close={row['close']:.4f}")

print("\n  Which 15m bars are in (07:00, 08:00] with right/right?")
for ts in times:
    if 7 <= ts.hour <= 8 and not (ts.hour == 7 and ts.minute == 0):
        if ts.hour == 7 or (ts.hour == 8 and ts.minute == 0):
            print(f"    {ts} close={df.loc[ts, 'close']:.4f}")

feat2 = pd.DataFrame({"close_1h": r_right["close"]})
feat2_ff = feat2.reindex(df.index, method="ffill")
print("\nAfter ffill to 15m (label=right):")
for ts in df.index:
    val = feat2_ff.loc[ts, "close_1h"]
    c15 = df.loc[ts, "close"]
    if pd.notna(val):
        print(f"  {ts}  1h_close={val:.4f}  15m_close={c15:.4f}")

# ── LIVE SIMULATION ──
print("\n" + "="*66)
print("=== LIVE SIMULATION: what happens when we process bar-by-bar ===")
print("="*66)
print("\nIn live trading, at each new 15m bar arrival:")
print("  - We have ALL past bars + the JUST-CLOSED current bar")
print("  - We call compute_v3_features(all_bars)")
print("  - _resample_ohlcv uses label='left', closed='left'")
print()

for i in range(len(times)):
    current_ts = times[i]
    # In live, we only have bars up to and including current_ts
    df_live = df.iloc[:i+1]

    # Resample with label='left' (production)
    r_live = df_live.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()

    # ffill
    feat_live = pd.DataFrame({"close_1h": r_live["close"]})
    feat_live_ff = feat_live.reindex(df_live.index, method="ffill")

    # What does the LAST bar see?
    val = feat_live_ff.iloc[-1]["close_1h"]

    # What is the last COMPLETE 1h bar?
    # A 1h bar labeled at hour H covers [H:00, H+1:00) with left/left
    # It's "complete" only when all 4 fifteen-minute bars have been received
    # i.e., when we have H:00, H:15, H:30, H:45

    # How many 15m bars in the current hour bucket?
    current_hour = current_ts.replace(minute=0, second=0)
    bars_in_hour = len(df_live[df_live.index >= current_hour])

    if current_ts.hour == 8 or (current_ts.hour == 7 and current_ts.minute >= 45):
        last_1h_label = r_live.index[-1]
        last_1h_close = r_live.iloc[-1]["close"]
        print(f"  LIVE at {current_ts}: see 1h_close={val:.4f}  "
              f"(last_1h_bar_label={last_1h_label}, 1h_close={last_1h_close:.4f}, "
              f"bars_in_hour={bars_in_hour})")

# ── KEY COMPARISON ──
print("\n" + "="*66)
print("KEY COMPARISON: What does the 08:15 bar see in BATCH vs LIVE?")
print("="*66)

ts_0815 = pd.Timestamp("2024-01-02 08:15", tz="UTC")
batch_val = feat_ff.loc[ts_0815, "close_1h"]

# Live at 08:15: we have all bars up to 08:15
df_live_0815 = df.loc[:ts_0815]
r_live_0815 = df_live_0815.resample("1h").agg(
    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
).dropna()
feat_live_0815 = pd.DataFrame({"close_1h": r_live_0815["close"]})
feat_live_0815_ff = feat_live_0815.reindex(df_live_0815.index, method="ffill")
live_val = feat_live_0815_ff.loc[ts_0815, "close_1h"]

batch_clean = feat2_ff.loc[ts_0815, "close_1h"]

print(f"\nAt 08:15 UTC:")
print(f"  BATCH (label=left):  1h_close = {batch_val:.4f}")
print(f"  LIVE  (label=left):  1h_close = {live_val:.4f}")
print(f"  BATCH (label=right): 1h_close = {batch_clean:.4f}")
print(f"  Actual 15m close:    {df.loc[ts_0815, 'close']:.4f}")
print()

if abs(batch_val - live_val) < 1e-8:
    print("  >>> BATCH and LIVE produce IDENTICAL results with label=left")
    print("  >>> The 'leak' in batch IS what happens in live!")
elif abs(live_val - batch_clean) < 1e-8:
    print("  >>> LIVE matches CLEAN (label=right)")
    print("  >>> The batch 'leak' does NOT match live behavior")
else:
    print(f"  >>> BATCH and LIVE DIFFER!")
    print(f"  >>> batch={batch_val:.4f}, live={live_val:.4f}, clean={batch_clean:.4f}")
    print("  >>> Need further investigation")
