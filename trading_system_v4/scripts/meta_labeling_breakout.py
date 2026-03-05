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
OUTPUT_FILE = DATA_DIR / "meta_labeled_1000t_breakout.parquet"

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

    # 3. Simulate Trades & Assign Meta-Labels
    print(f"Simulating trades (TP={TP_ATR} ATR, SL={SL_ATR} ATR, Lookahead={LOOKAHEAD_BARS} bars) ...")
    
    close_arr = df["close"].to_numpy()
    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    atr_arr = df["atr"].to_numpy()
    signal_arr = df["signal"].to_numpy()
    
    y_meta = np.full(len(df), -1, dtype=np.int8)
    
    for i in signal_indices:
        if i + LOOKAHEAD_BARS >= len(df):
            continue # Skip if too close to the end of the dataset
            
        c = close_arr[i]
        a = atr_arr[i]
        sig = signal_arr[i]
        
        h_path = high_arr[i+1 : i+1+LOOKAHEAD_BARS]
        l_path = low_arr[i+1 : i+1+LOOKAHEAD_BARS]
        
        if sig == 1: # Long Trade
            tp_level = (c + SPREAD_EST) + (a * TP_ATR)
            sl_level = (c + SPREAD_EST) - (a * SL_ATR)
            
            hit_tp = h_path >= tp_level
            hit_sl = l_path <= sl_level
            
        else: # Short Trade
            tp_level = (c - SPREAD_EST) - (a * TP_ATR)
            sl_level = (c - SPREAD_EST) + (a * SL_ATR)
            
            hit_tp = l_path <= tp_level
            hit_sl = h_path >= sl_level

        idx_tp = np.argmax(hit_tp) if np.any(hit_tp) else LOOKAHEAD_BARS
        idx_sl = np.argmax(hit_sl) if np.any(hit_sl) else LOOKAHEAD_BARS
        
        if idx_tp < idx_sl:
            y_meta[i] = 1  # Win
        elif idx_sl < idx_tp:
            y_meta[i] = 0  # Loss
        elif idx_tp == idx_sl and idx_tp < LOOKAHEAD_BARS:
            y_meta[i] = 0  # Hit both in same bar -> assume SL hit first (conservative)

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

    # 5. Filter down to ONLY the labeled signal rows
    # The ML model will ONLY be trained on these rows.
    ml_df = df[df["y_meta"] != -1].copy()
    
    # Drop raw price columns to prevent data leakage
    drop_cols = ["open", "high", "low", "close", "atr"]
    ml_df = ml_df.drop(columns=[c for c in drop_cols if c in ml_df.columns])
    
    ml_df = ml_df.dropna().reset_index(drop=True)
    
    win_rate = (ml_df["y_meta"] == 1).mean() * 100
    
    print(f"\n{'='*50}")
    print(f"META-LABELING COMPLETE")
    print(f"Total Training Rows (Signals): {len(ml_df):,}")
    print(f"Base Strategy Win Rate: {win_rate:.1f}%")
    print(f"Features: {len(ml_df.columns) - 3}") # Exclude timestamp, signal, y_meta
    print(f"{'='*50}")
    
    ml_df.to_parquet(OUTPUT_FILE, index=False)
    print(f"Saved Meta-Labeled dataset to: {OUTPUT_FILE}")

if __name__ == "__main__":
    run()
