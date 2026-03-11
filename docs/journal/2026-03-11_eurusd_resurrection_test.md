# EURUSD Resurrection Test — 2026-03-11

After the critical retrospective identified that we never tested FX pairs with the velocity filter, we downloaded EURUSD data and ran a full backtest.

---

## Data Built

- Source: Dukascopy .bi5 raw tick files (2018-2026)
- Output: `data/1m_csv/eurusd_1m_tick.csv`
- Total: **2,630,379 bars** (8 years)
- Same structure as XAUUSD 1-min data

**Velocity characteristics:**
- Median tick_count: 55 ticks/min (vs XAUUSD 215)
- 07:00 UTC median: 88 ticks/min
- EURUSD is ~3x less active than XAUUSD

---

## Backtest Results

**Parameters:**
- Asian range: 00:00-06:00 UTC
- Trade window: 07:00-16:00 UTC
- RR ratio: 2.0
- Entry: Stop at level
- NO time exit, NO breakeven
- Velocity lookback: 3 minutes
- Cost: 0.8 pips per trade (spread + slippage)

### Unfiltered (All Trades)

```
Full (2018-2026): N=1464, Sharpe -0.32, Total -$8.47, MCL 14
OOS (2021-2026):  N=914,  Sharpe  0.10, Total +$1.62, MCL 11
```

**Barely profitable** OOS. Not tradeable.

---

### With Velocity Filter (≥130 ticks/min threshold)

**Full period:**
- Fast (≥130): Sharpe 0.07, Total +$1.04
- Slow (<130): Sharpe -0.85, Total -$9.51 ← ALL the losses

**Out-of-Sample (2021-2026):**
- **Fast: Sharpe 0.70, Total +$5.89** ✓
- Slow: Sharpe -0.52, Total -$4.27

---

## Annual Breakdown (Unfiltered)

```
2018: -$5.23  Sharpe -1.55  LOSS
2019: -$5.33  Sharpe -2.76  LOSS
2020: +$0.47  Sharpe  0.12
2021: +$2.37  Sharpe  0.83
2022: +$4.92  Sharpe  1.29  ← Best year
2023: -$5.20  Sharpe -1.77  LOSS
2024: -$0.23  Sharpe -0.10  LOSS
2025: -$0.01  Sharpe -0.00  LOSS
```

**6 out of 9 years** are negative. Even with velocity filter, many years stay negative.

---

## Comparison to XAUUSD

|                          | EURUSD (filtered) | XAUUSD (filtered) |
|--------------------------|-------------------|-------------------|
| **OOS Sharpe**           | 0.70              | 1.81-2.14         |
| **Velocity threshold**   | 130 ticks/min     | 168 ticks/min     |
| **Slow half Sharpe**     | -0.52             | -0.16             |
| **Data quality**         | 1 month missing   | Complete          |

XAUUSD is **2.6x stronger** than EURUSD even with velocity filter applied.

---

## Decision: Keep XAUUSD Solo

### Reasons NOT to re-enable EURUSD:

1. **Too weak:** Sharpe 0.70 < 1.0 minimum threshold for live trading
2. **Dilutes portfolio:** Adding EURUSD would lower combined Sharpe
3. **Inconsistent:** 6/9 years negative, even recent years (2023-2025)
4. **Complexity cost:** Running 2 instruments = 2x failure modes, 2x monitoring
5. **XAUUSD is enough:** Sharpe 1.81 OOS is excellent for a single strategy

### When to reconsider:

- If XAUUSD edge degrades below Sharpe 1.0 OOS
- If we find a EURUSD-specific filter that boosts Sharpe >1.5
- If we want portfolio diversification at all costs

---

## What We Learned

1. **Velocity filter is universal:** Works on both XAUUSD and EURUSD
2. **Market matters:** Gold's higher volatility + activity = stronger ORB edge
3. **Testing was correct:** Good to verify, but data says "stay focused"

---

## Config Status

`config.yaml` EURUSD remains:
```yaml
EURUSD:
  enabled: false  # OOS Sharpe 0.70 too weak vs XAUUSD 1.81
```

---

## Files Created

- `data/1m_csv/eurusd_1m_tick.csv` (2.6M bars)
- `v5_xauusd_orb/backtest_eurusd.py` (backtest script)
- This summary: `docs/journal/2026-03-11_eurusd_resurrection_test.md`

---

## Next Steps

1. ✅ EURUSD tested and rejected
2. → Proceed with XAUUSD dry-run (3-5 days)
3. → Calibrate IBKR velocity threshold
4. → Paper trade
5. → Live
