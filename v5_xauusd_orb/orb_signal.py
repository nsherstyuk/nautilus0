"""
orb_signal.py -- Daily XAUUSD Asian Range Breakout signal  (v5)

Shows today's Asian range and breakout levels using offline tick_vault data.
All parameters read from config.yaml.

Usage:
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_signal
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_signal --date 2026-02-25
  .venv\\Scripts\\python.exe -m v5_xauusd_orb.orb_signal --config my_config.yaml
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np
import pandas as pd

from v5_xauusd_orb.config import load_config, Config


# ── Data loading ──────────────────────────────────────────────────────────────

def load_bars(cfg: Config) -> pd.DataFrame:
    """Load XAUUSD tick bars from the configured parquet file."""
    path = Path(cfg.paths.tick_bar_file)
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    return df


# ── Signal computation ────────────────────────────────────────────────────────

def get_signal(df: pd.DataFrame, cfg: Config, target_date=None) -> dict | None:
    """Compute Asian range and breakout levels for a given date."""
    if target_date is None:
        target_date = datetime.now(tz=timezone.utc).date()

    strat = cfg.strategy
    asian = df[(df['date'] == target_date)
               & (df['hour'] >= strat.asian_start_hour)
               & (df['hour'] < strat.asian_end_hour)]

    if len(asian) < 3:
        return None

    range_high = asian['high'].max()
    range_low = asian['low'].min()
    range_size = range_high - range_low
    last_close = asian['close'].iloc[-1]

    if range_size <= 0:
        return None

    rr = strat.rr_ratio

    return {
        'date': target_date,
        'range_high': range_high,
        'range_low': range_low,
        'range_size': range_size,
        'range_pct': range_size / last_close * 100,
        'last_asian_close': last_close,
        'n_bars': len(asian),
        'long_entry': range_high,
        'long_sl': range_low,
        'long_tp': range_high + rr * range_size,
        'short_entry': range_low,
        'short_sl': range_high,
        'short_tp': range_low - rr * range_size,
        'risk_per_oz': range_size,
        'rr_ratio': rr,
    }


# ── Historical performance ────────────────────────────────────────────────────

def historical_performance(df: pd.DataFrame, cfg: Config,
                           n_days: int = 30) -> list[dict]:
    """Backtest the last N days and return trade records."""
    strat = cfg.strategy
    dates = sorted(df['date'].unique())[-n_days - 1:]

    trades = []
    for target_date in dates:
        wd = target_date.weekday() if hasattr(target_date, 'weekday') else \
            pd.Timestamp(target_date).weekday()
        if wd in strat.skip_weekdays:
            continue

        signal = get_signal(df, cfg, target_date)
        if signal is None:
            continue

        london = df[(df['date'] == target_date)
                     & (df['hour'] >= strat.trade_start_hour)
                     & (df['hour'] < strat.trade_end_hour)]
        if len(london) < 2:
            continue

        rh = signal['range_high']
        rl = signal['range_low']
        rsize = signal['range_size']
        rr = strat.rr_ratio

        position = 0
        entry = sl = tp = 0
        result = 'NO_TRADE'
        pnl = 0.0

        for _, bar in london.iterrows():
            if position == 0:
                if bar['high'] > rh:
                    position = 1; entry = rh
                    sl = rl; tp = rh + rr * rsize
                elif bar['low'] < rl:
                    position = -1; entry = rl
                    sl = rh; tp = rl - rr * rsize
            else:
                hit_tp = hit_sl = False
                if position == 1:
                    if bar['low'] <= sl: hit_sl = True
                    if bar['high'] >= tp: hit_tp = True
                else:
                    if bar['high'] >= sl: hit_sl = True
                    if bar['low'] <= tp: hit_tp = True

                if hit_sl and hit_tp: hit_tp = False

                if hit_tp:
                    pnl = abs(tp - entry)
                    result = 'TP'; position = 0; break
                elif hit_sl:
                    pnl = -abs(sl - entry)
                    result = 'SL'; position = 0; break

        if position != 0:
            last_close = london['close'].iloc[-1]
            pnl = position * (last_close - entry)
            result = 'TIME'

        if result != 'NO_TRADE':
            trades.append({
                'date': target_date,
                'direction': 'LONG' if pnl > 0 or position == 1 else 'SHORT',
                'result': result,
                'pnl_per_oz': pnl,
                'range_size': rsize,
            })

    return trades


# ── Display ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='XAUUSD Asian Range Breakout Signal (v5)')
    parser.add_argument('--date', type=str, default=None,
                        help='Target date (YYYY-MM-DD). Default: today UTC')
    parser.add_argument('--history', type=int, default=None,
                        help='Override history_days from config')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to alternative config.yaml')
    args = parser.parse_args()

    cfg = load_config(args.config)
    history_days = args.history or cfg.signal.history_days

    print("=" * 60)
    print("  XAUUSD Asian Range -> London Breakout  (v5)")
    print(f"  RR ratio: {cfg.strategy.rr_ratio}")
    print(f"  Skip weekdays: {cfg.strategy.skip_weekdays}")
    print("=" * 60)

    print("\n  Loading tick bars...")
    df = load_bars(cfg)
    print(f"  {len(df):,} bars, last: {df['timestamp'].iloc[-1]}")

    if args.date:
        target = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        target = datetime.now(tz=timezone.utc).date()

    print(f"\n  Target date: {target}")

    # Check skip day
    if target.weekday() in cfg.strategy.skip_weekdays:
        day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][target.weekday()]
        print(f"\n  [!] {day_name} is in skip_weekdays -- no trade today")

    signal = get_signal(df, cfg, target)

    if signal is None:
        print(f"\n  [!] No Asian range data for {target}")
        dates = sorted(df['date'].unique())
        latest = dates[-1]
        signal = get_signal(df, cfg, latest)
        if signal:
            print(f"  Showing most recent signal: {latest}")
            target = latest
        else:
            return

    s = signal
    rr = s['rr_ratio']
    print(f"\n  +--------------------------------------------+")
    print(f"  |  Asian Range ({cfg.strategy.asian_start_hour:02d}:00-"
          f"{cfg.strategy.asian_end_hour:02d}:00 UTC)"
          f"{'':>14s}|")
    print(f"  |  High:    {s['range_high']:>10.2f}                       |")
    print(f"  |  Low:     {s['range_low']:>10.2f}                       |")
    print(f"  |  Size:    {s['range_size']:>10.2f}  ({s['range_pct']:.2f}%)"
          f"{'':>13s}|")
    print(f"  |  Bars:    {s['n_bars']:>10d}                       |")
    print(f"  +--------------------------------------------+")
    print(f"  |  LONG BREAKOUT  (RR={rr})"
          f"{'':>20s}|")
    print(f"  |  Entry:   {s['long_entry']:>10.2f}  (= Asian high)      |")
    print(f"  |  SL:      {s['long_sl']:>10.2f}  (= Asian low)       |")
    print(f"  |  TP:      {s['long_tp']:>10.2f}  ({rr}x range above)"
          f"{'':>4s}|")
    print(f"  |  Risk:    {s['risk_per_oz']:>10.2f}  per oz              |")
    print(f"  +--------------------------------------------+")
    print(f"  |  SHORT BREAKOUT  (RR={rr})"
          f"{'':>19s}|")
    print(f"  |  Entry:   {s['short_entry']:>10.2f}  (= Asian low)       |")
    print(f"  |  SL:      {s['short_sl']:>10.2f}  (= Asian high)      |")
    print(f"  |  TP:      {s['short_tp']:>10.2f}  ({rr}x range below)"
          f"{'':>4s}|")
    print(f"  |  Risk:    {s['risk_per_oz']:>10.2f}  per oz              |")
    print(f"  +--------------------------------------------+")

    # Position sizing
    risk = s['risk_per_oz']
    print(f"\n  -- Position Sizing Guide --")
    print(f"  SL distance: ${risk:.2f} per oz")
    for label, oz in [("Micro (1 oz)", 1), ("Mini (10 oz)", 10),
                      ("Standard (100 oz)", 100)]:
        risk_usd = risk * oz
        tp_usd = risk_usd * rr
        print(f"    {label:>20s}: risk ${risk_usd:>8.2f} / "
              f"reward ${tp_usd:>8.2f}")

    # Time windows
    now_utc = datetime.now(tz=timezone.utc)
    toronto_offset = timedelta(hours=-5)

    print(f"\n  -- Time Windows --")
    print(f"  Asian range:  {cfg.strategy.asian_start_hour:02d}:00-"
          f"{cfg.strategy.asian_end_hour:02d}:00 UTC")
    print(f"  Orders live:  {cfg.strategy.trade_start_hour:02d}:00-"
          f"{cfg.strategy.trade_end_hour:02d}:00 UTC")

    if now_utc.date() == target:
        h = now_utc.hour
        if h < cfg.strategy.asian_end_hour:
            print(f"\n  [..] Asian session still forming "
                  f"({now_utc.strftime('%H:%M')} UTC)")
        elif h < cfg.strategy.trade_start_hour:
            print(f"\n  [OK] Asian range complete. Orders at "
                  f"{cfg.strategy.trade_start_hour:02d}:00 UTC.")
        elif h < cfg.strategy.trade_end_hour:
            print(f"\n  [LIVE] Breakout orders should be active")
        else:
            print(f"\n  [--] Trading window closed for today")

    # Recent performance
    print(f"\n  -- Last {history_days} Days Performance --")
    history = historical_performance(df, cfg, history_days)

    if history:
        tp_count = sum(1 for t in history if t['result'] == 'TP')
        sl_count = sum(1 for t in history if t['result'] == 'SL')
        time_count = sum(1 for t in history if t['result'] == 'TIME')
        total_pnl = sum(t['pnl_per_oz'] for t in history)
        wins = sum(1 for t in history if t['pnl_per_oz'] > 0)

        print(f"  Trades: {len(history)} "
              f"(TP:{tp_count} SL:{sl_count} Time:{time_count})")
        print(f"  Win rate: {wins / len(history) * 100:.0f}%")
        print(f"  Total PnL: ${total_pnl:+.2f}/oz "
              f"(10 oz = ${total_pnl * 10:+.2f})")

        print(f"\n  {'Date':>12s} {'Dir':>5s} {'Result':>6s} "
              f"{'PnL/oz':>8s} {'Range':>6s}")
        print(f"  {'---':>12s} {'---':>5s} {'---':>6s} "
              f"{'---':>8s} {'---':>6s}")
        for t in history[-15:]:
            mark = "+" if t['pnl_per_oz'] > 0 else "-"
            print(f"  {t['date']}  {t['direction']:>5s}  "
                  f"{t['result']:>4s}  ${t['pnl_per_oz']:>+7.2f}  "
                  f"${t['range_size']:>5.1f}  {mark}")
    else:
        print("  No trades in recent history")


if __name__ == "__main__":
    main()
