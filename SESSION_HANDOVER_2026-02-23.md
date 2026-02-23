# Session Handover — trading_system_v4 ML Pipeline
**Timestamp:** 2026-02-23  
**Continuing from:** SESSION_HANDOVER_2026-02-22_v2.md

---

## 1. What Has Been Built & Changed This Session

The `trading_system_v4` ML pipeline has undergone a major architectural pivot. The previous model was failing to learn directional signals because the target label (`y=1` if TP hit before SL) was path-dependent and directionless. 

We have implemented a **Two-Model Split** (Long vs. Short) and pivoted the target to a **Fixed-Horizon Directional Prediction**.

### Key Architectural Changes:
1. **Directional Features Added (`feature_engineering.py` & `add_htf_features.py`)**
   - Added 5 new directional features: `consecutive_up_bars`, `consecutive_down_bars`, `dist_to_20bar_high`, `dist_to_20bar_low`, and `close_vs_htf_midpoint`.
   - Total feature count increased from 80 to **95**.

2. **Data Ingestion Extended (`.env`)**
   - Extended historical data ingestion back to **2020-01-01** (was 2022).
   - Added `GBP/USD` and `USD/CHF` to the ingestion list.
   - Added `1-DAY-MID` to the bar specs.
   - *Note: Ingestion completed successfully. We now have ~293k rows for EURUSD 5m.*

3. **Labeling Pivot (`add_labels.py`)**
   - **Old:** Path-dependent TP (1.4R) vs SL (1.8R) over 60 bars.
   - **New:** Fixed-horizon directional target.
     - `y_long = 1` if price is $\ge$ 0.5 ATR higher exactly 12 bars (1 hour) from now.
     - `y_short = 1` if price is $\le$ 0.5 ATR lower exactly 12 bars (1 hour) from now.
   - This forces the model to predict short-term momentum bursts rather than complex path trajectories.

4. **Two-Model Training (`train_model.py`)**
   - The script now requires a `--direction` argument (`long` or `short`).
   - It trains two completely separate XGBoost models.
   - The EV threshold search was updated to assume a 1:1 Risk/Reward ratio for the fixed-horizon target.

5. **Live Runner Update (`run_live_hybrid.py`)**
   - Completely rewritten to load both the Long and Short models.
   - At each 5m bar, it evaluates both models.
   - If `model_long.predict_proba() > threshold`, it sends a `buy` signal to the `RiskManager`.
   - If `model_short.predict_proba() > threshold`, it sends a `sell` signal.

---

## 2. Current Model Status (EURUSD, 2020–2026)

The pivot successfully changed the model's behavior. Previously, the model relied almost entirely on Daily (1D) features. Now, the top features are heavily weighted towards 5m session times (`is_london`, `hour_sin`) and 5m volatility expansion (`atr_ratio`).

However, the predictive power (Precision/AUC) remains low because predicting a 0.5 ATR move in exactly 1 hour is incredibly difficult in a mean-reverting FX market using only lagging indicators (RSI, EMA).

**Long Model (`hybrid_model_v4_eurusd_long`)**
- **AUC:** ~0.52
- **Optimal Threshold:** 0.77
- **Precision @ Threshold:** 0.464 (Target > 0.65 ❌)
- **Top Features:** `is_london` (48.1), `atr_ratio` (47.1), `hour_sin` (45.7)

*Note: The Short model has not been retrained on the new fixed-horizon labels yet.*

---

## 3. Immediate Next Steps

### Step 1 — Train the Short Model
The Long model was trained on the new fixed-horizon labels, but the Short model still needs to be trained.
```powershell
python -m trading_system_v4.scripts.train_model --input trading_system_v4/data/training_labeled_htf.parquet --stem hybrid_model_v4 --symbol EURUSD.IDEALPRO --direction short
```

### Step 2 — Re-evaluate the Pivot vs. TP/SL
The fixed-horizon pivot (predicting a 0.5 ATR move in 1 hour) proved that the model *can* learn short-term session momentum (hence `is_london` becoming the #1 feature). However, the precision (0.46) is too low for live trading.

You must decide:
1. **Stick with Fixed-Horizon:** If you keep this, you must engineer better micro-structure features (e.g., tick volume, multi-symbol correlation, distance to daily pivot points) to push precision > 0.65.
2. **Revert to TP/SL:** If you revert `add_labels.py` to the old 1.4R TP / 1.8R SL logic, you *must* keep the Two-Model Split (`y_long` and `y_short`). The old logic failed because it mixed long and short signals into a single `y=1` target. With the split, the TP/SL logic might actually work.

### Step 3 — Wire the Risk Manager
Currently, `run_live_hybrid.py` sends a `buy` or `sell` signal to the `ExecutionEngine`. Because the ML model is now purely a directional filter (Fixed Horizon), the `RiskManager` or `ExecutionEngine` must be updated to handle the actual trade lifecycle (e.g., attaching a trailing stop or a fixed ATR-based bracket order).

---

## 4. Key File Locations

| Path | Description |
|---|---|
| `trading_system_v4/scripts/add_labels.py` | Pivoted to Fixed-Horizon (12 bars, 0.5 ATR) + Two-Model Split (`y_long`, `y_short`) |
| `trading_system_v4/scripts/train_model.py` | Updated to accept `--direction` and train separate models |
| `trading_system_v4/scripts/run_live_hybrid.py` | Rewritten to load both models and gate orders |
| `trading_system_v4/features/feature_engineering.py` | Added 4 directional features |
| `trading_system_v4/scripts/add_htf_features.py` | Added `close_vs_htf_midpoint` feature |
| `trading_system_v4/model/hybrid_model_v4_eurusd_long.pkl` | Current Long model (Fixed-Horizon) |
| `.env` | Ingestion extended to 2020, added GBP/USD and USD/CHF |