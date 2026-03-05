# Project Journal

Chronological record of development sessions, decisions, and discoveries.
Read these files in order to understand how the project evolved.

## Timeline

### Phase 1: Live/Backtest Parity (Feb 20-21, 2026)
- **[2026-02-20_parity_investigation.md](2026-02-20_parity_investigation.md)** — Live vs backtest parity investigation: exit code debugging, deterministic computation fixes
- **[2026-02-21_idempotency_fix.md](2026-02-21_idempotency_fix.md)** — Critical idempotency fix for duplicate bars; validation required before resuming live trading

### Phase 2: ML Model Critique & v4 Architecture (Feb 22-23, 2026)
- **[2026-02-22_session_handover.md](2026-02-22_session_handover.md)** — Started trading_system_v4: hybrid modular trading system with NautilusTrader
- **[2026-02-22_session_handover_v2.md](2026-02-22_session_handover_v2.md)** — v4 ML pipeline continuation, meta-labeling approach
- **[2026-02-22_optimization.md](2026-02-22_optimization.md)** — Parameter optimization running (do not interrupt)
- **[2026-02-22_session_summary.md](2026-02-22_session_summary.md)** — Full session summary: ML model critique, new system planning, autonomous implementation
- **[2026-02-23_session_handover.md](2026-02-23_session_handover.md)** — v4 ML pipeline continuation from Feb 22

### Phase 3: v4 Tick-Bar System Exploration (Feb 23-25, 2026)
- **[2026-02-23_v4_session_handover.txt](2026-02-23_v4_session_handover.txt)** — EURUSD tick-bar meta-labeling system
- **[2026-02-23_v4_session_handover_v2.txt](2026-02-23_v4_session_handover_v2.txt)** — Afternoon continuation
- **[2026-02-24_v4_session_handover.md](2026-02-24_v4_session_handover.md)** — Path C implementation for EURUSD trading system
- **[2026-02-24_v4_session_handover_v2.md](2026-02-24_v4_session_handover_v2.md)** — Comprehensive signal & feature audit
- **[2026-02-24_v4_session_handover_v3.md](2026-02-24_v4_session_handover_v3.md)** — **Conclusion: market-making on EURUSD at tick level has NO robust edge**
- **[2026-02-25_v4_session_handover.md](2026-02-25_v4_session_handover.md)** — Signal audit continuation for EURUSD/XAUUSD

### Phase 4: Pivot to v5 ORB Strategy (Feb 27-28, 2026)
- **[2026-02-27_session_handover.md](2026-02-27_session_handover.md)** — Transition session, new direction
- **[2026-02-28_v5_orb_session_handover.md](2026-02-28_v5_orb_session_handover.md)** — v5 XAUUSD Asian Range Breakout: slippage modeling, BE rule sensitivity, RR optimization. Recommended Config B: 120-min BE + RR=3.0 + $10 BE offset

### Phase 5: Live Deployment & Multi-Instrument (Mar 2-5, 2026)
- **[2026-03-02_v5_orb_handover.md](2026-03-02_v5_orb_handover.md)** — ORB multi-instrument (XAUUSD + EURUSD) deployment to live trading
- **[2026-03-04_v5_orb_session_notes.md](2026-03-04_v5_orb_session_notes.md)** — 5 bugs found and fixed in orb_multi_live.py (skip_weekdays, stale orders, EURUSD window, gap-open trades)
- **[2026-03-04_session_notes.md](2026-03-04_session_notes.md)** — Earlier parity investigation notes (carried forward)
- **[2026-03-05_session_handover_latest.md](2026-03-05_session_handover_latest.md)** — Latest handover: dashboard improvements, repo cleanup, strategy validated live (+$244, 80% WR over 5 trades)

## Key Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| Feb 22 | Start trading_system_v4 from scratch | ML model critique revealed fundamental issues |
| Feb 24 | Abandon tick-level market-making | No robust edge found after exhaustive audit |
| Feb 27 | Pivot to v5 Asian Range Breakout | Simple, rule-based, backtested edge on XAUUSD |
| Feb 28 | Deploy Config: 2h BE + $2 offset | Balances robustness vs. cost coverage |
| Mar 2 | Add EURUSD as second instrument | Diversification, same ORB framework |
| Mar 5 | Merge to main, repo cleanup | Strategy validated live, branch no longer needed |
