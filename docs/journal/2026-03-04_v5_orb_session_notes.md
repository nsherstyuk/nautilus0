# ORB Multi-Live Session Notes — Mar 4, 2026

## Bugs Found & Fixed Today

### 1. `skip_weekdays` used wall-clock day instead of `trade_date` weekday
- **Impact**: XAUUSD skipped on Tue Mar 4 because process woke at 19:10 UTC Wed Mar 3 (`now.weekday()=2`, Wed is in `skip_weekdays=[2]`)
- **Fix**: `orb_multi_live.py` now uses `trade_date_dt.weekday()` for both weekend and skip_weekdays checks
- **Status**: ✅ Fixed. Also fixed weekend check same way.

### 2. EURUSD trade window mismatched backtest
- **Impact**: Live config had `trade_start_hour: 13, trade_end_hour: 21` (NY session), but backtest uses `trade_start=7, trade_end=16` (London session). Different strategy.
- **Fix**: `config.yaml` EURUSD changed to `trade_start_hour: 7, trade_end_hour: 16`
- **Status**: ✅ Fixed

### 3. Stale-price skip logic was discarding best trades
- **Impact**: When price was already above range_high at trade window open, long side was skipped. Analysis showed gap-open trades have **2-4x better avg P&L** (EURUSD: $71 vs $18, XAUUSD: $3.59 vs $1.55) and account for 65% of EURUSD total profit.
- **Fix**: Removed skip logic entirely. Both sides always placed. Gap-open stops fill immediately at market (matches backtest behavior).
- **Status**: ✅ Fixed

### 4. Stale orders after restart (ORDERS_PLACED but orders cancelled)
- **Impact**: Ctrl+C cancels orders at IBKR but state file still says `ORDERS_PLACED`. On restart, code watches for fills that will never come.
- **Fix**: Added `verify_orders_on_startup()` — queries IBKR for saved order IDs, resets to `RANGE_COMPUTED` if orders no longer exist.
- **Status**: ✅ Fixed

### 5. UTC clock "mystery" — resolved (was not a bug)
- **Investigation**: Orders placed at what appeared to be wrong hour. Diagnostic log revealed `hour=13` at 08:20 local time → `datetime.now(tz=timezone.utc)` returns **true UTC** (13:20 UTC = 08:20 EST). System clock is correct. The original EURUSD config `trade_start_hour: 13` was triggering correctly at 13:00 UTC.
- **Status**: ✅ No fix needed. Config change (#2 above) was still correct to match backtest.

## Config Changes (config.yaml)
- `EURUSD.trade_start_hour`: 13 → **7**
- `EURUSD.trade_end_hour`: 21 → **16**
- Both match backtest `INSTRUMENTS['EURUSD']` settings now

## Code Changes (orb_multi_live.py)
1. `trade_date_dt = datetime.strptime(today_str, "%Y-%m-%d")` — used for weekend + weekday skip checks
2. Diagnostic log at RANGE_COMPUTED → placement: prints `hour` and `trade_start_hour`
3. Stale-price skip logic replaced with informational gap-open log (no skip)
4. Order placement: always places both buy and sell brackets (no `skip_long`/`skip_short`)
5. `verify_orders_on_startup()` method added to `InstrumentManager`
6. Called in `run_day()` after state reset, before main loop

## Live Trade Today
- **EURUSD LONG** entered at 1.16429 (gap-open, buy stop filled immediately)
  - SL=1.15746, TP=1.16841
  - Entry order #68, OCA sell side #71 rejected (expected — OCA cancelled opposite side)
  - Position was closed (user set state to DONE_TODAY manually)

## XAUUSD Mar 3 Result
- **SHORT TP hit**: entry 5304.73 → exit 5153.70 = **+$151.03** ✅

## Pending / Known Issues
- XAUUSD missed Mar 4 entirely (weekday bug set DONE_TODAY before restart, state wasn't re-reset since trade_date already matched). Will work correctly from Mar 5.
- `analyze_gap_opens.py` created in `v5_xauusd_orb/` — can be deleted, was one-off analysis
