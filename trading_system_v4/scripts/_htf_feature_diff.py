"""
Quantify derived HTF feature differences between BATCH and LIVE modes.

In BATCH (label=left): all 1h bars are complete → features use end-of-hour close
In LIVE  (label=left): last 1h bar is partial   → features use current-bar close

This tests how much the DERIVED features (RSI, MACD, SMA, returns) differ,
not just the raw 1h close. The model consumes these derived features, so this
is the actual train/serve skew the model faces.

Uses the FULL v3 feature pipeline, comparing:
  A) BATCH mode: compute_v3_features on full dataset (production training)
  B) LIVE  mode: compute_v3_features bar-by-bar, simulating incremental arrival
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.feature_engineering_v3 import compute_v3_features, FEATURE_COLUMNS_V3

TICK_BARS_FILE = ROOT / "trading_system_v4" / "data" / "eurusd_1000t_bars.parquet"

# HTF feature names
HTF_FEATURES = [
    "returns_1h_4", "rsi_1h", "macd_diff_1h", "price_to_sma20_1h", "di_diff_1h",
    "returns_4h_4", "rsi_4h", "macd_diff_4h", "price_to_sma20_4h",
    "trend_alignment",
]

# 15m-only features (should be IDENTICAL between batch and live)
CONTROL_FEATURES = ["returns_1", "rsi", "macd_diff", "bb_zscore", "close_position"]


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

    # ── BATCH FEATURES: compute on full dataset ──────────────────────────────
    print("\nComputing BATCH features (full dataset) ...")
    batch_feats = compute_v3_features(df15)
    print(f"  Shape: {batch_feats.shape}")

    # ── LIVE FEATURES: simulate bar-by-bar arrival ────────────────────────────
    # Full bar-by-bar would take too long for 176k bars.
    # Instead, test a representative sample of 500 bars at different points.
    # For indicators like RSI(14) and SMA(20), we need sufficient warmup,
    # so we compute features from scratch each time with at least 1000 bars of history.

    sample_indices = sorted(set(
        list(range(5000, 5100)) +           # Early
        list(range(50000, 50100)) +         # Mid
        list(range(100000, 100100)) +       # Late-mid
        list(range(150000, 150100)) +       # Late
        list(range(170000, 170100))         # Recent
    ))

    print(f"\nComputing LIVE features for {len(sample_indices)} bars ...")
    live_rows = {}
    
    for count, idx in enumerate(sample_indices):
        if (count + 1) % 50 == 0:
            print(f"  {count+1}/{len(sample_indices)} ...")
        
        # In live, we have all bars up to this point but NOT future bars
        df_live = df15.iloc[:idx+1]
        
        # Compute v3 features — this will resample to 1h/4h from the available data
        feats = compute_v3_features(df_live)
        live_rows[df15.index[idx]] = feats.iloc[-1]  # latest row
    
    live_feats = pd.DataFrame.from_dict(live_rows, orient="index")
    print(f"  Live features shape: {live_feats.shape}")

    # ── COMPARE ──────────────────────────────────────────────────────────────
    batch_sample = batch_feats.loc[live_feats.index]
    
    # Sanity: 15m features should be identical
    print(f"\n{'='*80}")
    print("SANITY CHECK: 15m features (should be identical)")
    print(f"{'='*80}")
    for col in CONTROL_FEATURES:
        b = batch_sample[col].values
        l = live_feats[col].values
        max_diff = np.nanmax(np.abs(b - l))
        print(f"  {col:<25} max_diff = {max_diff:.10f} {'✓ IDENTICAL' if max_diff < 1e-10 else '✗ DIFFER!'}")

    # HTF features comparison
    print(f"\n{'='*80}")
    print("HTF FEATURE DIFFERENCES: Batch (training) vs Live (inference)")
    print(f"{'='*80}")
    
    print(f"\n  {'Feature':<25} {'Mean Diff':>12} {'Std Diff':>12} {'Max Diff':>12} "
          f"{'Mean |Feat|':>12} {'Rel Error%':>12} {'Match%':>8}")
    print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
    
    for col in HTF_FEATURES:
        b = batch_sample[col].values
        l = live_feats[col].values
        diff = b - l
        abs_diff = np.abs(diff)
        
        mean_diff = np.nanmean(diff)
        std_diff = np.nanstd(diff)
        max_diff = np.nanmax(abs_diff)
        mean_abs_feat = np.nanmean(np.abs(b))
        rel_error = (np.nanmean(abs_diff) / mean_abs_feat * 100) if mean_abs_feat > 1e-10 else float('inf')
        match_pct = np.mean(abs_diff < 1e-8) * 100
        
        print(f"  {col:<25} {mean_diff:>12.6f} {std_diff:>12.6f} {max_diff:>12.6f} "
              f"{mean_abs_feat:>12.6f} {rel_error:>11.1f}% {match_pct:>7.1f}%")

    # ── Hour-position breakdown ───────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("HOUR-POSITION BREAKDOWN: Relative error by position within hour")
    print(f"{'='*80}")
    
    minute_pos = batch_sample.index.minute // 15
    
    print(f"\n  {'Feature':<25} {'Pos0 RelErr%':>14} {'Pos1 RelErr%':>14} "
          f"{'Pos2 RelErr%':>14} {'Pos3 RelErr%':>14}")
    print(f"  {'-'*25} {'-'*14} {'-'*14} {'-'*14} {'-'*14}")
    
    for col in HTF_FEATURES:
        b = batch_sample[col].values
        l = live_feats[col].values
        abs_diff = np.abs(b - l)
        mean_abs_feat = np.nanmean(np.abs(b))
        
        parts = []
        for pos in range(4):
            mask = minute_pos == pos
            if mask.any() and mean_abs_feat > 1e-10:
                rel = np.nanmean(abs_diff[mask]) / mean_abs_feat * 100
                parts.append(f"{rel:>13.1f}%")
            else:
                parts.append(f"{'N/A':>14}")
        
        print(f"  {col:<25} {'  '.join(parts)}")

    # ── Direction agreement (most important for trading) ──────────────────────
    print(f"\n{'='*80}")
    print("DIRECTION AGREEMENT: Does live-inferred trend match batch-inferred trend?")
    print(f"{'='*80}")
    
    signed_features = [
        ("macd_diff_1h", "1h MACD > 0 → bullish"),
        ("di_diff_1h", "1h DI+ > DI- → bullish"),
        ("returns_1h_4", "1h 4-bar return > 0"),
        ("macd_diff_4h", "4h MACD > 0 → bullish"),
        ("returns_4h_4", "4h 4-bar return > 0"),
        ("trend_alignment", "Overall alignment same sign"),
    ]
    
    print(f"\n  {'Feature':<25} {'Same Sign%':>12} {'Diff at Pos0':>14} {'Diff at Pos3':>14}")
    print(f"  {'-'*25} {'-'*12} {'-'*14} {'-'*14}")
    
    for col, desc in signed_features:
        b = batch_sample[col].values
        l = live_feats[col].values
        
        # Same sign analysis
        same = np.sign(b) == np.sign(l)
        overall = same.mean() * 100
        
        pos0_mask = minute_pos == 0
        pos3_mask = minute_pos == 3
        
        pos0_agree = same[pos0_mask].mean() * 100 if pos0_mask.any() else float('nan')
        pos3_agree = same[pos3_mask].mean() * 100 if pos3_mask.any() else float('nan')
        
        print(f"  {col:<25} {overall:>11.1f}% {pos0_agree:>13.1f}% {pos3_agree:>13.1f}%")
    
    print(f"\n  Interpretation:")
    print(f"  - Position 0 (first bar of hour): MAXIMUM skew — live sees previous hour's last bar")
    print(f"  - Position 3 (last bar of hour): ZERO skew — hour is complete, batch = live")
    print(f"  - If direction agreement at Pos0 is high, the model may work despite the skew")
    print(f"  - If it's low, the model is effectively getting random HTF signals at Pos0")

    # ── Feature importance context ────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("CONCLUSION")
    print(f"{'='*80}")
    print(f"\n  The model was trained on BATCH features where HTF uses end-of-hour closes.")
    print(f"  In LIVE, the latest hour is PARTIAL (close = current 15m bar close).")
    print(f"  For derived indicators (RSI, MACD, SMA), only 1 bar out of 14-26 is wrong,")
    print(f"  so the ACTUAL feature differences for most HTF features should be modest.")
    print(f"  The critical question is whether direction agreement is high enough for the")
    print(f"  model's decisions to remain valid.")


if __name__ == "__main__":
    run()
