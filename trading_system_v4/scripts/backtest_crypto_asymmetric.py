"""
Asymmetric Entry/Exit Threshold Investigation
==============================================
Baseline:  Enter AND exit at 70th percentile (symmetric)
New idea:  Enter at 70th percentile, exit at 40th percentile (asymmetric)

The gap between entry and exit thresholds creates a "hold zone" that
reduces whipsaws — price must fall meaningfully before we exit.

Tests:
  1. Symmetric baseline (40d/70th both ways)
  2. Sweep of exit thresholds (10th to 65th) with fixed 70th entry
  3. Sweep of entry thresholds (65th to 85th) with fixed 40th exit
  4. Full 2D grid: entry_pct x exit_pct
  5. Year-by-year breakdown for best candidates
  6. Trade count / cost comparison vs baseline
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd


LOOKBACK = 40
COST_BPS = 20          # 0.20% per side (IBKR PAXOS realistic)
VOL_TARGET = 0.40
VOL_LOOKBACK = 20


# ─── Data ───────────────────────────────────────────────────────────────────

def load_btc():
    closes = pd.read_parquet("trading_system_v4/data/crypto_daily.parquet")
    col = "BTC-USD" if "BTC-USD" in closes.columns else "BTC"
    return closes[col].dropna()


# ─── Asymmetric Signal ──────────────────────────────────────────────────────

def sig_asymmetric(price, lookback=40, entry_pct=70, exit_pct=40):
    """
    State machine signal:
      - When FLAT: go LONG if price > rolling entry_pct percentile
      - When LONG: stay LONG if price > rolling exit_pct percentile
                   go FLAT if price <= rolling exit_pct percentile

    This creates hysteresis — the exit threshold is lower than entry,
    so price must drop further to trigger an exit than it rose to trigger entry.
    """
    entry_level = price.rolling(lookback).quantile(entry_pct / 100)
    exit_level  = price.rolling(lookback).quantile(exit_pct  / 100)

    signal = pd.Series(0.0, index=price.index)
    in_position = False

    for i in range(len(price)):
        if np.isnan(entry_level.iloc[i]) or np.isnan(exit_level.iloc[i]):
            signal.iloc[i] = 0.0
            continue

        if not in_position:
            if price.iloc[i] > entry_level.iloc[i]:
                in_position = True
        else:
            if price.iloc[i] <= exit_level.iloc[i]:
                in_position = False

        signal.iloc[i] = 1.0 if in_position else 0.0

    return signal, entry_level, exit_level


# ─── Backtest ────────────────────────────────────────────────────────────────

def bt(price, signal, cost_bps=COST_BPS, vol_target=VOL_TARGET):
    """Vectorized vol-targeted backtest."""
    ret = price.pct_change()
    vol = ret.rolling(VOL_LOOKBACK).std() * np.sqrt(365)

    # Position (delayed by 1 day)
    pos = (signal * vol_target / vol.clip(lower=0.01)).clip(0, 1.0)
    pos_delayed = pos.shift(1)

    pnl = pos_delayed * ret
    turnover = pos_delayed.diff().abs()
    costs = turnover * (cost_bps / 10000)
    net = (pnl - costs).fillna(0)

    # Trim to where signal starts
    first = signal[signal > 0].index
    if len(first) == 0:
        return {"sr": np.nan, "ret": 0, "dd": 0, "trades": 0, "cost": 0,
                "time_in": 0, "yearly": pd.Series(dtype=float)}
    net = net[first[0]:]
    costs_trim = costs[first[0]:]
    sig_trim = signal[first[0]:]

    if len(net) < 100:
        return {"sr": np.nan, "ret": 0, "dd": 0, "trades": 0, "cost": 0,
                "time_in": 0, "yearly": pd.Series(dtype=float)}

    equity = (1 + net).cumprod()
    n_yr = len(net) / 365
    total = equity.iloc[-1] - 1
    ann_ret = (1 + total) ** (1 / n_yr) - 1 if (n_yr > 0 and total > -1) else -1.0
    ann_vol = net.std() * np.sqrt(365)
    sr = ann_ret / ann_vol if ann_vol > 0 else 0
    dd = (equity / equity.cummax() - 1).min()

    # Trades = significant position changes (>2% of max position)
    sig_changes = (sig_trim.diff().abs() > 0.01).sum()

    yearly = net.resample("YE").sum()

    return {
        "sr": sr,
        "ret": ann_ret,
        "dd": dd,
        "trades": int(sig_changes),
        "cost": costs_trim.sum() * 10000 / (cost_bps + 1e-9),  # normalized
        "total_cost_bps": costs_trim.sum(),
        "time_in": (sig_trim > 0).mean(),
        "yearly": yearly,
    }


def bt_period(price, signal, start, end, cost_bps=COST_BPS):
    """Backtest over a sub-period."""
    p = price[start:end]
    s = signal[start:end]
    if len(p) < 50:
        return {"sr": np.nan, "ret": 0}
    return bt(p, s, cost_bps)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  ASYMMETRIC ENTRY/EXIT THRESHOLD INVESTIGATION")
    print("=" * 72)

    btc = load_btc()
    print(f"  BTC: {len(btc)} days, {btc.index[0].date()} → {btc.index[-1].date()}\n")

    # ──────────────────────────────────────────────────────────────────
    # 1. Baseline: symmetric 70th/70th
    # ──────────────────────────────────────────────────────────────────
    print("─" * 72)
    print("  BASELINE: Symmetric 70th entry / 70th exit")
    print("─" * 72)

    sig_base, _, _ = sig_asymmetric(btc, LOOKBACK, entry_pct=70, exit_pct=70)
    r_base = bt(btc, sig_base)

    oos_base = bt(btc["2022":], sig_base["2022":])

    print(f"  Full period:  SR={r_base['sr']:+.2f}  Ret={r_base['ret']:+.1%}  "
          f"DD={r_base['dd']:.1%}  Trades={r_base['trades']}  "
          f"TimeIn={r_base['time_in']:.0%}")
    print(f"  OOS (2022+):  SR={oos_base['sr']:+.2f}  Ret={oos_base['ret']:+.1%}  "
          f"DD={oos_base['dd']:.1%}  Trades={oos_base['trades']}")

    # ──────────────────────────────────────────────────────────────────
    # 2. Sweep exit threshold (entry fixed at 70th)
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SWEEP: Exit threshold (entry fixed at 70th percentile)")
    print("─" * 72)
    print(f"\n  {'Exit%':>6s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>7s}  {'TimeIn':>7s}  {'OOS_SR':>7s}  {'2025_SR':>8s}")
    print(f"  {'─'*6}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*8}")

    exit_results = {}
    for ep in [65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 10]:
        sig, _, _ = sig_asymmetric(btc, LOOKBACK, entry_pct=70, exit_pct=ep)
        r = bt(btc, sig)
        oos = bt(btc["2022":], sig["2022":])
        r25 = bt(btc["2025":], sig["2025":])
        exit_results[ep] = r

        sym_marker = " ← baseline" if ep == 70 else ""
        ep_marker  = " ◄ selected" if ep == 40 else ""
        print(f"  {ep:>5d}%  {r['sr']:>+5.2f}  {r['ret']:>+7.1%}  {r['dd']:>+7.1%}  "
              f"{r['trades']:>6d}  {r['time_in']:>6.0%}  {oos['sr']:>+6.2f}  "
              f"{r25['sr']:>+7.2f}{ep_marker}{sym_marker}")

    # ──────────────────────────────────────────────────────────────────
    # 3. Sweep entry threshold (exit fixed at 40th)
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SWEEP: Entry threshold (exit fixed at 40th percentile)")
    print("─" * 72)
    print(f"\n  {'Entry%':>7s}  {'SR':>6s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>7s}  {'TimeIn':>7s}  {'OOS_SR':>7s}  {'2025_SR':>8s}")
    print(f"  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*8}")

    for ep in [60, 65, 70, 75, 80, 85]:
        sig, _, _ = sig_asymmetric(btc, LOOKBACK, entry_pct=ep, exit_pct=40)
        r = bt(btc, sig)
        oos = bt(btc["2022":], sig["2022":])
        r25 = bt(btc["2025":], sig["2025":])

        marker = " ◄ selected" if ep == 70 else ""
        print(f"  {ep:>6d}%  {r['sr']:>+5.2f}  {r['ret']:>+7.1%}  {r['dd']:>+7.1%}  "
              f"{r['trades']:>6d}  {r['time_in']:>6.0%}  {oos['sr']:>+6.2f}  "
              f"{r25['sr']:>+7.2f}{marker}")

    # ──────────────────────────────────────────────────────────────────
    # 4. 2D Grid: entry x exit
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  2D GRID: Sharpe ratio (entry% rows × exit% columns)")
    print("─" * 72)

    entry_pcts = [60, 65, 70, 75, 80]
    exit_pcts  = [20, 30, 40, 50, 60, 65]

    # Header
    print(f"\n  {'Entry\\Exit':>10s}", end="")
    for ex in exit_pcts:
        print(f"  {ex:>5d}%", end="")
    print()
    print(f"  {'─'*10}", end="")
    for _ in exit_pcts:
        print(f"  {'─'*6}", end="")
    print()

    best_sr = -99
    best_combo = (70, 40)

    for en in entry_pcts:
        print(f"  {en:>9d}%", end="")
        for ex in exit_pcts:
            if ex >= en:
                print(f"  {'  --':>6s}", end="")
                continue
            sig, _, _ = sig_asymmetric(btc, LOOKBACK, entry_pct=en, exit_pct=ex)
            r = bt(btc, sig)
            sr_val = r["sr"] if not np.isnan(r["sr"]) else -99
            marker = "*" if (en == 70 and ex == 40) else " "
            print(f"  {sr_val:>+5.2f}{marker}", end="")
            if sr_val > best_sr:
                best_sr = sr_val
                best_combo = (en, ex)
        print()

    print(f"\n  Best in grid: entry={best_combo[0]}%, exit={best_combo[1]}%, SR={best_sr:+.2f}")

    # ──────────────────────────────────────────────────────────────────
    # 5. Year-by-year: baseline vs best asymmetric
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print(f"  YEAR-BY-YEAR: Symmetric (70/70) vs Asymmetric (70/40) vs Best ({best_combo[0]}/{best_combo[1]})")
    print("─" * 72)

    sig_asym, _, _ = sig_asymmetric(btc, LOOKBACK, entry_pct=70, exit_pct=40)
    sig_best, _, _ = sig_asymmetric(btc, LOOKBACK,
                                    entry_pct=best_combo[0], exit_pct=best_combo[1])

    r_asym = bt(btc, sig_asym)
    r_best = bt(btc, sig_best)

    all_years = sorted(set(
        list(r_base["yearly"].index.year) +
        list(r_asym["yearly"].index.year) +
        list(r_best["yearly"].index.year)
    ))

    print(f"\n  {'Year':>5s}  {'Symm 70/70':>11s}  {'Asym 70/40':>11s}  "
          f"{'Best {}/{}'.format(*best_combo):>12s}  {'Better?':>8s}")
    print(f"  {'─'*5}  {'─'*11}  {'─'*11}  {'─'*12}  {'─'*8}")

    for yr in all_years:
        def get_yr(yrl, yr):
            matches = [v for d, v in yrl.items() if d.year == yr]
            return matches[0] if matches else np.nan

        b = get_yr(r_base["yearly"], yr)
        a = get_yr(r_asym["yearly"], yr)
        bst = get_yr(r_best["yearly"], yr)

        if np.isnan(b) and np.isnan(a):
            continue

        def fmt(v):
            return f"{v:>+9.1%}" if not np.isnan(v) else "        --"

        # Flag years where asymmetric wins vs baseline
        better = ""
        if not np.isnan(b) and not np.isnan(a):
            if a > b + 0.02:
                better = "ASYM ✓"
            elif b > a + 0.02:
                better = "SYM  ✓"
            else:
                better = "~tie"

        print(f"  {yr:>5d}  {fmt(b)}  {fmt(a)}  {fmt(bst):>11s}  {better:>8s}")

    # ──────────────────────────────────────────────────────────────────
    # 6. Summary comparison
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SUMMARY COMPARISON")
    print("─" * 72)

    oos_asym = bt(btc["2022":], sig_asym["2022":])
    oos_best = bt(btc["2022":], sig_best["2022":])
    r25_base = bt(btc["2025":], sig_base["2025":])
    r25_asym = bt(btc["2025":], sig_asym["2025":])
    r25_best = bt(btc["2025":], sig_best["2025":])

    def row(label, r_f, r_oos, r_25):
        print(f"  {label:22s}  "
              f"SR={r_f['sr']:>+5.2f}  Ret={r_f['ret']:>+6.1%}  DD={r_f['dd']:>+6.1%}  "
              f"Tr={r_f['trades']:>4d}  "
              f"OOS_SR={r_oos['sr']:>+5.2f}  "
              f"2025_SR={r_25['sr']:>+5.2f}")

    print(f"\n  {'Label':22s}  {'Full SR':>8s}  {'AnnRet':>8s}  {'MaxDD':>8s}  "
          f"{'Trades':>6s}  {'OOS SR':>8s}  {'2025 SR':>8s}")
    print(f"  {'─'*22}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*8}  {'─'*8}")
    row("Symmetric 70/70", r_base, oos_base, r25_base)
    row("Asymmetric 70/40", r_asym, oos_asym, r25_asym)
    row(f"Best  {best_combo[0]}/{best_combo[1]}", r_best, oos_best, r25_best)

    # Trade reduction
    print(f"\n  Trade reduction (vs baseline):")
    print(f"    Symmetric 70/70:   {r_base['trades']:>4d} signal flips")
    print(f"    Asymmetric 70/40:  {r_asym['trades']:>4d} signal flips  "
          f"(-{(1 - r_asym['trades'] / max(r_base['trades'], 1)):.0%} fewer)")
    print(f"    Best {best_combo[0]}/{best_combo[1]}:       {r_best['trades']:>4d} signal flips  "
          f"(-{(1 - r_best['trades'] / max(r_base['trades'], 1)):.0%} fewer)")

    # ──────────────────────────────────────────────────────────────────
    # 7. What does the current signal state look like?
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  CURRENT SIGNAL STATE (last 10 days)")
    print("─" * 72)

    entry_lvl = btc.rolling(LOOKBACK).quantile(0.70)
    exit_lvl  = btc.rolling(LOOKBACK).quantile(0.40)

    print(f"\n  {'Date':12s}  {'BTC Price':>10s}  {'Entry(70th)':>12s}  "
          f"{'Exit(40th)':>11s}  {'State':>8s}")
    print(f"  {'─'*12}  {'─'*10}  {'─'*12}  {'─'*11}  {'─'*8}")

    sig_cur = sig_asym.iloc[-10:]
    for dt in btc.index[-10:]:
        p = btc.loc[dt]
        en = entry_lvl.loc[dt]
        ex = exit_lvl.loc[dt]
        s = sig_asym.loc[dt]
        state = "LONG" if s > 0 else "FLAT"
        zone = ""
        if s == 0 and p > ex:
            zone = " (hold zone)"
        print(f"  {str(dt.date()):12s}  ${p:>9,.0f}  ${en:>11,.0f}  ${ex:>10,.0f}  "
              f"{state:>8s}{zone}")


if __name__ == "__main__":
    main()
