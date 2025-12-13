#!/usr/bin/env python3
"""
Simple backtest for MTF ML Strategy using CSV data directly.
Phase 4: Baseline backtest with minimal filters.
"""
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from strategies.ml_strategy_mtf import MLSignalStrategy
from strategies.ml_strategy_config import MLSignalStrategyConfig

def load_and_prepare_data():
    """Load 15-minute CSV data."""
    csv_path = PROJECT_ROOT / "data" / "historical" / "EUR-USD_EUR_USD_IDEALPRO_15_MINUTE_MID_EXTERNAL.csv"
    
    print(f"Loading data from: {csv_path}")
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter to backtest period (Jan-Oct 2025)
    df = df['2025-01-01':'2025-10-30']
    
    print(f"Loaded {len(df)} bars")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    
    return df

def simulate_strategy(df, config):
    """
    Simple simulation of the MTF strategy.
    This is a simplified version for quick testing.
    """
    from joblib import load
    import pandas_ta as ta
    
    # Load model
    model = load(PROJECT_ROOT / config.model_path)
    print(f"Loaded model from {config.model_path}")
    
    # Calculate 15m features
    df['hl2'] = (df['high'] + df['low']) / 2
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    mama_fama = ta.mama(df['hl2'], fast=0.5, slow=0.05)
    df['mama'] = mama_fama.iloc[:, 0]
    df['fama'] = mama_fama.iloc[:, 1]
    df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
    
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    # Resample to 30m for 30m indicators
    df_30m = df.resample('30min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    # Calculate 30m indicators
    dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
    df_30m['dmp'] = dmi_30m.iloc[:, 1] / 100.0
    df_30m['dmn'] = dmi_30m.iloc[:, 2] / 100.0
    
    stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
    df_30m['stoch_k'] = stoch_30m.iloc[:, 0] / 100.0
    df_30m['stoch_d'] = stoch_30m.iloc[:, 1] / 100.0
    
    wma_short = ta.wma(df_30m['close'], length=8)
    wma_long = ta.wma(df_30m['close'], length=23)
    df_30m['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
    
    # Merge 30m indicators to 15m
    df_30m_renamed = df_30m[['dmp', 'dmn', 'stoch_k', 'stoch_d', 'wma_diff']].copy()
    df_30m_renamed.columns = ['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']
    df = df.join(df_30m_renamed, how='left')
    df = df.ffill()  # Forward fill 30m values
    
    # Drop NaN rows
    df = df.dropna()
    
    print(f"After feature calculation: {len(df)} bars")
    
    # Simulate trading
    trades = []
    position = None
    last_trade_time = None
    cooldown = pd.Timedelta(minutes=30)
    
    for idx, row in df.iterrows():
        # Skip if in position
        if position is not None:
            # Check if stop loss or take profit hit
            if position['side'] == 'LONG':
                if row['low'] <= position['sl']:
                    # Stop loss hit
                    pnl = (position['sl'] - position['entry']) * position['size']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'LONG',
                        'entry': position['entry'],
                        'exit': position['sl'],
                        'pnl': pnl,
                        'exit_reason': 'SL'
                    })
                    position = None
                elif row['high'] >= position['tp']:
                    # Take profit hit
                    pnl = (position['tp'] - position['entry']) * position['size']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'LONG',
                        'entry': position['entry'],
                        'exit': position['tp'],
                        'pnl': pnl,
                        'exit_reason': 'TP'
                    })
                    position = None
            else:  # SHORT
                if row['high'] >= position['sl']:
                    pnl = (position['entry'] - position['sl']) * position['size']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'SHORT',
                        'entry': position['entry'],
                        'exit': position['sl'],
                        'pnl': pnl,
                        'exit_reason': 'SL'
                    })
                    position = None
                elif row['low'] <= position['tp']:
                    pnl = (position['entry'] - position['tp']) * position['size']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'SHORT',
                        'entry': position['entry'],
                        'exit': position['tp'],
                        'pnl': pnl,
                        'exit_reason': 'TP'
                    })
                    position = None
            continue
        
        # Check cooldown
        if last_trade_time is not None:
            if idx - last_trade_time < cooldown:
                continue
        
        # Prepare features
        features = np.array([
            row['log_ret'],
            row['mama_diff'],
            row['dmp_30m'],
            row['dmn_30m'],
            row['stoch_k_30m'],
            row['stoch_d_30m'],
            row['wma_diff_30m'],
            row['atr'],
            row['hour'],
            row['day_of_week']
        ]).reshape(1, -1)
        
        # Check for NaN
        if np.isnan(features).any():
            continue
        
        # Get prediction
        probs = model.predict_proba(features)[0]
        prediction = model.predict(features)[0]
        confidence = float(probs[1] if prediction == 1 else probs[0])
        
        # Apply filters
        if confidence < config.prediction_threshold:
            continue
        
        if row['atr'] < 0.0003:
            continue
        
        # Enter trade
        entry_price = row['close']
        atr_value = row['atr'] * row['close']
        
        if prediction == 1:  # LONG
            sl_price = entry_price - (atr_value * config.sl_atr_mult)
            tp_price = entry_price + (atr_value * config.tp_atr_mult)
            position = {
                'side': 'LONG',
                'entry': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'size': config.position_size,
                'entry_time': idx
            }
        else:  # SHORT
            sl_price = entry_price + (atr_value * config.sl_atr_mult)
            tp_price = entry_price - (atr_value * config.tp_atr_mult)
            position = {
                'side': 'SHORT',
                'entry': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'size': config.position_size,
                'entry_time': idx
            }
        
        last_trade_time = idx
    
    return trades

def analyze_results(trades):
    """Analyze trading results."""
    if not trades:
        print("\n❌ No trades executed!")
        return
    
    df_trades = pd.DataFrame(trades)
    
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    
    total_pnl = df_trades['pnl'].sum()
    winning_trades = df_trades[df_trades['pnl'] > 0]
    losing_trades = df_trades[df_trades['pnl'] < 0]
    
    print(f"\nTotal Trades: {len(df_trades)}")
    print(f"Long Trades: {len(df_trades[df_trades['side'] == 'LONG'])}")
    print(f"Short Trades: {len(df_trades[df_trades['side'] == 'SHORT'])}")
    
    print(f"\nWinning Trades: {len(winning_trades)}")
    print(f"Losing Trades: {len(losing_trades)}")
    print(f"Win Rate: {len(winning_trades) / len(df_trades) * 100:.1f}%")
    
    print(f"\nTotal P&L: ${total_pnl:,.2f}")
    print(f"Average Win: ${winning_trades['pnl'].mean():,.2f}" if len(winning_trades) > 0 else "Average Win: N/A")
    print(f"Average Loss: ${losing_trades['pnl'].mean():,.2f}" if len(losing_trades) > 0 else "Average Loss: N/A")
    
    if len(winning_trades) > 0 and len(losing_trades) > 0:
        rr_ratio = abs(winning_trades['pnl'].mean() / losing_trades['pnl'].mean())
        print(f"Reward/Risk Ratio: {rr_ratio:.2f}")
    
    # Exit reasons
    print(f"\nExit Reasons:")
    print(df_trades['exit_reason'].value_counts())
    
    return df_trades

def main():
    """Run simple MTF backtest."""
    print("="*80)
    print("MTF ML STRATEGY - SIMPLE BACKTEST")
    print("="*80)
    
    # Configuration (using dataclass)
    from dataclasses import dataclass
    
    @dataclass
    class SimpleConfig:
        instrument_id: str = "EUR/USD.IDEALPRO"
        bar_spec: str = "15-MINUTE-MID-EXTERNAL"
        position_size: int = 100000
        model_path: str = "models/ml_model_mtf.pkl"
        prediction_threshold: float = 0.45
        sl_atr_mult: float = 1.5
        tp_atr_mult: float = 2.5
    
    config = SimpleConfig()
    
    # Load data
    df = load_and_prepare_data()
    
    # Run simulation
    print("\nRunning strategy simulation...")
    trades = simulate_strategy(df, config)
    
    # Analyze results
    df_trades = analyze_results(trades)
    
    print("\n" + "="*80)
    print("PHASE 4 BASELINE COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
