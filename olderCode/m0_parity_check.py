import sys
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import os
import argparse
from bar_aggregator import normalize_timeframe, timeframe_to_seconds

from trading_engine_v2 import TradingEngineV2
from streaming_adapter import StreamingEngineAdapter


def build_sample_bars(n: int = 50, start: Optional[datetime] = None, timeframe: Optional[str] = '30s') -> pd.DataFrame:
    """
    Build a deterministic synthetic OHLC dataframe with selected spacing.
    Prices oscillate to exercise turning point logic; even if no signals, parity is still validated.
    """
    start = start or datetime(2025, 1, 1, 10, 0, 0)
    tf = normalize_timeframe(timeframe)
    secs = timeframe_to_seconds(tf)
    times = [start + timedelta(seconds=secs * i) for i in range(n)]

    # Create a simple wave pattern around 1.1000
    base = 1.1000
    vals = []
    for i in range(n):
        # small oscillation with larger swings every few bars
        delta = ((i % 10) - 5) * 0.00002 + (0.0001 if (i % 15 == 0) else 0)
        close = base + delta
        open_ = close - 0.00003
        high = max(open_, close) + 0.00002
        low = min(open_, close) - 0.00002
        vals.append((open_, high, low, close))

    df = pd.DataFrame(vals, columns=["open", "high", "low", "close"], index=pd.to_datetime(times))
    return df


def run_batch(df: pd.DataFrame) -> dict:
    engine = TradingEngineV2(params={})
    # Align with PRD: trailing-only default 5 pips
    engine.trailing_stop_pips = 5
    results = engine.run_trading_system(df, time_filter=None)
    return {
        'turning_points': results.get('turning_points', []),
        'signals': results.get('signals', []),
        'trade_log': results.get('trade_log'),  # DataFrame
        'final_position': results.get('final_position'),
    }


def run_streaming(df: pd.DataFrame) -> dict:
    engine = TradingEngineV2(params={})
    engine.trailing_stop_pips = 5

    adapter = StreamingEngineAdapter(engine, time_filter=None, trailing_stop_pips=5)
    for ts, bar in df.iterrows():
        adapter.on_bar_close(bar, ts)

    trade_df = pd.DataFrame(engine.trade_log) if engine.trade_log else pd.DataFrame()
    return {
        'turning_points': adapter.turning_points,
        'signals': adapter.signals,
        'trade_log': trade_df,
        'final_position': engine.current_position,
    }


def compare_results(batch: dict, streaming: dict) -> list[str]:
    diffs: list[str] = []

    # Compare counts (exact content may differ in ancillary fields, counts should match)
    if len(batch['turning_points']) != len(streaming['turning_points']):
        diffs.append(f"turning_points count mismatch: batch={len(batch['turning_points'])}, streaming={len(streaming['turning_points'])}")

    if len(batch['signals']) != len(streaming['signals']):
        diffs.append(f"signals count mismatch: batch={len(batch['signals'])}, streaming={len(streaming['signals'])}")

    b_trades = 0 if batch['trade_log'] is None or batch['trade_log'].empty else len(batch['trade_log'])
    s_trades = 0 if streaming['trade_log'] is None or streaming['trade_log'].empty else len(streaming['trade_log'])
    if b_trades != s_trades:
        diffs.append(f"trade_log length mismatch: batch={b_trades}, streaming={s_trades}")

    # Final position both None or both not None
    if (batch['final_position'] is None) != (streaming['final_position'] is None):
        diffs.append("final_position presence mismatch (one is None, the other is not)")

    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description="M0 parity check between batch and streaming engines")
    parser.add_argument("-t", "--timeframe", default=os.getenv("BAR_TIMEFRAME", "30s"),
                        help="Bar timeframe: 30s,1m,2m,3m,5m (default from BAR_TIMEFRAME or 30s)")
    args = parser.parse_args()
    tf = normalize_timeframe(args.timeframe)
    df = build_sample_bars(n=60, timeframe=tf)
    print(f"Timeframe: {tf} ({timeframe_to_seconds(tf)}s) for synthetic bars")

    batch = run_batch(df)
    streaming = run_streaming(df)

    diffs = compare_results(batch, streaming)
    if diffs:
        print("M0 PARITY CHECK: FAILED")
        for d in diffs:
            print(" -", d)
        return 1

    print("M0 PARITY CHECK: PASSED")
    print(f"turning_points={len(batch['turning_points'])}, signals={len(batch['signals'])}, trades={0 if batch['trade_log'] is None or batch['trade_log'].empty else len(batch['trade_log'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
