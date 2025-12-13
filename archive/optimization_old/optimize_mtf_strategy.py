#!/usr/bin/env python3
"""
Optimize MTF ML Strategy by testing different configurations.
Tests: Confidence thresholds (0.45, 0.50, 0.55) and partial closes.
"""
import sys
from pathlib import Path
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from joblib import load
import pandas_ta as ta

@dataclass
class StrategyConfig:
    name: str
    confidence_threshold: float
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    partial_close_enabled: bool = False
    partial_close_pct: float = 0.5
    partial_close_at_atr_mult: float = 1.5

def load_and_prepare_data():
    """Load 15-minute CSV data."""
    csv_path = PROJECT_ROOT / "data" / "historical" / "EUR-USD_EUR_USD_IDEALPRO_15_MINUTE_MID_EXTERNAL.csv"
    
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter to backtest period (Jan-Oct 2025)
    df = df['2025-01-01':'2025-10-30']
    
    return df

def calculate_features(df):
    """Calculate MTF features."""
    # 15m features
    df['hl2'] = (df['high'] + df['low']) / 2
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1)) * 100
    
    mama_fama = ta.mama(df['hl2'], fast=0.5, slow=0.05)
    df['mama'] = mama_fama.iloc[:, 0]
    df['fama'] = mama_fama.iloc[:, 1]
    df['mama_diff'] = (df['mama'] - df['fama']) / df['close']
    
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    # Resample to 30m
    df_30m = df.resample('30min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    # 30m indicators
    dmi_30m = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
    df_30m['dmp'] = dmi_30m.iloc[:, 1] / 100.0
    df_30m['dmn'] = dmi_30m.iloc[:, 2] / 100.0
    
    stoch_30m = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
    df_30m['stoch_k'] = stoch_30m.iloc[:, 0] / 100.0
    df_30m['stoch_d'] = stoch_30m.iloc[:, 1] / 100.0
    
    wma_short = ta.wma(df_30m['close'], length=8)
    wma_long = ta.wma(df_30m['close'], length=23)
    df_30m['wma_diff'] = 100 * (wma_short - wma_long) / wma_long
    
    # Merge
    df_30m_renamed = df_30m[['dmp', 'dmn', 'stoch_k', 'stoch_d', 'wma_diff']].copy()
    df_30m_renamed.columns = ['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']
    df = df.join(df_30m_renamed, how='left')
    df = df.ffill()
    df = df.dropna()
    
    return df

def simulate_strategy(df, config, model):
    """Simulate trading with given configuration."""
    trades = []
    position = None
    last_trade_time = None
    cooldown = pd.Timedelta(minutes=30)
    position_size = 100000
    
    for idx, row in df.iterrows():
        # Manage existing position
        if position is not None:
            # Check partial close first (if enabled and not done yet)
            if config.partial_close_enabled and not position.get('partial_closed', False):
                if position['side'] == 'LONG':
                    profit = row['close'] - position['entry']
                    atr_value = position['atr_value']
                    if profit >= atr_value * config.partial_close_at_atr_mult:
                        # Partial close
                        partial_size = position['size'] * config.partial_close_pct
                        partial_pnl = profit * partial_size
                        position['size'] -= partial_size
                        position['partial_closed'] = True
                        position['partial_pnl'] = partial_pnl
                else:  # SHORT
                    profit = position['entry'] - row['close']
                    atr_value = position['atr_value']
                    if profit >= atr_value * config.partial_close_at_atr_mult:
                        partial_size = position['size'] * config.partial_close_pct
                        partial_pnl = profit * partial_size
                        position['size'] -= partial_size
                        position['partial_closed'] = True
                        position['partial_pnl'] = partial_pnl
            
            # Check stop loss / take profit
            if position['side'] == 'LONG':
                if row['low'] <= position['sl']:
                    pnl = (position['sl'] - position['entry']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'LONG',
                        'entry': position['entry'],
                        'exit': position['sl'],
                        'pnl': pnl,
                        'exit_reason': 'SL',
                        'partial_closed': position.get('partial_closed', False)
                    })
                    position = None
                elif row['high'] >= position['tp']:
                    pnl = (position['tp'] - position['entry']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'LONG',
                        'entry': position['entry'],
                        'exit': position['tp'],
                        'pnl': pnl,
                        'exit_reason': 'TP',
                        'partial_closed': position.get('partial_closed', False)
                    })
                    position = None
            else:  # SHORT
                if row['high'] >= position['sl']:
                    pnl = (position['entry'] - position['sl']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'SHORT',
                        'entry': position['entry'],
                        'exit': position['sl'],
                        'pnl': pnl,
                        'exit_reason': 'SL',
                        'partial_closed': position.get('partial_closed', False)
                    })
                    position = None
                elif row['low'] <= position['tp']:
                    pnl = (position['entry'] - position['tp']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'SHORT',
                        'entry': position['entry'],
                        'exit': position['tp'],
                        'pnl': pnl,
                        'exit_reason': 'TP',
                        'partial_closed': position.get('partial_closed', False)
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
        
        if np.isnan(features).any():
            continue
        
        # Get prediction
        probs = model.predict_proba(features)[0]
        prediction = model.predict(features)[0]
        confidence = float(probs[1] if prediction == 1 else probs[0])
        
        # Apply filters
        if confidence < config.confidence_threshold:
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
                'size': position_size,
                'entry_time': idx,
                'atr_value': atr_value
            }
        else:  # SHORT
            sl_price = entry_price + (atr_value * config.sl_atr_mult)
            tp_price = entry_price - (atr_value * config.tp_atr_mult)
            position = {
                'side': 'SHORT',
                'entry': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'size': position_size,
                'entry_time': idx,
                'atr_value': atr_value
            }
        
        last_trade_time = idx
    
    return trades

def analyze_results(trades, config_name):
    """Analyze trading results."""
    if not trades:
        return {
            'config': config_name,
            'total_trades': 0,
            'total_pnl': 0,
            'win_rate': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'rr_ratio': 0,
            'profit_factor': 0
        }
    
    df_trades = pd.DataFrame(trades)
    
    total_pnl = df_trades['pnl'].sum()
    winning_trades = df_trades[df_trades['pnl'] > 0]
    losing_trades = df_trades[df_trades['pnl'] < 0]
    
    win_rate = len(winning_trades) / len(df_trades) * 100 if len(df_trades) > 0 else 0
    avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
    avg_loss = losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    gross_profit = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0
    gross_loss = abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    long_trades = len(df_trades[df_trades['side'] == 'LONG'])
    short_trades = len(df_trades[df_trades['side'] == 'SHORT'])
    
    partial_closed_count = len(df_trades[df_trades.get('partial_closed', False) == True]) if 'partial_closed' in df_trades.columns else 0
    
    return {
        'config': config_name,
        'total_trades': len(df_trades),
        'long_trades': long_trades,
        'short_trades': short_trades,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'rr_ratio': rr_ratio,
        'profit_factor': profit_factor,
        'partial_closed': partial_closed_count
    }

def main():
    """Run optimization tests."""
    print("="*80)
    print("MTF ML STRATEGY OPTIMIZATION")
    print("="*80)
    
    # Load model
    model = load(PROJECT_ROOT / "models" / "ml_model_mtf.pkl")
    print("✅ Model loaded")
    
    # Load and prepare data
    print("\nLoading and preparing data...")
    df = load_and_prepare_data()
    df = calculate_features(df)
    print(f"✅ Data prepared: {len(df)} bars")
    
    # Define configurations to test
    configs = [
        # Baseline
        StrategyConfig(name="Baseline (0.45)", confidence_threshold=0.45),
        
        # Higher confidence thresholds
        StrategyConfig(name="Confidence 0.50", confidence_threshold=0.50),
        StrategyConfig(name="Confidence 0.55", confidence_threshold=0.55),
        
        # Partial closes with baseline confidence
        StrategyConfig(
            name="Partial Close 50% @ 1.5×ATR (conf=0.45)",
            confidence_threshold=0.45,
            partial_close_enabled=True,
            partial_close_pct=0.5,
            partial_close_at_atr_mult=1.5
        ),
        
        # Partial closes with higher confidence
        StrategyConfig(
            name="Partial Close 50% @ 1.5×ATR (conf=0.50)",
            confidence_threshold=0.50,
            partial_close_enabled=True,
            partial_close_pct=0.5,
            partial_close_at_atr_mult=1.5
        ),
        
        StrategyConfig(
            name="Partial Close 50% @ 1.5×ATR (conf=0.55)",
            confidence_threshold=0.55,
            partial_close_enabled=True,
            partial_close_pct=0.5,
            partial_close_at_atr_mult=1.5
        ),
    ]
    
    # Run all configurations
    results = []
    for config in configs:
        print(f"\n{'='*80}")
        print(f"Testing: {config.name}")
        print(f"{'='*80}")
        
        trades = simulate_strategy(df, config, model)
        result = analyze_results(trades, config.name)
        results.append(result)
        
        print(f"Total Trades: {result['total_trades']}")
        print(f"Total P&L: ${result['total_pnl']:,.2f}")
        print(f"Win Rate: {result['win_rate']:.1f}%")
        print(f"R/R Ratio: {result['rr_ratio']:.2f}")
        print(f"Profit Factor: {result['profit_factor']:.2f}")
    
    # Compare results
    print("\n" + "="*80)
    print("COMPARISON TABLE")
    print("="*80)
    
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('total_pnl', ascending=False)
    
    print("\n" + df_results.to_string(index=False))
    
    # Best configuration
    best = df_results.iloc[0]
    print("\n" + "="*80)
    print("🏆 BEST CONFIGURATION")
    print("="*80)
    print(f"Config: {best['config']}")
    print(f"Total P&L: ${best['total_pnl']:,.2f}")
    print(f"Total Trades: {best['total_trades']}")
    print(f"Win Rate: {best['win_rate']:.1f}%")
    print(f"R/R Ratio: {best['rr_ratio']:.2f}")
    print(f"Profit Factor: {best['profit_factor']:.2f}")
    
    print("\n" + "="*80)
    print("OPTIMIZATION COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
