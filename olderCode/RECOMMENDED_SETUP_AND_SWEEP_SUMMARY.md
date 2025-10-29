# Recommended Setup and Sweep Summary

Date: 2025-08-22
Work folder: `MINIMAL_LIVE_IBKR_TRADER_before/`

## Recommended Setup (Backtest/Validation)
- Timeframe: 1m
- TP: 180 micropips
- Trailing stop: 2.0 pips
- Window size: 3
- Spacing threshold: 2
- Amplitude filters: amp12=50, amp40=50
- Position size: 1.0 lots
- HTF bias: OFF (`use_htf_bias=false`)
- Time filter: OFF for backtests (`time_filter_enabled=false`)

Rationale: This configuration produced the strongest net PnL and profit factor in the sweep and in the A/B experiment baseline.

## HTF Bias A/B Experiment (1m, same core params)
Inputs: TP=180µp, TS=2.0p, w=3, s=2, amp12=50, amp40=50, pos=1.0, time filter OFF.

- Baseline (no HTF): trades=10,303, win=53.34%, PF=2.05, total_pips=12,049.3, maxDD=-45.15p, net PnL=$73,836.21  
  Files: `logs/htf_exp_1m_baseline_trades.*`
- HTF Direction-only (5m): trades=6,422, win=52.97%, PF=1.99, total_pips=7,013.3, maxDD=-53.10p, net PnL=$41,041.96  
  Files: `logs/htf_exp_1m_htf_dir_trades.*`
- HTF TP-cap (5m): trades=10,972, win=55.19%, PF=1.80, total_pips=9,671.9, maxDD=-66.00p, net PnL=$47,033.12  
  Files: `logs/htf_exp_1m_htf_captp_trades.*`

Summary: Baseline outperformed both HTF bias modes on net PnL and PF for this setup. Direction-only reduced participation; TP-cap increased win rate and TP hits but lowered avg pips and worsened drawdown.

## Directional Loss Lockout (DLL) — Short Summary
- Goal: After a losing trade, block same-direction signals until opposite-side turning point (or timeout).
- State: Neutral → LockoutUp (blocks BUY) / LockoutDown (blocks SELL) after a loss; wins do not lock.
- Reset: On opposite-side TP detection (default) or confirmation; optional timeout.
- Median override: While locked, allow same-direction signal if TP bar median isn't significantly worse than prior same-side TP bar.
  - BUY lockout: allow if prev_median − curr_median ≤ threshold_median_micropips.
  - SELL lockout: allow if curr_median − prev_median ≤ threshold_median_micropips.
- Config (keys): directional_lockout.enabled, reset_on, timeout_bars, threshold_median_micropips, min_bars_between_same_side, single_override_then_relock.
- Logs: lockout_entered, lockout_ignored_signal, lockout_override_allowed, lockout_reset.
- Status: Planned; to be implemented after backup confirmation.

## General Sweep Findings (Completed 1800/1800 runs)
- Leaderboard favored TP=180 micropips and TS=2.0 pips at 1m and 2m timeframes.
- Example top config: 1m, w=3, s=2 ≈ net PnL $73.8k over ~10.3k trades, win rate ≈53.3%.
- Time filter disabled during the sweep (all hours included).

## Notes / Next Steps
- If exploring HTF bias further, vary `htf_timeframe` (e.g., 15m) and `htf_buffer_micropips` (10–100). Consider adaptive/conditional capping.
- Optionally evaluate hour exclusions with time filter enabled to see interaction effects.
