from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    """Pure strategy parameters. Environment-agnostic.

    No file paths, no API keys, no broker settings.
    """
    instrument: str

    # Pivot detection
    pivot_window: int = 60          # bars each side for centered rolling max/min
    confirm_bars: int = 3           # shift delay: bars after pivot before it becomes visible

    # Imbalance classification
    imbalance_window: int = 3       # bars after breakout to measure buy_ratio
    divergence_threshold: float = 0.50

    # Rebreak pattern
    max_pullback_bars: int = 60     # max bars between first break and rebreak
    min_pullback_bars: int = 3      # min bars for pullback to form

    # Trade management
    sl_atr_multiple: float = 10.0   # catastrophe SL distance = N * ATR
    tp_atr_multiple: float = 99.0   # TP distance = M * ATR (99 = disabled)
    max_hold_bars: int = 60         # time stop in bars
    atr_period: int = 60            # bars for ATR computation

    # Volume quality filter
    min_bar_ticks: int = 75         # min tick_count per bar in imbalance window

    # Costs
    spread_cost: float = 0.30       # round-trip spread for XAUUSD
