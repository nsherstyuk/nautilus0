# Live MTF V2 Dashboard Implementation Plan

## Goal
Build a local dashboard (GUI with colors and buttons) for monitoring and controlling the Live MTF V2 trading system.

Hard requirements:
- Day-1 buttons (Pause/Resume trading, Flatten, Cancel orders).
- Do not modify the existing working live runner: `live/run_live_mtf_v2.py`.
- Create a new live runner script which reuses existing strategy + streamer but adds a machine-readable status export and a command channel.
- Dashboard should combine:
  - IBKR live account/portfolio data (authoritative account truth)
  - Strategy status + prediction/confidence + internal state (exported by the live runner)

Non-goals (for v1):
- No external deployment.
- No remote access / multi-user.
- No order placement directly from the dashboard process (orders should be executed only by the live runner).

## High-level design
Two processes:

1) Live runner (authoritative trading process)
- Connects to IBKR and receives bars (existing behavior).
- Runs `MLSignalStrategyV2` (existing behavior).
- Writes status snapshots to disk for the dashboard.
- Reads commands from disk and executes them safely.

2) Dashboard process (UI)
- Read-only for trading state (except writing commands).
- Polls IBKR for account summary / portfolio / orders.
- Reads status snapshots/events exported by the live runner.
- Writes commands to the command channel file.

## Proposed tech
- Dashboard UI: Streamlit (local web UI)
  - Pros: fast to build, good charts, easy metric widgets, easy buttons.
  - Runs on Windows reliably.
- Inter-process communication (IPC): files in `logs/live_mtf/`
  - `status.json` (latest snapshot, overwritten)
  - `events.jsonl` (append-only event stream)
  - `commands.jsonl` (append-only commands)

## Files / modules to add (new)
- `live/run_live_mtf_v2_dashboard.py`
  - New runner script. Uses the same config and trading logic as `live/run_live_mtf_v2.py`.
  - Adds status export + command polling.
- `live/dashboard_ipc.py`
  - Helpers to write `status.json`, append `events.jsonl`, read/ack commands.
- `dashboard/app.py`
  - Streamlit app.
  - Reads `status.json` + tails `events.jsonl`.
  - Polls IBKR for account/positions/orders.

Notes:
- The `dashboard/` directory can be created at repo root.
- All written output should be ASCII-only.

## Data contracts (v1)

### `logs/live_mtf/status.json` (overwrite)
Minimum fields:
- `ts_wall_utc`: ISO timestamp when status was written
- `run_id`: unique ID for this live session
- `mode`: `LIVE` or `PAPER` (or similar)
- `connection`:
  - `ib_connected`: bool
  - `last_bar_received_utc`: ISO timestamp
  - `last_bar_time_utc`: ISO timestamp (bar time)
  - `bar_lag_sec`: number
- `strategy`:
  - `state`: `WARMUP`, `READY`, `IN_POSITION`, `PAUSED`
  - `symbol`: string
  - `bar_type`: string
  - `buffer_15m_len`: int
  - `buffer_30m_len`: int
  - `last_prediction`:
    - `pred`: int/string
    - `confidence`: float
    - `threshold`: float
    - `ts_bar_utc`: ISO timestamp
  - `last_decision_reason`: string
- `positions` (from strategy view if available):
  - `has_open_position`: bool
  - `side`: `LONG`/`SHORT`/`NONE`
  - `qty`: float
  - `entry_price`: float
  - `unrealized_pnl`: float (optional if available)

### `logs/live_mtf/events.jsonl` (append)
JSON per line, event types like:
- `BAR_RECEIVED`
- `PREDICTION`
- `FILTERED`
- `SIGNAL`
- `ORDER_SUBMITTED`
- `FILL`
- `POSITION_CLOSED`

### `logs/live_mtf/commands.jsonl` (append)
JSON per line, dashboard writes; live runner reads and acks.
Fields:
- `cmd_id`: unique id (uuid)
- `ts_wall_utc`: ISO timestamp when command created
- `command`: `PAUSE`, `RESUME`, `FLATTEN`, `CANCEL_ALL`
- `source`: `dashboard`
- `notes`: optional

Optional ack file:
- `logs/live_mtf/command_acks.jsonl`

## UI feature list (v1)

### A) Top status banner
- Connection status (green/yellow/red)
- Trading state (READY/PAUSED/WARMUP)
- Last bar time + bar lag seconds

### B) Buttons (day 1)
- Pause trading (no new entries)
- Resume trading
- Flatten now (close positions + cancel orders)
- Cancel all open orders

Safety rules:
- Buttons only write commands to `commands.jsonl`.
- Live runner is the only process allowed to send/cancel orders.
- Commands should be idempotent when possible.

### C) Account panel (IBKR)
- Net liquidation / equity
- Cash balance
- Unrealized PnL
- Realized PnL (if available)
- Margin usage (if available)

### D) Portfolio / exposure panel (IBKR)
- Positions table
- Open orders table

### E) Strategy panel (from `status.json`)
- Last prediction + confidence + threshold
- Last decision reason
- Warmup buffers sizes

### F) Performance panel (computed in dashboard from events)
- Win rate (rolling N)
- Profit factor
- Trades list (last N)
- Equity curve (optional if enough data)

## Live runner feature list (v1)
- Status snapshot update at:
  - each completed bar
  - after each prediction decision
  - after each order submission
  - after each fill/position close
- Command polling loop:
  - poll every 0.5-2.0 seconds
  - execute commands in-order
  - write ack lines
- Flatten implementation:
  - cancel open orders
  - close open positions (market order) OR use existing strategy exit logic

## Acceptance criteria

### Functional
- Dashboard starts and shows green connection if IBKR is connected.
- For each completed 15m bar, dashboard updates within 5 seconds.
- Buttons work:
  - PAUSE prevents new entries (exits still managed)
  - RESUME re-enables new entries
  - CANCEL_ALL cancels all open orders
  - FLATTEN cancels orders and closes any open positions
- Live runner keeps trading even if dashboard is closed.

### Reliability
- Dashboard can run 3+ days without manual restart (assuming TWS/IB Gateway stays up).
- On IBKR disconnect, dashboard shows disconnected and auto-recovers on reconnect.
- Command channel is robust to partial writes (use atomic writes for `status.json`, append-only for jsonl).

### Safety
- No direct order placement from dashboard.
- Commands are logged and acknowledged.

## Implementation phases

### Phase 0: prerequisites
- Confirm `requirements.txt` includes needed packages (streamlit, ib_insync, pandas, plotly).

### Phase 1: IPC layer
- Implement `dashboard_ipc.py` to:
  - write `status.json` atomically
  - append `events.jsonl`
  - append/read/ack `commands.jsonl`

### Phase 2: New live runner
- Create `live/run_live_mtf_v2_dashboard.py`.
- Reuse existing config + strategy wiring.
- Add status export and command polling.

### Phase 3: Dashboard UI
- Create `dashboard/app.py` (Streamlit).
- Implement panels + charts + buttons.

### Phase 4: Dry-run validation
- Run live runner in paper mode for 1-2 hours.
- Confirm:
  - bar cadence
  - status freshness
  - buttons behavior

## Open questions (need answers before coding)
1) Should FLATTEN close using market orders immediately, or use strategy-managed exits?
2) When PAUSED: should it still update trailing stops / manage exits? (recommended: yes)
3) Where should IBKR connection for dashboard come from?
   - Option A: dashboard makes its own ib_insync connection (simpler)
   - Option B: share data only via files (dashboard does not connect to IBKR)
   Recommendation: Option A.
