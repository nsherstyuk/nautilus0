#!/usr/bin/env python3
"""
Compare 30m OHLC bar snapshots between live and replay logs.

Parses [DMI_PARITY] debug lines from replay log to extract the last 14 30m bars
and compares them with live's 30m aggregation to identify OHLC divergences.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict


def parse_dmi_parity_line(line: str) -> Tuple[Optional[datetime], Optional[float], Optional[List[Tuple]]]:
    """
    Parse [DMI_PARITY] line to extract timestamp, DMI+, and 30m bar OHLC sequence.
    
    Format: [DMI_PARITY] t=2026-02-20T05:15:00+00:00 dmi_plus=0.1827 bars14=TS|O|H|L|C;TS|O|H|L|C;...
    
    Returns (timestamp, dmi_plus, [(ts, open, high, low, close), ...])
    """
    match = re.search(r'\[DMI_PARITY\]\s+t=([^\s]+)\s+dmi_plus=([^\s]+)\s+bars14=(.+)', line)
    if not match:
        return None, None, None
    
    ts_str, dmi_plus_str, bars_str = match.groups()
    
    # Parse timestamp and DMI
    try:
        ts = datetime.fromisoformat(ts_str)
        dmi_plus = float(dmi_plus_str)
    except Exception:
        return None, None, None
    
    # Parse bars14 (OHLC sequences)
    bars = []
    bar_parts = bars_str.split(';')
    for bar_part in bar_parts:
        bar_part = bar_part.strip()
        if not bar_part:
            continue
        
        # Format: 2026-02-20T05:15:00+00:00|1.17542|1.17542|1.17542|1.17542
        components = bar_part.split('|')
        if len(components) == 5:
            bar_ts_str, o, h, l, c = components
            try:
                bar_ts = datetime.fromisoformat(bar_ts_str)
                bars.append((bar_ts, float(o), float(h), float(l), float(c)))
            except Exception:
                continue
    
    return ts, dmi_plus, bars


def parse_bar_metrics_line(line: str) -> Tuple[Optional[datetime], Optional[dict]]:
    """
    Parse [BAR_METRICS] line to extract timestamp and metrics.
    
    Returns (timestamp, {close, atr, pred, conf, mama_diff, dmi_plus, ...})
    """
    match = re.search(r'\[BAR_METRICS\]\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\+\d{2}:\d{2})\s+close=([^\s]+)\s+atr=([^\s]+)\s+pred=([^\s]+)\s+conf=([^\s]+)\s+.*?mama_diff=([^\s]+)\s+dmi_plus=([^\s]+)', line)
    if not match:
        return None, None
    
    ts_str, close_str, atr_str, pred_str, conf_str, mama_diff_str, dmi_plus_str = match.groups()
    
    try:
        ts = datetime.fromisoformat(ts_str)
        return ts, {
            'close': float(close_str),
            'atr': float(atr_str),
            'pred': int(pred_str),
            'conf': float(conf_str),
            'mama_diff': float(mama_diff_str),
            'dmi_plus': float(dmi_plus_str),
        }
    except Exception as e:
        return None, None


def load_replay_dmi_snapshots(log_path: str, start_dt: datetime, end_dt: datetime) -> Dict[datetime, Tuple[float, List[Tuple]]]:
    """
    Load [DMI_PARITY] snapshots from replay log.
    
    Returns dict: {bar_timestamp: (dmi_plus, [(30m_ts, o, h, l, c), ...])}
    """
    snapshots = {}
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if '[DMI_PARITY]' not in line:
                continue
            
            ts, dmi_plus, bars = parse_dmi_parity_line(line)
            if ts and bars and start_dt <= ts <= end_dt:
                snapshots[ts] = (dmi_plus, bars)
    
    return snapshots


def load_live_bar_metrics(log_path: str, start_dt: datetime, end_dt: datetime) -> Dict[datetime, dict]:
    """
    Load [BAR_METRICS] from live log.
    
    Returns dict: {bar_timestamp: {metrics}}
    """
    from datetime import timedelta
    
    metrics = {}
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if '[BAR_METRICS]' not in line:
                continue
            
            ts, bar_metrics = parse_bar_metrics_line(line)
            if ts and bar_metrics:
                # Live logs use ts_init (bar close), shift -15min to get bar open for alignment
                ts_open = ts - timedelta(minutes=15)
                if start_dt <= ts_open <= end_dt:
                    metrics[ts_open] = bar_metrics
    
    return metrics


def compare_snapshots(replay_snapshots: Dict, live_metrics: Dict):
    """
    Compare replay 30m OHLC snapshots with live metrics.
    """
    common_times = sorted(set(replay_snapshots.keys()) & set(live_metrics.keys()))
    
    print(f"\n{'='*80}")
    print(f"30m OHLC Snapshot Comparison")
    print(f"{'='*80}")
    print(f"Common timestamps: {len(common_times)}")
    print(f"Replay snapshots: {len(replay_snapshots)}")
    print(f"Live metrics: {len(live_metrics)}")
    print()
    
    if not common_times:
        print("No common timestamps found.")
        return
    
    # Analyze DMI divergence and 30m bar consistency
    print(f"\n{'='*80}")
    print(f"DMI Divergence and 30m Bar Analysis")
    print(f"{'='*80}\n")
    
    dmi_diffs = []
    unique_30m_bars = {}  # Track unique 30m bars and their OHLC
    
    for ts in common_times:
        replay_dmi, replay_bars = replay_snapshots.get(ts, (None, None))
        live_met = live_metrics.get(ts)
        
        if not replay_bars or not live_met:
            continue
        
        # Get latest 30m bar from replay
        latest_30m = replay_bars[-1] if replay_bars else None
        
        if not latest_30m:
            continue
        
        bar_30m_ts, o, h, l, c = latest_30m
        
        # Track unique 30m bars
        if bar_30m_ts not in unique_30m_bars:
            unique_30m_bars[bar_30m_ts] = (o, h, l, c)
        
        # Calculate DMI difference
        live_dmi = live_met['dmi_plus']
        dmi_diff = abs(live_dmi - replay_dmi)
        dmi_diffs.append((ts, live_dmi, replay_dmi, dmi_diff))
        
        print(f"{ts.strftime('%Y-%m-%d %H:%M:%S%z')}:")
        print(f"  Latest 30m bar: {bar_30m_ts.strftime('%Y-%m-%d %H:%M:%S%z')}")
        print(f"  30m OHLC: O={o:.5f} H={h:.5f} L={l:.5f} C={c:.5f}")
        print(f"  DMI+ Live:{live_dmi:.4f} Replay:{replay_dmi:.4f} Diff:{dmi_diff:.4f}")
        print(f"  Num 30m bars in snapshot: {len(replay_bars)}")
        print()
    
    # Summary statistics
    if dmi_diffs:
        print(f"\n{'='*80}")
        print(f"Summary Statistics")
        print(f"{'='*80}\n")
        
        dmi_diff_values = [d[3] for d in dmi_diffs]
        print(f"DMI+ Differences:")
        print(f"  Mean: {sum(dmi_diff_values)/len(dmi_diff_values):.6f}")
        print(f"  Min:  {min(dmi_diff_values):.6f}")
        print(f"  Max:  {max(dmi_diff_values):.6f}")
        print(f"  Median: {sorted(dmi_diff_values)[len(dmi_diff_values)//2]:.6f}")
        
        # Top 5 divergences
        top_5 = sorted(dmi_diffs, key=lambda x: x[3], reverse=True)[:5]
        print(f"\nTop 5 DMI+ Divergences:")
        for ts, live_dmi, replay_dmi, diff in top_5:
            print(f"  {ts.strftime('%Y-%m-%d %H:%M:%S%z')}: Live={live_dmi:.4f} Replay={replay_dmi:.4f} Diff={diff:.4f}")
        
        print(f"\nUnique 30m bars tracked: {len(unique_30m_bars)}")
        print(f"15m bars compared: {len(common_times)}")
        print(f"Expected 30m bars (15m bars / 2): {len(common_times) // 2}")



def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Compare 30m OHLC snapshots between live and replay')
    parser.add_argument('--live', required=True, help='Path to live strategy log')
    parser.add_argument('--replay', required=True, help='Path to replay log with DMI_PARITY lines')
    parser.add_argument('--start', required=True, help='Start datetime (YYYY-MM-DD HH:MM)')
    parser.add_argument('--end', required=True, help='End datetime (YYYY-MM-DD HH:MM)')
    
    args = parser.parse_args()
    
    # Parse datetimes
    start_dt = datetime.strptime(args.start, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(args.end, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
    
    print(f"Loading replay DMI snapshots from {args.replay}...")
    replay_snapshots = load_replay_dmi_snapshots(args.replay, start_dt, end_dt)
    print(f"  Loaded {len(replay_snapshots)} snapshots")
    if replay_snapshots:
        first_key = sorted(replay_snapshots.keys())[0]
        last_key = sorted(replay_snapshots.keys())[-1]
        print(f"  Range: {first_key} to {last_key}")
    
    print(f"Loading live bar metrics from {args.live}...")
    live_metrics = load_live_bar_metrics(args.live, start_dt, end_dt)
    print(f"  Loaded {len(live_metrics)} metrics")
    if live_metrics:
        first_key = sorted(live_metrics.keys())[0]
        last_key = sorted(live_metrics.keys())[-1]
        print(f"  Range: {first_key} to {last_key}")
    
    compare_snapshots(replay_snapshots, live_metrics)


if __name__ == '__main__':
    main()
