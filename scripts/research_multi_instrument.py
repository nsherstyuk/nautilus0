"""
research_multi_instrument.py -- Multi-instrument evaluation of V6 ORB and V8 Confirmed Rebreak.

Research question: Do V6 and V8 strategies produce positive returns on FX pairs
beyond XAUUSD/EURUSD, and what parameter adjustments are needed?

Governed by: docs/standards/layer1-research-standards.md

Data: 1-minute bars from data/1m_csv/*.csv (Dukascopy tick data, 2018-2026).

Approach:
  Phase 1: Data audit (date range, bar count, median spread, median tick_count)
  Phase 2: V6 ORB baseline on hourly bars (no velocity/gap filter, RR=2.0)
  Phase 3: V8 Confirmed Rebreak baseline on 1m bars (default params, adjusted spread)
  Phase 4: Parameter sensitivity for pairs that show promise

Usage:
  python scripts/research_multi_instrument.py                    # full run
  python scripts/research_multi_instrument.py --phase 1          # data audit only
  python scripts/research_multi_instrument.py --phase 2          # V6 only
  python scripts/research_multi_instrument.py --phase 3          # V8 only
  python scripts/research_multi_instrument.py --pairs GBPUSD USDJPY  # subset
"""
import argparse
import gc
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict

import numpy as np
import pandas as pd

# Add project root to path for V8 imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "1m_csv"

ALL_PAIRS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF"]

def derive_instrument_params(df_1m: pd.DataFrame) -> dict:
    """Derive spread/slippage from actual data.
    Returns dict with spread_per_side, slippage, median_price."""
    med_spread = df_1m["avg_spread"].median()
    med_price = df_1m["close"].median()
    return dict(
        spread_per_side=med_spread / 2,
        slippage=med_spread,  # conservative: 1x avg_spread for stop slippage
        median_price=med_price,
    )


# ============================================================================
# Shared utilities
# ============================================================================

def compute_stats(pnls: list, label: str = "") -> dict:
    """Compute standard strategy metrics from a list of per-trade PnLs."""
    if not pnls:
        return dict(label=label, n=0, sharpe=0, pf=0, wr=0, mean=0, total=0, max_dd=0)
    arr = np.array(pnls)
    n = len(arr)
    mean = arr.mean()
    std = arr.std()
    sharpe = float(mean / std * np.sqrt(252)) if std > 0 else 0.0
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    gp = wins.sum() if len(wins) else 0
    gl = abs(losses.sum()) if len(losses) else 0
    pf = float(gp / gl) if gl > 0 else float("inf")
    wr = float(len(wins) / n * 100) if n > 0 else 0
    eq = arr.cumsum()
    dd = float((eq - np.maximum.accumulate(eq)).min())
    return dict(
        label=label, n=n, sharpe=round(sharpe, 2), pf=round(pf, 2),
        wr=round(wr, 1), mean=round(mean, 6), total=round(arr.sum(), 2),
        max_dd=round(dd, 4),
    )


def load_1m_csv(symbol: str) -> Optional[pd.DataFrame]:
    """Load 1-minute CSV data for a symbol."""
    path = DATA_DIR / f"{symbol.lower()}_1m_tick.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["timestamp"])
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def resample_to_1h(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-minute bars to 1-hour OHLCV with spread."""
    df = df_1m.set_index("timestamp").sort_index()
    ohlcv = pd.DataFrame({
        "open": df["open"].resample("1h").first(),
        "high": df["high"].resample("1h").max(),
        "low": df["low"].resample("1h").min(),
        "close": df["close"].resample("1h").last(),
        "tick_count": df["tick_count"].resample("1h").sum(),
        "avg_spread": df["avg_spread"].resample("1h").mean(),
    }).dropna(subset=["open"])
    return ohlcv


# ============================================================================
# Phase 1: Data Audit
# ============================================================================

def phase1_data_audit(pairs: List[str]):
    print(f"\n{'='*90}")
    print("PHASE 1: DATA AUDIT")
    print(f"{'='*90}")
    header = (f"{'Symbol':<10} {'Bars':>12} {'Start':>12} {'End':>12} "
              f"{'Med Spread':>12} {'Med Ticks':>10} {'Price':>10}")
    print(header)
    print("-" * 90)

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            print(f"{symbol:<10} {'NO DATA':>12}")
            continue
        n = len(df)
        start = df["timestamp"].iloc[0].strftime("%Y-%m-%d")
        end = df["timestamp"].iloc[-1].strftime("%Y-%m-%d")
        med_spread = df["avg_spread"].median()
        med_ticks = df["tick_count"].median()
        med_price = df["close"].median()
        print(f"{symbol:<10} {n:>12,} {start:>12} {end:>12} "
              f"{med_spread:>12.6f} {med_ticks:>10.0f} {med_price:>10.4f}")
        del df
        gc.collect()

    print(f"{'='*90}\n")


# ============================================================================
# Phase 2: V6 ORB Baseline (Hourly bars, no velocity/gap filter)
# ============================================================================

@dataclass
class V6Config:
    """V6 ORB strategy parameters for multi-instrument research."""
    range_start: int = 0
    range_end: int = 6
    trade_start: int = 8
    trade_end: int = 16
    rr_ratio: float = 2.0
    min_range_pct: float = 0.01
    max_range_pct: float = 2.0
    be_minutes: Optional[int] = None    # breakeven after N minutes (None=disabled)
    be_offset: float = 0.0              # BE offset in price units
    skip_weekdays: list = field(default_factory=list)
    time_exit_minutes: int = 0          # close at market after N min (0=disabled)


@dataclass
class V6Trade:
    date: object
    direction: str
    entry_price: float
    exit_price: float
    result: str           # SL, TP, BE, EOD
    pnl_price: float      # P&L in price units
    range_size: float
    hold_bars: int
    entry_tick_count: int = 0


def v6_backtest_pair(df_1m: pd.DataFrame, cfg: V6Config) -> List[V6Trade]:
    """Run V6 ORB backtest on 1-minute bars.

    Fill logic matches V5 backtest_1m.py:
      - Entry: stop at range boundary, fill at level+hs or open+hs (gap)
      - Exit SL/TP: level +/- hs (half spread from that bar)
      - EOD: close +/- hs
      - SL checked before TP (SL precedence on same bar)
      - SL/TP skip entry bar (monitor from next bar)
    """
    df = df_1m.copy()
    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour
    df["weekday"] = df["timestamp"].dt.weekday

    trades = []

    for day, day_df in df.groupby("date"):
        wd = day_df["weekday"].iloc[0]
        if wd >= 5:
            continue
        if cfg.skip_weekdays and wd in cfg.skip_weekdays:
            continue

        # Asian range
        asian = day_df[(day_df["hour"] >= cfg.range_start) &
                       (day_df["hour"] < cfg.range_end)]
        if len(asian) < 10:
            continue

        rh = asian["high"].max()
        rl = asian["low"].min()
        rs = rh - rl
        if rs <= 0:
            continue

        mid = (rh + rl) / 2
        rpct = rs / mid * 100
        if rpct < cfg.min_range_pct or rpct > cfg.max_range_pct:
            continue

        tp_long = rh + cfg.rr_ratio * rs
        tp_short = rl - cfg.rr_ratio * rs

        # Trade window bars
        window = day_df[(day_df["hour"] >= cfg.trade_start) &
                        (day_df["hour"] < cfg.trade_end)]
        if len(window) < 5:
            continue

        bars = list(window.itertuples(index=False))
        n = len(bars)

        # Find entry (stop order at range boundary)
        direction = None
        entry_px = None
        entry_i = None
        entry_ts = None

        for i, bar in enumerate(bars):
            hs = bar.avg_spread / 2

            if bar.high >= rh:
                direction = "LONG"
                if bar.open >= rh:
                    entry_px = bar.open + hs      # gap fill
                else:
                    entry_px = rh + hs             # level fill
                entry_i = i
                entry_ts = bar.timestamp
                break
            elif bar.low <= rl:
                direction = "SHORT"
                if bar.open <= rl:
                    entry_px = bar.open - hs
                else:
                    entry_px = rl - hs
                entry_i = i
                entry_ts = bar.timestamp
                break

        if direction is None:
            continue

        sl = rl if direction == "LONG" else rh
        tp = tp_long if direction == "LONG" else tp_short

        # Monitor trade (start from bar AFTER entry)
        current_sl = sl
        be_triggered = False
        exit_px = None
        result = "EOD"
        hold_bars = n - entry_i - 1

        for j in range(entry_i + 1, n):
            bar = bars[j]
            hs = bar.avg_spread / 2
            mins_held = j - entry_i  # 1-minute bars, so j-entry_i = minutes

            # Time exit
            if cfg.time_exit_minutes > 0 and mins_held >= cfg.time_exit_minutes:
                if direction == "LONG":
                    exit_px = bar.open - hs
                else:
                    exit_px = bar.open + hs
                result = "TIME"
                hold_bars = mins_held
                break

            # Breakeven
            if (not be_triggered and cfg.be_minutes is not None
                    and mins_held >= cfg.be_minutes):
                be_triggered = True
                if direction == "LONG":
                    current_sl = entry_px + cfg.be_offset
                else:
                    current_sl = entry_px - cfg.be_offset

            # SL (checked first — precedence over TP)
            if direction == "LONG":
                if bar.low <= current_sl:
                    exit_px = current_sl - hs
                    result = "BE" if be_triggered else "SL"
                    hold_bars = mins_held
                    break
                if bar.high >= tp:
                    exit_px = tp - hs
                    result = "TP"
                    hold_bars = mins_held
                    break
            else:
                if bar.high >= current_sl:
                    exit_px = current_sl + hs
                    result = "BE" if be_triggered else "SL"
                    hold_bars = mins_held
                    break
                if bar.low <= tp:
                    exit_px = tp + hs
                    result = "TP"
                    hold_bars = mins_held
                    break

        # EOD close
        if exit_px is None:
            last_bar = bars[-1]
            hs = last_bar.avg_spread / 2
            if direction == "LONG":
                exit_px = last_bar.close - hs
            else:
                exit_px = last_bar.close + hs

        raw_pnl = (exit_px - entry_px) if direction == "LONG" else (entry_px - exit_px)

        entry_tc = int(bars[entry_i].tick_count) if hasattr(bars[entry_i], 'tick_count') else 0
        trades.append(V6Trade(
            date=day, direction=direction,
            entry_price=entry_px, exit_price=exit_px,
            result=result, pnl_price=raw_pnl,
            range_size=rs, hold_bars=hold_bars,
            entry_tick_count=entry_tc,
        ))

    return trades


def phase2_v6_orb(pairs: List[str], start_date: str = "2018-01-01"):
    """Run V6 ORB baseline across all instruments."""
    print(f"\n{'='*90}")
    print("PHASE 2: V6 ORB BASELINE (1-minute bars, V5-parity fills)")
    print(f"  Config: Asian 00-06 UTC, Trade 08-16 UTC, RR=2.0, no BE, no velocity")
    print(f"  Spread: per-bar avg_spread/2 (half-spread) from data")
    print(f"  PnL: reported as basis points (bps) of median price for cross-pair comparison")
    print(f"  Start: {start_date}")
    print(f"{'='*90}")

    cfg = V6Config(rr_ratio=2.0)

    header = (f"{'Symbol':<10} {'Trades':>6} {'WR%':>6} {'Sharpe':>7} "
              f"{'PF':>6} {'AvgBps':>8} {'TotBps':>10} "
              f"{'L/S':>7} {'SL':>4} {'TP':>4} {'EOD':>4}")
    print(header)
    print("-" * 90)

    all_results = {}

    for symbol in pairs:
        t0 = time.time()
        df = load_1m_csv(symbol)
        if df is None:
            print(f"{symbol:<10} NO DATA")
            continue

        df = df[df["timestamp"] >= start_date].reset_index(drop=True)
        params = derive_instrument_params(df)

        trades = v6_backtest_pair(df, cfg)
        del df
        gc.collect()

        if not trades:
            print(f"{symbol:<10} {'0 trades':>6}")
            continue

        # Convert PnL to basis points of median price for cross-pair comparison
        med_px = params["median_price"]
        pnls_bps = [t.pnl_price / med_px * 10000 for t in trades]
        s = compute_stats(pnls_bps, symbol)

        longs = sum(1 for t in trades if t.direction == "LONG")
        shorts = sum(1 for t in trades if t.direction == "SHORT")
        n_sl = sum(1 for t in trades if t.result == "SL")
        n_tp = sum(1 for t in trades if t.result == "TP")
        n_eod = sum(1 for t in trades if t.result == "EOD")

        elapsed = time.time() - t0
        ls = f"{longs}/{shorts}"
        avg_bps = s['total'] / s['n'] if s['n'] > 0 else 0
        print(f"{symbol:<10} {s['n']:>6} {s['wr']:>5.1f}% {s['sharpe']:>+7.2f} "
              f"{s['pf']:>6.2f} {avg_bps:>+8.2f} {s['total']:>+10.1f} "
              f"{ls:>7} {n_sl:>4} {n_tp:>4} {n_eod:>4}")

        all_results[symbol] = {"trades": trades, "stats": s, "med_px": med_px}

    # Yearly breakdown for each pair
    print(f"\n{'='*90}")
    print("V6 ORB: YEARLY BREAKDOWN (PnL in bps of median price)")
    print(f"{'='*90}")

    years = sorted(set(str(t.date.year) if hasattr(t.date, 'year') else str(t.date)[:4]
                       for res in all_results.values() for t in res["trades"]))

    header = f"{'Symbol':<10}" + "".join(f"{y:>10}" for y in years) + f"{'Total':>10}"
    print(header)
    print("-" * (10 + 10 * (len(years) + 1)))

    for symbol, res in all_results.items():
        med_px = res["med_px"]
        yearly = {}
        for t in res["trades"]:
            yr = str(t.date.year) if hasattr(t.date, "year") else str(t.date)[:4]
            yearly[yr] = yearly.get(yr, 0) + t.pnl_price / med_px * 10000
        row = f"{symbol:<10}"
        for y in years:
            v = yearly.get(y, 0)
            row += f"{v:>+10.0f}"
        row += f"{sum(yearly.values()):>+10.0f}"
        print(row)

    print(f"{'='*90}")
    return all_results


# ============================================================================
# Phase 3: V8 Confirmed Rebreak Baseline
# ============================================================================

def phase3_v8_rebreak(pairs: List[str], start_date: str = "2018-01-01"):
    """Run V8 Confirmed Rebreak across all instruments."""
    import contextlib
    import io
    import logging

    from v8_confirmed_rebreak.config.strategy_config import StrategyConfig
    from v8_confirmed_rebreak.backtest.runner import BacktestRunner

    print(f"\n{'='*90}")
    print("PHASE 3: V8 CONFIRMED REBREAK BASELINE (1m bars)")
    print(f"  Config: pw=60 confirm=3 hold=60 sl=10xATR min_ticks=50")
    print(f"  Spread: derived from each pair's data median avg_spread")
    print(f"  PnL: reported as basis points (bps) of median price")
    print(f"  Start: {start_date}")
    print(f"{'='*90}")

    header = (f"{'Symbol':<10} {'Trades':>6} {'WR%':>6} {'Sharpe':>7} "
              f"{'PF':>6} {'AvgBps':>8} {'TotBps':>10} "
              f"{'L/S':>7} {'SL':>4} {'TIME':>5}")
    print(header)
    print("-" * 90)

    all_results = {}
    logger = logging.getLogger("v8_research")
    logger.setLevel(logging.CRITICAL)

    for symbol in pairs:
        data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
        if not Path(data_path).exists():
            print(f"{symbol:<10} NO DATA")
            continue

        t0 = time.time()
        # Derive spread from data
        df_sample = pd.read_csv(data_path, usecols=["avg_spread", "close"], nrows=500_000)
        med_spread = df_sample["avg_spread"].median()
        med_price = df_sample["close"].median()
        spread = float(med_spread)
        del df_sample
        gc.collect()

        config = StrategyConfig(
            instrument=symbol,
            pivot_window=60,
            confirm_bars=3,
            imbalance_window=3,
            divergence_threshold=0.50,
            max_pullback_bars=60,
            min_pullback_bars=3,
            sl_atr_multiple=10.0,
            tp_atr_multiple=99.0,
            max_hold_bars=60,
            atr_period=60,
            min_bar_ticks=50,
            spread_cost=spread,
        )

        runner = BacktestRunner(
            data_path=data_path,
            config=config,
            start_date=start_date,
            logger=logger,
        )

        f_buf = io.StringIO()
        with contextlib.redirect_stdout(f_buf):
            trades = runner.run()

        elapsed = time.time() - t0

        if not trades:
            print(f"{symbol:<10} {'0 trades':>6}  ({elapsed:.0f}s)")
            continue

        # Convert PnL to bps of median price for cross-pair comparison
        pnls_bps = [t.pnl / med_price * 10000 for t in trades]
        s = compute_stats(pnls_bps, symbol)

        longs = sum(1 for t in trades if t.direction == "long")
        shorts = sum(1 for t in trades if t.direction == "short")
        n_sl = sum(1 for t in trades if t.exit_reason == "CATASTROPHE_SL")
        n_time = sum(1 for t in trades if t.exit_reason == "TIME_STOP")

        ls = f"{longs}/{shorts}"
        avg_bps = s['total'] / s['n'] if s['n'] > 0 else 0

        print(f"{symbol:<10} {s['n']:>6} {s['wr']:>5.1f}% {s['sharpe']:>+7.2f} "
              f"{s['pf']:>6.2f} {avg_bps:>+8.2f} {s['total']:>+10.1f} "
              f"{ls:>7} {n_sl:>4} {n_time:>5}  ({elapsed:.0f}s)")

        all_results[symbol] = {"trades": trades, "stats": s, "med_px": med_price}

    # Yearly breakdown
    if all_results:
        print(f"\n{'='*90}")
        print("V8 REBREAK: YEARLY BREAKDOWN (PnL in bps of median price)")
        print(f"{'='*90}")

        years = sorted(set(str(t.entry_time.year)
                           for res in all_results.values() for t in res["trades"]))

        header = f"{'Symbol':<10}" + "".join(f"{y:>10}" for y in years) + f"{'Total':>10}"
        print(header)
        print("-" * (10 + 10 * (len(years) + 1)))

        for symbol, res in all_results.items():
            med_px = res["med_px"]
            yearly = {}
            for t in res["trades"]:
                yr = str(t.entry_time.year)
                yearly[yr] = yearly.get(yr, 0) + t.pnl / med_px * 10000
            row = f"{symbol:<10}"
            for y in years:
                v = yearly.get(y, 0)
                row += f"{v:>+10.0f}"
            row += f"{sum(yearly.values()):>+10.0f}"
            print(row)

        print(f"{'='*90}")

    return all_results


# ============================================================================
# Phase 4: Parameter sensitivity (for pairs with promise)
# ============================================================================

def phase4_v6_param_sweep(pairs: List[str], start_date: str = "2018-01-01"):
    """Test V6 ORB with different RR ratios and breakeven settings."""
    print(f"\n{'='*90}")
    print("PHASE 4: V6 ORB PARAMETER SENSITIVITY")
    print(f"  Sharpe / N trades reported for each config")
    print(f"{'='*90}")

    rr_values = [1.5, 2.0, 2.5, 3.0]
    be_configs = [
        ("no_BE", None, 0.0),
        ("BE@2h", 120, 0.0),    # 120 minutes = 2 hours
    ]

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df = df[df["timestamp"] >= start_date].reset_index(drop=True)
        params = derive_instrument_params(df)

        print(f"\n  {symbol}")
        header = f"  {'Config':<20}" + "".join(f"{'RR='+str(rr):>12}" for rr in rr_values)
        print(header)
        print("  " + "-" * (20 + 12 * len(rr_values)))

        for be_label, be_mins, be_offset in be_configs:
            row = f"  {be_label:<20}"
            med_px = params["median_price"]
            for rr in rr_values:
                cfg = V6Config(rr_ratio=rr, be_minutes=be_mins, be_offset=be_offset)
                trades = v6_backtest_pair(df, cfg)
                if not trades:
                    row += f"{'--':>12}"
                    continue
                pnls = [t.pnl_price / med_px * 10000 for t in trades]
                s = compute_stats(pnls)
                row += f"{s['sharpe']:>+6.2f}/{s['n']:>4}t"
            print(row)

        # Test different trade windows
        print(f"\n  Trade window sensitivity (RR=2.0, no BE):")
        windows = [
            ("07-16 (early)", 7, 16),
            ("08-16 (default)", 8, 16),
            ("08-14 (short)", 8, 14),
            ("07-18 (wide)", 7, 18),
        ]
        med_px = params["median_price"]
        for wlabel, ts, te in windows:
            cfg = V6Config(rr_ratio=2.0, trade_start=ts, trade_end=te)
            trades = v6_backtest_pair(df, cfg)
            if not trades:
                print(f"  {wlabel:<20} --")
                continue
            pnls = [t.pnl_price / med_px * 10000 for t in trades]
            s = compute_stats(pnls)
            print(f"  {wlabel:<20} Sharpe={s['sharpe']:>+6.2f}  "
                  f"PF={s['pf']:>5.2f}  WR={s['wr']:>5.1f}%  "
                  f"N={s['n']:>4}  TotBps={s['total']:>+.0f}")

        del df
        gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Phase 5: V8 min_bar_ticks sensitivity (50 vs 75)
# ============================================================================

def phase5_v8_minticks_sensitivity(pairs: List[str], start_date: str = "2018-01-01"):
    """Compare V8 results with min_bar_ticks=50 vs 75 (StrategyConfig default)."""
    import contextlib
    import io
    import logging

    from v8_confirmed_rebreak.config.strategy_config import StrategyConfig
    from v8_confirmed_rebreak.backtest.runner import BacktestRunner

    print(f"\n{'='*90}")
    print("PHASE 5: V8 min_bar_ticks SENSITIVITY (50 vs 75)")
    print(f"  All other params: pw=60 confirm=3 hold=60 sl=10xATR")
    print(f"  Start: {start_date}")
    print(f"{'='*90}")

    header = (f"{'Symbol':<10} {'mt':>3} {'Trades':>6} {'WR%':>6} {'Sharpe':>7} "
              f"{'PF':>6} {'AvgBps':>8} {'TotBps':>10}")
    print(header)
    print("-" * 70)

    logger = logging.getLogger("v8_minticks")
    logger.setLevel(logging.CRITICAL)

    for symbol in pairs:
        data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
        if not Path(data_path).exists():
            print(f"{symbol:<10} NO DATA")
            continue

        df_sample = pd.read_csv(data_path, usecols=["avg_spread", "close"], nrows=500_000)
        med_spread = float(df_sample["avg_spread"].median())
        med_price = float(df_sample["close"].median())
        del df_sample
        gc.collect()

        for mt in [50, 75]:
            t0 = time.time()
            config = StrategyConfig(
                instrument=symbol,
                pivot_window=60,
                confirm_bars=3,
                imbalance_window=3,
                divergence_threshold=0.50,
                max_pullback_bars=60,
                min_pullback_bars=3,
                sl_atr_multiple=10.0,
                tp_atr_multiple=99.0,
                max_hold_bars=60,
                atr_period=60,
                min_bar_ticks=mt,
                spread_cost=med_spread,
            )
            runner = BacktestRunner(
                data_path=data_path, config=config,
                start_date=start_date, logger=logger,
            )
            f_buf = io.StringIO()
            with contextlib.redirect_stdout(f_buf):
                trades = runner.run()

            if not trades:
                print(f"{symbol:<10} {mt:>3} {'0 trades':>6}")
                continue

            pnls_bps = [t.pnl / med_price * 10000 for t in trades]
            s = compute_stats(pnls_bps, symbol)
            avg_bps = s['total'] / s['n'] if s['n'] > 0 else 0
            elapsed = time.time() - t0
            print(f"{symbol:<10} {mt:>3} {s['n']:>6} {s['wr']:>5.1f}% {s['sharpe']:>+7.2f} "
                  f"{s['pf']:>6.2f} {avg_bps:>+8.2f} {s['total']:>+10.1f}  ({elapsed:.0f}s)")

    print(f"{'='*90}")


# ============================================================================
# Phase 6: V6+BE Walk-Forward OOS Validation
# ============================================================================

def phase6_v6_be_walkforward(pairs: List[str], start_date: str = "2018-01-01"):
    """Walk-forward: train on 2018-2022, test on 2023-2026 for V6+BE."""
    print(f"\n{'='*90}")
    print("PHASE 6: V6+BE WALK-FORWARD OOS VALIDATION")
    print(f"  In-sample: 2018-01-01 to 2022-12-31")
    print(f"  Out-of-sample: 2023-01-01 to end of data")
    print(f"  Configs: RR=1.5/2.0/2.5/3.0, no_BE and BE@2h")
    print(f"{'='*90}")

    oos_start = "2023-01-01"
    rr_values = [1.5, 2.0, 2.5, 3.0]

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df = df[df["timestamp"] >= start_date].reset_index(drop=True)
        params = derive_instrument_params(df)
        med_px = params["median_price"]

        df_is = df[df["timestamp"] < oos_start].reset_index(drop=True)
        df_oos = df[df["timestamp"] >= oos_start].reset_index(drop=True)

        if len(df_is) < 1000 or len(df_oos) < 1000:
            print(f"\n  {symbol}: insufficient data for IS/OOS split")
            continue

        print(f"\n  {symbol} (IS: {len(df_is):,} bars, OOS: {len(df_oos):,} bars)")

        header = (f"  {'Config':<20} {'IS_Sh':>7} {'IS_N':>6} {'IS_WR':>6} "
                  f"{'OOS_Sh':>7} {'OOS_N':>6} {'OOS_WR':>7} {'OOS_PF':>7} {'OOS_Bps':>10}")
        print(header)
        print("  " + "-" * 85)

        for rr in rr_values:
            for be_label, be_mins, be_off in [("no_BE", None, 0.0), ("BE@2h", 120, 0.0)]:
                cfg = V6Config(rr_ratio=rr, be_minutes=be_mins, be_offset=be_off)

                trades_is = v6_backtest_pair(df_is, cfg)
                trades_oos = v6_backtest_pair(df_oos, cfg)

                pnls_is = [t.pnl_price / med_px * 10000 for t in trades_is] if trades_is else []
                pnls_oos = [t.pnl_price / med_px * 10000 for t in trades_oos] if trades_oos else []

                s_is = compute_stats(pnls_is)
                s_oos = compute_stats(pnls_oos)

                label = f"RR={rr} {be_label}"
                oos_bps = f"{s_oos['total']:>+10.0f}" if s_oos['n'] > 0 else f"{'--':>10}"
                print(f"  {label:<20} {s_is['sharpe']:>+7.2f} {s_is['n']:>6} {s_is['wr']:>5.1f}% "
                      f"{s_oos['sharpe']:>+7.2f} {s_oos['n']:>6} {s_oos['wr']:>5.1f}% "
                      f"{s_oos['pf']:>7.2f} {oos_bps}")

        del df, df_is, df_oos
        gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Phase 7: V6+BE Yearly Breakdown
# ============================================================================

def phase7_v6_be_yearly(pairs: List[str], start_date: str = "2018-01-01"):
    """Yearly PnL breakdown for V6+BE@2h at best RR per pair."""
    print(f"\n{'='*90}")
    print("PHASE 7: V6+BE@2h YEARLY BREAKDOWN")
    print(f"  Config: BE@2h (120 min), testing RR=1.5 and RR=2.0")
    print(f"{'='*90}")

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df = df[df["timestamp"] >= start_date].reset_index(drop=True)
        params = derive_instrument_params(df)
        med_px = params["median_price"]

        for rr in [1.5, 2.0]:
            cfg = V6Config(rr_ratio=rr, be_minutes=120, be_offset=0.0)
            trades = v6_backtest_pair(df, cfg)
            if not trades:
                continue

            yearly = {}
            yearly_n = {}
            yearly_wr = {}
            for t in trades:
                yr = str(t.date.year) if hasattr(t.date, "year") else str(t.date)[:4]
                bps = t.pnl_price / med_px * 10000
                yearly[yr] = yearly.get(yr, 0) + bps
                yearly_n[yr] = yearly_n.get(yr, 0) + 1
                if bps > 0:
                    yearly_wr[yr] = yearly_wr.get(yr, 0) + 1

            years = sorted(yearly.keys())
            pnls_bps = [t.pnl_price / med_px * 10000 for t in trades]
            s = compute_stats(pnls_bps)

            print(f"\n  {symbol} RR={rr} BE@2h  (Sharpe={s['sharpe']:>+.2f}, N={s['n']}, WR={s['wr']:.1f}%)")
            print(f"  {'Year':<6} {'Trades':>7} {'WR%':>6} {'TotBps':>10} {'Status':>8}")
            print(f"  {'-'*40}")

            neg_years = 0
            for yr in years:
                n_yr = yearly_n[yr]
                wr = yearly_wr.get(yr, 0) / n_yr * 100 if n_yr > 0 else 0
                tot = yearly[yr]
                status = "LOSS" if tot < 0 else "ok"
                if tot < 0:
                    neg_years += 1
                print(f"  {yr:<6} {n_yr:>7} {wr:>5.1f}% {tot:>+10.0f} {status:>8}")

            print(f"  Total: {sum(yearly_n.values()):>5} trades, "
                  f"{neg_years} negative years out of {len(years)}")

        del df
        gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Phase 8: BE Duration Sweep (is 2h optimal for all pairs?)
# ============================================================================

def phase8_be_duration_sweep(pairs: List[str], start_date: str = "2018-01-01"):
    """Sweep BE duration from 30 to 240 minutes for all pairs."""
    print(f"\n{'='*90}")
    print("PHASE 8: BE DURATION SWEEP (is 2hr optimal for all pairs?)")
    print(f"  RR=1.5 and RR=2.0 tested. Start: {start_date}")
    print(f"{'='*90}")

    be_durations = [0, 30, 60, 90, 120, 150, 180, 240]  # 0 = no BE

    for rr in [1.5, 2.0]:
        print(f"\n  --- RR = {rr} ---")
        header = f"  {'Symbol':<10}" + "".join(f"{'BE='+str(d)+'m':>10}" if d > 0 else f"{'no_BE':>10}" for d in be_durations)
        print(header)
        print("  " + "-" * (10 + 10 * len(be_durations)))

        for symbol in pairs:
            df = load_1m_csv(symbol)
            if df is None:
                continue
            df = df[df["timestamp"] >= start_date].reset_index(drop=True)
            params = derive_instrument_params(df)
            med_px = params["median_price"]

            row = f"  {symbol:<10}"
            best_sharpe = -999
            best_dur = 0
            for dur in be_durations:
                be_mins = dur if dur > 0 else None
                cfg = V6Config(rr_ratio=rr, be_minutes=be_mins, be_offset=0.0)
                trades = v6_backtest_pair(df, cfg)
                if not trades:
                    row += f"{'--':>10}"
                    continue
                pnls = [t.pnl_price / med_px * 10000 for t in trades]
                s = compute_stats(pnls)
                row += f"{s['sharpe']:>+10.2f}"
                if s['sharpe'] > best_sharpe:
                    best_sharpe = s['sharpe']
                    best_dur = dur
            row += f"  best={'no_BE' if best_dur == 0 else str(best_dur)+'m'}"
            print(row)

            del df
            gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Phase 9: Trade Date Overlap Analysis (diversification)
# ============================================================================

def phase9_trade_date_overlap(pairs: List[str], start_date: str = "2018-01-01"):
    """Analyze whether V6 and V8 trades cluster on the same days across pairs."""
    import contextlib
    import io
    import logging
    from collections import Counter

    from v8_confirmed_rebreak.config.strategy_config import StrategyConfig
    from v8_confirmed_rebreak.backtest.runner import BacktestRunner

    print(f"\n{'='*90}")
    print("PHASE 9: TRADE DATE OVERLAP ANALYSIS")
    print(f"  Do trades cluster on the same days across pairs?")
    print(f"  Start: {start_date}")
    print(f"{'='*90}")

    logger = logging.getLogger("overlap")
    logger.setLevel(logging.CRITICAL)

    # Common date range: use pairs with long data (exclude GBPUSD)
    common_start = "2018-01-01"
    common_end = "2026-01-01"  # full years only

    # ── V6+BE@2h trades per pair ──
    print("\n  === V6 ORB + BE@2h (RR=1.5) ===")
    v6_dates = {}  # symbol -> set of trade dates
    v6_win_dates = {}  # symbol -> set of winning trade dates

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df = df[(df["timestamp"] >= common_start) & (df["timestamp"] < common_end)].reset_index(drop=True)
        if len(df) < 1000:
            print(f"  {symbol}: insufficient data in common range")
            continue

        cfg = V6Config(rr_ratio=1.5, be_minutes=120, be_offset=0.0)
        trades = v6_backtest_pair(df, cfg)

        dates = set()
        win_dates = set()
        for t in trades:
            d = t.date
            dates.add(d)
            if t.pnl_price > 0:
                win_dates.add(d)

        v6_dates[symbol] = dates
        v6_win_dates[symbol] = win_dates
        print(f"  {symbol}: {len(trades)} trades on {len(dates)} unique days")

        del df
        gc.collect()

    # Pairwise overlap for V6
    v6_symbols = sorted(v6_dates.keys())
    if len(v6_symbols) >= 2:
        print(f"\n  V6 pairwise trade-day overlap (% of days BOTH pairs trade):")
        header = f"  {'':>10}" + "".join(f"{s:>10}" for s in v6_symbols)
        print(header)
        for s1 in v6_symbols:
            row = f"  {s1:>10}"
            for s2 in v6_symbols:
                if s1 == s2:
                    row += f"{'---':>10}"
                else:
                    overlap = len(v6_dates[s1] & v6_dates[s2])
                    union = len(v6_dates[s1] | v6_dates[s2])
                    pct = overlap / union * 100 if union > 0 else 0
                    row += f"{pct:>9.0f}%"
            print(row)

        # How many pairs trade on same day?
        all_v6_dates = set()
        for dates in v6_dates.values():
            all_v6_dates |= dates

        day_counts = Counter()
        for d in all_v6_dates:
            n_pairs = sum(1 for s in v6_symbols if d in v6_dates[s])
            day_counts[n_pairs] += 1

        print(f"\n  V6 concurrent trades per day (out of {len(v6_symbols)} pairs):")
        total_days = len(all_v6_dates)
        for n_pairs in sorted(day_counts.keys()):
            count = day_counts[n_pairs]
            print(f"    {n_pairs} pairs: {count:>5} days ({count/total_days*100:>5.1f}%)")

        # Average concurrent trades
        total_pair_days = sum(n * c for n, c in day_counts.items())
        avg_concurrent = total_pair_days / total_days if total_days > 0 else 0
        print(f"    Average: {avg_concurrent:.1f} pairs trade per day")

    # ── V8 trades per pair ──
    print(f"\n  === V8 Confirmed Rebreak ===")
    v8_dates = {}

    for symbol in pairs:
        data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
        if not Path(data_path).exists():
            continue

        df_sample = pd.read_csv(data_path, usecols=["avg_spread", "close"], nrows=500_000)
        med_spread = float(df_sample["avg_spread"].median())
        del df_sample
        gc.collect()

        config = StrategyConfig(
            instrument=symbol,
            pivot_window=60, confirm_bars=3, imbalance_window=3,
            divergence_threshold=0.50, max_pullback_bars=60, min_pullback_bars=3,
            sl_atr_multiple=10.0, tp_atr_multiple=99.0, max_hold_bars=60,
            atr_period=60, min_bar_ticks=50, spread_cost=med_spread,
        )
        runner = BacktestRunner(
            data_path=data_path, config=config,
            start_date=common_start, end_date=common_end, logger=logger,
        )
        f_buf = io.StringIO()
        with contextlib.redirect_stdout(f_buf):
            trades = runner.run()

        dates = set()
        for t in trades:
            dates.add(t.entry_time.date())
        v8_dates[symbol] = dates
        print(f"  {symbol}: {len(trades)} trades on {len(dates)} unique days")

    # Pairwise overlap for V8
    v8_symbols = sorted(v8_dates.keys())
    if len(v8_symbols) >= 2:
        print(f"\n  V8 pairwise trade-day overlap (% of days BOTH pairs trade):")
        header = f"  {'':>10}" + "".join(f"{s:>10}" for s in v8_symbols)
        print(header)
        for s1 in v8_symbols:
            row = f"  {s1:>10}"
            for s2 in v8_symbols:
                if s1 == s2:
                    row += f"{'---':>10}"
                else:
                    overlap = len(v8_dates[s1] & v8_dates[s2])
                    union = len(v8_dates[s1] | v8_dates[s2])
                    pct = overlap / union * 100 if union > 0 else 0
                    row += f"{pct:>9.0f}%"
            print(row)

        all_v8_dates = set()
        for dates in v8_dates.values():
            all_v8_dates |= dates

        day_counts = Counter()
        for d in all_v8_dates:
            n_pairs = sum(1 for s in v8_symbols if d in v8_dates[s])
            day_counts[n_pairs] += 1

        print(f"\n  V8 concurrent trades per day (out of {len(v8_symbols)} pairs):")
        total_days = len(all_v8_dates)
        for n_pairs in sorted(day_counts.keys()):
            count = day_counts[n_pairs]
            print(f"    {n_pairs} pairs: {count:>5} days ({count/total_days*100:>5.1f}%)")

        total_pair_days = sum(n * c for n, c in day_counts.items())
        avg_concurrent = total_pair_days / total_days if total_days > 0 else 0
        print(f"    Average: {avg_concurrent:.1f} pairs trade per day")

    # ── Cross-strategy: V6 vs V8 overlap ──
    common_symbols = sorted(set(v6_symbols) & set(v8_symbols))
    if common_symbols:
        print(f"\n  === V6 vs V8 same-pair overlap ===")
        print(f"  {'Symbol':<10} {'V6 days':>8} {'V8 days':>8} {'Overlap':>8} {'V6only':>8} {'V8only':>8} {'Jaccard':>8}")
        for sym in common_symbols:
            v6d = v6_dates.get(sym, set())
            v8d = v8_dates.get(sym, set())
            overlap = len(v6d & v8d)
            v6only = len(v6d - v8d)
            v8only = len(v8d - v6d)
            union = len(v6d | v8d)
            jaccard = overlap / union * 100 if union > 0 else 0
            print(f"  {sym:<10} {len(v6d):>8} {len(v8d):>8} {overlap:>8} {v6only:>8} {v8only:>8} {jaccard:>7.0f}%")

    print(f"\n{'='*90}")


# ============================================================================
# Phase 10: Walk-Forward Velocity Filter Analysis for V6+BE
# ============================================================================

def phase10_velocity_analysis(pairs: List[str], start_date: str = "2018-01-01"):
    """Walk-forward tick-count velocity filter for V6+BE.
    
    For each pair: run V6+BE at optimal BE duration, then test whether
    filtering trades by entry bar tick_count improves Sharpe OOS.
    Uses rolling 3-year train / 1-year test windows (matches V5 section 6).
    """
    print(f"\n{'='*90}")
    print("PHASE 10: WALK-FORWARD VELOCITY (TICK COUNT) FILTER FOR V6+BE")
    print(f"  Method: Train threshold on 3yr rolling, test on next year")
    print(f"  Threshold = median entry_tick_count from training set")
    print(f"  Start: {start_date}")
    print(f"{'='*90}")

    # Optimal BE per pair from Phase 8
    optimal_be = {
        'XAUUSD': 90, 'EURUSD': 30, 'GBPUSD': 30, 'USDJPY': 120,
        'AUDUSD': 90, 'NZDUSD': 90, 'USDCAD': 30, 'USDCHF': 30,
    }

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df = df[df["timestamp"] >= start_date].reset_index(drop=True)
        params = derive_instrument_params(df)
        med_px = params["median_price"]

        be_mins = optimal_be.get(symbol, 120)
        cfg = V6Config(rr_ratio=1.5, be_minutes=be_mins, be_offset=0.0)
        all_trades = v6_backtest_pair(df, cfg)

        if not all_trades:
            print(f"\n  {symbol}: no trades")
            continue

        # Tick count distribution
        tcs = [t.entry_tick_count for t in all_trades]
        tc_med = np.median(tcs)
        tc_p25 = np.percentile(tcs, 25)
        tc_p75 = np.percentile(tcs, 75)

        print(f"\n  {symbol} (BE={be_mins}m, RR=1.5, N={len(all_trades)})")
        print(f"  Entry tick_count: P25={tc_p25:.0f}  median={tc_med:.0f}  P75={tc_p75:.0f}")

        # Group by year
        by_year = {}
        for t in all_trades:
            yr = t.date.year if hasattr(t.date, 'year') else int(str(t.date)[:4])
            by_year.setdefault(yr, []).append(t)

        years = sorted(by_year.keys())

        print(f"\n  {'Test':>6} | {'Train':>12} | {'Thresh':>6} | {'N_all':>6} | {'N_fast':>6} | "
              f"{'Sh_all':>7} | {'Sh_fast':>7} | {'Sh_slow':>7} | {'Better?':>8}")
        print(f"  {'-'*85}")

        filter_helps = 0
        total_tests = 0

        for test_yr in years:
            train_yrs = [y for y in years if y < test_yr][-3:]
            if len(train_yrs) < 2:
                continue
            train_trades = [t for t in all_trades if (t.date.year if hasattr(t.date, 'year') else int(str(t.date)[:4])) in train_yrs]
            test_trades = [t for t in all_trades if (t.date.year if hasattr(t.date, 'year') else int(str(t.date)[:4])) == test_yr]
            if len(train_trades) < 20 or len(test_trades) < 10:
                continue

            thresh = np.median([t.entry_tick_count for t in train_trades])
            fast_test = [t for t in test_trades if t.entry_tick_count >= thresh]
            slow_test = [t for t in test_trades if t.entry_tick_count < thresh]

            pnls_all = [t.pnl_price / med_px * 10000 for t in test_trades]
            pnls_fast = [t.pnl_price / med_px * 10000 for t in fast_test]
            pnls_slow = [t.pnl_price / med_px * 10000 for t in slow_test]

            sh_all = compute_stats(pnls_all)['sharpe']
            sh_fast = compute_stats(pnls_fast)['sharpe'] if len(fast_test) >= 5 else 0
            sh_slow = compute_stats(pnls_slow)['sharpe'] if len(slow_test) >= 5 else 0

            total_tests += 1
            helps = sh_fast > sh_all
            if helps:
                filter_helps += 1

            print(f"  {test_yr:>6} | {train_yrs[0]}-{train_yrs[-1]} | {thresh:>6.0f} | "
                  f"{len(test_trades):>6} | {len(fast_test):>6} | "
                  f"{sh_all:>+7.2f} | {sh_fast:>+7.2f} | {sh_slow:>+7.2f} | "
                  f"{'YES' if helps else 'no':>8}")

        if total_tests > 0:
            pct = filter_helps / total_tests * 100
            verdict = "HELPS" if pct >= 60 else "MIXED" if pct >= 40 else "HURTS"
            print(f"\n  Velocity filter helped in {filter_helps}/{total_tests} years ({pct:.0f}%) => {verdict}")
        else:
            print(f"  Insufficient data for walk-forward test")

        # Also show: percentile sweep (which threshold works best?)
        # Use full IS period (2018-2022) and OOS (2023+)
        is_trades = [t for t in all_trades if (t.date.year if hasattr(t.date, 'year') else int(str(t.date)[:4])) <= 2022]
        oos_trades = [t for t in all_trades if (t.date.year if hasattr(t.date, 'year') else int(str(t.date)[:4])) >= 2023]

        if len(is_trades) >= 50 and len(oos_trades) >= 20:
            print(f"\n  Percentile sweep (threshold from IS 2018-2022, test on OOS 2023+):")
            print(f"  {'Pctl':>6} {'Thresh':>7} {'OOS_N':>7} {'OOS_Sh':>8} {'OOS_PF':>8} {'OOS_WR':>7} {'Reject_N':>9} {'Rej_Sh':>8}")

            for pctl in [25, 33, 40, 50, 60, 67, 75]:
                thresh = np.percentile([t.entry_tick_count for t in is_trades], pctl)
                fast_oos = [t for t in oos_trades if t.entry_tick_count >= thresh]
                slow_oos = [t for t in oos_trades if t.entry_tick_count < thresh]

                pnls_f = [t.pnl_price / med_px * 10000 for t in fast_oos]
                pnls_s = [t.pnl_price / med_px * 10000 for t in slow_oos]

                sf = compute_stats(pnls_f)
                ss = compute_stats(pnls_s)

                print(f"  P{pctl:>4} {thresh:>7.0f} {sf['n']:>7} {sf['sharpe']:>+8.2f} "
                      f"{sf['pf']:>8.2f} {sf['wr']:>6.1f}% {ss['n']:>9} {ss['sharpe']:>+8.2f}")

        del df
        gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Phase 11: Wednesday Skip Analysis for V6+BE
# ============================================================================

def phase11_wednesday_analysis(pairs: List[str], start_date: str = "2018-01-01"):
    """Test whether skipping Wednesdays helps each pair for V6+BE."""
    print(f"\n{'='*90}")
    print("PHASE 11: WEDNESDAY SKIP ANALYSIS FOR V6+BE")
    print(f"  V5 production skips Wed for XAUUSD. Is this optimal per pair?")
    print(f"  Config: RR=1.5, optimal BE per pair")
    print(f"{'='*90}")

    optimal_be = {
        'XAUUSD': 90, 'EURUSD': 30, 'GBPUSD': 30, 'USDJPY': 120,
        'AUDUSD': 90, 'NZDUSD': 90, 'USDCAD': 30, 'USDCHF': 30,
    }

    print(f"\n  {'Symbol':<10} {'All_Sh':>7} {'All_N':>6} {'NoWed_Sh':>9} {'NoWed_N':>8} "
          f"{'Wed_Sh':>7} {'Wed_N':>6} {'Wed_WR':>7} {'Wed_PF':>7} {'Skip?':>8}")
    print(f"  {'-'*85}")

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df = df[df["timestamp"] >= start_date].reset_index(drop=True)
        params = derive_instrument_params(df)
        med_px = params["median_price"]

        be_mins = optimal_be.get(symbol, 120)

        # All days
        cfg_all = V6Config(rr_ratio=1.5, be_minutes=be_mins, be_offset=0.0, skip_weekdays=[])
        trades_all = v6_backtest_pair(df, cfg_all)

        # Skip Wednesday
        cfg_nowed = V6Config(rr_ratio=1.5, be_minutes=be_mins, be_offset=0.0, skip_weekdays=[2])
        trades_nowed = v6_backtest_pair(df, cfg_nowed)

        if not trades_all:
            continue

        # Wednesday-only trades
        trades_wed = [t for t in trades_all
                      if (t.date.weekday() if hasattr(t.date, 'weekday') else 2) == 2]

        pnls_all = [t.pnl_price / med_px * 10000 for t in trades_all]
        pnls_nowed = [t.pnl_price / med_px * 10000 for t in trades_nowed]
        pnls_wed = [t.pnl_price / med_px * 10000 for t in trades_wed]

        s_all = compute_stats(pnls_all)
        s_nowed = compute_stats(pnls_nowed)
        s_wed = compute_stats(pnls_wed) if trades_wed else {'sharpe': 0, 'n': 0, 'wr': 0, 'pf': 0}

        skip = "YES" if s_nowed['sharpe'] > s_all['sharpe'] else "no"
        print(f"  {symbol:<10} {s_all['sharpe']:>+7.2f} {s_all['n']:>6} {s_nowed['sharpe']:>+9.2f} {s_nowed['n']:>8} "
              f"{s_wed['sharpe']:>+7.2f} {s_wed['n']:>6} {s_wed['wr']:>6.1f}% {s_wed['pf']:>7.2f} {skip:>8}")

        del df
        gc.collect()

    # Now do OOS split: IS 2018-2022, OOS 2023+
    print(f"\n  --- OOS Validation (2023+) ---")
    print(f"  {'Symbol':<10} {'OOS_All':>8} {'OOS_NoW':>8} {'OOS_Wed':>8} {'Wed_N':>6} {'Skip?':>8}")
    print(f"  {'-'*55}")

    for symbol in pairs:
        df = load_1m_csv(symbol)
        if df is None:
            continue
        df_oos = df[df["timestamp"] >= "2023-01-01"].reset_index(drop=True)
        if len(df_oos) < 1000:
            continue
        params = derive_instrument_params(df)
        med_px = params["median_price"]

        be_mins = optimal_be.get(symbol, 120)

        cfg_all = V6Config(rr_ratio=1.5, be_minutes=be_mins, be_offset=0.0, skip_weekdays=[])
        cfg_nowed = V6Config(rr_ratio=1.5, be_minutes=be_mins, be_offset=0.0, skip_weekdays=[2])

        trades_all = v6_backtest_pair(df_oos, cfg_all)
        trades_nowed = v6_backtest_pair(df_oos, cfg_nowed)
        trades_wed = [t for t in trades_all
                      if (t.date.weekday() if hasattr(t.date, 'weekday') else 2) == 2]

        if not trades_all:
            continue

        pnls_all = [t.pnl_price / med_px * 10000 for t in trades_all]
        pnls_nowed = [t.pnl_price / med_px * 10000 for t in trades_nowed]
        pnls_wed = [t.pnl_price / med_px * 10000 for t in trades_wed]

        s_all = compute_stats(pnls_all)
        s_nowed = compute_stats(pnls_nowed)
        s_wed = compute_stats(pnls_wed) if trades_wed else {'sharpe': 0, 'n': 0}

        skip = "YES" if s_nowed['sharpe'] > s_all['sharpe'] else "no"
        print(f"  {symbol:<10} {s_all['sharpe']:>+8.2f} {s_nowed['sharpe']:>+8.2f} "
              f"{s_wed['sharpe']:>+8.2f} {s_wed['n']:>6} {skip:>8}")

        del df, df_oos
        gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Phase 12: V8 pivot_window Sweep
# ============================================================================

def phase12_v8_pivot_sweep(pairs: List[str], start_date: str = "2018-01-01"):
    """Sweep V8 pivot_window across all pairs. Full sample + OOS split."""
    import contextlib
    import io
    import logging

    from v8_confirmed_rebreak.config.strategy_config import StrategyConfig
    from v8_confirmed_rebreak.backtest.runner import BacktestRunner

    print(f"\n{'='*90}")
    print("PHASE 12: V8 PIVOT_WINDOW SWEEP (30, 60, 90, 120)")
    print(f"  Other params: confirm=3, hold=60, sl=10xATR, min_ticks=50")
    print(f"  Start: {start_date}")
    print(f"{'='*90}")

    logger = logging.getLogger("v8_pw")
    logger.setLevel(logging.CRITICAL)

    pw_values = [30, 60, 90, 120]

    # ── Full sample ──
    print(f"\n  --- Full Sample ({start_date} onward) ---")
    header = f"  {'Symbol':<10}" + "".join(f"{'pw='+str(pw):>10}" for pw in pw_values) + f"{'best':>8}"
    print(header)
    print("  " + "-" * (10 + 10 * len(pw_values) + 8))

    full_results = {}  # symbol -> {pw: stats_dict}

    for symbol in pairs:
        data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
        if not Path(data_path).exists():
            continue

        try:
            # Preload data once per pair
            f_buf = io.StringIO()
            with contextlib.redirect_stdout(f_buf):
                df_full = BacktestRunner.load_csv(data_path)
            med_spread = float(df_full["avg_spread"].median())
            med_price = float(df_full["close"].median())
        except Exception as e:
            print(f"  {symbol:<10} ERROR loading: {e}")
            continue

        row = f"  {symbol:<10}"
        best_sharpe = -999
        best_pw = 60
        pw_stats = {}

        for pw in pw_values:
            config = StrategyConfig(
                instrument=symbol,
                pivot_window=pw,
                confirm_bars=3, imbalance_window=3,
                divergence_threshold=0.50,
                max_pullback_bars=60, min_pullback_bars=3,
                sl_atr_multiple=10.0, tp_atr_multiple=99.0,
                max_hold_bars=60, atr_period=60,
                min_bar_ticks=50, spread_cost=med_spread,
            )
            runner = BacktestRunner(
                data_path=data_path, config=config,
                start_date=start_date, logger=logger,
                preloaded_df=df_full,
            )
            f_buf = io.StringIO()
            with contextlib.redirect_stdout(f_buf):
                trades = runner.run()

            if not trades:
                row += f"{'--':>10}"
                pw_stats[pw] = {'sharpe': 0, 'n': 0, 'wr': 0, 'pf': 0, 'total': 0}
                continue

            pnls_bps = [t.pnl / med_price * 10000 for t in trades]
            s = compute_stats(pnls_bps)
            pw_stats[pw] = s
            row += f"{s['sharpe']:>+10.2f}"
            if s['sharpe'] > best_sharpe:
                best_sharpe = s['sharpe']
                best_pw = pw

        row += f"  pw={best_pw}"
        print(row)
        full_results[symbol] = pw_stats
        del df_full
        gc.collect()

    # Detail table: trades, WR, PF for each
    print(f"\n  Detail (Trades / WR% / PF):")
    header2 = f"  {'Symbol':<10}" + "".join(f"{'pw='+str(pw):>22}" for pw in pw_values)
    print(header2)
    print("  " + "-" * (10 + 22 * len(pw_values)))
    for symbol, pw_stats in full_results.items():
        row = f"  {symbol:<10}"
        for pw in pw_values:
            s = pw_stats.get(pw, {})
            if s.get('n', 0) == 0:
                row += f"{'--':>22}"
            else:
                row += f"{s['n']:>6}/{s['wr']:>5.1f}%/{s['pf']:>5.2f}"
        print(row)

    # ── OOS split: IS 2018-2022, OOS 2023+ ──
    print(f"\n  --- OOS Validation (IS 2018-2022, OOS 2023+) ---")
    header3 = f"  {'Symbol':<10}" + "".join(f"{'pw='+str(pw):>10}" for pw in pw_values) + f"{'best':>8}"
    print(header3)
    print("  " + "-" * (10 + 10 * len(pw_values) + 8))

    for symbol in pairs:
        data_path = str(DATA_DIR / f"{symbol.lower()}_1m_tick.csv")
        if not Path(data_path).exists():
            continue

        try:
            f_buf = io.StringIO()
            with contextlib.redirect_stdout(f_buf):
                df_full = BacktestRunner.load_csv(data_path)
            med_spread = float(df_full["avg_spread"].median())
            med_price = float(df_full["close"].median())
        except Exception as e:
            print(f"  {symbol:<10} ERROR loading: {e}")
            continue

        row = f"  {symbol:<10}"
        best_sharpe = -999
        best_pw = 60

        for pw in pw_values:
            config = StrategyConfig(
                instrument=symbol,
                pivot_window=pw,
                confirm_bars=3, imbalance_window=3,
                divergence_threshold=0.50,
                max_pullback_bars=60, min_pullback_bars=3,
                sl_atr_multiple=10.0, tp_atr_multiple=99.0,
                max_hold_bars=60, atr_period=60,
                min_bar_ticks=50, spread_cost=med_spread,
            )
            runner = BacktestRunner(
                data_path=data_path, config=config,
                start_date="2023-01-01", logger=logger,
                preloaded_df=df_full,
            )
            f_buf = io.StringIO()
            with contextlib.redirect_stdout(f_buf):
                trades = runner.run()

            if not trades:
                row += f"{'--':>10}"
                continue

            pnls_bps = [t.pnl / med_price * 10000 for t in trades]
            s = compute_stats(pnls_bps)
            row += f"{s['sharpe']:>+10.2f}"
            if s['sharpe'] > best_sharpe:
                best_sharpe = s['sharpe']
                best_pw = pw

        row += f"  pw={best_pw}"
        print(row)
        del df_full
        gc.collect()

    print(f"\n{'='*90}")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Multi-instrument V6/V8 research")
    parser.add_argument("--phase", type=int, nargs="+", default=[1, 2, 3, 4],
                        help="Phases to run (1-12, 10=velocity, 11=wednesday, 12=pw sweep)")
    parser.add_argument("--pairs", nargs="+", default=ALL_PAIRS,
                        help="Symbols to test")
    parser.add_argument("--start", default="2018-01-01",
                        help="Start date for backtests")
    args = parser.parse_args()

    pairs = [p.upper() for p in args.pairs]
    print(f"Multi-Instrument Research: {', '.join(pairs)}")
    print(f"Start date: {args.start}")

    if 1 in args.phase:
        phase1_data_audit(pairs)

    v6_results = None
    if 2 in args.phase:
        v6_results = phase2_v6_orb(pairs, args.start)

    v8_results = None
    if 3 in args.phase:
        v8_results = phase3_v8_rebreak(pairs, args.start)

    if 4 in args.phase:
        # Only run param sweep on pairs that showed some promise in phase 2
        sweep_pairs = pairs
        if v6_results:
            sweep_pairs = [s for s, r in v6_results.items()
                           if r["stats"]["n"] >= 50]
        if sweep_pairs:
            phase4_v6_param_sweep(sweep_pairs, args.start)

    if 5 in args.phase:
        phase5_v8_minticks_sensitivity(pairs, args.start)

    if 6 in args.phase:
        phase6_v6_be_walkforward(pairs, args.start)

    if 7 in args.phase:
        phase7_v6_be_yearly(pairs, args.start)

    if 8 in args.phase:
        phase8_be_duration_sweep(pairs, args.start)

    if 9 in args.phase:
        phase9_trade_date_overlap(pairs, args.start)

    if 10 in args.phase:
        phase10_velocity_analysis(pairs, args.start)

    if 11 in args.phase:
        phase11_wednesday_analysis(pairs, args.start)

    if 12 in args.phase:
        phase12_v8_pivot_sweep(pairs, args.start)

    print("\nDone.")


if __name__ == "__main__":
    main()
