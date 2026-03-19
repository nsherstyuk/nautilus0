"""
research_range_quality_multi.py -- Multi-instrument range quality validation.

Validates the key findings from XAUUSD range quality research on EURUSD:
  1. NR4 inversion (narrow ranges hurt, not help)
  2. POC misalignment signal (breakouts against volume consensus work better)
  3. VWAP misalignment signal
  4. Intra-range volatility Goldilocks effect
  5. Touch count (fewer = better)

Uses 1-min tick-aggregated bars with full volume data.

Usage:
  python -m v5_xauusd_orb.research_range_quality_multi [instrument]
  e.g.: python -m v5_xauusd_orb.research_range_quality_multi eurusd
"""
from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Reuse infrastructure from backtest_1m
sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
OOS_START = dt.date(2021, 1, 1)

# ── Instrument-specific config ──────────────────────────────────────────

INSTRUMENT_CONFIG = {
    'xauusd': {
        'file': ROOT / 'data' / '1m_csv' / 'xauusd_1m_tick.csv',
        'pip_size': 0.01,       # gold moves in $0.01 increments
        'spread_cost': 0.10,    # typical spread per side
        'label': 'XAUUSD (Gold)',
    },
    'eurusd': {
        'file': ROOT / 'data' / '1m_csv' / 'eurusd_1m_tick.csv',
        'pip_size': 0.00001,    # 5-digit FX pricing
        'spread_cost': 0.00003, # ~0.3 pips typical spread
        'label': 'EURUSD',
    },
}


# ── Data Loading ────────────────────────────────────────────────────────

def load_1m_bars(path):
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp').sort_index()
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['weekday'] = pd.to_datetime(df['date']).dt.weekday
    return df


# ── Trade simulation (simplified, matches backtest_1m logic) ────────────

def run_backtest(df, skip_wednesdays=True, rr=2.0,
                 min_range_pct=0.05, max_range_pct=2.0):
    """Simplified ORB backtest returning trades with range metadata."""
    trades = []

    for day, day_df in df.groupby('date'):
        wd = day_df['weekday'].iloc[0]
        if wd >= 5:
            continue
        if skip_wednesdays and wd == 2:
            continue

        # Asian range
        asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
        if len(asian) < 10:
            continue

        rh = asian['high'].max()
        rl = asian['low'].min()
        rs = rh - rl
        if rs <= 0:
            continue
        mid = (rh + rl) / 2
        rpct = rs / mid * 100
        if rpct < min_range_pct or rpct > max_range_pct:
            continue

        tp_long = rh + rr * rs
        tp_short = rl - rr * rs

        # Trade window
        window = day_df[(day_df['hour'] >= 8) & (day_df['hour'] < 16)]
        if len(window) < 5:
            continue

        # Find entry
        direction = None
        entry_idx = None
        entry_px = None

        for i, (ts, bar) in enumerate(window.iterrows()):
            hs = bar['avg_spread'] / 2

            if bar['high'] >= rh:
                direction = 'LONG'
                entry_idx = i
                if bar['open'] >= rh:
                    entry_px = bar['open'] + hs
                else:
                    entry_px = rh + hs
                break
            elif bar['low'] <= rl:
                direction = 'SHORT'
                entry_idx = i
                if bar['open'] <= rl:
                    entry_px = bar['open'] - hs
                else:
                    entry_px = rl - hs
                break

        if direction is None:
            continue

        # Monitor
        sl = rl if direction == 'LONG' else rh
        tp = tp_long if direction == 'LONG' else tp_short
        entry_ts = window.index[entry_idx]
        exit_px = None
        exit_type = 'EOD'

        monitor = window.iloc[entry_idx + 1:]
        for ts, bar in monitor.iterrows():
            hs = bar['avg_spread'] / 2
            if direction == 'LONG':
                if bar['low'] <= sl:
                    exit_px = sl - hs
                    exit_type = 'SL'
                    break
                if bar['high'] >= tp:
                    exit_px = tp - hs
                    exit_type = 'TP'
                    break
            else:
                if bar['high'] >= sl:
                    exit_px = sl + hs
                    exit_type = 'SL'
                    break
                if bar['low'] <= tp:
                    exit_px = tp + hs
                    exit_type = 'TP'
                    break

        if exit_px is None:
            last_bar = window.iloc[-1]
            hs = last_bar['avg_spread'] / 2
            exit_px = last_bar['close'] - hs if direction == 'LONG' else last_bar['close'] + hs

        pnl = (exit_px - entry_px) if direction == 'LONG' else (entry_px - exit_px)

        trades.append({
            'date': day,
            'direction': direction,
            'entry_price': entry_px,
            'exit_price': exit_px,
            'exit_type': exit_type,
            'pnl': pnl,
            'range_high': rh,
            'range_low': rl,
            'range_size': rs,
        })

    return trades


# ── Range Quality Features ──────────────────────────────────────────────

def compute_features(day_df, rh, rl, rs, recent_ranges):
    asian = day_df[(day_df['hour'] >= 0) & (day_df['hour'] < 6)]
    if len(asian) < 10:
        return None

    features = {}

    # NR4
    if len(recent_ranges) >= 4:
        features['nr4'] = 1 if rs <= min(recent_ranges[-4:]) else 0
    else:
        features['nr4'] = np.nan

    # Range vs recent
    if len(recent_ranges) >= 5:
        features['range_vs_5d'] = rs / np.mean(recent_ranges[-5:])
    else:
        features['range_vs_5d'] = np.nan

    # POC position — adaptive bin size
    if 'total_volume' in asian.columns and asian['total_volume'].sum() > 0:
        bin_size = rs / 20  # 20 bins across range regardless of instrument
        if bin_size > 0:
            bins = np.arange(rl, rh + bin_size, bin_size)
            if len(bins) >= 2:
                typical_price = (asian['high'] + asian['low'] + asian['close']) / 3
                vol = asian['total_volume'].values
                bin_idx = np.digitize(typical_price.values, bins) - 1
                bin_idx = np.clip(bin_idx, 0, len(bins) - 2)
                bin_vol = np.zeros(len(bins) - 1)
                for i, v in zip(bin_idx, vol):
                    bin_vol[i] += v
                poc_bin = np.argmax(bin_vol)
                poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2
                features['poc_position'] = (poc_price - rl) / rs
            else:
                features['poc_position'] = 0.5
        else:
            features['poc_position'] = 0.5
    else:
        features['poc_position'] = 0.5

    # VWAP position
    if 'total_volume' in asian.columns and asian['total_volume'].sum() > 0:
        typical = (asian['high'] + asian['low'] + asian['close']) / 3
        vol = asian['total_volume']
        vwap = (typical * vol).sum() / vol.sum()
        features['vwap_position'] = (vwap - rl) / rs if rs > 0 else 0.5
    else:
        features['vwap_position'] = 0.5

    # Intra-range volatility
    returns = asian['close'].pct_change().dropna()
    if len(returns) > 5:
        intra_vol = returns.std()
        range_pct = rs / ((rh + rl) / 2)
        features['intra_vol'] = intra_vol / range_pct if range_pct > 0 else 0
    else:
        features['intra_vol'] = np.nan

    # Touch count — 5% of range as touch zone
    touch_zone = 0.05 * rs
    touches_high = np.sum(asian['high'].values >= (rh - touch_zone))
    touches_low = np.sum(asian['low'].values <= (rl + touch_zone))
    features['total_touches'] = touches_high + touches_low

    return features


# ── Stats ───────────────────────────────────────────────────────────────

def calc_stats(trades, label=''):
    if not trades:
        return {'label': label, 'n': 0, 'sharpe': 0, 'pf': 0, 'wr': 0,
                'mean': 0, 'total': 0, 'max_dd': 0}
    pnl = pd.Series([t['pnl'] for t in trades])
    n = len(pnl)
    mean = pnl.mean()
    std = pnl.std()
    sharpe = mean / std * np.sqrt(252) if std > 0 else 0
    wr = (pnl > 0).mean() * 100
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else float('inf')
    eq = pnl.cumsum()
    dd = (eq - eq.cummax()).min()
    return {
        'label': label, 'n': n, 'sharpe': round(sharpe, 2),
        'pf': round(pf, 2), 'wr': round(wr, 1),
        'mean': mean, 'total': round(pnl.sum(), 4),
        'max_dd': round(dd, 4),
    }


def fmt_stats(s):
    if s['n'] == 0:
        return f"  {s['label']:>35}: NO TRADES"
    return (f"  {s['label']:>35}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
            f"PF {s['pf']:>5.2f} | WR {s['wr']:>5.1f}% | Mean {s['mean']:>+10.6f} | "
            f"Total {s['total']:>+12.4f}")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    instrument = sys.argv[1].lower() if len(sys.argv) > 1 else 'eurusd'

    if instrument not in INSTRUMENT_CONFIG:
        print(f"Unknown instrument: {instrument}")
        print(f"Available: {list(INSTRUMENT_CONFIG.keys())}")
        return

    cfg = INSTRUMENT_CONFIG[instrument]
    print(f"{'='*110}")
    print(f"  RANGE QUALITY VALIDATION: {cfg['label']}")
    print(f"{'='*110}")

    df = load_1m_bars(cfg['file'])
    print(f"Loaded {len(df):,} 1-min bars ({df.index.min().date()} to {df.index.max().date()})")

    trades = run_backtest(df)
    print(f"Total trades: {len(trades)}")

    s_all = calc_stats(trades, 'ALL')
    s_oos = calc_stats([t for t in trades if t['date'] >= OOS_START], 'OOS')
    print(fmt_stats(s_all))
    print(fmt_stats(s_oos))

    # Enrich with features
    by_date = {d: g for d, g in df.groupby('date')}
    all_dates = sorted(by_date.keys())
    range_by_date = {}
    for d in all_dates:
        dd = by_date[d]
        asian = dd[(dd['hour'] >= 0) & (dd['hour'] < 6)]
        if len(asian) >= 10:
            rh = asian['high'].max()
            rl = asian['low'].min()
            rs = rh - rl
            if rs > 0:
                range_by_date[d] = rs

    enriched = []
    for t in trades:
        day_df = by_date.get(t['date'])
        if day_df is None:
            continue
        recent = [range_by_date[d] for d in sorted(range_by_date.keys()) if d < t['date']]
        features = compute_features(day_df, t['range_high'], t['range_low'], t['range_size'], recent)
        if features is None:
            continue
        enriched.append({**t, **features})

    print(f"Enriched {len(enriched)} trades")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 1: NR4 FILTER
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 1: NR4 FILTER (XAUUSD finding: NR4 days are WORSE)")
    print("=" * 110)

    nr4_trades = [e for e in enriched if e.get('nr4') == 1]
    non_nr4 = [e for e in enriched if e.get('nr4') == 0]

    if len(nr4_trades) >= 5:
        print(fmt_stats(calc_stats(nr4_trades, 'NR4 days')))
        print(fmt_stats(calc_stats(non_nr4, 'Non-NR4 days')))
        print(fmt_stats(calc_stats([e for e in nr4_trades if e['date'] >= OOS_START], 'NR4 OOS')))
        print(fmt_stats(calc_stats([e for e in non_nr4 if e['date'] >= OOS_START], 'Non-NR4 OOS')))

        nr4_conf = calc_stats(nr4_trades)['sharpe'] < calc_stats(non_nr4)['sharpe']
        nr4_oos_conf = (calc_stats([e for e in nr4_trades if e['date'] >= OOS_START])['sharpe'] <
                        calc_stats([e for e in non_nr4 if e['date'] >= OOS_START])['sharpe'])
        print(f"\n  XAUUSD pattern confirmed (IS)? {'YES' if nr4_conf else 'NO'}")
        print(f"  XAUUSD pattern confirmed (OOS)? {'YES' if nr4_oos_conf else 'NO'}")
    else:
        print(f"  Insufficient NR4 trades: {len(nr4_trades)}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 2: POC DIRECTIONAL ALIGNMENT
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 2: POC DIRECTIONAL ALIGNMENT (XAUUSD finding: misaligned is BETTER)")
    print("=" * 110)

    aligned = [e for e in enriched
               if (e['direction'] == 'LONG' and e.get('poc_position', 0.5) > 0.5) or
                  (e['direction'] == 'SHORT' and e.get('poc_position', 0.5) < 0.5)]
    misaligned = [e for e in enriched
                  if (e['direction'] == 'LONG' and e.get('poc_position', 0.5) <= 0.5) or
                     (e['direction'] == 'SHORT' and e.get('poc_position', 0.5) >= 0.5)]

    print(fmt_stats(calc_stats(aligned, 'POC Aligned')))
    print(fmt_stats(calc_stats(misaligned, 'POC Misaligned')))
    print(fmt_stats(calc_stats([e for e in aligned if e['date'] >= OOS_START], 'Aligned OOS')))
    print(fmt_stats(calc_stats([e for e in misaligned if e['date'] >= OOS_START], 'Misaligned OOS')))

    poc_conf = calc_stats(misaligned)['sharpe'] > calc_stats(aligned)['sharpe']
    poc_oos_conf = (calc_stats([e for e in misaligned if e['date'] >= OOS_START])['sharpe'] >
                    calc_stats([e for e in aligned if e['date'] >= OOS_START])['sharpe'])
    print(f"\n  XAUUSD pattern confirmed (IS)? {'YES' if poc_conf else 'NO'}")
    print(f"  XAUUSD pattern confirmed (OOS)? {'YES' if poc_oos_conf else 'NO'}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 3: VWAP DIRECTIONAL ALIGNMENT
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 3: VWAP DIRECTIONAL ALIGNMENT (XAUUSD finding: misaligned is BETTER)")
    print("=" * 110)

    v_aligned = [e for e in enriched
                 if (e['direction'] == 'LONG' and e.get('vwap_position', 0.5) > 0.5) or
                    (e['direction'] == 'SHORT' and e.get('vwap_position', 0.5) < 0.5)]
    v_misaligned = [e for e in enriched
                    if (e['direction'] == 'LONG' and e.get('vwap_position', 0.5) <= 0.5) or
                       (e['direction'] == 'SHORT' and e.get('vwap_position', 0.5) >= 0.5)]

    print(fmt_stats(calc_stats(v_aligned, 'VWAP Aligned')))
    print(fmt_stats(calc_stats(v_misaligned, 'VWAP Misaligned')))
    print(fmt_stats(calc_stats([e for e in v_aligned if e['date'] >= OOS_START], 'VWAP Aligned OOS')))
    print(fmt_stats(calc_stats([e for e in v_misaligned if e['date'] >= OOS_START], 'VWAP Misaligned OOS')))

    vwap_conf = calc_stats(v_misaligned)['sharpe'] > calc_stats(v_aligned)['sharpe']
    print(f"\n  XAUUSD pattern confirmed (IS)? {'YES' if vwap_conf else 'NO'}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 4: INTRA-RANGE VOLATILITY QUINTILES
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 4: INTRA-RANGE VOLATILITY (XAUUSD finding: Q2-Q3 best, extremes bad)")
    print("=" * 110)

    vol_vals = [(e, e['intra_vol']) for e in enriched if not np.isnan(e.get('intra_vol', np.nan))]
    vol_vals.sort(key=lambda x: x[1])
    n = len(vol_vals)
    if n >= 25:
        q_size = n // 5
        for qi in range(5):
            start = qi * q_size
            end = start + q_size if qi < 4 else n
            subset = vol_vals[start:end]
            trades_q = [e[0] for e in subset]
            feat_vals = [e[1] for e in subset]
            oos_q = [e for e in trades_q if e['date'] >= OOS_START]
            s = calc_stats(trades_q)
            so = calc_stats(oos_q)
            label = f"Q{qi+1} ({min(feat_vals):.4f}-{max(feat_vals):.4f})"
            print(f"  {label:>35}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
                  f"WR {s['wr']:>5.1f}% | OOS Sh {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 5: TOUCH COUNT QUINTILES
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 5: TOUCH COUNT (XAUUSD finding: fewer touches = better)")
    print("=" * 110)

    touch_vals = [(e, e['total_touches']) for e in enriched]
    touch_vals.sort(key=lambda x: x[1])
    n = len(touch_vals)
    if n >= 25:
        q_size = n // 5
        for qi in range(5):
            start = qi * q_size
            end = start + q_size if qi < 4 else n
            subset = touch_vals[start:end]
            trades_q = [e[0] for e in subset]
            feat_vals = [e[1] for e in subset]
            oos_q = [e for e in trades_q if e['date'] >= OOS_START]
            s = calc_stats(trades_q)
            so = calc_stats(oos_q)
            label = f"Q{qi+1} ({min(feat_vals):.0f}-{max(feat_vals):.0f})"
            print(f"  {label:>35}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
                  f"WR {s['wr']:>5.1f}% | OOS Sh {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # TEST 6: RANGE SIZE QUINTILES (range_vs_5d)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("  TEST 6: RANGE SIZE vs 5d AVG (XAUUSD finding: Q1 worst, Q5 best)")
    print("=" * 110)

    rv_vals = [(e, e['range_vs_5d']) for e in enriched if not np.isnan(e.get('range_vs_5d', np.nan))]
    rv_vals.sort(key=lambda x: x[1])
    n = len(rv_vals)
    if n >= 25:
        q_size = n // 5
        for qi in range(5):
            start = qi * q_size
            end = start + q_size if qi < 4 else n
            subset = rv_vals[start:end]
            trades_q = [e[0] for e in subset]
            feat_vals = [e[1] for e in subset]
            oos_q = [e for e in trades_q if e['date'] >= OOS_START]
            s = calc_stats(trades_q)
            so = calc_stats(oos_q)
            label = f"Q{qi+1} ({min(feat_vals):.3f}-{max(feat_vals):.3f})"
            print(f"  {label:>35}: N={s['n']:>5} | Sh {s['sharpe']:>6.2f} | "
                  f"WR {s['wr']:>5.1f}% | OOS Sh {so['sharpe']:>6.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print(f"  SUMMARY: {cfg['label']}")
    print("=" * 110)
    print(f"\n  Finding confirmation matrix:")
    print(f"  {'Finding':>35} | {'XAUUSD':>8} | {cfg['label']:>8}")
    print(f"  {'-'*35}-+-{'-'*8}-+-{'-'*8}")

    if len(nr4_trades) >= 5:
        nr4_s = calc_stats(nr4_trades)['sharpe']
        non_nr4_s = calc_stats(non_nr4)['sharpe']
        print(f"  {'NR4 worse than Non-NR4':>35} | {'YES':>8} | {'YES' if nr4_s < non_nr4_s else 'NO':>8}")

    if aligned and misaligned:
        al_s = calc_stats(aligned)['sharpe']
        mis_s = calc_stats(misaligned)['sharpe']
        print(f"  {'POC Misaligned > Aligned':>35} | {'YES':>8} | {'YES' if mis_s > al_s else 'NO':>8}")

    if v_aligned and v_misaligned:
        val_s = calc_stats(v_aligned)['sharpe']
        vmis_s = calc_stats(v_misaligned)['sharpe']
        print(f"  {'VWAP Misaligned > Aligned':>35} | {'YES':>8} | {'YES' if vmis_s > val_s else 'NO':>8}")

    print(f"\n{'='*110}")
    print("  DONE")
    print("=" * 110)


if __name__ == "__main__":
    main()
