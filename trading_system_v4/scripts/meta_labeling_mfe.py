"""
meta_labeling_ema.py — Meta-Labeling Pipeline for Tick Bars

This script implements the "Meta-Labeling" architecture:
1. Base Strategy: EMA Crossover (Fast EMA crosses Slow EMA).
2. Trade Simulation: For every crossover, simulates a trade with fixed TP/SL (in ATR).
3. Meta-Labeling: Assigns y=1 if the trade won (hit TP), y=0 if it lost (hit SL).
4. Feature Engineering: Calculates market microstructure and standard features 
   *only* at the exact moment of the crossover.

The resulting dataset is used to train an ML model to answer:
"Given this EMA crossover, what is the probability it will hit TP before SL?"

Usage:
  python -m trading_system_v4.scripts.meta_labeling_ema
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

# ── Configuration ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"
INPUT_FILE = DATA_DIR / "eurusd_1000t_bars.parquet"
OUTPUT_FILE = DATA_DIR / "meta_labeled_1000t_mfe.parquet"

# Base Strategy Parameters
EMA_FAST = 20
EMA_SLOW = 50

# Trade Simulation Parameters
TP_ATR = 1.5
SL_ATR = 1.0
LOOKAHEAD_BARS = 100  # Max bars to hold the trade
SPREAD_EST = 0.00010  # 1 pip spread penalty

# ── Helpers ───────────────────────────────────────────────────────────────────
def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))

# ── Main Logic ────────────────────────────────────────────────────────────────
def run():
    if not INPUT_FILE.exists():
        print(f"[ERROR] Tick bar data not found at {INPUT_FILE}")
        print("Please wait for download_tick_data.py to finish saving checkpoints.")
        return

    print(f"Loading Tick Bars from {INPUT_FILE} ...")
    df = pd.read_parquet(INPUT_FILE)
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"Loaded {len(df):,} bars.")

    # 1. Calculate Base Indicators
    print("Calculating Base Strategy (Microstructure Breakout) ...")
    df["atr"] = _atr(df, 14)

    # 2. Find Breakouts (The Base Signals)
    lookback = 10
    df["roll_high"] = df["high"].shift(1).rolling(lookback).max()
    df["roll_low"]  = df["low"].shift(1).rolling(lookback).min()
    df["vel_sma"]   = df["tick_velocity"].shift(1).rolling(lookback).mean()

    df["signal"] = 0

    # Long: Close breaks high, velocity surges, order flow is positive
    long_cond = (
        (df["close"] > df["roll_high"]) & 
        (df["tick_velocity"] > df["vel_sma"] * 1.2) & 
        (df["vol_imbalance"] > 0)
    )
    df.loc[long_cond, "signal"] = 1

    # Short: Close breaks low, velocity surges, order flow is negative
    short_cond = (
        (df["close"] < df["roll_low"]) & 
        (df["tick_velocity"] > df["vel_sma"] * 1.2) & 
        (df["vol_imbalance"] < 0)
    )
    df.loc[short_cond, "signal"] = -1

    # Drop temporary columns
    df = df.drop(columns=["roll_high", "roll_low", "vel_sma"])

    signal_indices = df[df["signal"] != 0].index
    print(f"Found {len(signal_indices):,} total breakout signals.")

    # 3. Calculate Maximum Favorable Excursion (MFE)
    print(f"Calculating MFE (Lookahead={LOOKAHEAD_BARS} bars) ...")
    
    close_arr = df["close"].to_numpy()
    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    atr_arr = df["atr"].to_numpy()
    signal_arr = df["signal"].to_numpy()
    
    # y_meta will now store the MFE in terms of ATR multiples
    y_meta = np.full(len(df), np.nan, dtype=np.float32)
    
    for i in signal_indices:
        if i + LOOKAHEAD_BARS >= len(df):
            continue # Skip if too close to the end of the dataset
            
        c = close_arr[i]
        a = atr_arr[i]
        sig = signal_arr[i]
        
        h_path = high_arr[i+1 : i+1+LOOKAHEAD_BARS]
        l_path = low_arr[i+1 : i+1+LOOKAHEAD_BARS]
        
        if sig == 1: # Long Trade
            # Max price reached before hitting a 1.0 ATR stop loss
            sl_level = (c + SPREAD_EST) - (a * SL_ATR)
            hit_sl = l_path <= sl_level
            idx_sl = np.argmax(hit_sl) if np.any(hit_sl) else LOOKAHEAD_BARS
            
            # MFE is the highest high before the SL was hit
            max_price = np.max(h_path[:idx_sl]) if idx_sl > 0 else c
            mfe_pips = max_price - (c + SPREAD_EST)
            
        else: # Short Trade
            # Min price reached before hitting a 1.0 ATR stop loss
            sl_level = (c - SPREAD_EST) + (a * SL_ATR)
            hit_sl = h_path >= sl_level
            idx_sl = np.argmax(hit_sl) if np.any(hit_sl) else LOOKAHEAD_BARS
            
            # MFE is the lowest low before the SL was hit
            min_price = np.min(l_path[:idx_sl]) if idx_sl > 0 else c
            mfe_pips = (c - SPREAD_EST) - min_price

        # Convert MFE to ATR multiples
        y_meta[i] = mfe_pips / a

    df["y_meta"] = y_meta

    # 4. Feature Engineering (Only for the signal rows to save memory/compute)
    print("Engineering Microstructure & Context Features ...")
    
    # Time features
    ts = pd.to_datetime(df["timestamp"], utc=True)
    hour = ts.dt.hour
    df["hour_sin"] = np.sin(2 * math.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * math.pi * hour / 24)
    df["is_london"] = ((hour >= 7) & (hour < 16)).astype(float)
    df["is_ny"] = ((hour >= 13) & (hour < 21)).astype(float)
    
    # Oscillators & Volatility
    df["rsi_14"] = _rsi(df["close"], 14) / 100.0
    df["atr_norm"] = df["atr"] / df["close"]
    
    # Microstructure (Tick Velocity & Spread)
    # Smooth the tick velocity to get the recent trend of activity
    df["tick_velocity_sma5"] = df["tick_velocity"].rolling(5).mean()
    df["tick_velocity_ratio"] = df["tick_velocity"] / (df["tick_velocity_sma5"] + 1e-6)
    
    df["spread_sma5"] = df["avg_spread"].rolling(5).mean()
    df["spread_ratio"] = df["avg_spread"] / (df["spread_sma5"] + 1e-6)
    
    # NEW: Liquidity Shock (Max spread vs Average spread)
    df["liquidity_shock"] = df["max_spread"] / (df["avg_spread"] + 1e-6)
    
    # Volume Imbalance Momentum
    df["vol_imbalance_sma5"] = df["vol_imbalance"].rolling(5).mean()
    
    # NEW: Order Flow Toxicity (Buy Ratio Momentum)
    df["buy_ratio_sma5"] = df["buy_ratio"].rolling(5).mean()
    df["order_flow_toxicity"] = df["buy_ratio"] - df["buy_ratio_sma5"]
    
    # NEW: Microstructure Trend Alignment
    # Is the tick velocity increasing while the spread is decreasing? (Healthy trend)
    df["micro_trend_alignment"] = np.where(
        (df["tick_velocity_ratio"] > 1.0) & (df["spread_ratio"] < 1.0), 1.0,
        np.where((df["tick_velocity_ratio"] < 1.0) & (df["spread_ratio"] > 1.0), -1.0, 0.0)
    )
    
    # NEW: Volume Imbalance vs Price Action Divergence
    # If price is breaking out up but volume imbalance is negative (more selling), that's a divergence
    df["price_vol_divergence"] = np.where(
        (df["signal"] == 1) & (df["vol_imbalance_sma5"] < 0), 1.0,
        np.where((df["signal"] == -1) & (df["vol_imbalance_sma5"] > 0), 1.0, 0.0)
    )

    # NEW: Macro Context Features (Longer-term trends)
    # Price Momentum (10-bar and 50-bar returns)
    df["ret_10"] = df["close"] / df["close"].shift(10) - 1.0
    df["ret_50"] = df["close"] / df["close"].shift(50) - 1.0
    
    # Distance to recent highs/lows (normalized by ATR)
    roll_high_10 = df["high"].shift(1).rolling(10).max()
    roll_low_10  = df["low"].shift(1).rolling(10).min()
    roll_high_50 = df["high"].shift(1).rolling(50).max()
    roll_low_50  = df["low"].shift(1).rolling(50).min()
    
    df["dist_to_high_10"] = (df["close"] - roll_high_10) / (df["atr"] + 1e-8)
    df["dist_to_low_10"]  = (df["close"] - roll_low_10) / (df["atr"] + 1e-8)
    df["dist_to_high_50"] = (df["close"] - roll_high_50) / (df["atr"] + 1e-8)
    df["dist_to_low_50"]  = (df["close"] - roll_low_50) / (df["atr"] + 1e-8)
    
    # Volatility Regime (Current ATR vs 50-bar average ATR)
    df["atr_sma50"] = df["atr"].rolling(50).mean()
    df["volatility_regime"] = df["atr"] / (df["atr_sma50"] + 1e-8)
    
    # Macro Order Flow (50-bar average volume imbalance)
    df["vol_imbalance_sma50"] = df["vol_imbalance"].rolling(50).mean()

    # NEW: Candle/path-shape and microstructure quality features
    bar_range = (df["high"] - df["low"]).clip(lower=1e-8)
    df["bar_range_norm"] = bar_range / (df["close"] + 1e-8)
    df["body_ratio"] = (df["close"] - df["open"]).abs() / bar_range
    df["upper_wick_ratio"] = (df["high"] - df[["open", "close"]].max(axis=1)) / bar_range
    df["lower_wick_ratio"] = (df[["open", "close"]].min(axis=1) - df["low"]) / bar_range

    df["range_sma10"] = bar_range.rolling(10).mean()
    df["range_ratio"] = bar_range / (df["range_sma10"] + 1e-8)
    df["spread_to_range"] = df["avg_spread"] / (bar_range + 1e-8)

    df["vol_imbalance_chg1"] = df["vol_imbalance"].diff(1)
    df["buy_ratio_chg1"] = df["buy_ratio"].diff(1)

    tv_sma20 = df["tick_velocity"].rolling(20).mean()
    tv_std20 = df["tick_velocity"].rolling(20).std().replace(0, np.nan)
    df["tick_velocity_z20"] = (df["tick_velocity"] - tv_sma20) / (tv_std20 + 1e-8)

    # Breakout quality at trigger bar (distance beyond prior 10-bar boundary)
    prior_high_10 = df["high"].shift(1).rolling(10).max()
    prior_low_10 = df["low"].shift(1).rolling(10).min()
    df["breakout_distance_atr"] = np.where(
        df["signal"] == 1,
        (df["close"] - prior_high_10) / (df["atr"] + 1e-8),
        np.where(
            df["signal"] == -1,
            (prior_low_10 - df["close"]) / (df["atr"] + 1e-8),
            0.0,
        ),
    )

    # NEW: 15-minute HTF context (strict no-lookahead via 1-bar shift)
    ts_utc = pd.to_datetime(df["timestamp"], utc=True)
    htf_src = df[[
        "timestamp", "open", "high", "low", "close",
        "tick_velocity", "avg_spread", "vol_imbalance", "buy_ratio", "total_volume",
    ]].copy()
    htf_src["timestamp"] = ts_utc
    htf_src = htf_src.set_index("timestamp")

    htf = htf_src.resample("15min", label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "tick_velocity": "mean",
            "avg_spread": "mean",
            "vol_imbalance": "mean",
            "buy_ratio": "mean",
            "total_volume": "sum",
        }
    ).dropna().reset_index()

    htf["htf15_atr"] = _atr(htf, 14)
    htf["htf15_atr_norm"] = htf["htf15_atr"] / (htf["close"] + 1e-8)
    htf["htf15_rsi14"] = _rsi(htf["close"], 14) / 100.0
    htf["htf15_ret3"] = htf["close"] / htf["close"].shift(3) - 1.0
    htf["htf15_ret8"] = htf["close"] / htf["close"].shift(8) - 1.0
    htf["htf15_ema20"] = _ema(htf["close"], 20)
    htf["htf15_ema50"] = _ema(htf["close"], 50)
    htf["htf15_trend_strength"] = (htf["htf15_ema20"] - htf["htf15_ema50"]) / (htf["close"] + 1e-8)
    htf_range = (htf["high"] - htf["low"]).clip(lower=1e-8)
    htf["htf15_spread_to_range"] = htf["avg_spread"] / (htf_range + 1e-8)
    htf["htf15_vol_imb_sma4"] = htf["vol_imbalance"].rolling(4).mean()
    htf["htf15_buy_ratio_sma4"] = htf["buy_ratio"].rolling(4).mean()

    htf_feature_cols = [
        "htf15_atr_norm",
        "htf15_rsi14",
        "htf15_ret3",
        "htf15_ret8",
        "htf15_trend_strength",
        "htf15_spread_to_range",
        "htf15_vol_imb_sma4",
        "htf15_buy_ratio_sma4",
    ]
    htf[htf_feature_cols] = htf[htf_feature_cols].shift(1)

    df_merge = df.copy()
    df_merge["timestamp"] = ts_utc
    htf_merge = htf[["timestamp"] + htf_feature_cols].sort_values("timestamp")
    df_merge = pd.merge_asof(
        df_merge.sort_values("timestamp"),
        htf_merge,
        on="timestamp",
        direction="backward",
        allow_exact_matches=True,
    )
    df = df_merge

    # NEW: 1-hour HTF context (independent structure, strict no-lookahead)
    htf1h = htf_src.resample("1h", label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "tick_velocity": "mean",
            "avg_spread": "mean",
            "vol_imbalance": "mean",
            "buy_ratio": "mean",
            "total_volume": "sum",
        }
    ).dropna().reset_index()

    htf1h["htf1h_atr"] = _atr(htf1h, 14)
    htf1h["htf1h_atr_norm"] = htf1h["htf1h_atr"] / (htf1h["close"] + 1e-8)
    htf1h["htf1h_rsi14"] = _rsi(htf1h["close"], 14) / 100.0
    htf1h["htf1h_ret3"] = htf1h["close"] / htf1h["close"].shift(3) - 1.0
    htf1h["htf1h_ret8"] = htf1h["close"] / htf1h["close"].shift(8) - 1.0
    htf1h["htf1h_ema20"] = _ema(htf1h["close"], 20)
    htf1h["htf1h_ema50"] = _ema(htf1h["close"], 50)
    htf1h["htf1h_trend_strength"] = (htf1h["htf1h_ema20"] - htf1h["htf1h_ema50"]) / (htf1h["close"] + 1e-8)
    htf1h_range = (htf1h["high"] - htf1h["low"]).clip(lower=1e-8)
    htf1h["htf1h_spread_to_range"] = htf1h["avg_spread"] / (htf1h_range + 1e-8)

    htf1h_feature_cols = [
        "htf1h_atr_norm",
        "htf1h_rsi14",
        "htf1h_ret3",
        "htf1h_ret8",
        "htf1h_trend_strength",
        "htf1h_spread_to_range",
    ]
    htf1h[htf1h_feature_cols] = htf1h[htf1h_feature_cols].shift(1)

    htf1h_merge = htf1h[["timestamp"] + htf1h_feature_cols].sort_values("timestamp")
    df = pd.merge_asof(
        df.sort_values("timestamp"),
        htf1h_merge,
        on="timestamp",
        direction="backward",
        allow_exact_matches=True,
    )

    # NEW: regime-conditioned interaction features
    atr_q_hi = df["atr_norm"].quantile(0.70)
    spread_q_hi = df["spread_to_range"].quantile(0.70)

    df["regime_high_vol"] = (df["atr_norm"] >= atr_q_hi).astype(float)
    df["regime_wide_spread"] = (df["spread_to_range"] >= spread_q_hi).astype(float)
    df["regime_stress"] = (df["regime_high_vol"] * df["regime_wide_spread"]).astype(float)

    df["edge_breakout_x_trend15"] = df["breakout_distance_atr"] * df["htf15_trend_strength"]
    df["edge_breakout_x_trend1h"] = df["breakout_distance_atr"] * df["htf1h_trend_strength"]
    df["edge_signal_x_trend15"] = df["signal"] * df["htf15_trend_strength"]
    df["edge_signal_x_trend1h"] = df["signal"] * df["htf1h_trend_strength"]
    df["edge_velocity_x_regime"] = df["tick_velocity_z20"] * (1.0 - df["regime_stress"])
    df["edge_spreadpenalty_x_regime"] = df["spread_to_range"] * df["regime_stress"]

    # 5. Filter down to ONLY the labeled signal rows
    # The ML model will ONLY be trained on these rows.
    ml_df = df[~df["y_meta"].isna()].copy()
    
    # Drop raw price columns to prevent data leakage
    drop_cols = ["open", "high", "low", "close", "atr"]
    ml_df = ml_df.drop(columns=[c for c in drop_cols if c in ml_df.columns])
    
    ml_df = ml_df.dropna().reset_index(drop=True)
    
    avg_mfe = ml_df["y_meta"].mean()
    
    print(f"\n{'='*50}")
    print(f"META-LABELING COMPLETE")
    print(f"Total Training Rows (Signals): {len(ml_df):,}")
    print(f"Average MFE (ATR multiples): {avg_mfe:.2f}")
    print(f"Features: {len(ml_df.columns) - 3}") # Exclude timestamp, signal, y_meta
    print(f"{'='*50}")
    
    ml_df.to_parquet(OUTPUT_FILE, index=False)
    print(f"Saved Meta-Labeled dataset to: {OUTPUT_FILE}")

if __name__ == "__main__":
    run()
