"""
Deep module: Computes pivot highs and lows from bar arrays.

Two modes:
  1. batch_centered() -- for backtest: centered rolling max/min with shift delay
  2. rolling_centered() -- for live: same math on a rolling buffer

Both return forward-filled pivot_high / pivot_low arrays that can be passed
directly to PatternDetector.process_bar().
"""
import numpy as np
import pandas as pd


def batch_centered(highs: np.ndarray, lows: np.ndarray,
                   window: int, shift: int) -> tuple:
    """Pre-compute centered pivots with shift delay over full dataset.

    Uses centered rolling max/min (window bars each side), then forward-fills
    detected pivots with a `shift`-bar delay to simulate causal visibility.

    This is the proven research methodology from engine_v2.

    Args:
        highs: array of bar highs
        lows: array of bar lows
        window: bars each side for centered rolling (e.g. 60)
        shift: bars of delay before pivot becomes visible (e.g. 3)

    Returns:
        (pivot_high, pivot_low): forward-filled arrays, NaN where no pivot yet
    """
    n = len(highs)
    full_win = 2 * window + 1

    roll_max = pd.Series(highs).rolling(full_win, center=True).max().values
    roll_min = pd.Series(lows).rolling(full_win, center=True).min().values

    is_ph = (highs == roll_max) & ~np.isnan(roll_max)
    is_pl = (lows == roll_min) & ~np.isnan(roll_min)

    pivot_high = np.full(n, np.nan)
    pivot_low = np.full(n, np.nan)
    last_ph = np.nan
    last_pl = np.nan

    for i in range(n):
        lookback = i - shift
        if lookback >= 0:
            if is_ph[lookback]:
                last_ph = highs[lookback]
            if is_pl[lookback]:
                last_pl = lows[lookback]
        pivot_high[i] = last_ph
        pivot_low[i] = last_pl

    return pivot_high, pivot_low


def rolling_centered(highs: np.ndarray, lows: np.ndarray,
                     window: int, shift: int) -> tuple:
    """Compute centered pivots on a rolling buffer (for live trading).

    Same math as batch_centered but operates on the current buffer contents.
    Called once per new bar with the full buffer arrays.

    Returns:
        (pivot_high, pivot_low): forward-filled arrays over buffer length
    """
    # Same implementation -- centered rolling works on any array
    return batch_centered(highs, lows, window, shift)
