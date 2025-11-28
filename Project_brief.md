# 📂 Project Brief: ML Strategy Integration (Custom Architecture)

## **1. Core Objective**
We are extending an existing, customized NautilusTrader codebase to include a Machine Learning (ML) trading strategy.
**Crucial Constraint:** The codebase uses a **custom IBKR connector** and **custom data injection** and other elements like partial position close. Use existing local classes, do not hallucinate standard Nautilus implementations.

## **2. Trading Logic**
* **Timeframe:** M5 (5-Minute Bars).
* **Strategy:** Momentum/Mean-Reversion Hybrid (Random Forest).
* **Targets:** Dynamic Volatility (ATR-based).

## **3. Architecture & Components**

### **Component A: Research (Offline Training)**
* **File:** `research/train_model.py`
* **Goal:** Train/Test split. Train model on 2023-2024 data.
* **Features (Normalized):** LogRet, RSI(14), MACD, Stoch(14,3,3), ADX(14), ATR(14).
* **Labeling:** Dynamic Triple Barrier (Upper/Lower = Entry +/- 1.5*ATR).
* **Output:** `models/strategy_model.joblib`.

### **Component B: Strategy (The Logic)**
* **File:** `strategies/ml_strategy.py`
* **Goal:** The "Brain" that runs in both Backtest and Live.
* **Logic:**
    * `on_start`: Load `.joblib` model.
    * `on_bar`: Reconstruct features (parity with Research is critical).
    * `Signal`: `model.predict()`.
    * `Execution`: If Signal is 1/-1, send Order.

### **Component C: Backtesting (Verification)**
* **File:** `backtest/run_backtest.py`
* **Goal:** Prove the strategy works before live trading.
* **Logic:**
    * Load `MLSignalStrategy`.
    * Load historical data (ensure it matches the custom data loader format).
    * Run `BacktestEngine`.
    * **Analysis:** Print Total PnL, Win Rate, and Count of Trades.

## **4. Implementation Rules**
1.  **Parity is King:** `train_model.py` and `ml_strategy.py` MUST calculate indicators exactly the same way (use `pandas-ta`).
2.  **Custom Data:** The Backtest engine must ingest data that looks identical to the live custom data feed.