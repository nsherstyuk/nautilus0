# Critical Retrospective Report: Recent Development (Phase 6–7)
Date: 2026-03-11

After stepping back and reviewing the entire sequence of events—including the codebase evolution, backtest iterations, and the extensive correspondence between Windsurf and Claude—here is a critical assessment of the last several days. 

## 1. What Was Done Right (The Wins)

**1. Discovering the "Blind BE" Backtest Bug**
Claude's discovery that the backtest was crediting profits for Breakeven (BE) exits while the actual market price was deeply underwater is the most valuable finding of the project. It proved that the previous Sharpe ratios (4.0–7.0) were fiction. Disabling BE immediately was the correct, albeit painful, decision.

**2. Moving to Ground-Truth Data (Raw .bi5 to 1-Min Bars)**
The decision to abandon the 1h bars, 1000-tick bars, and 5-min bars in favor of downloading raw Dukascopy tick data and building precise 1-min bars is the best engineering decision made this week. It completely solved the "entry bar ambiguity" problem and gave us a true basis for measuring time and velocity. 

**3. Walk-Forward Validation**
When testing the new velocity filter, the use of walk-forward validation (testing 6 sequential years strictly out-of-sample) proved that the velocity edge is structurally real and not just curve-fitted to a specific year. 

**4. Adding Live Guardrails & Reconciliation**
Building `guardrails.py` (daily loss limits, max position checks) and `reconcile.py` before scaling up the live system was excellent defensive engineering. It ensures the live script won't destroy the account if an edge-case bug occurs.

---

## 2. Valid Criticisms & What Went Wrong (The Misses)

**1. Data Whiplash and Premature Optimization**
Over the last few days, we aggressively optimized strategies on **four different data resolutions** (1h -> 1000-tick -> 5-min -> 1-min). 
*   We optimized entry timings on 1h bars.
*   We found an "edge" in Q1 tick-bars, which turned out to be an artifact.
*   We added a 60-minute time exit based on 5-min bars, only to violently reverse that decision 24 hours later because 1-min bars proved it harmful.
*   **Criticism:** We spent too much time sweeping parameters on flawed data instead of fixing the data foundation first. A massive amount of research (and Claude's time) was wasted analyzing artifacts of bar aggregation.

**2. The "Option B" Velocity Gate Execution is Sloppy**
To implement the velocity filter live, we chose "Option B": place the stop orders, and if a fill happens during low velocity, immediately close the trade at market.
*   **Criticism:** We are purposely accepting a 1-spread loss (~$0.30 to $0.50) every time the system rejects a false breakout. In the backtest, we just *didn't take the trade*. In live, we are actively taking guaranteed small losses for bad signals. 
*   **Better approach:** We should dynamically place the IBKR stop orders only when the tick velocity is currently above the threshold (Option A), or use IBKR's condition-based routing if possible. Taking deliberate losses, even small ones, is poor execution mechanics.

**3. Massive Structural Risk: Dukascopy vs. IBKR Tick Calibration**
The entire strategy now rests on a highly specific threshold: **168 ticks per minute**. 
*   **Criticism:** This number is derived from Dukascopy's retail feed. IBKR's data feed aggregates and batches ticks completely differently (IBKR sends snapshots every 250ms or when volume thresholds hit). 168 ticks/min on Dukascopy might equal 40 ticks/min on IBKR, or it might equal 300. 
*   We added a CSV logger to calibrate this, which is good, but running the live script (even on paper) with a hardcoded `168` threshold before we know IBKR's baseline is effectively flying blind.

**4. Abandoning the Portfolio Too Quickly**
As soon as the BE bug was discovered, the Sharpe ratios for EURUSD, GBPUSD, and AUDUSD collapsed. We instantly disabled them to focus 100% on XAUUSD.
*   **Criticism:** We threw the baby out with the bathwater. We just discovered the Velocity Filter—a massive upgrade that doubled XAUUSD's performance—but we *haven't even tested it* on the FX pairs. It is highly likely that FX pairs also suffer from "quiet market false breakouts." We abandoned diversification when we should have re-tested the FX pairs using the new 1-min data and velocity filter.

**5. Parameter Over-Tuning on XAUUSD**
We currently have RR set to 2.5, Lookback set to 3 minutes, Threshold at P50, and Entry restricted strictly to 08:00 sharp. 
*   **Criticism:** While walk-forward testing validates the core velocity concept, combining exactly 3 minutes + exactly RR 2.5 + exactly 08:00 feels like we are squeezing the last drop of juice out of the historical XAUUSD dataset. We need to be prepared for live performance to be notably worse than the 1.87 Sharpe suggests.

---

## 3. Recommended Course Correction

1. **Stop Parameter Sweeping:** We have found a logical, structural edge (don't buy breakouts in dead markets). Stop trying to squeeze out an extra 0.1 Sharpe by tweaking the RR ratio or lookback minutes. The model is tuned enough.
2. **Fix the Live Execution Mechanics:** Rewrite the `orb_multi_live.py` logic to monitor velocity *pre-fill*. Do not place the bracket orders until velocity crosses the threshold. Stop paying spread costs for rejected trades.
3. **Calibrate IBKR Immediately:** Run the script on paper for exactly 3 days. Do nothing else but extract `velocity_xauusd.csv`, compare the median tick rate to Dukascopy's, and update the `168` hardcoded value.
4. **Resurrect EURUSD with Velocity:** Run `build_1m_from_bi5.py` for EURUSD. Run the velocity filter backtest on it. If the velocity filter saves EURUSD the way it saved XAUUSD, turn EURUSD back on. A 2-instrument portfolio is vastly safer than relying 100% on Gold.
