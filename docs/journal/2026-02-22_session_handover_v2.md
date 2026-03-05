# Session Handover — trading_system_v4 ML Pipeline
**Timestamp:** 2026-02-22  
**Continuing from:** SESSION_HANDOVER_2026-02-22.md (v4 architecture overview)

---

## 1. What Has Been Built

`trading_system_v4` is a new ML trading pipeline running alongside (not replacing) the existing v2/v3 HMTF system. It targets EURUSD.IDEALPRO initially. The pipeline consists of:

| Script | Purpose |
|---|---|
| `trading_system_v4/scripts/build_training_dataset.py` | Loads NautilusTrader Parquet bar catalog → computes 32 features → saves `training_features.parquet` |
| `trading_system_v4/scripts/add_htf_features.py` | Merges 15m and 1D HTF features (no-lookahead `merge_asof`) into 5m dataset → saves `training_features_htf.parquet` |
| `trading_system_v4/scripts/add_labels.py` | Simulates forward TP/SL hits (vectorised NumPy) → assigns y=1/0/-1 → saves `training_labeled_htf.parquet` |
| `trading_system_v4/scripts/train_model.py` | Walk-forward XGBoost training → EV threshold search → saves model + threshold JSON |
| `trading_system_v4/features/feature_engineering.py` | Core 32-feature calculation (dimensionless, no lookahead) |
| `trading_system_v4/model/model_inference.py` | Live inference wrapper (loads model + feature list + threshold) |

---

## 2. Current Data State

### Historical catalog (`data/historical/data/bar/`)
- **EURUSD.IDEALPRO** — 5-MINUTE, 15-MINUTE, 1-DAY: currently starts **March 2024**
- **GBPUSD.IDEALPRO, USDCHF.IDEALPRO** — same date range

### Data ingestion IN PROGRESS as of this handover
The user started `python data/ingest_historical.py` to ingest **Jan 2022 → Jan 2024** for EURUSD (and likely GBPUSD, USDCHF) for all three bar sizes (5-MINUTE, 15-MINUTE, 1-DAY). This will run for 1-3 hours.

**After ingestion completes, the full pipeline must be re-run** (see Section 5).

### Labeled dataset (pre-ingestion, existing)
`trading_system_v4/data/training_labeled_htf.parquet` — 581,436 rows × 107 cols (stale, pre-fix)
- EURUSD.IDEALPRO: 145,942 rows (2024-03 to 2026-02)
- GBPUSD.IDEALPRO: 217,747 rows
- USDCHF.IDEALPRO: 217,747 rows

After ingestion + re-pipeline, projected EURUSD rows: **~292,000** (adding 2 full years).

---

## 3. Model Artifacts (Current — Stale, Pre-Fix)

All models in `trading_system_v4/model/` were trained before the code fixes below. **Do not use for live trading.**

| File | Notes |
|---|---|
| `hybrid_model_eurusd_v4.pkl` | Stale — trained with duplicate session features + stall labels |
| `hybrid_model_eurusd_v4_calibrator.pkl` | Stale — isotonic calibration was collapsing recall to 8% |
| `hybrid_model_eurusd_v4_features.json` | Lists 96 features (will change to 80 after fix) |

Best performance achieved so far: AUC ~0.51, precision ~0.55 @ threshold 0.54. This is near-random — the fixes + new data are expected to improve it substantially.

---

## 4. Code Fixes Applied This Session (All Complete)

Three concrete bugs/design flaws were diagnosed and fixed. All scripts pass `ast.parse()` syntax check.

### Fix 1 — `add_htf_features.py`: remove duplicate session/time columns from HTF prefixes
**Problem:** `htf_is_london`, `htf_is_ny`, `htf_is_overlap`, `htf_hour_sin/cos`, `htf_dow_sin/cos` were 100% identical copies of the same 5m columns (r=1.000). The top-2 XGBoost features by gain were these duplicates, masking real signals and wasting 8 of 64 HTF/D1 slots.  
**Fix:** Added `_HTF_REMOVE_TIME_COLS` frozenset. `_load_htf_features()` now strips these columns before applying `htf_` / `d1_` prefix.  
**Effect:** Feature count drops from 96 → **80** (8 removed from 15m, 8 from 1D). Importance scores will now reflect real price/momentum features.

### Fix 2 — `add_labels.py`: drop stall rows instead of forcing stall → y=0
**Problem:** Rows where neither TP nor SL hit within 60 bars were relabelled y=0 (same as SL), polluting the negative class. ~25% of y=0 rows had near-zero forward returns — pure noise, not directional signals. This blurred the SL decision boundary.  
**Fix:** Removed `stall_mask = ...; labels[stall_mask] = 0`. Stall rows keep label `-1` and are dropped by the existing `kept = labelled[labelled["y"] != -1]` filter.  
**Effect:** ~15-20% fewer total rows, but the negative class is now a clean SL-hit signal only. Class balance will shift (fewer negatives).

### Fix 3 — `train_model.py`: disable isotonic calibration, retrain final model on all data
**Problem:** `IsotonicRegression` with AUC~0.50 was fitting a monotone function through noise, collapsing recall from 49% → 8% (most probabilities pushed below threshold).  
**Fix:**
- Removed `IsotonicRegression` import and all calibration code.
- The 80/20 time split is now used only to **find the EV-optimal threshold** (`_find_optimal_threshold`), not to calibrate.
- The final model then **retrains on 100% of the data** (not just 80%), using the threshold derived from the eval slice.
- `_calibrator.pkl` now saves `None` as a sentinel.
- A new `_threshold.json` file is saved alongside the model: `{"threshold": 0.XX}`.  
**Effect:** Live inference code should load this JSON to get the decision threshold instead of hardcoding 0.60.

---

## 5. Immediate Next Steps (After Ingestion Completes)

### Step 0 — Verify ingestion succeeded BEFORE doing anything else

Run this snippet to check what data landed in the catalog:

```python
import pandas as pd
from pathlib import Path

bar_root = Path(r"c:\nautilus0\data\historical\data\bar")
for sym_dir in sorted(bar_root.iterdir()):
    if not sym_dir.is_dir():
        continue
    files = sorted(sym_dir.glob("*.parquet"))
    if not files:
        continue
    df = pd.concat([pd.read_parquet(f) for f in files])
    # ts_init is nanoseconds
    ts = pd.to_datetime(df["ts_init"], unit="ns", utc=True)
    print(f"{sym_dir.name:<55}  rows={len(df):>7,}  {ts.min().date()} → {ts.max().date()}")
```

**What you must see before proceeding:**
- `EURUSD.IDEALPRO` 5-MINUTE directory shows data starting **2022-01-xx** (previously started 2024-03)
- `EURUSD.IDEALPRO` 15-MINUTE and 1-DAY directories also show 2022 start
- Total 5-MINUTE rows for EURUSD should be **~290,000+** (was 145,942 before ingestion)

**If the date still starts at 2024**, the ingestion did not complete or environment variables were wrong. Check `.env.mtf_v3` for `DATA_START_DATE`, `DATA_END_DATE`, and `DATA_SYMBOLS`. Do not proceed to Step 1 until data is confirmed.

---

### Step 1 — Rebuild the 5m feature dataset

```powershell
python -m trading_system_v4.scripts.build_training_dataset
```

**Expected output (look for these lines):**
```
EURUSD.IDEALPRO   rows loaded: ~290,000+   date range: 2022-01 → 2026-02
```
If rows are still ~145k, the catalog did not update — stop and re-check ingestion.

---

### Step 2 — Merge 15m + 1D HTF features (fixed — no duplicate session columns)

```powershell
python -m trading_system_v4.scripts.add_htf_features
```

**Expected output:**
```
Total features: 80   (was 96 before fix — 8 session cols removed from 15m, 8 from 1D)
Output: ~580,000+ rows × ~91 cols
```

---

### Step 3 — Label dataset (fixed — stalls dropped, not relabelled)

```powershell
python -m trading_system_v4.scripts.add_labels trading_system_v4/data/training_features_htf.parquet
```

**Expected output:**
```
Label balance: ~45–55% positive  (slightly lower than the old 54% because stall rows are now dropped)
dropped = non-trivial number (stall rows + tail rows without full lookahead window)
```
If positive rate is outside 35–60%, something is wrong with the labeling — investigate before training.

---

### Step 4 — Train EURUSD model (fixed — no isotonic, full-data final model)

```powershell
python -m trading_system_v4.scripts.train_model trading_system_v4/data/training_labeled_htf.parquet hybrid_model_eurusd_v4 EURUSD.IDEALPRO
```

**Expected output (watch for these improvements vs the old stale model):**
```
Fold 1: train=~146,000 (≤2023)  test=~60,000 (2024)   ← THIS FOLD WAS EMPTY BEFORE
Fold 2: train=~207,000 (≤2024)  test=~73,000 (2025)   ← was only 60k train
Fold 3: train=~280,000 (≤2025)  test=~12,000 (2026)   ← was only 134k train
AUC should be noticeably above 0.51 (old value)
recall should be above 20% (old value was collapsing to 8% due to isotonic bug)
```

**Outputs saved:**
- `trading_system_v4/model/hybrid_model_eurusd_v4.pkl` — retrained XGBoost on 100% of data
- `trading_system_v4/model/hybrid_model_eurusd_v4_calibrator.pkl` — contains `None` (no calibration; sentinel only)
- `trading_system_v4/model/hybrid_model_eurusd_v4_threshold.json` — `{"threshold": X.XX}` (EV-optimal, read this at inference time)
- `trading_system_v4/model/hybrid_model_eurusd_v4_features.json` — 80 features

---

## 6. Remaining Improvements Not Yet Implemented

These were discussed and agreed upon but not yet coded:

### Priority 1 — Add directional features to `feature_engineering.py`
The model currently has ~AUC 0.51 because all 32 features describe *what the current bar looks like* (shape, RSI, ADX), not *which direction price is likely to move*. Suggested additions:
- `consecutive_up_bars` — count of consecutive bullish closes (max 10)
- `consecutive_down_bars` — count of consecutive bearish closes (max 10)
- `dist_to_20bar_high` — `(high_20bar - close) / atr` — distance to resistance
- `dist_to_20bar_low` — `(close - low_20bar) / atr` — distance to support
- `close_vs_htf_midpoint` — whether 5m close is above/below the prior 15m bar's midpoint

These belong in `trading_system_v4/features/feature_engineering.py` → `add_features()`.

### Priority 2 — Wire trained model into `run_live_hybrid.py`
`trading_system_v4/scripts/run_live_hybrid.py` exists but does not yet load or use the model for signal filtering. The `model_inference.py` wrapper exists in `trading_system_v4/model/`. The live runner needs to:
1. Load model + feature list + threshold JSON at startup
2. At each 5m bar close, compute the 80 features (including HTF features from the live 15m/1D streams)
3. Gate entry signals behind `model.predict_proba(features)[1] >= threshold`

### Priority 3 — Acquire more historical data if ingestion didn't cover 2020-2021
If the Jan 2022 → Jan 2024 ingestion gives only ~147k new EURUSD rows, consider also ingesting 2020-2021 to add 2 more training folds.

---

## 7. Architecture Constraints (Do Not Break)

- Do **not** modify v2/v3 HMTF code (`trading_system_v3/`, `run_live_hybrid.py` in root) unless asked.
- All v4 scripts live under `trading_system_v4/`.
- No-lookahead rule: `merge_asof(direction='backward')` — each 5m bar gets the *previously closed* 15m/1D bar's features, not the current one.
- Config is env-driven via `.env.mtf_v3`. Do not hardcode credentials.
- `_threshold.json` must be read by the live runner — do not hardcode the threshold value.

---

## 8. Key File Locations

| Path | Description |
|---|---|
| `trading_system_v4/scripts/add_htf_features.py` | Fixed ✅ session-col dedup |
| `trading_system_v4/scripts/add_labels.py` | Fixed ✅ stall rows dropped |
| `trading_system_v4/scripts/train_model.py` | Fixed ✅ no isotonic, full-data final model |
| `trading_system_v4/features/feature_engineering.py` | 32 base features — directional features pending |
| `trading_system_v4/data/training_features_htf.parquet` | Stale (pre-ingestion) |
| `trading_system_v4/data/training_labeled_htf.parquet` | Stale (pre-ingestion, pre-fix) |
| `trading_system_v4/model/hybrid_model_eurusd_v4.pkl` | Stale model — retrain after ingestion |
| `data/ingest_historical.py` | IBKR ingestion script (currently running) |
