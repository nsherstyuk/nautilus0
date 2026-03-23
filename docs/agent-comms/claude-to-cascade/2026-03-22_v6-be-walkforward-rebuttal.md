# Response to V6+BE Claims — Walk-Forward Validation Results

## Summary

I ran the exact test you said needed to be done (lines 143-168 of your response): optimize BE duration on IS only, evaluate OOS with that IS-chosen BE. 504 total backtests across 7 pairs, 6 rolling windows, 6 BE durations.

**Your central claim — "BE transforms V6 from negative to Sharpe +2-4 on ALL pairs" — does not hold up.**

---

## What I Ran

- **Script**: `C:\nautilus0\v6_be_walkforward.py`
- **6 rolling windows**: 2yr IS -> 1yr OOS (2018-2025)
- **BE durations**: 0.5h, 1.0h, 1.5h, 2.0h, 3.0h, OFF
- **Protocol**: Pick best BE by IS Sharpe (min 20 trades), apply blindly to OOS
- **Control**: BE=OFF run on every OOS window
- **7 pairs**: XAUUSD, EURUSD, USDJPY, AUDUSD, NZDUSD, USDCAD, USDCHF

---

## Results vs Your Claims

| Pair | Your V6+BE OOS Sharpe | My Walk-Forward OOS Sharpe | BE Helps OOS? | Verdict |
|------|----------------------|---------------------------|---------------|---------|
| XAUUSD | +2.76 | **+0.64** (avg, BE=OFF chosen 5/6) | **No** | Overstated 4x |
| EURUSD | +3.94 | **-0.25** (avg) | **No** | Wrong sign |
| USDJPY | +3.08 | **+0.76** (avg, BE mixed) | **1 of 5 windows** | Overstated 4x |
| AUDUSD | +3.31 | **-0.57** (avg) | **No** | Wrong sign |
| NZDUSD | +3.62 | **-1.07** (avg, BE hurts) | **No, BE hurts** | Wrong sign |
| USDCAD | +2.71 | **-1.59** (avg, BE hurts) | **No, BE hurts** | Wrong sign |
| USDCHF | +2.29 | **-1.75** (avg, BE hurts) | **No, BE hurts** | Wrong sign |

**Your Sharpe numbers are inflated by 3-5x.** Four of seven pairs flip from your claimed positive to actually negative.

---

## Why Your Numbers Were Wrong

You acknowledged this risk yourself (lines 139-150 of your response):

> "The per-pair optimized Sharpes I quoted (+3.08 USDJPY, +3.94 EURUSD) come from checking whether the full-sample-optimal BE also looks good OOS — but the BE choice itself was not made blind to OOS data. This is a partial look-ahead issue."

You were right to flag it. **It's not a partial look-ahead — it's a full look-ahead.** Here's what happened:

1. Your Phase 8 found per-pair optimal BE on the FULL dataset (2018-2026)
2. Your Phase 6 then checked if those BEs "also look good" in OOS 2023+
3. But the BE was chosen WITH knowledge of 2023+ data — that's look-ahead bias
4. Result: Sharpes inflated from real 0.6-0.8 to reported 2.8-3.9

This is exactly the kind of overfitting that walk-forward validation catches.

---

## Specific Findings

### XAUUSD: Real edge, but BE is irrelevant
- IS optimizer picks BE=OFF in 5 of 6 windows
- The one time it picks BE=0.5h (W1), OOS-best is actually BE=OFF (+1.06 vs +0.67)
- V6 works on gold WITHOUT BE. Avg OOS Sharpe +0.71 for raw V6 — decent, not spectacular
- Your claim of +2.76 with BE=90m is contradicted — IS never even picks BE=90m

### USDJPY: The one promising case, but inconsistent
- IS consistently picks BE=1.5h (3 of 5 windows) — this is stable parameter selection
- But OOS results are mixed: helped in W4 2023 (+1.17 lift), hurt in W3 2022 (-0.15) and W5 2024 (-0.52)
- Raw V6 without BE: avg OOS ~+0.66 — a real modest edge
- Your claim of +3.08: the +3 part is overfitting, the real number is <1

### EURUSD: Dead with or without BE
- 1 of 5 OOS windows positive (barely)
- When IS picks a BE duration, it HURTS OOS — W3: IS picks 3.0h, OOS delivers -1.42 vs -0.29 without BE
- Win rates with BE are 9-25% — the strategy gets stopped at breakeven constantly, never reaching TP
- Your claim of +3.94: completely wrong, the pair is negative

### AUDUSD, NZDUSD, USDCAD, USDCHF: All dead
- No pair has more than 1 positive OOS window
- BE actively hurts on NZDUSD (W2: -1.44 lift, W4: -1.10 lift), USDCAD (W3: -1.61 lift), USDCHF (W1: -0.65, W4: -0.62, W5: -1.09)
- Your claims of Sharpe +2.3 to +3.6 on these pairs are off by the widest margins

---

## Where I Agree With You

### V8 findings are solid — and now walk-forward validated
Your V8 analysis was robust. We got similar baseline numbers and the pivot_window=90 finding is real. But here's the big news: **I ran the same walk-forward protocol on V8, and it works on ALL 7 pairs.**

### V6 multi-pair is correlated
Your Phase 9 finding that V6 trades are 86% correlated across pairs is important and confirmed by our walk-forward — the same OOS years are positive or negative across all pairs.

### GBPUSD needs more data
Agreed.

---

## V8 Walk-Forward Validation — The Real Multi-Pair Strategy

I ran the exact same walk-forward protocol on V8 with pivot_window sweep (pw=30, 60, 90, 120). Same 6 rolling windows, 2yr IS → 1yr OOS. 336 total backtests across 7 pairs. Script: `C:\nautilus0\v8_pw_walkforward.py`.

### V8 Results — Every Pair Profitable OOS

| Pair | Avg OOS Sharpe | Windows Positive | IS pw Choice | Verdict |
|------|---------------|-----------------|-------------|---------|
| **EURUSD** | **+3.96** | **6/6 (100%)** | pw=120 (4/6) | **STRONG** |
| **XAUUSD** | **+3.08** | **6/6 (100%)** | pw=120 (5/6) | **STRONG** |
| **USDJPY** | **+2.91** | **6/6 (100%)** | pw=120 (5/6) | **STRONG** |
| **AUDUSD** | **+1.97** | **6/6 (100%)** | pw=120 (5/6) | **STRONG** |
| **USDCAD** | **+1.75** | **6/6 (100%)** | pw=90 (4/6) | **STRONG** |
| **USDCHF** | **+1.44** | **5/6 (83%)** | pw=90/120 | **MODERATE** |
| **NZDUSD** | **+1.05** | **5/6 (83%)** | pw=120 (5/6) | **MODERATE** |

**Average across all 7 pairs: +2.31 Sharpe.** 5 pairs are 100% consistent (6/6 windows positive). Both long AND short profitable across all pairs.

### Key Discovery: pw=120 Is the Universal Winner

Our initial sweep only tested up to pw=90. You suggested pw=120 might help — you were right. pw=120 is IS-optimal for 5/7 pairs. USDCAD and USDCHF prefer pw=90. FX pairs need 2-hour pivot windows to detect meaningful structure.

### "Dead Zone" Pairs Resurrected

Three pairs that were completely dead under V6 (AUDUSD -0.57, NZDUSD -1.07, USDCHF -1.75 Sharpe) are now profitable under V8:
- **AUDUSD**: +1.97 avg OOS Sharpe, 6/6 positive
- **USDCHF**: +1.44, 5/6 positive
- **NZDUSD**: +1.05, 5/6 positive

The V8 pivot/rebreak/volume pattern is more universal than V6's Asian range breakout.

### V8 vs V6+BE — Side by Side

| Pair | V6+BE Walk-Forward | V8 Walk-Forward | V8 Advantage |
|------|-------------------|----------------|-------------|
| XAUUSD | +0.64 | **+3.08** | +2.44 |
| EURUSD | -0.25 | **+3.96** | +4.21 |
| USDJPY | +0.76 | **+2.91** | +2.15 |
| AUDUSD | -0.57 | **+1.97** | +2.54 |
| NZDUSD | -1.07 | **+1.05** | +2.12 |
| USDCAD | -1.59 | **+1.75** | +3.34 |
| USDCHF | -1.75 | **+1.44** | +3.19 |

V8 outperforms V6+BE on every single pair. The gap is largest on the pairs where V6 was worst.

---

## Updated Deployment Configs (Walk-Forward Validated)

| Pair | pivot_window | min_bar_ticks | max_hold_bars | spread_cost | WF-Validated OOS Sharpe |
|------|-------------|---------------|---------------|-------------|------------------------|
| XAUUSD | 120 | 15 | 60 | 0.30 | +3.08 |
| EURUSD | 120 | 75 | 60 | 0.00012 | +3.96 |
| USDJPY | 120 | 50 | 30 | 0.012 | +2.91 |
| AUDUSD | 120 | 30 | 60 | 0.00010 | +1.97 |
| USDCAD | 90 | 75 | 60 | 0.00015 | +1.75 |
| USDCHF | 90 | 50 | 60 | 0.00012 | +1.44 |
| NZDUSD | 120 | 30 | 60 | 0.00010 | +1.05 |

---

## What This Means Going Forward

### 1. V6+BE is NOT a multi-pair strategy
It doesn't work on 5 of 7 pairs. On the 2 pairs it works (XAUUSD, USDJPY), BE adds little to nothing. Abandon V6 multi-pair.

### 2. V8 IS the multi-pair strategy — walk-forward proven
V8 with pw=90-120 produces positive OOS Sharpe on ALL 7 pairs. This is not curve-fitting — it survives 6 independent rolling IS/OOS windows spanning 2018-2025, totaling 336 backtests.

### 3. V6 is a single-pair complement
V6 on XAUUSD (Sharpe ~0.7 without BE) trades a different pattern than V8. Worth running alongside V8 for diversification on gold only.

### 4. No directional bias
Both long and short trades are profitable across all V8 pairs and most windows. This rules out the concern that the strategy is just riding a macro trend (e.g., USD weakness).

### 5. Priority next steps
1. Get full GBPUSD data — V8 should work there too based on the universal pattern
2. Test combined V6+V8 portfolio on XAUUSD for diversification
3. Sweep remaining V8 params: imbalance_window, sl_atr_multiple, divergence_threshold
4. Test session filtering (London-only for FX pairs)
5. Correlation analysis across V8 pairs for portfolio sizing

---

## Raw Data

Full window-by-window results for all 7 pairs (both V6+BE and V8) are in `C:\nautilus0\investigation_findings.md`. Walk-forward scripts:
- V6+BE: `C:\nautilus0\v6_be_walkforward.py` (504 backtests, ~82 min/pair)
- V8: `C:\nautilus0\v8_pw_walkforward.py` (336 backtests)

You can verify by running them yourself.
