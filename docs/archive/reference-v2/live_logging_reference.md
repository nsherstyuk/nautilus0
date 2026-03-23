# Live Logging Reference (MTF V2 Adaptive Fail-Safe)

Purpose: single source of truth for where live logs are written, what each file contains, and which event tags are stable for downstream analysis.

## 1) Primary log directories

- `logs/live_mtf/`
  - Main live run logs (runner + strategy + supervisor).
- `logs/trader_logs/`
  - NautilusTrader internal engine/client logs.

## 2) Per-run files in `logs/live_mtf/`

Created by live runner startup:

- `console_adaptive_failsafe_<YYYYMMDD_HHMMSS>.log`
  - Per-run complete console capture.
  - Best first source for incident timelines.
- `application.log`
  - General rotating application log.
- `live_trading.log`
  - Live process level events.
- `strategy.log`
  - Strategy-level events (signals, confirmations, protection checks).
- `orders.log`
  - Order lifecycle events.
- `trades.log`
  - Trade execution events.
- `errors.log`
  - Error-level events only.
- `supervisor_adaptive_failsafe_<YYYYMMDD_HHMMSS>.log`
  - Supervisor process lifecycle, restart behavior.
- `run_metadata_live_<run_id>.json`
  - Run metadata with git branch/commit/dirty state.

## 3) Log format

Default format:

- `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

Detailed formatter (used in selected files):

- `%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s`

Rotation:

- Rotating files are configured with 10MB max size and backups.

## 4) Stable strategy event tags for parsing

Use these tags as canonical parse anchors:

- `[BAR_METRICS]` — per-bar metrics snapshot.
- `[STARTUP_GUARD]` — stale startup/backfill filtering behavior.
- `[CONFIRM]` — entry confirmation checks and decisions.
- `[SUBMIT]` — order submit intent with side/size/SL/TP.
- `[ORDER_IDS]` — entry/SL/TP order IDs.
- `[PROTECTION_CHECK]` — protection verification failures.
- `[EMERGENCY FLATTEN]` — forced close path.
- `STATUS REPORT` — periodic runtime/portfolio health snapshot.

## 5) Recommended sources by analysis goal

- Trade decision reconstruction:
  - `console_adaptive_failsafe_<run_id>.log` + `strategy.log` + `orders.log`
- Execution/fill mismatch analysis:
  - `orders.log` + `trades.log` + `logs/trader_logs/`
- Restart/reconnect incident analysis:
  - `supervisor_adaptive_failsafe_<run_id>.log` + `console_adaptive_failsafe_<run_id>.log`
- Reproducibility/version audit:
  - `run_metadata_live_<run_id>.json`

## 6) Correlation keys

Correlate records using:

1. UTC timestamp
2. `client_order_id`
3. `venue_order_id` (when present)
4. Layer names (`POS1`, `POS2`, `POS3`)

## 7) Operational notes

- Keep UTC assumptions for all timeline joins.
- For analysis jobs, prefer reading latest per-run console file first, then enrich from structured logs.
- If logger names or routing change, update this file and parsers in `scripts/` together.
