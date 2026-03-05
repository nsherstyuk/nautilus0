"""
Trailing Stop Overlay Investigation
=====================================
Base strategy: 40d/70th percentile signal (enter when price > 70th pctl)
Overlay:       Trailing stop exits the position early if price drops X% from peak

How it works:
  - Enter when percentile signal fires (price crosses above 70th pctl)
  - Track the highest price seen since entry (the "high water mark")
  - Exit early if price drops > X% from that high water mark
  - Do NOT re-enter until percentile signal fires again fresh

Tests:
  1. Sweep trailing stop %: 5% to 40%
  2. ATR-based trailing stop (dynamic, scales with volatility)
  3. Year-by-year breakdown for key variants
  4. Comparison: baseline vs best trailing stop
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd


LOOKBACK    = 40
ENTRY_PCT   = 70
COST_BPS    = 20
VOL_TARGET  = 0.40
VOL_LOOKBACK = 20


def load_btc():
    closes = pd.read_parquet("trading_system_v4/data/crypto_daily.parquet")
    col = "BTC-USD" if "BTC-USD" in closes.columns else "BTC"
    btc = closes[col].dropna()
    try:
        highs = pd.read_parquet("trading_system_v4/data/crypto_daily_high.parquet")
        hcol = "BTC-USD" if "BTC-USD" in highs.columns else "BTC"
        high = highs[hcol].dropna()
    except Exception:
        high = btc  # fallback: use close as high
    return btc, high


# ─── Signal with trailing stop ───────────────────────────────────────────────

def sig_with_trailing_stop(price, lookback=40, entry_pct=70, trail_pct=None,
                            trail_atr_mult=None, atr=None):
    """
    State machine:
      FLAT  → LONG when price > rolling entry_pct percentile
      LONG  → track high water mark each day
              exit (→ FLAT) if:
                (a) price < rolling entry_pct (original signal exit), OR
                (b) price < high_water_mark * (1 - trail_pct)  [trailing stop]
    
    trail_pct: fixed percent (e.g., 0.15 = 15%)
    trail_atr_mult: use N * ATR as trailing distance (dynamic)
    """
    entry_level = price.rolling(lookback).quantile(entry_pct / 100)

    signal    = pd.Series(0.0, index=price.index)
    stop_level = pd.Series(np.nan, index=price.index)  # for diagnostics

    in_position  = False
    high_water   = 0.0

    for i in range(len(price)):
        if np.isnan(entry_level.iloc[i]):
            signal.iloc[i] = 0.0
            continue

        p = price.iloc[i]

        if not in_position:
            # Try to enter
            if p > entry_level.iloc[i]:
                in_position = True
                high_water  = p
        else:
            # Update high water mark
            if p > high_water:
                high_water = p

            # Compute trailing stop distance
            if trail_pct is not None:
                trail_dist = high_water * trail_pct
            elif trail_atr_mult is not None and atr is not None:
                atr_val = atr.iloc[i] if not np.isnan(atr.iloc[i]) else high_water * 0.03
                trail_dist = trail_atr_mult * atr_val
            else:
                trail_dist = 0.0

            trail_stop = high_water - trail_dist
            stop_level.iloc[i] = trail_stop

            # Exit conditions
            pctl_exit = p < entry_level.iloc[i]
            trail_exit = (trail_dist > 0) and (p < trail_stop)

            if pctl_exit or trail_exit:
                in_position = False
                high_water  = 0.0

        signal.iloc[i] = 1.0 if in_position else 0.0

    return signal, stop_level


# ─── ATR calculation ──────────────────────────────────────────────────────────

def compute_atr(price, period=14):
    """Simple ATR using close-to-close (daily data, no high/low needed)."""
    tr = price.pct_change().abs() * price.shift(1)  # approx true range from closes
    return tr.rolling(period).mean()


# ─── Backtest ────────────────────────────────────────────────────────────────

def bt(price, signal, cost_bps=COST_BPS, vol_target=VOL_TARGET):
    ret = price.pct_change()
    vol = ret.rolling(VOL_LOOKBACK).std() * np.sqrt(365)

    pos = (signal * vol_target / vol.clip(lower=0.01)).clip(0, 1.0)
    pos_delayed = pos.shift(1)

    pnl   = pos_delayed * ret
    costs = pos_delayed.diff().abs() * (cost_bps / 10000)
    net   = (pnl - costs).fillna(0)

    first = signal[signal > 0].index
    if len(first) == 0:
        return {"sr": np.nan, "ret": 0, "dd": 0, "trades": 0, "yearly": pd.Series(dtype=float), "time_in": 0}
    net = net[first[0]:]
    sig_trim = signal[first[0]:]

    if len(net) < 100:
        return {"sr": np.nan, "ret": 0, "dd": 0, "trades": 0, "yearly": pd.Series(dtype=float), "time_in": 0}

    equity  = (1 + net).cumprod()
    n_yr    = len(net) / 365
    total   = equity.iloc[-1] - 1
    ann_ret = (1 + total) ** (1 / n_yr) - 1 if (n_yr > 0 and total > -1) else -1.0
    ann_vol = net.std() * np.sqrt(365)
    sr      = ann_ret / ann_vol if ann_vol > 0 else 0
    dd      = (equity / equity.cummax() - 1).min()
    trades  = int((sig_trim.diff().abs() > 0.01).sum())
    yearly  = net.resample("YE").sum()
    time_in = (sig_trim > 0).mean()

    return {"sr": sr, "ret": ann_ret, "dd": dd, "trades": trades,
            "yearly": yearly, "time_in": time_in, "equity": equity}


def get_yr(yearly, yr):
    matches = [v for d, v in yearly.items() if d.year == yr]
    return matches[0] if matches else np.nan


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  TRAILING STOP OVERLAY INVESTIGATION")
    print("=" * 72)

    btc, _ = load_btc()
    atr = compute_atr(btc, 14)
    print(f"  BTC: {len(btc)} days, {btc.index[0].date()} -> {btc.index[-1].date()}\n")

    # ── Baseline ──────────────────────────────────────────────────────────────
    sig_base, _ = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=None)
    r_base = bt(btc, sig_base)
    oos_base = bt(btc["2022":], sig_base["2022":])
    r25_base = bt(btc["2025":], sig_base["2025":])

    print("─" * 72)
    print("  BASELINE: 40d/70th percentile, NO trailing stop")
    print("─" * 72)
    print(f"  Full: SR={r_base['sr']:+.2f}  Ret={r_base['ret']:+.1%}  DD={r_base['dd']:.1%}  "
          f"Trades={r_base['trades']}  TimeIn={r_base['time_in']:.0%}")
    print(f"  OOS (2022+): SR={oos_base['sr']:+.2f}   2025: SR={r25_base['sr']:+.2f}")

    # ── Sweep fixed trailing stop % ───────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SWEEP: Fixed trailing stop % from peak")
    print("─" * 72)
    print(f"\n  {'Trail%':>7s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>7s}  {'TimeIn':>7s}  {'OOS_SR':>7s}  {'2025_SR':>8s}  {'DD_improv':>10s}")
    print(f"  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  "
          f"{'─'*7}  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*10}")

    trail_results = {}
    for tp in [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40]:
        sig, stp = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=tp)
        r    = bt(btc, sig)
        oos  = bt(btc["2022":], sig["2022":])
        r25  = bt(btc["2025":], sig["2025":])
        trail_results[tp] = r
        dd_improv = r['dd'] - r_base['dd']  # positive = worse, negative = better
        improv_str = f"{dd_improv:+.1%}"
        print(f"  {tp:>6.0%}  {r['sr']:>+5.2f}  {r['ret']:>+7.1%}  {r['dd']:>+7.1%}  "
              f"{r['trades']:>6d}  {r['time_in']:>6.0%}  {oos['sr']:>+6.2f}  "
              f"{r25['sr']:>+7.2f}  {improv_str:>10s}")

    # ── ATR-based trailing stop ───────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  ATR-BASED trailing stop (dynamic — scales with volatility)")
    print("─" * 72)
    print(f"\n  {'ATR mult':>8s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>7s}  {'TimeIn':>7s}  {'OOS_SR':>7s}  {'2025_SR':>8s}")
    print(f"  {'─'*8}  {'─'*6}  {'─'*8}  {'─'*8}  "
          f"{'─'*7}  {'─'*7}  {'─'*7}  {'─'*8}")

    atr_results = {}
    for mult in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0]:
        sig, _ = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT,
                                         trail_atr_mult=mult, atr=atr)
        r   = bt(btc, sig)
        oos = bt(btc["2022":], sig["2022":])
        r25 = bt(btc["2025":], sig["2025":])
        atr_results[mult] = r
        print(f"  {mult:>7.1f}x  {r['sr']:>+5.2f}  {r['ret']:>+7.1%}  {r['dd']:>+7.1%}  "
              f"{r['trades']:>6d}  {r['time_in']:>6.0%}  {oos['sr']:>+6.2f}  "
              f"{r25['sr']:>+7.2f}")

    # ── Year-by-year for key variants ─────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  YEAR-BY-YEAR: Baseline vs best trail variants")
    print("─" * 72)

    # Pick best from fixed and ATR sweeps (by OOS SR)
    candidates = {
        "No stop (base)":   (sig_base, r_base),
        "Trail 15%":        bt(btc, sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=0.15)[0]),
        "Trail 20%":        bt(btc, sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=0.20)[0]),
        "Trail 25%":        bt(btc, sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=0.25)[0]),
        "ATR 3x":           bt(btc, sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_atr_mult=3.0, atr=atr)[0]),
        "ATR 5x":           bt(btc, sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_atr_mult=5.0, atr=atr)[0]),
    }
    # Fix: No stop (base) is a tuple, unpack
    candidates["No stop (base)"] = r_base

    years = list(range(2017, 2026))
    header = f"  {'Year':>5s}" + "".join(f"  {k:>14s}" for k in candidates)
    print(header)
    print("  " + "─" * (7 + 16 * len(candidates)))

    for yr in years:
        row = f"  {yr:>5d}"
        for label, r in candidates.items():
            v = get_yr(r["yearly"], yr)
            if np.isnan(v):
                row += f"  {'--':>14s}"
            else:
                row += f"  {v:>+13.1%}"
        print(row)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SUMMARY")
    print("─" * 72)

    sig_t15, _ = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=0.15)
    sig_t20, _ = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=0.20)
    sig_t25, _ = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_pct=0.25)
    sig_a3,  _ = sig_with_trailing_stop(btc, LOOKBACK, ENTRY_PCT, trail_atr_mult=3.0, atr=atr)

    def summary_row(label, sig, r):
        oos = bt(btc["2022":], sig["2022":])
        r25 = bt(btc["2025":], sig["2025":])
        print(f"  {label:20s}  SR={r['sr']:>+5.2f}  Ret={r['ret']:>+6.1%}  "
              f"DD={r['dd']:>+6.1%}  Tr={r['trades']:>4d}  "
              f"OOS_SR={oos['sr']:>+5.2f}  2025_SR={r25['sr']:>+5.2f}")

    print(f"\n  {'Label':20s}  {'Full SR':>8s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>6s}  {'OOS SR':>8s}  {'2025 SR':>8s}")
    print(f"  {'─'*20}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*8}  {'─'*8}")

    summary_row("No trailing stop",  sig_base, r_base)
    summary_row("Trail 15%",         sig_t15,  bt(btc, sig_t15))
    summary_row("Trail 20%",         sig_t20,  bt(btc, sig_t20))
    summary_row("Trail 25%",         sig_t25,  bt(btc, sig_t25))
    summary_row("ATR 3x trailing",   sig_a3,   bt(btc, sig_a3))

    # ── How would trailing stop look right now? ───────────────────────────────
    print(f"\n{'─'*72}")
    print("  IF YOU WERE LONG RIGHT NOW — where would stops be?")
    print("─" * 72)

    current_price = btc.iloc[-1]
    current_atr   = atr.iloc[-1]
    example_entry = 95_000   # hypothetical recent entry near highs

    print(f"\n  Hypothetical: entered at $95,000, BTC now at ${current_price:,.0f}")
    print(f"  Current 14d ATR: ${current_atr:,.0f}\n")
    print(f"  {'Stop Type':25s}  {'Stop Level':>12s}  {'Distance from entry':>20s}")
    print(f"  {'─'*25}  {'─'*12}  {'─'*20}")
    for tp in [0.10, 0.15, 0.20, 0.25]:
        lvl = example_entry * (1 - tp)
        dist = (lvl - example_entry) / example_entry
        print(f"  {'Trail '+str(int(tp*100))+'% from peak':25s}  ${lvl:>11,.0f}  {dist:>+19.1%}")
    for mult in [2.0, 3.0, 5.0]:
        lvl = example_entry - mult * current_atr
        dist = (lvl - example_entry) / example_entry
        print(f"  {'ATR '+str(mult)+'x trailing':25s}  ${lvl:>11,.0f}  {dist:>+19.1%}")


if __name__ == "__main__":
    main()
