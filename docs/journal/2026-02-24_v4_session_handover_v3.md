# Session 5 Handover — 2026-02-24 Evening (v3)

## Executive Summary

**Market-making on EURUSD at tick level has NO robust edge.**

After exhaustive testing with a properly-implemented resting-order market-making
simulator across 1,346 trading days (2020–2025), the full backtest result is:

| Metric         | Value     |
|----------------|-----------|
| Total PnL      | **-1,105 pips** |
| Avg per day    | -0.82 pips |
| Daily WR       | 54.2%     |
| Sharpe ratio   | **-0.20** |
| Profit factor  | 0.96      |
| Trade WR       | 61.3%     |
| Avg trade      | -0.01 pips |
| Max drawdown   | -5,311 pips |
| Total fills    | 355,768 (264/day) |
| Round trips    | 177,446   |

This is **before** any real-world costs (commissions, wider effective spreads, etc).

---

## What Was Tested This Session

### 1. Mean Reversion Signals (Bar Level) → DEAD END
- File: `trading_system_v4/scripts/test_mean_reversion_edge.py`
- Tested 11 mean-reversion signals across 15min/1h/4h timeframes.
- Finding: Signals have 3–5pp WR edge above random but ALL produce **negative PnL**.
  Price reverts 97%+ of the time within 6 bars, but SL gets hit before TP.
- Profit factors ranged 0.69 to 0.96 — no viable edge.

### 2. Bar-Level Market-Making Simulation → LOOKED PROMISING
- Same file, second section.
- Simplified MM model on 15min bars showed attractive numbers:
  - London 3.0p half-spread: 2,830 trades, +5,433 pips, WR 81.7%, Sharpe 2.87
  - London 2.0p: 4,504 trades, +5,900 pips, WR 87.6%, Sharpe 2.76
- **These numbers were unrealistic** — bar-level simulation cannot properly model fill
  dynamics. Fills happen at bar boundaries, ignoring intra-bar price paths.

### 3. Tick-Level MM v1 → CRITICAL BUGS
- File: `trading_system_v4/scripts/test_mm_tick_level.py`
- First attempt at tick-level validation had fatal fill logic bug:
  - Checked fills against same tick quotes were placed on (impossible by definition)
  - Kill switch too aggressive (173k kills, 0 fills)
- Abandoned in favor of v2.

### 4. Tick-Level MM v2 → COMPREHENSIVE TEST, NO EDGE
- File: `trading_system_v4/scripts/test_mm_tick_v2.py`
- Results file: `trading_system_v4/scripts/mm_v2_results.txt`
- Properly models resting limit orders that persist until filled or refreshed.
- Full 7-phase parameter sweep across 1,346 trading days.

---

## Detailed Phase Results

### Phase 1: Base Case (hs=2.0p, rq=50, London 7-17, 100 random days)
| PnL   | Avg/day | DailyWR | Sharpe | PF   |
|-------|---------|---------|--------|------|
| +420p | +5.12p  | 59.8%   | 1.63   | 1.33 |

This looked promising on a 100-day random sample, but was **misleading** 
— see Phase 7 full backtest below.

### Phase 2: Half-Spread Sweep (80 random days each)
| Half-Spread | Fills/day | PnL    | DailyWR | Sharpe | PF   |
|-------------|-----------|--------|---------|--------|------|
| 0.5p        | 7,130     | +3,952 | 32.8%   | 1.73   | 1.41 |
| 1.0p        | 1,544     | +324   | 49.3%   | 0.63   | 1.12 |
| 1.5p        | 542       | -532   | 41.8%   | -1.70  | 0.72 |
| **2.0p**    | **228**   | **-65**| **61.2%**| **-0.28**| **0.95** |
| **2.5p**    | **93**    |**+522**| **53.7%**| **3.29**| **1.88** |
| 3.0p        | 39        | +222   | 49.3%   | 1.59   | 1.30 |
| 5.0p        | 2         | +245   | 26.9%   | 2.09   | 1.70 |

Best: hs=2.5p (Sharpe 3.29). BUT on 80 random days only. Very different from
base case (same hs=2.0p but 100 days → Sharpe 1.63 vs 80 days → Sharpe -0.28).
**High variance across samples = noise, not signal.**

### Phase 3: Requote Interval Sweep (hs=2.0p, 80 random days)
| Requote | Fills/day | PnL    | DailyWR | Sharpe | PF   |
|---------|-----------|--------|---------|--------|------|
| 10      | 22        | -441   | 43.3%   | -4.01  | 0.48 |
| 25      | 114       | +30    | 56.7%   | 0.18   | 1.03 |
| 50      | 228       | -65    | 61.2%   | -0.28  | 0.95 |
| 100     | 311       | +378   | 61.2%   | 1.37   | 1.28 |
| **200** | **347**   |**+525**| **64.2%**| **1.66**| **1.34** |
| 500     | 350       | +433   | 59.7%   | 1.38   | 1.26 |

Longer requote intervals are better (orders rest longer, more time to fill).
But again, 80-day sample variance is very high.

### Phase 4: Session Comparison (hs=2.0p, 80 random days)
| Session         | Fills/day | PnL    | DailyWR | Sharpe | PF   |
|-----------------|-----------|--------|---------|--------|------|
| London 7-17     | 228       | -65    | 61.2%   | -0.28  | 0.95 |
| London AM 7-12  | 93        | +419   | 61.2%   | 2.68   | 1.61 |
| NY overlap 13-17| 112       | -254   | 44.8%   | -1.64  | 0.75 |
| Extended 7-21   | 268       | +653   | 65.7%   | 2.29   | 1.57 |
| **Asian 0-7**   | **46**    |**+479**| **64.2%**| **4.87**| **2.36** |

Asian session looks best (Sharpe 4.87) but only 46 fills/day with high kill rate.
NY overlap is worst — high adverse selection during news-heavy hours.

### Phase 5: Fill Probability Sensitivity (hs=2.0p)
| Fill Prob | PnL    | DailyWR | Sharpe | PF   |
|-----------|--------|---------|--------|------|
| 0.3       | -998   | 37.3%   | -4.41  | 0.40 |
| 0.5       | -127   | 58.2%   | -0.54  | 0.90 |
| 0.7       | -65    | 61.2%   | -0.28  | 0.95 |
| 0.9       | -7     | 56.7%   | -0.03  | 0.99 |
| 1.0       | +221   | 62.7%   | 0.95   | 1.20 |

**Critical finding:** At fp=0.7 (our default, modeling adverse selection),
the strategy loses money. Only with fp=1.0 (unrealistic 100% fill rate)
does it marginally profit. Real-world fill rates are closer to 0.3–0.5
at retail level, which means **heavy losses**.

### Phase 6: Inventory Limits & Skew (hs=2.0p)
| MaxInv | Skew | PnL  | DailyWR | Sharpe | PF   |
|--------|------|------|---------|--------|------|
| 1      | 0.0  | -54  | 53.7%   | -0.34  | 0.95 |
| 1      | 0.5  | -2   | 59.7%   | -0.01  | 1.00 |
| 2      | 0.3  | +111 | 58.2%   | 0.50   | 1.10 |
| 3      | 0.3  | -65  | 61.2%   | -0.28  | 0.95 |
| 3      | 0.5  | +141 | 58.2%   | 0.73   | 1.15 |
| 5      | 0.3  | -10  | 61.2%   | -0.04  | 0.99 |

All variations hover near zero. No robust edge from inventory management.

### Phase 7: FULL BACKTEST — ALL 1,346 days (2020–2025)
| Metric     | Value       |
|------------|-------------|
| PnL        | **-1,105p** |
| Avg/day    | -0.82p      |
| DailyWR    | 54.2%       |
| Sharpe     | **-0.20**   |
| PF         | 0.96        |
| TradeWR    | 61.3%       |
| Avg trade  | -0.01p      |
| MaxDD      | -5,311p     |
| Fills      | 355,768     |
| Round trips| 177,446     |

**The full backtest conclusively shows no edge.** Negative PnL, negative Sharpe,
and massive drawdown — BEFORE real-world costs.

---

## Key Insights & Why Market-Making Doesn't Work Here

### 1. Adverse Selection Kills Profits
When the fill probability < 1.0, the strategy loses money. This is because in
real markets, limit orders get filled disproportionately when the market is
moving AGAINST you (informed traders lift your resting quotes). The 0.7 fill
probability in the simulation is actually GENEROUS — real retail execution would
be worse.

### 2. Sample Variance Creates False Signals
The same parameters (hs=2.0p) gave Sharpe +1.63 on 100 random days but -0.28
on a different 80-day sample. Mean reversion-type results on small samples are
unreliable. The full 1,346-day backtest tells the truth: Sharpe -0.20.

### 3. Bar-Level Simulations Are Dangerously Optimistic
The bar-level MM simulation showed Sharpe 2.87 for London session. The tick-level
simulation (which properly models order resting, fills, and adverse selection) shows
the real result: Sharpe -0.20. Bar-level backtests create phantom profits by
assuming perfect fills at bar close prices.

### 4. Spread Capture ≈ Zero After Adverse Selection
The average trade PnL is -0.01 pips — essentially zero. The 2.0-pip half-spread
(4.0 pip round-trip capture) is entirely consumed by adverse selection losses.
Winning 61.3% of trades is not enough when the losers are larger than winners.

---

## Cumulative Dead Ends (Sessions 1–5)

| Approach | Sessions | Verdict |
|----------|----------|---------|
| EURUSD 15min direction prediction (TA) | 1-4 | AUC 0.519, zero edge |
| HTF (4h) features for 15min prediction | 2-3 | No improvement |
| Tick microstructure features (62 features) | 4 | AUC 0.519, zero edge |
| Multi-horizon sweeps (1min–1h) | 4 | All zero edge |
| Session breakout strategies | 3-4 | Zero edge |
| Mean reversion signals (11 variants) | 5 | Negative PnL always |
| Bar-level market-making | 5 | Unrealistic fills |
| **Tick-level market-making** | **5** | **-1,105p on full backtest** |

---

## EURUSD Trading Reality Check

After 5 sessions of systematic testing:

1. **Direction prediction is impossible** with TA/microstructure features on any
   timeframe from 1min to 4h. AUC never exceeds 0.52.

2. **Mean reversion signals exist statistically** (97% revert within 6 bars) but
   are **not tradeable** — stop losses trigger before take profits.

3. **Market-making appears profitable on simplified models** but fails at tick
   level due to adverse selection. The spread is consumed by informed flow.

4. **EURUSD is extremely efficient at retail-accessible timeframes.** The median
   spread of 0.2-0.3 pips and tick-to-tick moves of 0.08 pips leave essentially
   zero extractable edge for a non-HFT participant.

### What Would Actually Be Needed (Beyond Our Reach):
- **Sub-millisecond execution** with co-located servers (not available via IBKR)
- **Order book depth data** (not available in FX spot)
- **Cross-venue arbitrage** between ECNs (requires institutional infrastructure)
- **Flow data / positioning data** (proprietary, not publicly available)

---

## Files Created/Modified This Session

| File | Purpose |
|------|---------|
| `trading_system_v4/scripts/test_mean_reversion_edge.py` | Mean reversion + bar-level MM test |
| `trading_system_v4/scripts/test_mm_tick_level.py` | Tick-level MM v1 (buggy, abandoned) |
| `trading_system_v4/scripts/debug_mm_fills.py` | Tick data analysis diagnostic |
| `trading_system_v4/scripts/run_mm_quick.py` | v1 runner (obsolete) |
| `trading_system_v4/scripts/test_mm_tick_v2.py` | Tick-level MM v2 (comprehensive) |
| `trading_system_v4/scripts/mm_v2_results.txt` | Full v2 simulation output |
| `trading_system_v4/SESSION_HANDOVER_2026-02-24_v3.md` | This document |

## Recommendations for Next Session

If continuing EURUSD exploration:
- Consider **completely different instruments** (crypto, less liquid FX pairs)
  where market microstructure is less efficient.
- Or shift to **longer horizons** (daily/weekly) where fundamental factors might
  provide edge that TA cannot capture.
- Or explore **event-driven strategies** around scheduled macro releases where
  volatility clustering is more predictable.

The EURUSD 15min–intraday space is conclusively exhausted for edge at retail.
