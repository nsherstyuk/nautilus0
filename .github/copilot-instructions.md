# Copilot instructions (nautilus0)

## Project context
- This repo is a Python trading system with:
  - Live trading via IBKR (`ib_insync`) + NautilusTrader integration.
  - Multi-timeframe ML strategies (existing **v2**) and a new Hierarchical Multi-Timeframe (**HMTF / v3**) implementation.
- Assume timestamps are **UTC** and use ISO-8601 with timezone offsets.

## Safety + scope
- Do **not** change v2 behavior unless explicitly requested; prefer adding/adjusting v3/HMTF files.
- Do **not** add new UX/pages/dashboards unless the user asks.
- Never commit secrets. Do not write API keys into code or configs.

## Environment + config conventions
- Config is env-driven; prefer reading from `.env.mtf_v2` / `.env.mtf_v3` via config loaders.
- Respect these defaults unless the user changes them:
  - `MTF3_DATASET_PATH` defaults to `logs/live_mtf/hmtf_5m_dataset.csv`.
  - Model paths are controlled by `MTF3_*_MODEL_PATH` variables.

## IBKR streaming conventions
- The IB streamer must support **multiple concurrent subscriptions per symbol** (e.g., 5m + 15m).
  - Use a **composite subscription key** (symbol + bar_size + what_to_show + use_rth).
  - When modifying streamer code, update reconnect/status/health-check logic consistently.

## HMTF (v3) correctness requirements
- **No lookahead:** 5m soldier features must use the most recently *completed* 15m master prediction.
- **Quarter-hour ordering:** when a 15m and 5m bar share the same close timestamp, process the 15m master first.
- Keep the HMTF state machine semantics: `IDLE → HUNTING → ACTIVE → COOLDOWN` (cooldown ~30 minutes).
- Dynamic sizing must match the exact `get_dynamic_size` implementation used by v3; do not “improve” or refactor it unless requested.

## Dataset logging + offline tooling
- Live HMTF writes an append-only CSV dataset for 5m rows. When adding new features:
  - Add new columns at the end and keep backwards compatibility.
  - Ensure headers are written once and row appends are atomic.
- Prefer streaming/iterative processing for large CSVs (avoid loading entire files unless the dataset is known small).

## Code style + changes
- Keep changes minimal and localized.
- Prefer explicit names over abbreviations.
- Add/adjust scripts in `scripts/` for offline tasks (audit, stitch, train).
- After edits, run the narrowest check possible (script run or targeted import) instead of broad refactors.
