"""Quick debug script to trace what the PatternDetector is doing."""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_confirmed_rebreak.core.market_types import Bar
from v7_confirmed_rebreak.core.pattern_detector import PatternDetector

DATA_DIR = Path(r"C:\nautilus0\data\1m_csv")


def main():
    df = pd.read_csv(DATA_DIR / "xauusd_1m_tick.csv", parse_dates=["timestamp"])
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[df["tick_count"] > 0].reset_index(drop=True)
    df = df[df["timestamp"] >= "2023-01-01"].reset_index(drop=True)

    print(f"Bars: {len(df):,}")

    det = PatternDetector(
        pivot_window=30,
        imbalance_window=3,
        divergence_threshold=0.5,
        max_pullback_bars=60,
        min_pullback_bars=3,
        atr_period=60,
        min_bar_ticks=50,
    )

    signal_count = 0
    pivot_changes_h = 0
    pivot_changes_l = 0
    process_high_calls = 0
    close_above_pivot = 0
    pending_set = 0

    for i in range(min(len(df), 50_000)):
        row = df.iloc[i]
        bar = Bar(
            timestamp=row["timestamp"].to_pydatetime(),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            tick_count=int(row["tick_count"]),
            buy_volume=row["buy_volume"],
            sell_volume=row["sell_volume"],
        )

        signals = det.process_bar(bar)
        if signals:
            signal_count += len(signals)

        if det._pivot.high_changed:
            pivot_changes_h += 1
        if det._pivot.low_changed:
            pivot_changes_l += 1

        # Check if close is above pivot high
        ph = det._pivot.current_pivot_high
        if ph is not None and bar.close > ph:
            close_above_pivot += 1

        if det._pending_high_break is not None:
            pending_set += 1

    # Check state at end
    hs = det._high_state
    ls = det._low_state
    print(f"\nAfter 50k bars:")
    print(f"  pivot_high_changes: {pivot_changes_h}")
    print(f"  pivot_low_changes: {pivot_changes_l}")
    print(f"  bars where close > pivot_high: {close_above_pivot}")
    print(f"  bars with pending_high_break set: {pending_set}")
    print(f"  signals: {signal_count}")
    print(f"  current pivot_high: {det._pivot.current_pivot_high}")
    print(f"  current pivot_low: {det._pivot.current_pivot_low}")
    if hs:
        print(f"  high_state: first_break_idx={hs.first_break_idx}, "
              f"pulled_back={hs.pulled_back}, done={hs.done}")
    if ls:
        print(f"  low_state: first_break_idx={ls.first_break_idx}, "
              f"pulled_back={ls.pulled_back}, done={ls.done}")

    # Manually test: find a bar where close crosses above a known pivot
    print(f"\n  Sample: first 5 pivot high changes and whether close > level soon after:")
    det2 = PatternDetector(
        pivot_window=30, imbalance_window=3, divergence_threshold=0.5,
        max_pullback_bars=60, min_pullback_bars=3, atr_period=60, min_bar_ticks=0,
    )
    ph_changes = []
    for i in range(min(len(df), 10_000)):
        row = df.iloc[i]
        bar = Bar(
            timestamp=row["timestamp"].to_pydatetime(),
            open=row["open"], high=row["high"], low=row["low"], close=row["close"],
            tick_count=int(row["tick_count"]),
            buy_volume=row["buy_volume"], sell_volume=row["sell_volume"],
        )
        det2.process_bar(bar)
        if det2._pivot.high_changed:
            ph_changes.append((i, det2._pivot.current_pivot_high, bar.close))
            if len(ph_changes) <= 3:
                print(f"    bar {i}: new pivot_high={det2._pivot.current_pivot_high:.3f}, close={bar.close:.3f}")

    # Now check: after each pivot change, how soon does close cross above?
    if ph_changes:
        for idx, (bar_i, level, _) in enumerate(ph_changes[:5]):
            for j in range(bar_i+1, min(bar_i+100, len(df))):
                c = df.iloc[j]["close"]
                if c > level:
                    print(f"    pivot at bar {bar_i} (level={level:.3f}): "
                          f"crossed at bar {j} (gap={j-bar_i}), close={c:.3f}")
                    break


if __name__ == "__main__":
    main()
