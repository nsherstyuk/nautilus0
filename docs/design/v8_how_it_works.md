# How V8 Works — Simple Explanation

## The Core Idea

V8 trades **confirmed rebreaks** of pivot levels. It waits for price to:

1. Break through an important level
2. Pull back below/above it
3. Break through **again**

The key insight: the first breakout often fails (trapped traders), but when price comes back and breaks through a second time with the right order flow, it tends to follow through.

## Step by Step

### 1. Find Pivot Levels

V8 computes **pivot highs** and **pivot lows** using a centered rolling window (default: 120 bars = 2 hours on 1-min data).

- **Pivot High**: the highest price in a 240-bar window (120 bars each side). This is a resistance level — price struggled to go higher.
- **Pivot Low**: the lowest price in the same window. This is a support level — price struggled to go lower.

These are the "important levels" the strategy watches.

### 2. Watch for a Breakout with Divergence

When price closes above a pivot high (or below a pivot low), V8 measures the **buy ratio** over the next 3 bars:

```
buy_ratio = buy_volume / (buy_volume + sell_volume)
```

V8 looks for **divergence** — the order flow disagrees with the price move:

- Price breaks **above** pivot high, but buy_ratio < 0.50 (sellers dominating) → divergent
- Price breaks **below** pivot low, but buy_ratio > 0.50 (buyers dominating) → divergent

A divergent breakout means the move is likely to fail. The strategy starts tracking it.

If the breakout is NOT divergent (order flow agrees with direction), V8 ignores it — that breakout is more likely to hold.

### 3. Wait for Pullback

After a divergent breakout, V8 waits for price to pull back through the level:

- Broke above pivot high → wait for price to drop back below it
- Broke below pivot low → wait for price to rise back above it

This confirms the initial breakout was indeed a false move.

### 4. Enter on Rebreak (with Confirmation)

Now V8 waits for price to break through the level **again**, but this time checks that order flow has **resolved** — the divergence is gone:

- **Long entry**: price breaks above pivot high again AND buy_ratio ≥ 0.50 (buyers now agree)
- **Short entry**: price breaks below pivot low again AND buy_ratio ≤ 0.50 (sellers now agree)

The rebreak must happen within a time window (3–60 bars after the first break). Too soon and the pullback wasn't real; too late and the level is stale.

### 5. Trade Management

Once in a trade:

- **Time stop**: exit after 60 bars (1 hour). The edge is short-lived.
- **Catastrophe SL**: 10× ATR away from entry. Only hit in extreme moves — protects against tail risk.
- **No take-profit**: the time stop handles exit. Research showed fixed TP doesn't improve results.

## Visual Example (Short Trade)

```
Price
  │
  │     ╭──╮                              First breakout BELOW pivot low
  │  ───┤  ├──── Pivot Low ────           (sellers push through)
  │     │  │  ╭──╮                        BUT buy_ratio > 0.50 → DIVERGENT
  │     ╰──╯  │  │    ╭──╮               (buyers still active = likely to fail)
  │           ╰──╯    │  │
  │   pullback ↑      │  │               Price pulls back above pivot low
  │   back above      │  │               (confirming false breakout)
  │                ───┤  ├──── 
  │                   │  │                Price breaks below AGAIN
  │                   ╰──╯  ← ENTER SHORT (buy_ratio ≤ 0.50 now = sellers confirmed)
  │                      │
  │                      ╰── hold 60 bars → EXIT
  time →
```

## Why It Works

The pattern exploits **trapped traders**:

1. First breakout catches traders entering in the breakout direction
2. Pullback stops them out or makes them nervous
3. Second breakout has cleaner flow — the weak hands are already gone
4. Divergence filter ensures we only track breakouts that are likely to fail first

## Key Parameters

| Parameter | Default | What It Does |
|-----------|---------|-------------|
| `pivot_window` | 120 | Bars each side for pivot detection. Larger = bigger, more significant levels |
| `confirm_bars` | 3 | Delay before a pivot becomes visible (avoids premature signals) |
| `imbalance_window` | 3 | Bars after breakout to measure buy/sell ratio |
| `divergence_threshold` | 0.50 | Buy ratio threshold for divergence detection |
| `min_pullback_bars` | 3 | Minimum bars between first break and rebreak |
| `max_pullback_bars` | 60 | Maximum bars — after this the setup expires |
| `max_hold_bars` | 60 | Time stop — exit after N bars |
| `sl_atr_multiple` | 10.0 | Catastrophe stop-loss distance (10× ATR) |
| `min_bar_ticks` | varies | Min tick count per bar to trust volume data |

## Current Deployment

| Pair | Status | Notes |
|------|--------|-------|
| XAUUSD | Paper trading | Main earner. Gold has strong volume signal |
| EURUSD | Paper trading | Smaller moves at 20k size |
| USDJPY | Paper trading | Same — verifying mechanics |
| GBPUSD | Paper trading | Walk-forward validated, recently added |

All pairs use `pivot_window=120` (validated by walk-forward optimization across 6 rolling windows, 32/32 profitable pair-years).
