# ML Model Critique & Improvement Notes — Feb 22, 2026

## Current Model: `models/ml_model_mtf_v3_xgb.pkl`
Retrained Feb 22, 2026. XGBoost, 50 features, SL/TP-aware labels, trained on 2024 only.

---

## Known Weaknesses

**1. Stale training window**
- Trained on 2024 only (`TRAIN_END_DATE=2024-12-31`)
- Model has never seen 2025 data — the entire OOS optimization window is unseen
- EUR/USD 2024 had specific macro regimes (Fed pivot, US election) that may not generalize to 2025–2026

**2. Labels only simulate TP1, not the full trade**
- Label = 1 if price hits `close + ATR×1.4` before `close - ATR×1.8`
- Strategy has two positions: TP1 at 1.2×ATR, TP2 at 2.0×ATR
- Model never learns whether TP2 is reachable — it's optimizing for half the real payoff

**3. Class imbalance without correction**
- 57% label=1 reflects 2024's upward EUR/USD drift, not a neutral market
- No `class_weight='balanced'` or resampling applied
- Model is systematically biased toward predicting LONG

**4. All hours treated equally during training**
- Low-liquidity bars (Asian session, rollover) trained identically to London/NY overlap
- Strategy applies hour filters in live trading but model was trained on all bars
- Features learned from quiet hours may mislead predictions on active hours

**5. Uncalibrated probabilities**
- XGBoost `predict_proba` outputs are not probability-calibrated
- Thresholds (0.65–0.80) are tuned numerically but have no true probabilistic meaning
- Should use isotonic regression or Platt scaling post-training

**6. Potential live data leakage**
- `retrain_model.py` reads from `logs/live_mtf/hmtf_5m_dataset.csv`
- If any 2025 live-forward bars are in that file, the model has seen the future relative to the OOS optimization window

**7. Weak walk-forward validation**
- 3-fold CV on 12 months = ~4 month test folds
- Too short to capture regime changes reliably
- If folds share similar macro conditions, generalization is overstated

---

## What Would Work Better

**Labels**
- Simulate the full trade (both positions), compute realized PnL including fees/slippage
- Label by whether the complete trade was profitable — not just which level was touched first
- Or use a continuous label (expected PnL per trade) and treat as regression, optimize Sharpe directly

**Features**
- Add regime features: rolling 20-day realized vol, distance from 200-day MA, macro event proximity flag
- Add cross-pair confirmation as native features (EUR/USD vs GBP/USD, USD/CHF log return spread)
- Reduce/decorrelate the 50 features — XGBoost on a small dataset with many correlated features overfits without heavy regularization

**Model architecture**
- Stacked ensemble: XGBoost (trend), LightGBM (mean-reversion), Logistic Regression meta-learner
- Or a temporal model (LSTM/Transformer) that consumes raw last-N bars directly — current approach loses temporal structure by collapsing to hand-crafted features
- Add isotonic regression calibration so thresholds are interpretable

**Training discipline**
- Expanding walk-forward with monthly retraining: train on all data up to month M, test month M+1
- Exclude low-liquidity hours from both training AND inference — align exactly with the strategy's own hour filter
- Use `class_weight='balanced'` or per-regime undersampling

**Strategy integration**
- Move ML prediction to be the FINAL gate, after DMI/MAMA/ATR filters have narrowed the candidate set
- Train only on bars that would pass all other filters — makes the signal much cleaner
- Replace fixed ATR SL/TP with distribution-aware exits: fit forward price path distribution, set SL/TP at quantile levels (e.g., 10th and 70th percentile) per vol regime

**Optimization approach**
- Current: sequential group grid search over strategy params, with model fixed
- Better: Bayesian optimization over model hyperparameters AND strategy parameters jointly
- Objective: maximize Sharpe on OOS window, not total PnL or avg_trade score
