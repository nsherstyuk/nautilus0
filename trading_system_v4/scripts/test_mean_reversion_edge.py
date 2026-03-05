"""
Mean-Reversion & Market-Making Edge Test for EURUSD
====================================================
Tests whether EURUSD exhibits exploitable mean-reversion behavior at
various timeframes. This is fundamentally different from direction
prediction — we test whether price snaps back after deviations.

Signals tested:
  1. Bollinger Band reversion (price touches outer band → reverts to mean)
  2. RSI extremes (oversold/overbought → reversion)
  3. Z-score of price deviation from VWAP
  4. Intraday range exhaustion (price near session high/low → reverts)
  5. Microstructure-informed reversion (vol_imbalance extremes + BB)
  6. Simple market-making simulation (quote around mid, manage inventory)

Metrics: hit rate, profit factor, avg PnL per trade (in pips), Sharpe.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

DATA_PATH = Path("trading_system_v4/data/eurusd_1000t_bars.parquet")
SPREAD_PIPS = 1.0        # 1 pip spread cost each way (realistic for EURUSD)
SPREAD = SPREAD_PIPS * 0.0001
PIP = 0.0001

# ─────────────────────────────────────────────────
# Data Loading & Resampling
# ─────────────────────────────────────────────────

def load_and_resample(timeframe: str = "15min") -> pd.DataFrame:
    """Load tick bars, resample to fixed timeframe, compute indicators."""
    raw = pd.read_parquet(DATA_PATH)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])
    raw = raw.set_index("timestamp").sort_index()

    # Resample OHLCV (label=right, closed=right — no lookahead)
    ohlcv = raw["close"].resample(timeframe, label="right", closed="right").ohlc()
    ohlcv.columns = ["open", "high", "low", "close"]
    ohlcv["volume"] = raw["total_volume"].resample(timeframe, label="right", closed="right").sum()
    ohlcv["vol_imbalance"] = raw["vol_imbalance"].resample(timeframe, label="right", closed="right").mean()
    ohlcv["buy_ratio"] = raw["buy_ratio"].resample(timeframe, label="right", closed="right").mean()
    ohlcv["avg_spread"] = raw["avg_spread"].resample(timeframe, label="right", closed="right").mean()
    ohlcv = ohlcv.dropna(subset=["close"])

    # Bollinger Bands (20-period)
    ohlcv["bb_mid"] = ohlcv["close"].rolling(20).mean()
    ohlcv["bb_std"] = ohlcv["close"].rolling(20).std()
    ohlcv["bb_upper"] = ohlcv["bb_mid"] + 2 * ohlcv["bb_std"]
    ohlcv["bb_lower"] = ohlcv["bb_mid"] - 2 * ohlcv["bb_std"]
    ohlcv["bb_pct"] = (ohlcv["close"] - ohlcv["bb_lower"]) / (ohlcv["bb_upper"] - ohlcv["bb_lower"])

    # RSI (14-period)
    delta = ohlcv["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    ohlcv["rsi"] = 100 - (100 / (1 + rs))

    # ATR (14-period)
    tr = pd.concat([
        ohlcv["high"] - ohlcv["low"],
        (ohlcv["high"] - ohlcv["close"].shift(1)).abs(),
        (ohlcv["low"] - ohlcv["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    ohlcv["atr"] = tr.rolling(14).mean()

    # Z-score of close vs rolling mean
    ohlcv["zscore"] = (ohlcv["close"] - ohlcv["bb_mid"]) / ohlcv["bb_std"]

    # Session info (UTC hours)
    ohlcv["hour"] = ohlcv.index.hour
    ohlcv["is_london"] = ohlcv["hour"].between(7, 16)
    ohlcv["is_ny"] = ohlcv["hour"].between(13, 21)
    ohlcv["is_asian"] = ohlcv["hour"].between(0, 7) | (ohlcv["hour"] >= 22)

    # Rolling session high/low (last 4h = 16 bars for 15m)
    lookback = max(1, int(pd.Timedelta("4h") / pd.Timedelta(timeframe)))
    ohlcv["rolling_high"] = ohlcv["high"].rolling(lookback).max()
    ohlcv["rolling_low"] = ohlcv["low"].rolling(lookback).min()
    ohlcv["range_pct"] = (ohlcv["close"] - ohlcv["rolling_low"]) / \
                          (ohlcv["rolling_high"] - ohlcv["rolling_low"]).replace(0, np.nan)

    # Forward returns for evaluation (1-bar, 3-bar, 6-bar)
    for n in [1, 3, 6, 12]:
        ohlcv[f"fwd_ret_{n}"] = ohlcv["close"].shift(-n) - ohlcv["close"]
        ohlcv[f"fwd_high_{n}"] = ohlcv["high"].shift(-1).rolling(n).max() - ohlcv["close"]
        ohlcv[f"fwd_low_{n}"] = ohlcv["low"].shift(-1).rolling(n).min() - ohlcv["close"]

    ohlcv = ohlcv.dropna()
    return ohlcv


# ─────────────────────────────────────────────────
# Test Framework
# ─────────────────────────────────────────────────

def evaluate_signal(df: pd.DataFrame, signal_name: str,
                    long_mask: pd.Series, short_mask: pd.Series,
                    tp_atr: float = 1.0, sl_atr: float = 1.5,
                    max_bars: int = 12):
    """
    Evaluate a mean-reversion signal.
    
    For LONG signals: we expect price to go UP (revert from oversold).
    For SHORT signals: we expect price to go DOWN (revert from overbought).
    
    Uses bar-by-bar simulation with TP/SL based on ATR.
    Also computes "reversion rate" — how often price moves at least X pips
    toward the mean within max_bars.
    """
    results = {"signal": signal_name}
    
    for direction, mask in [("LONG", long_mask), ("SHORT", short_mask)]:
        entries = df[mask].copy()
        n_trades = len(entries)
        results[f"{direction}_n"] = n_trades
        
        if n_trades < 50:
            results[f"{direction}_wr"] = np.nan
            results[f"{direction}_avg_pnl_pips"] = np.nan
            results[f"{direction}_sharpe"] = np.nan
            results[f"{direction}_pf"] = np.nan
            continue
        
        # TP/SL in price terms
        tp_dist = entries["atr"] * tp_atr
        sl_dist = entries["atr"] * sl_atr
        
        pnls = []
        for idx in entries.index:
            pos = df.index.get_loc(idx)
            entry_price = df.iloc[pos]["close"]
            
            if direction == "LONG":
                tp_price = entry_price + tp_dist.loc[idx]
                sl_price = entry_price - sl_dist.loc[idx]
            else:
                tp_price = entry_price - tp_dist.loc[idx]
                sl_price = entry_price + sl_dist.loc[idx]
            
            # Simulate bar-by-bar
            pnl = 0
            for j in range(1, min(max_bars + 1, len(df) - pos)):
                bar = df.iloc[pos + j]
                if direction == "LONG":
                    # Check SL first (conservative)
                    if bar["low"] <= sl_price:
                        pnl = -(sl_dist.loc[idx]) - SPREAD
                        break
                    if bar["high"] >= tp_price:
                        pnl = tp_dist.loc[idx] - SPREAD
                        break
                else:
                    if bar["high"] >= sl_price:
                        pnl = -(sl_dist.loc[idx]) - SPREAD
                        break
                    if bar["low"] <= tp_price:
                        pnl = tp_dist.loc[idx] - SPREAD
                        break
            else:
                # Timeout — exit at close of last bar
                if direction == "LONG":
                    pnl = (df.iloc[min(pos + max_bars, len(df) - 1)]["close"] - entry_price) - SPREAD
                else:
                    pnl = (entry_price - df.iloc[min(pos + max_bars, len(df) - 1)]["close"]) - SPREAD
            
            pnls.append(pnl)
        
        pnls = np.array(pnls)
        pnl_pips = pnls / PIP
        
        wins = (pnls > 0).sum()
        losses = (pnls <= 0).sum()
        
        results[f"{direction}_wr"] = wins / n_trades * 100
        results[f"{direction}_avg_pnl_pips"] = pnl_pips.mean()
        results[f"{direction}_total_pips"] = pnl_pips.sum()
        results[f"{direction}_sharpe"] = (pnl_pips.mean() / pnl_pips.std() * np.sqrt(252 * 4)) if pnl_pips.std() > 0 else 0
        
        gross_profit = pnls[pnls > 0].sum() if (pnls > 0).any() else 0
        gross_loss = abs(pnls[pnls <= 0].sum()) if (pnls <= 0).any() else 1
        results[f"{direction}_pf"] = gross_profit / gross_loss if gross_loss > 0 else 0
    
    return results


def evaluate_reversion_rate(df: pd.DataFrame, signal_name: str,
                            long_mask: pd.Series, short_mask: pd.Series):
    """
    Pure reversion rate test: after signal fires, how often does price
    move at least X pips toward the mean within N bars?
    No TP/SL, just checking if reversion happens.
    """
    results = {"signal": signal_name + " (reversion rate)"}
    
    for direction, mask in [("LONG", long_mask), ("SHORT", short_mask)]:
        entries = df[mask]
        n = len(entries)
        if n < 50:
            continue
        
        for pip_target in [3, 5, 10]:
            target = pip_target * PIP
            for bar_window in [3, 6, 12]:
                col = f"fwd_high_{bar_window}" if direction == "LONG" else f"fwd_low_{bar_window}"
                if direction == "LONG":
                    hit = (entries[col] >= target).mean() * 100
                else:
                    hit = (entries[col] <= -target).mean() * 100
                results[f"{direction}_{pip_target}pip_{bar_window}bar"] = hit
    
    return results


# ─────────────────────────────────────────────────
# Signal Definitions
# ─────────────────────────────────────────────────

def test_bollinger_reversion(df):
    """Price touches outer BB → expect reversion to mean."""
    long_mask = df["bb_pct"] < 0.05   # Price near/below lower band
    short_mask = df["bb_pct"] > 0.95  # Price near/above upper band
    return long_mask, short_mask

def test_rsi_reversion(df, oversold=30, overbought=70):
    """RSI extreme → expect reversion."""
    long_mask = df["rsi"] < oversold
    short_mask = df["rsi"] > overbought
    return long_mask, short_mask

def test_zscore_reversion(df, threshold=2.0):
    """Z-score extreme → expect reversion."""
    long_mask = df["zscore"] < -threshold
    short_mask = df["zscore"] > threshold
    return long_mask, short_mask

def test_range_exhaustion(df, low_pct=0.05, high_pct=0.95):
    """Price near rolling range extremes → expect reversion."""
    long_mask = df["range_pct"] < low_pct
    short_mask = df["range_pct"] > high_pct
    return long_mask, short_mask

def test_micro_bollinger(df):
    """Microstructure-enhanced BB: strong imbalance + BB extreme."""
    # Buy when price at lower band AND selling exhausted (vol_imbalance very negative = heavy selling)
    long_mask = (df["bb_pct"] < 0.1) & (df["vol_imbalance"] < df["vol_imbalance"].rolling(100).quantile(0.1))
    short_mask = (df["bb_pct"] > 0.9) & (df["vol_imbalance"] > df["vol_imbalance"].rolling(100).quantile(0.9))
    return long_mask, short_mask

def test_session_reversion(df):
    """Asian session range extremes → revert during London."""
    # Price at bottom of Asian range, London about to open
    long_mask = (df["range_pct"] < 0.1) & (df["hour"].between(6, 8))
    short_mask = (df["range_pct"] > 0.9) & (df["hour"].between(6, 8))
    return long_mask, short_mask

def test_spread_widening_fade(df):
    """When spread widens significantly (volatility event), fade the move."""
    spread_z = (df["avg_spread"] - df["avg_spread"].rolling(50).mean()) / df["avg_spread"].rolling(50).std()
    # Spread wide + price dropped = buy the dip
    long_mask = (spread_z > 2) & (df["zscore"] < -1)
    short_mask = (spread_z > 2) & (df["zscore"] > 1)
    return long_mask, short_mask

def test_combined_reversion(df):
    """Multiple reversion signals agree (strongest filter)."""
    long_mask = (df["bb_pct"] < 0.15) & (df["rsi"] < 35) & (df["zscore"] < -1.5)
    short_mask = (df["bb_pct"] > 0.85) & (df["rsi"] > 65) & (df["zscore"] > 1.5)
    return long_mask, short_mask


# ─────────────────────────────────────────────────
# Market-Making Simulation
# ─────────────────────────────────────────────────

def simulate_market_making(df: pd.DataFrame, half_spread_pips: float = 2.0,
                           max_inventory: int = 3, inventory_skew: float = 0.3,
                           session_filter: str = "all"):
    """
    Simple market-making simulation.
    
    Each bar we place a limit buy (bid) and limit sell (ask) around mid.
    - half_spread_pips: distance from mid to each quote
    - max_inventory: max position (long or short)
    - inventory_skew: widen one side when inventory builds up
    - session_filter: 'all', 'london', 'asian', 'ny'
    
    We check if the bar's range would have filled either quote.
    """
    half_spread = half_spread_pips * PIP
    
    inventory = 0  # positive = long, negative = short
    pnl_total = 0
    trades = []
    fills = 0
    
    mask = pd.Series(True, index=df.index)
    if session_filter == "london":
        mask = df["is_london"]
    elif session_filter == "asian":
        mask = df["is_asian"]
    elif session_filter == "ny":
        mask = df["is_ny"]
    
    active_df = df[mask]
    
    for i in range(1, len(active_df)):
        bar = active_df.iloc[i]
        prev_close = active_df.iloc[i - 1]["close"]
        
        # Adjust quotes based on inventory
        skew = inventory * inventory_skew * PIP
        bid = prev_close - half_spread - skew  # pull bid down when long
        ask = prev_close + half_spread - skew  # pull ask down when long
        
        bid_filled = bar["low"] <= bid and inventory < max_inventory
        ask_filled = bar["high"] >= ask and inventory > -max_inventory
        
        if bid_filled and ask_filled:
            # Both filled — round trip, profit = spread
            pnl = (ask - bid) - SPREAD
            pnl_total += pnl
            trades.append(pnl / PIP)
            fills += 2
        elif bid_filled:
            inventory += 1
            fills += 1
            # Mark-to-market at bar close
            unrealized = (bar["close"] - bid) / PIP
        elif ask_filled:
            inventory -= 1
            fills += 1
            unrealized = (ask - bar["close"]) / PIP
        
        # Flatten stale inventory at end of session (simplified: every 100 bars)
        if i % 100 == 0 and inventory != 0:
            # Close at market
            if inventory > 0:
                pnl = (bar["close"] - prev_close) * inventory - SPREAD * abs(inventory)
            else:
                pnl = (prev_close - bar["close"]) * abs(inventory) - SPREAD * abs(inventory)
            pnl_total += pnl
            trades.append(pnl / PIP)
            inventory = 0
    
    trades = np.array(trades) if trades else np.array([0])
    
    return {
        "session": session_filter,
        "half_spread_pips": half_spread_pips,
        "n_trades": len(trades),
        "total_fills": fills,
        "total_pnl_pips": trades.sum(),
        "avg_pnl_pips": trades.mean(),
        "win_rate": (trades > 0).mean() * 100 if len(trades) > 0 else 0,
        "sharpe": trades.mean() / trades.std() * np.sqrt(252) if trades.std() > 0 else 0,
        "max_drawdown_pips": np.minimum.accumulate(np.cumsum(trades)).min() if len(trades) > 1 else 0,
    }


# ─────────────────────────────────────────────────
# Random Baseline
# ─────────────────────────────────────────────────

def random_baseline(df: pd.DataFrame, n_signals: int = 1000, n_trials: int = 5,
                    tp_atr: float = 1.0, sl_atr: float = 1.5, max_bars: int = 12):
    """Generate random entry signals and measure expected WR/PnL."""
    all_wrs = []
    all_pnls = []
    
    for _ in range(n_trials):
        idx = np.random.choice(len(df) - max_bars - 1, size=n_signals, replace=False)
        wins = 0
        pnls = []
        
        for i in idx:
            entry = df.iloc[i]["close"]
            atr = df.iloc[i]["atr"]
            direction = np.random.choice(["LONG", "SHORT"])
            
            tp = atr * tp_atr
            sl = atr * sl_atr
            
            pnl = 0
            for j in range(1, max_bars + 1):
                if i + j >= len(df):
                    break
                bar = df.iloc[i + j]
                if direction == "LONG":
                    if bar["low"] <= entry - sl:
                        pnl = -sl - SPREAD
                        break
                    if bar["high"] >= entry + tp:
                        pnl = tp - SPREAD
                        break
                else:
                    if bar["high"] >= entry + sl:
                        pnl = -sl - SPREAD
                        break
                    if bar["low"] <= entry - tp:
                        pnl = tp - SPREAD
                        break
            else:
                if direction == "LONG":
                    pnl = (df.iloc[min(i + max_bars, len(df) - 1)]["close"] - entry) - SPREAD
                else:
                    pnl = (entry - df.iloc[min(i + max_bars, len(df) - 1)]["close"]) - SPREAD
            
            if pnl > 0:
                wins += 1
            pnls.append(pnl / PIP)
        
        all_wrs.append(wins / n_signals * 100)
        all_pnls.append(np.mean(pnls))
    
    return {
        "baseline_wr": np.mean(all_wrs),
        "baseline_avg_pnl_pips": np.mean(all_pnls),
        "baseline_wr_std": np.std(all_wrs),
    }


# ─────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────

def main():
    np.random.seed(42)
    
    print("=" * 80)
    print("MEAN-REVERSION & MARKET-MAKING EDGE TEST — EURUSD")
    print("=" * 80)
    
    # Test multiple timeframes
    for tf in ["15min", "1h", "4h"]:
        print(f"\n{'=' * 80}")
        print(f"TIMEFRAME: {tf}")
        print(f"{'=' * 80}")
        
        df = load_and_resample(tf)
        print(f"Bars: {len(df):,} | Date range: {df.index[0].date()} to {df.index[-1].date()}")
        
        # Random baseline
        print(f"\n--- Random Baseline (TP=1.0×ATR, SL=1.5×ATR, {tf}) ---")
        baseline = random_baseline(df, n_signals=min(2000, len(df) // 10))
        print(f"  Random WR: {baseline['baseline_wr']:.1f}% ± {baseline['baseline_wr_std']:.1f}%")
        print(f"  Random avg PnL: {baseline['baseline_avg_pnl_pips']:.2f} pips")
        
        # ── Mean-Reversion Signals ──
        print(f"\n--- Mean-Reversion Signals ({tf}) ---")
        
        signals = [
            ("BB Reversion (5%/95%)", test_bollinger_reversion),
            ("RSI Reversion (30/70)", lambda d: test_rsi_reversion(d, 30, 70)),
            ("RSI Reversion (25/75)", lambda d: test_rsi_reversion(d, 25, 75)),
            ("RSI Reversion (20/80)", lambda d: test_rsi_reversion(d, 20, 80)),
            ("Z-score > 2.0", lambda d: test_zscore_reversion(d, 2.0)),
            ("Z-score > 2.5", lambda d: test_zscore_reversion(d, 2.5)),
            ("Range Exhaustion (5%/95%)", test_range_exhaustion),
            ("Micro + BB", test_micro_bollinger),
            ("Session Reversion (Asian→London)", test_session_reversion),
            ("Spread Widening Fade", test_spread_widening_fade),
            ("Combined (BB+RSI+Z)", test_combined_reversion),
        ]
        
        print(f"\n  {'Signal':<40} {'Dir':>5} {'N':>6} {'WR%':>7} {'AvgPnL':>8} {'TotPips':>9} {'PF':>6} {'Sharpe':>7}")
        print(f"  {'-' * 40} {'-' * 5} {'-' * 6} {'-' * 7} {'-' * 8} {'-' * 9} {'-' * 6} {'-' * 7}")
        
        for name, signal_fn in signals:
            long_mask, short_mask = signal_fn(df)
            # Use tighter TP for mean reversion (target = return to mean, not trend continuation)
            result = evaluate_signal(df, name, long_mask, short_mask,
                                    tp_atr=1.0, sl_atr=1.5, max_bars=12)
            
            for direction in ["LONG", "SHORT"]:
                n = result.get(f"{direction}_n", 0)
                wr = result.get(f"{direction}_wr", np.nan)
                avg = result.get(f"{direction}_avg_pnl_pips", np.nan)
                tot = result.get(f"{direction}_total_pips", np.nan)
                pf = result.get(f"{direction}_pf", np.nan)
                sh = result.get(f"{direction}_sharpe", np.nan)
                
                if not np.isnan(wr):
                    edge = wr - baseline["baseline_wr"]
                    marker = " ★" if edge > 3 and avg > 0 else ""
                    print(f"  {name:<40} {direction:>5} {n:>6} {wr:>6.1f}% {avg:>7.2f}p {tot:>8.0f}p {pf:>6.2f} {sh:>6.2f}{marker}")
        
        # ── Reversion Rate (no TP/SL, just does price move back?) ──
        print(f"\n--- Reversion Rate Test ({tf}) ---")
        print(f"  Signal fires → does price move X pips in expected direction within N bars?")
        
        for name, signal_fn in [("BB Reversion", test_bollinger_reversion),
                                  ("Z-score > 2.0", lambda d: test_zscore_reversion(d, 2.0)),
                                  ("Combined", test_combined_reversion)]:
            long_mask, short_mask = signal_fn(df)
            rev = evaluate_reversion_rate(df, name, long_mask, short_mask)
            print(f"\n  {rev['signal']}:")
            for key, val in rev.items():
                if key != "signal" and isinstance(val, (int, float)):
                    print(f"    {key}: {val:.1f}%")
        
        # ── Yearly Breakdown for best signal ──
        if tf == "15min":
            print(f"\n--- Yearly Breakdown: Combined (BB+RSI+Z) at 15min ---")
            long_mask, short_mask = test_combined_reversion(df)
            df["year"] = df.index.year
            years = sorted(df["year"].unique())
            
            print(f"  {'Year':<8} {'LONG_N':>7} {'LONG_WR':>8} {'SHORT_N':>8} {'SHORT_WR':>9}")
            for yr in years:
                yr_mask = df["year"] == yr
                yr_long = long_mask & yr_mask
                yr_short = short_mask & yr_mask
                
                n_long = yr_long.sum()
                n_short = yr_short.sum()
                
                if n_long > 10:
                    result = evaluate_signal(df, f"Combined {yr}", yr_long, yr_short,
                                            tp_atr=1.0, sl_atr=1.5, max_bars=12)
                    wr_l = result.get("LONG_wr", np.nan)
                    wr_s = result.get("SHORT_wr", np.nan)
                    print(f"  {yr:<8} {n_long:>7} {wr_l:>7.1f}% {n_short:>8} {wr_s:>8.1f}%")
                else:
                    print(f"  {yr:<8} {n_long:>7}  (too few)  {n_short:>8}  (too few)")
    
    # ── Market-Making Simulation ──
    print(f"\n{'=' * 80}")
    print("MARKET-MAKING SIMULATION")
    print(f"{'=' * 80}")
    
    df_15m = load_and_resample("15min")
    
    print(f"\n  {'Session':<10} {'HalfSprd':>9} {'Trades':>7} {'TotPnL':>9} {'AvgPnL':>8} {'WR%':>6} {'Sharpe':>7} {'MaxDD':>8}")
    print(f"  {'-' * 10} {'-' * 9} {'-' * 7} {'-' * 9} {'-' * 8} {'-' * 6} {'-' * 7} {'-' * 8}")
    
    for session in ["all", "london", "asian", "ny"]:
        for hs in [1.5, 2.0, 3.0, 5.0]:
            result = simulate_market_making(df_15m, half_spread_pips=hs,
                                            session_filter=session)
            print(f"  {result['session']:<10} {result['half_spread_pips']:>8.1f}p {result['n_trades']:>7} "
                  f"{result['total_pnl_pips']:>8.0f}p {result['avg_pnl_pips']:>7.2f}p "
                  f"{result['win_rate']:>5.1f}% {result['sharpe']:>6.2f} {result['max_drawdown_pips']:>7.0f}p")
    
    # ── Mean-Reversion with tighter TP/SL ratios ──
    print(f"\n{'=' * 80}")
    print("TP/SL RATIO SWEEP for Best Signals (15min)")
    print(f"{'=' * 80}")
    
    df_15m = load_and_resample("15min")
    
    for tp_atr, sl_atr in [(0.5, 1.0), (0.75, 1.0), (1.0, 1.0), (1.0, 1.5), (1.5, 1.0), (0.5, 0.5)]:
        print(f"\n  TP={tp_atr}×ATR, SL={sl_atr}×ATR — break-even WR = {sl_atr/(tp_atr+sl_atr)*100:.1f}%")
        baseline = random_baseline(df_15m, n_signals=1000, tp_atr=tp_atr, sl_atr=sl_atr, max_bars=12)
        print(f"  Random baseline: WR={baseline['baseline_wr']:.1f}%, AvgPnL={baseline['baseline_avg_pnl_pips']:.2f}p")
        
        for name, signal_fn in [("BB Reversion", test_bollinger_reversion),
                                  ("Z-score > 2.0", lambda d: test_zscore_reversion(d, 2.0)),
                                  ("Combined", test_combined_reversion)]:
            long_mask, short_mask = signal_fn(df_15m)
            result = evaluate_signal(df_15m, name, long_mask, short_mask,
                                    tp_atr=tp_atr, sl_atr=sl_atr, max_bars=12)
            for d in ["LONG", "SHORT"]:
                wr = result.get(f"{d}_wr", np.nan)
                avg = result.get(f"{d}_avg_pnl_pips", np.nan)
                pf = result.get(f"{d}_pf", np.nan)
                n = result.get(f"{d}_n", 0)
                if not np.isnan(wr):
                    edge = wr - baseline["baseline_wr"]
                    print(f"    {name:<30} {d:>5} n={n:>5} WR={wr:.1f}% (edge={edge:+.1f}pp) AvgPnL={avg:.2f}p PF={pf:.2f}")
    
    print(f"\n{'=' * 80}")
    print("TEST COMPLETE")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
