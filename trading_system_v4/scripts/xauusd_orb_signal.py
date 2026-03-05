"""
xauusd_orb_signal.py — Daily XAUUSD Asian Range Breakout Signal

Shows today's Asian session range (00:00-06:00 UTC) and the breakout
levels for the London session trade.

Strategy:
  Range:  00:00 - 06:00 UTC  (Asian session)
  Trade:  08:00 - 16:00 UTC  (London session)
  Long:   Buy if price breaks ABOVE Asian high
  Short:  Sell if price breaks BELOW Asian low
  SL:     Opposite side of the Asian range
  TP:     2x the range size from entry (RR = 2:1)

Usage:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\xauusd_orb_signal.py
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\xauusd_orb_signal.py --date 2026-02-25
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

TICK_BAR_FILE = DATA_DIR / "xauusd_1000t_bars.parquet"


def load_bars():
    """Load XAUUSD tick bars."""
    df = pd.read_parquet(TICK_BAR_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    return df


def get_signal(df, target_date=None):
    """
    Compute the Asian range and breakout levels for a given date.
    
    Returns dict with entry/exit levels or None if no range available.
    """
    if target_date is None:
        target_date = datetime.now(tz=timezone.utc).date()
    
    # Asian range: 00:00-06:00 UTC on target_date
    asian = df[(df['date'] == target_date) & (df['hour'] >= 0) & (df['hour'] < 6)]
    
    if len(asian) < 3:
        return None
    
    range_high = asian['high'].max()
    range_low = asian['low'].min()
    range_size = range_high - range_low
    last_close = asian['close'].iloc[-1]
    n_bars = len(asian)
    
    if range_size <= 0:
        return None
    
    # Breakout levels
    long_entry = range_high
    long_sl = range_low
    long_tp = long_entry + 2.0 * range_size  # RR=2:1
    
    short_entry = range_low
    short_sl = range_high
    short_tp = short_entry - 2.0 * range_size  # RR=2:1
    
    # Risk per contract (1 standard lot = 100 oz)
    # Mini lot = 10 oz, Micro lot = 1 oz
    risk_per_oz = range_size  # SL distance = range_size
    
    return {
        'date': target_date,
        'range_high': range_high,
        'range_low': range_low,
        'range_size': range_size,
        'range_pct': range_size / last_close * 100,
        'last_asian_close': last_close,
        'n_bars': n_bars,
        'long_entry': long_entry,
        'long_sl': long_sl,
        'long_tp': long_tp,
        'short_entry': short_entry,
        'short_sl': short_sl,
        'short_tp': short_tp,
        'risk_per_oz': risk_per_oz,
    }


def historical_performance(df, n_days=30):
    """Show recent performance of the strategy."""
    dates = sorted(df['date'].unique())[-n_days-1:]
    
    trades = []
    for target_date in dates:
        signal = get_signal(df, target_date)
        if signal is None:
            continue
        
        # Check what happened in London session (08:00-16:00)
        london = df[(df['date'] == target_date) & (df['hour'] >= 8) & (df['hour'] < 16)]
        if len(london) < 2:
            continue
        
        rh = signal['range_high']
        rl = signal['range_low']
        rsize = signal['range_size']
        
        # Simulate
        position = 0
        entry = sl = tp = 0
        result = 'NO_TRADE'
        pnl = 0
        
        for _, bar in london.iterrows():
            if position == 0:
                if bar['high'] > rh:
                    position = 1; entry = rh
                    sl = rl; tp = rh + 2.0 * rsize
                elif bar['low'] < rl:
                    position = -1; entry = rl
                    sl = rh; tp = rl - 2.0 * rsize
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
                    result = 'TP'
                    position = 0; break
                elif hit_sl:
                    pnl = -abs(sl - entry)
                    result = 'SL'
                    position = 0; break
        
        if position != 0:
            last_close = london['close'].iloc[-1]
            pnl = position * (last_close - entry)
            result = 'TIME'
        
        if result != 'NO_TRADE':
            trades.append({
                'date': target_date,
                'direction': 'LONG' if position == 1 or (position == 0 and pnl > 0) else 'SHORT',
                'result': result,
                'pnl_per_oz': pnl,
                'range_size': rsize,
            })
    
    return trades


def main():
    parser = argparse.ArgumentParser(description='XAUUSD Asian Range Breakout Signal')
    parser.add_argument('--date', type=str, default=None,
                        help='Target date (YYYY-MM-DD). Default: today UTC')
    parser.add_argument('--history', type=int, default=30,
                        help='Show last N days of performance')
    args = parser.parse_args()
    
    print("=" * 60)
    print("  XAUUSD Asian Range -> London Breakout")
    print("  Strategy: break Asian high/low, SL opposite, TP 2x range")
    print("=" * 60)
    
    # Load data
    print("\n  Loading tick bars...")
    df = load_bars()
    print(f"  {len(df):,} bars, last: {df['timestamp'].iloc[-1]}")
    
    # Target date
    if args.date:
        target = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        target = datetime.now(tz=timezone.utc).date()
    
    print(f"\n  Target date: {target}")
    
    # Get signal
    signal = get_signal(df, target)
    
    if signal is None:
        print(f"\n  [!] No Asian range data for {target}")
        print(f"    (Data may not be available yet — runs on tick_vault offline data)")
        print(f"    For live, use xauusd_orb_live.py which streams from IBKR")
        
        # Show most recent available signal
        dates = sorted(df['date'].unique())
        latest = dates[-1]
        signal = get_signal(df, latest)
        if signal:
            print(f"\n  Showing most recent signal instead: {latest}")
            target = latest
        else:
            return
    
    # Display signal
    s = signal
    print(f"\n  ┌────────────────────────────────────────────┐")
    print(f"  │  Asian Range (00:00-06:00 UTC)              │")
    print(f"  │  High:    {s['range_high']:>10.2f}                       │")
    print(f"  │  Low:     {s['range_low']:>10.2f}                       │")
    print(f"  │  Size:    {s['range_size']:>10.2f}  ({s['range_pct']:.2f}%)             │")
    print(f"  │  Bars:    {s['n_bars']:>10d}                       │")
    print(f"  ├────────────────────────────────────────────┤")
    print(f"  │  LONG BREAKOUT (buy stop above range)       │")
    print(f"  │  Entry:   {s['long_entry']:>10.2f}  (= Asian high)      │")
    print(f"  │  SL:      {s['long_sl']:>10.2f}  (= Asian low)       │")
    print(f"  │  TP:      {s['long_tp']:>10.2f}  (2x range above)    │")
    print(f"  │  Risk:    {s['risk_per_oz']:>10.2f}  per oz              │")
    print(f"  ├────────────────────────────────────────────┤")
    print(f"  │  SHORT BREAKOUT (sell stop below range)     │")
    print(f"  │  Entry:   {s['short_entry']:>10.2f}  (= Asian low)       │")
    print(f"  │  SL:      {s['short_sl']:>10.2f}  (= Asian high)      │")
    print(f"  │  TP:      {s['short_tp']:>10.2f}  (2x range below)    │")
    print(f"  │  Risk:    {s['risk_per_oz']:>10.2f}  per oz              │")
    print(f"  └────────────────────────────────────────────┘")
    
    # Position sizing guidance
    print(f"\n  ── Position Sizing Guide ──")
    risk_per_oz = s['risk_per_oz']
    print(f"  SL distance: ${risk_per_oz:.2f} per oz")
    for label, oz_per_lot in [("Micro (1 oz)", 1), ("Mini (10 oz)", 10), ("Standard (100 oz)", 100)]:
        risk_usd = risk_per_oz * oz_per_lot
        tp_usd = risk_usd * 2  # RR=2:1
        print(f"    {label:>20s}: risk ${risk_usd:>8.2f} / reward ${tp_usd:>8.2f}")
    
    # Time windows
    now_utc = datetime.now(tz=timezone.utc)
    ldn_open = datetime(target.year, target.month, target.day, 8, 0, 0, tzinfo=timezone.utc)
    ldn_close = datetime(target.year, target.month, target.day, 16, 0, 0, tzinfo=timezone.utc)
    toronto_offset = timedelta(hours=-5)  # EST
    
    print(f"\n  ── Time Windows ──")
    print(f"  Asian range:  00:00-06:00 UTC  (7:00 PM - 1:00 AM Toronto)")
    print(f"  Orders live:  08:00-16:00 UTC  (3:00 AM - 11:00 AM Toronto)")
    print(f"  Set orders:   ~08:00 UTC       (~3:00 AM Toronto)")
    print(f"  Cancel if no fill by: 16:00 UTC (11:00 AM Toronto)")
    
    if now_utc.date() == target:
        if now_utc.hour < 6:
            print(f"\n  [..] Asian session still forming ({now_utc.strftime('%H:%M')} UTC)")
        elif now_utc.hour < 8:
            print(f"\n  [OK] Asian range complete. Orders ready to place at 08:00 UTC.")
        elif now_utc.hour < 16:
            print(f"\n  [LIVE] Breakout orders should be active")
        else:
            print(f"\n  [--] Trading window closed for today")
    
    # Recent performance
    print(f"\n  ── Last {args.history} Days Performance ──")
    history = historical_performance(df, args.history)
    
    if history:
        tp_count = sum(1 for t in history if t['result'] == 'TP')
        sl_count = sum(1 for t in history if t['result'] == 'SL')
        time_count = sum(1 for t in history if t['result'] == 'TIME')
        total_pnl = sum(t['pnl_per_oz'] for t in history)
        wins = sum(1 for t in history if t['pnl_per_oz'] > 0)
        
        print(f"  Trades: {len(history)} (TP:{tp_count} SL:{sl_count} Time:{time_count})")
        print(f"  Win rate: {wins/len(history)*100:.0f}%")
        print(f"  Total PnL: ${total_pnl:+.2f}/oz (10 oz = ${total_pnl*10:+.2f})")
        
        print(f"\n  {'Date':>12s} {'Dir':>5s} {'Result':>6s} {'PnL/oz':>8s} {'Range':>6s}")
        print(f"  {'─'*12} {'─'*5} {'─'*6} {'─'*8} {'─'*6}")
        for t in history[-15:]:  # Last 15
            mark = "+" if t['pnl_per_oz'] > 0 else "-"
            print(f"  {t['date']}  {t['direction']:>5s}  {t['result']:>4s} "
                  f" ${t['pnl_per_oz']:>+7.2f}  ${t['range_size']:>5.1f}  {mark}")
    else:
        print("  No trades in recent history")


if __name__ == "__main__":
    main()
