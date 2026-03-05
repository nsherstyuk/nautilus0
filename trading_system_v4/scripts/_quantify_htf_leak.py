"""
Quantify HTF alignment: BATCH vs LIVE vs CLEAN for all 15m bars.

For each 15m bar, compute what the 1h close feature value is under:
  A) BATCH label=left  (production training — has future data for 3/4 bars per hour)
  B) LIVE  label=left  (production inference — sees partial current hour)
  C) CLEAN label=right (no leak — sees only completed hours)
  
This tells us:
  - How much of batch training used info live doesn't have (the real leak)
  - Whether live inference is closer to batch or clean
  - Whether the model trained on batch can be expected to work in live

Uses real tick-bar data (not synthetic).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"


def run():
    print("Loading tick bars ...")
    tick = pd.read_parquet(TICK_BARS_FILE)
    tick["timestamp"] = pd.to_datetime(tick["timestamp"], utc=True)
    tick = tick.sort_values("timestamp").set_index("timestamp")

    print("Resampling to 15m ...")
    df15 = tick.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("total_volume", "sum"),
    ).dropna()
    print(f"  {len(df15):,} 15m bars")

    # ── A) BATCH label=left (production training) ─────────────────────────────
    print("\nComputing BATCH (label=left) 1h features ...")
    df_1h_left = df15.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    batch_close = df_1h_left["close"].reindex(df15.index, method="ffill")

    # ── B) LIVE label=left (what actually happens bar-by-bar) ─────────────────
    # In live: at each 15m bar, resample ALL history with label=left
    # The key difference: the LAST 1h bucket is PARTIAL (only has bars up to now)
    # 
    # We can compute this efficiently:
    # For each 15m bar at minute M within hour H:
    #   - If M > 0: the 1h bar labeled at H exists but is PARTIAL (close = current 15m close)
    #   - The PREVIOUS 1h bar (labeled H-1) is complete
    #
    # Actually in live the resample sees:
    #   label=left, closed=left: [H:00, H+1:00)
    #   When the current bar is H:15, the bucket [H:00, H+1:00) has only {H:00, H:15}
    #   So the "1h close" at label H = close of H:15 (partial!)
    #   When bar H:00 arrives, bucket [H:00, H+1:00) has only {H:00}
    #   So "1h close" at label H = close of H:00 (just the first 15m bar)
    
    # Efficient computation: For bar at time T:
    # - The 1h bucket labeled at floor(T, 1h) contains bars from floor(T) to T
    # - Its "close" = close of the LAST bar in the bucket = close(T) itself
    # - Actually with ffill, the last bar T gets the 1h close of the bucket it falls in
    #   which contains T itself → close = close(T) always
    # Wait, that's still not quite right. Let me trace more carefully.
    
    # With label=left, closed=left, 15m bars go into 1h buckets:
    #   06:00 → bucket [06:00, 07:00) → label 06:00
    #   06:15 → bucket [06:00, 07:00) → label 06:00
    #   ...
    #   06:45 → bucket [06:00, 07:00) → label 06:00
    #   07:00 → bucket [07:00, 08:00) → label 07:00
    #   07:15 → bucket [07:00, 08:00) → label 07:00
    
    # In BATCH: all bars exist, so bucket [07:00, 08:00) = {07:00, 07:15, 07:30, 07:45}
    #   close = 07:45 close
    # In LIVE at 07:15: bucket [07:00, 08:00) = {07:00, 07:15} only
    #   close = 07:15 close

    # But wait — the 15m bars have label=right, closed=right indexing.
    # So a bar with timestamp 07:15 covers the period (07:00, 07:15].
    # When we resample those with label=left, closed=left:
    #   Pandas groups by the LEFT edge of 1h bins: [07:00, 08:00), [08:00, 09:00), ...
    #   A 15m bar at TS falls into bin where bin_start <= TS < bin_end
    #   So TS=07:00 falls into [07:00, 08:00) with label 07:00
    #   TS=07:15 falls into [07:00, 08:00) with label 07:00
    #   TS=08:00 falls into [08:00, 09:00) with label 08:00
    
    # In BATCH mode: label 08:00 = {08:00, 08:15, 08:30, 08:45}, close = 08:45 close
    # After ffill: 15m bar at 08:00 sees 1h_close = 08:45 close (LOOKAHEAD!)
    
    # In LIVE at 08:00: only {08:00} exists in bucket, close = 08:00 close
    # In LIVE at 08:15: {08:00, 08:15} exist, close = 08:15 close
    # In LIVE at 08:30: {08:00, 08:15, 08:30} exist, close = 08:30 close
    # In LIVE at 08:45: {08:00, 08:15, 08:30, 08:45} exist, close = 08:45 close (SAME as batch!)

    # So: for the LAST bar of each hour (minute position 3/4 = the 4th bar),
    #      live = batch (no leak)
    # For the FIRST bar of each hour (minute position 0),
    #      live sees current bar close, batch sees end-of-hour close (MAX leak)
    
    # In live mode, the 1h feature at any 15m bar = that bar's own close (approx)
    # because the partial bucket always has the current bar as the last entry.
    # Actually: the ffill means the PREVIOUS completed hour's features might be used...
    # No — the current hour's bucket IS created (with partial data), so ffill isn't needed
    # for the current bucket. The 1h_close visible at each 15m bar = close of that 15m bar.
    
    # Wait, actually: in live when we have only bar 08:00, resample creates:
    #   label 07:00 → {07:00, 07:15, 07:30, 07:45} → close = 07:45 close (COMPLETE)
    #   label 08:00 → {08:00} → close = 08:00 close (PARTIAL)
    # Then ffill to 15m: bar at 08:00 gets label 08:00's close = 08:00 close
    
    # So live_1h_close(T) = close(T) itself for first 3 bars of hour,
    #    and = close(T) for last bar too
    # This means: LIVE_1h_close ≈ current 15m close (always!)
    # This is NEITHER batch behavior NOR clean behavior.

    # Let me verify this properly by computing for a subset
    print("Computing LIVE (label=left, bar-by-bar) for sample ...")
    
    # Take a small representative sample
    sample_start = 5000
    sample_end = 5200
    sample = df15.iloc[sample_start:sample_end]
    
    live_1h_close = pd.Series(index=sample.index, dtype=float)
    
    for i in range(len(sample)):
        # In live: we have all bars up to this point
        df_so_far = df15.iloc[:sample_start + i + 1]
        
        r = df_so_far.resample("1h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        
        feat = pd.DataFrame({"close_1h": r["close"]})
        feat_ff = feat.reindex(df_so_far.index, method="ffill")
        
        live_1h_close.iloc[i] = feat_ff.iloc[-1]["close_1h"]
    
    # ── C) CLEAN label=right ──────────────────────────────────────────────────
    print("Computing CLEAN (label=right) ...")
    df_1h_right = df15.resample("1h", label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    clean_close = df_1h_right["close"].reindex(df15.index, method="ffill")

    # ── Compare for the sample ────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"COMPARISON: 200-bar sample (bars {sample_start}-{sample_end})")
    print(f"{'='*80}")
    
    batch_sample = batch_close.iloc[sample_start:sample_end]
    clean_sample = clean_close.iloc[sample_start:sample_end]
    actual_close = df15["close"].iloc[sample_start:sample_end]
    
    # Categorize each bar's position within its hour
    minute_pos = sample.index.minute // 15  # 0, 1, 2, 3
    
    print(f"\n  Hour-position analysis:")
    print(f"  {'Pos':>4} {'N':>5} {'Batch=Live':>11} {'Batch≠Live':>11} {'Live=Clean':>11}")
    
    for pos in range(4):
        mask = minute_pos == pos
        n = mask.sum()
        b = batch_sample[mask].values
        l = live_1h_close[mask].values
        c = clean_sample[mask].values
        
        bl_match = np.sum(np.abs(b - l) < 1e-8)
        lc_match = np.sum(np.abs(l - c) < 1e-8)
        
        print(f"  {pos:>4} {n:>5} {bl_match:>11} {n - bl_match:>11} {lc_match:>11}")
    
    # Show specific examples
    print(f"\n  Sample bars (first 40):")
    print(f"  {'Timestamp':<28} {'Pos':>4} {'Actual':>9} {'Batch_1h':>10} "
          f"{'Live_1h':>10} {'Clean_1h':>10} {'Notes':>20}")
    
    for i in range(min(40, len(sample))):
        ts = sample.index[i]
        pos = minute_pos[i]
        actual = actual_close.iloc[i]
        b = batch_sample.iloc[i]
        l = live_1h_close.iloc[i]
        c = clean_sample.iloc[i]
        
        notes = ""
        if abs(b - l) < 1e-8:
            notes = "batch=live"
        elif abs(l - c) < 1e-8:
            notes = "live=clean"
        elif abs(l - actual) < 1e-8:
            notes = "live=self"
        else:
            notes = "ALL DIFFER"
        
        # Flag lookahead
        if abs(b - l) > 1e-6:
            leak_pips = abs(b - l) * 10000
            notes += f" leak={leak_pips:.1f}p"
        
        print(f"  {str(ts):<28} {pos:>4} {actual:.5f} {b:.5f}  "
              f"{l:.5f}  {c:.5f}  {notes}")

    # ── Quantify the real leak ────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"LEAK QUANTIFICATION (200-bar sample)")
    print(f"{'='*80}")
    
    batch_vs_live = np.abs(batch_sample.values - live_1h_close.values) * 10000
    live_vs_clean = np.abs(live_1h_close.values - clean_sample.values) * 10000
    batch_vs_clean = np.abs(batch_sample.values - clean_sample.values) * 10000
    
    print(f"\n  Batch vs Live  (lookahead in training not available live):")
    print(f"    Mean: {batch_vs_live.mean():.2f} pips")
    print(f"    Max:  {batch_vs_live.max():.2f} pips")
    print(f"    Bars with any diff: {(batch_vs_live > 0.01).sum()}/{len(batch_vs_live)}")
    
    print(f"\n  Live vs Clean  (diff between live inference and no-leak):")
    print(f"    Mean: {live_vs_clean.mean():.2f} pips")
    print(f"    Max:  {live_vs_clean.max():.2f} pips")
    print(f"    Bars with any diff: {(live_vs_clean > 0.01).sum()}/{len(live_vs_clean)}")
    
    print(f"\n  Batch vs Clean (total leak in training data):")
    print(f"    Mean: {batch_vs_clean.mean():.2f} pips")
    print(f"    Max:  {batch_vs_clean.max():.2f} pips")

    # ── The key question: what does LIVE actually see? ────────────────────────
    print(f"\n{'='*80}")
    print(f"KEY INSIGHT: What does LIVE inference actually see?")
    print(f"{'='*80}")
    
    actual_vals = actual_close.values
    live_vals = live_1h_close.values
    live_eq_self = np.abs(live_vals - actual_vals) < 1e-8
    
    print(f"\n  Live 1h_close == current 15m close: {live_eq_self.sum()}/{len(live_eq_self)} "
          f"({live_eq_self.mean()*100:.1f}%)")
    print(f"\n  This means in LIVE mode with label=left:")
    print(f"  The '1h close' feature is just the current bar's own close!")
    print(f"  It carries NO higher-timeframe information at all.")
    print(f"  The model trained on BATCH data saw FUTURE 1h closes,")
    print(f"  but in LIVE it just sees the current price — a completely")
    print(f"  different distribution.")
    
    print(f"\n  CONCLUSION:")
    print(f"  The model was trained on future-leaked 1h/4h features,")
    print(f"  but in live trading it sees DIFFERENT values (partial-hour close).")
    print(f"  The batch leak does NOT match live behavior.")
    print(f"  The model's live performance is UNPREDICTABLE — it was never")
    print(f"  exposed to the data distribution it encounters in production.")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    run()
