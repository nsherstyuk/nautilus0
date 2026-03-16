"""Session-filtered backtest + reverse signal test for Claude's requests."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v8_confirmed_rebreak.backtest.runner import BacktestRunner
from v8_confirmed_rebreak.config.strategy_config import StrategyConfig


def sharpe(pnls):
    arr = np.array(pnls)
    if len(arr) < 5 or arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(252))


def session_analysis():
    cfg = StrategyConfig(
        instrument="XAUUSD",
        pivot_window=60, confirm_bars=3, sl_atr_multiple=10.0,
        max_hold_bars=60, min_bar_ticks=75, spread_cost=0.3,
    )
    runner = BacktestRunner(
        data_path="c:/nautilus0/data/1m_csv/xauusd_1m_tick.csv",
        config=cfg, start_date="2023-01-01",
    )
    trades = runner.run()

    sessions = {
        "Asian (23:00-08:00 UTC)": lambda t: t.entry_time.hour >= 23 or t.entry_time.hour < 8,
        "London (08:00-13:00 UTC)": lambda t: 8 <= t.entry_time.hour < 13,
        "NY (13:00-21:00 UTC)": lambda t: 13 <= t.entry_time.hour < 21,
        "Late (21:00-23:00 UTC)": lambda t: 21 <= t.entry_time.hour < 23,
    }

    print("=" * 90)
    print("SESSION-FILTERED BACKTEST (2023+, optimized params)")
    print("=" * 90)
    header = f"{'Session':<30} {'N':>5} {'PnL':>10} {'Avg':>8} {'WR%':>6} {'Sharpe':>7} {'L/S':>10}"
    print(header)
    print("-" * 90)

    for name, filt in sessions.items():
        subset = [t for t in trades if filt(t)]
        if not subset:
            print(f"{name:<30} {'--':>5}")
            continue
        pnls = [t.pnl for t in subset]
        wins = sum(1 for p in pnls if p > 0)
        longs = sum(1 for t in subset if t.direction == "long")
        shorts = len(subset) - longs
        long_pnl = sum(t.pnl for t in subset if t.direction == "long")
        short_pnl = sum(t.pnl for t in subset if t.direction == "short")
        wr = wins / len(subset) * 100
        sh = sharpe(pnls)
        print(f"{name:<30} {len(subset):>5} {sum(pnls):>+10.2f} {np.mean(pnls):>+8.3f} {wr:>6.1f} {sh:>+7.2f} {longs:>4}L/{shorts:>3}S")
        print(f"{'':>30}   Long: {long_pnl:>+8.2f}  Short: {short_pnl:>+8.2f}")

    print("-" * 90)
    pnls_all = [t.pnl for t in trades]
    wins_all = sum(1 for p in pnls_all if p > 0)
    longs_all = sum(1 for t in trades if t.direction == "long")
    shorts_all = len(trades) - longs_all
    wr_all = wins_all / len(trades) * 100
    sh_all = sharpe(pnls_all)
    print(f"{'ALL':<30} {len(trades):>5} {sum(pnls_all):>+10.2f} {np.mean(pnls_all):>+8.3f} {wr_all:>6.1f} {sh_all:>+7.2f} {longs_all:>4}L/{shorts_all:>3}S")

    # Direction breakdown
    print("\n" + "=" * 90)
    print("DIRECTION BREAKDOWN (2023+)")
    print("=" * 90)
    long_trades = [t for t in trades if t.direction == "long"]
    short_trades = [t for t in trades if t.direction == "short"]
    long_pnls = [t.pnl for t in long_trades]
    short_pnls = [t.pnl for t in short_trades]
    long_wins = sum(1 for p in long_pnls if p > 0)
    short_wins = sum(1 for p in short_pnls if p > 0)
    print(f"  LONG:  {len(long_trades):>5} trades, PnL={sum(long_pnls):>+10.2f}, Avg={np.mean(long_pnls):>+7.3f}, WR={long_wins/len(long_trades)*100:.1f}%, Sharpe={sharpe(long_pnls):>+.2f}")
    print(f"  SHORT: {len(short_trades):>5} trades, PnL={sum(short_pnls):>+10.2f}, Avg={np.mean(short_pnls):>+7.3f}, WR={short_wins/len(short_trades)*100:.1f}%, Sharpe={sharpe(short_pnls):>+.2f}")


def reverse_signal_test():
    """Run backtest with INVERTED divergence logic.
    
    Normal: first break divergent (buy_ratio < 0.5 for long) + rebreak matching (>= 0.5)
    Inverted: first break matching + rebreak divergent
    
    If inverted also makes money, the edge is from "trade any rebreak in trending gold"
    and buy_ratio is just noise. If inverted loses, the imbalance classification is real.
    """
    print("\n\n" + "=" * 90)
    print("REVERSE SIGNAL TEST")
    print("Inverted: matching first break + divergent rebreak (OPPOSITE of normal)")
    print("=" * 90)
    _reverse_signal_manual()


def _reverse_signal_manual():
    """Reverse test: invert buy_ratio so divergent becomes matching and vice versa.
    
    We feed (1 - buy_ratio) to the detector. This means:
    - Normal LONG: first break has br < 0.5 (divergent), rebreak has br >= 0.5 (matching)
    - Inverted LONG: first break has br >= 0.5 (was matching, now looks divergent),
                     rebreak has br < 0.5 (was divergent, now looks matching)
    """
    import pandas as pd
    from v8_confirmed_rebreak.core.pattern_detector import PatternDetector
    from v8_confirmed_rebreak.core.pivot_computer import batch_centered

    data_path = "c:/nautilus0/data/1m_csv/xauusd_1m_tick.csv"
    print("  Loading data...")
    df = pd.read_csv(data_path, parse_dates=["timestamp"])
    start_dt = pd.Timestamp("2023-01-01")
    df = df[df["timestamp"] >= start_dt].reset_index(drop=True)
    n = len(df)
    print(f"  {n} bars from {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")

    pw, confirm, hold, sl_mult, min_ticks, spread, imb_w = 60, 3, 60, 10.0, 75, 0.30, 3

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    buy_vols = df["buy_volume"].values
    sell_vols = df["sell_volume"].values
    tick_counts = df["tick_count"].values

    pivot_high, pivot_low = batch_centered(highs, lows, window=pw, shift=confirm)

    detector = PatternDetector(
        imbalance_window=imb_w, divergence_threshold=0.50,
        max_pullback_bars=60, min_pullback_bars=3,
    )

    # Pre-compute ATR
    atr_vals = np.full(n, np.nan)
    for i in range(1, n):
        tr = highs[i] - lows[i]
        atr_vals[i] = tr if np.isnan(atr_vals[i - 1]) else 0.95 * atr_vals[i - 1] + 0.05 * tr

    trades = []
    in_trade = False
    trade_entry_idx = 0
    trade_direction = ""
    entry_price = 0.0
    sl_price = 0.0

    for i in range(2 * pw + imb_w, n - imb_w):
        if in_trade:
            bars_held = i - trade_entry_idx
            if trade_direction == "long" and lows[i] <= sl_price:
                trades.append({"dir": "long", "pnl": sl_price - entry_price - spread, "exit": "SL"})
                in_trade = False
                continue
            elif trade_direction == "short" and highs[i] >= sl_price:
                trades.append({"dir": "short", "pnl": entry_price - sl_price - spread, "exit": "SL"})
                in_trade = False
                continue
            if bars_held >= hold:
                ep = closes[i]
                pnl = (ep - entry_price - spread) if trade_direction == "long" else (entry_price - ep - spread)
                trades.append({"dir": trade_direction, "pnl": pnl, "exit": "TIME"})
                in_trade = False
            continue

        # INVERTED buy_ratio callback: feed (1 - br) to detector
        def get_buy_ratio(start, end, _i=i):
            if end > n or start >= end:
                return float("nan")
            ticks = tick_counts[start:end]
            if min_ticks > 0 and np.any(ticks < min_ticks):
                return float("nan")
            bv = buy_vols[start:end].sum()
            sv = sell_vols[start:end].sum()
            total = bv + sv
            if total == 0:
                return float("nan")
            return 1.0 - (bv / total)  # INVERTED

        ph = pivot_high[i]
        pl = pivot_low[i]

        signal = detector.process_bar(
            close=float(closes[i]), bar_idx=i,
            pivot_high=float(ph) if not np.isnan(ph) else float("nan"),
            pivot_low=float(pl) if not np.isnan(pl) else float("nan"),
            get_buy_ratio=get_buy_ratio,
        )

        if signal is not None:
            direction, gap, buy_ratio = signal
            entry_price = closes[i]
            trade_direction = direction
            trade_entry_idx = i
            atr = atr_vals[i] if not np.isnan(atr_vals[i]) else 1.0
            sl_price = entry_price - sl_mult * atr if direction == "long" else entry_price + sl_mult * atr
            in_trade = True

    _print_reverse_results(trades)


def _print_reverse_results(trades):
    if not trades:
        print("  No trades generated with inverted logic.")
        return

    pnls = [t["pnl"] if isinstance(t, dict) else t.pnl for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = wins / len(trades) * 100
    sh = sharpe(pnls)

    print(f"\n  INVERTED Results:")
    print(f"    Trades:    {len(trades)}")
    print(f"    Total PnL: {sum(pnls):>+.2f}")
    print(f"    Avg/trade: {np.mean(pnls):>+.3f}")
    print(f"    Win Rate:  {wr:.1f}%")
    print(f"    Sharpe:    {sh:>+.2f}")

    # Compare to normal
    print(f"\n  COMPARISON:")
    print(f"    {'Metric':<15} {'Normal':>10} {'Inverted':>10}")
    print(f"    {'-'*35}")
    print(f"    {'Trades':<15} {'973':>10} {len(trades):>10}")
    print(f"    {'Total PnL':<15} {'+$1,871':>10} {f'${sum(pnls):>+.0f}':>10}")
    print(f"    {'Avg/trade':<15} {'+$1.92':>10} {f'${np.mean(pnls):>+.2f}':>10}")
    print(f"    {'Win Rate':<15} {'58.7%':>10} {f'{wr:.1f}%':>10}")
    print(f"    {'Sharpe':<15} {'+3.72':>10} {f'{sh:>+.2f}':>10}")

    # Direction breakdown
    longs = [t for t in trades if (t["dir"] if isinstance(t, dict) else t.direction) == "long"]
    shorts = [t for t in trades if (t["dir"] if isinstance(t, dict) else t.direction) == "short"]
    long_pnl = sum(t["pnl"] if isinstance(t, dict) else t.pnl for t in longs)
    short_pnl = sum(t["pnl"] if isinstance(t, dict) else t.pnl for t in shorts)
    print(f"\n    Long:  {len(longs)} trades, PnL={long_pnl:>+.2f}")
    print(f"    Short: {len(shorts)} trades, PnL={short_pnl:>+.2f}")


if __name__ == "__main__":
    session_analysis()
    reverse_signal_test()
