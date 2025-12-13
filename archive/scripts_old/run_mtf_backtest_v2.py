#!/usr/bin/env python3
"""
MTF V2 Backtest - Three-Position Bracket Approach

Uses same Parquet data and simulation approach as run_mtf_backtest_multi_layer.py
but implements the V2 architecture: 3 separate positions instead of partial closes.

Position 1 (70%): SL=1.4 ATR, TP=0.9 ATR
Position 2 (25%): SL=1.4 ATR, TP=1.75 ATR, SL->BE after POS1 TP
Position 3 (5%):  SL=1.4 ATR, TP=1.75 ATR, SL->BE after POS1 TP, Trail after POS2 TP
"""

import sys
from pathlib import Path
from datetime import datetime
import logging

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from joblib import load
import pandas_ta as ta

from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config

# Setup logging
log_buffer = []

def log_info(msg, bar_time=None):
    """Log message with optional bar time."""
    if bar_time:
        log_buffer.append(f"[{bar_time}] {msg}")
    else:
        log_buffer.append(msg)
    print(msg)


def load_and_prepare_data(config):
    """Load 15-minute data from Parquet catalog."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from Parquet catalog...")
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type}")
    
    data = {
        'timestamp': [pd.Timestamp(bar.ts_init, unit='ns', tz='UTC') for bar in bars],
        'open': [float(bar.open) for bar in bars],
        'high': [float(bar.high) for bar in bars],
        'low': [float(bar.low) for bar in bars],
        'close': [float(bar.close) for bar in bars],
        'volume': [int(bar.volume) for bar in bars]
    }
    
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter to date range
    df = df[config.backtest_start:config.backtest_end]
    
    print(f"Loaded {len(df)} bars")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    
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
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
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
    
    # Merge 30m to 15m
    df_30m_renamed = df_30m[['dmp', 'dmn', 'stoch_k', 'stoch_d', 'wma_diff']].copy()
    df_30m_renamed.columns = ['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']
    df = df.join(df_30m_renamed, how='left').ffill()
    
    return df.dropna()


def simulate_v2_strategy(df, config, model):
    """
    Simulate V2 three-position strategy.
    
    Instead of partial closes, opens 3 positions with different TPs:
    - POS1: 70%, TP at 0.9 ATR
    - POS2: 25%, TP at 1.75 ATR
    - POS3: 5%, TP at 1.75 ATR (trails after POS2 closes)
    """
    
    trades = []
    
    # Active positions (None if not open)
    positions = {
        'POS1': None,
        'POS2': None,
        'POS3': None
    }
    
    # Configuration
    sizes = {
        'POS1': config.total_position_size * config.pos1_fraction,
        'POS2': config.total_position_size * config.pos2_fraction,
        'POS3': config.total_position_size * config.pos3_fraction,
    }
    tp_mults = {
        'POS1': config.pos1_tp_atr_mult,
        'POS2': config.pos2_tp_atr_mult,
        'POS3': config.pos3_tp_atr_mult,
    }
    
    cooldown = pd.Timedelta(minutes=30)
    last_trade_time = None
    feature_cols = ['log_ret', 'mama_diff', 'dmp_30m', 'dmn_30m', 'stoch_k_30m', 
                    'stoch_d_30m', 'wma_diff_30m', 'atr', 'hour', 'day_of_week']
    
    for idx, row in df.iterrows():
        # Check if any position is open
        any_open = any(p is not None for p in positions.values())
        
        if any_open:
            side = positions['POS1']['side'] if positions['POS1'] else \
                   (positions['POS2']['side'] if positions['POS2'] else positions['POS3']['side'])
            
            # Update trailing stop for POS3 if active
            if positions['POS3'] and positions['POS3'].get('trailing_active'):
                trail_dist = positions['POS3']['atr_value'] * config.trailing_distance_atr_mult
                if side == 'LONG':
                    new_sl = row['close'] - trail_dist
                    if new_sl > positions['POS3']['sl']:
                        positions['POS3']['sl'] = new_sl
                else:
                    new_sl = row['close'] + trail_dist
                    if new_sl < positions['POS3']['sl']:
                        positions['POS3']['sl'] = new_sl
            
            # Check each position
            for pos_name in ['POS1', 'POS2', 'POS3']:
                pos = positions[pos_name]
                if pos is None:
                    continue
                
                hit_sl = False
                hit_tp = False
                exit_price = None
                exit_reason = None
                
                if pos['side'] == 'LONG':
                    if row['low'] <= pos['sl']:
                        hit_sl = True
                        exit_price = pos['sl']
                        exit_reason = 'TRAILING' if pos.get('trailing_active') else 'SL'
                    elif row['high'] >= pos['tp']:
                        hit_tp = True
                        exit_price = pos['tp']
                        exit_reason = 'TP'
                else:  # SHORT
                    if row['high'] >= pos['sl']:
                        hit_sl = True
                        exit_price = pos['sl']
                        exit_reason = 'TRAILING' if pos.get('trailing_active') else 'SL'
                    elif row['low'] <= pos['tp']:
                        hit_tp = True
                        exit_price = pos['tp']
                        exit_reason = 'TP'
                
                if hit_sl or hit_tp:
                    # Calculate PnL
                    if pos['side'] == 'LONG':
                        pnl = (exit_price - pos['entry']) * pos['size']
                    else:
                        pnl = (pos['entry'] - exit_price) * pos['size']
                    
                    trades.append({
                        'entry_time': pos['entry_time'],
                        'exit_time': idx,
                        'position': pos_name,
                        'side': pos['side'],
                        'entry': pos['entry'],
                        'exit': exit_price,
                        'size': pos['size'],
                        'pnl': pnl,
                        'exit_reason': exit_reason
                    })
                    
                    log_info(f"[{pos_name} {exit_reason}] {pos['side']} exit @ {exit_price:.5f}, "
                            f"entry={pos['entry']:.5f}, pnl=${pnl:.2f}", bar_time=idx)
                    
                    # Handle progression
                    if pos_name == 'POS1' and hit_tp:
                        # POS1 TP hit -> Move POS2/POS3 SL to breakeven+1pip
                        pip = 0.0001
                        for other in ['POS2', 'POS3']:
                            if positions[other]:
                                old_sl = positions[other]['sl']
                                if positions[other]['side'] == 'LONG':
                                    positions[other]['sl'] = positions[other]['entry'] + pip
                                else:
                                    positions[other]['sl'] = positions[other]['entry'] - pip
                                log_info(f"[{other} SL->BE] Moved from {old_sl:.5f} to {positions[other]['sl']:.5f}", 
                                        bar_time=idx)
                    
                    elif pos_name == 'POS2' and hit_tp:
                        # POS2 TP hit -> Convert POS3 to trailing
                        if positions['POS3']:
                            positions['POS3']['trailing_active'] = True
                            log_info(f"[POS3 TRAILING] Activated", bar_time=idx)
                    
                    positions[pos_name] = None
            
            continue  # Don't open new positions while any is open
        
        # No positions open - check for new signal
        
        # Session filter
        if not (config.trade_start_hour <= idx.hour < config.trade_end_hour):
            continue
        
        # Cooldown
        if last_trade_time and (idx - last_trade_time) < cooldown:
            continue
        
        # ATR filter
        atr = row['atr']
        if pd.isna(atr) or atr < config.min_atr or atr > config.max_atr:
            continue
        
        # Get prediction
        try:
            features = row[feature_cols].values.reshape(1, -1)
            if np.isnan(features).any():
                continue
            prediction = model.predict(features)[0]
            confidence = model.predict_proba(features)[0].max()
        except Exception:
            continue
        
        if confidence < config.prediction_threshold:
            continue
        
        # Open all 3 positions
        side = 'LONG' if prediction == 1 else 'SHORT'
        entry = row['close']
        atr_value = entry * atr
        
        last_trade_time = idx
        
        log_info(f"\n[ENTRY] {side} @ {entry:.5f}, ATR={atr:.5f}, conf={confidence:.3f}", bar_time=idx)
        
        for pos_name in ['POS1', 'POS2', 'POS3']:
            size = sizes[pos_name]
            tp_mult = tp_mults[pos_name]
            
            if side == 'LONG':
                sl = entry - atr_value * config.sl_atr_mult
                tp = entry + atr_value * tp_mult
            else:
                sl = entry + atr_value * config.sl_atr_mult
                tp = entry - atr_value * tp_mult
            
            positions[pos_name] = {
                'side': side,
                'entry': entry,
                'entry_time': idx,
                'sl': sl,
                'tp': tp,
                'size': size,
                'atr_value': atr_value,
                'trailing_active': False
            }
            
            log_info(f"  [{pos_name}] size={size:.0f}, SL={sl:.5f}, TP={tp:.5f} ({tp_mult}x ATR)")
    
    return trades


def analyze_results(trades, config):
    """Analyze backtest results."""
    if not trades:
        print("\nNo trades executed!")
        return None
    
    df = pd.DataFrame(trades)
    
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS - V2 Three-Position Strategy")
    print("=" * 70)
    
    total_pnl = df['pnl'].sum()
    total_trades = len(df)
    
    # By position
    print("\n[By Position]")
    for pos in ['POS1', 'POS2', 'POS3']:
        pos_df = df[df['position'] == pos]
        if len(pos_df) > 0:
            pos_pnl = pos_df['pnl'].sum()
            wins = (pos_df['pnl'] > 0).sum()
            losses = (pos_df['pnl'] <= 0).sum()
            win_rate = wins / len(pos_df) * 100 if len(pos_df) > 0 else 0
            print(f"  {pos}: {len(pos_df)} trades, PnL=${pos_pnl:,.2f}, WR={win_rate:.1f}%")
    
    # Overall
    print(f"\n[Overall]")
    print(f"  Total Trades: {total_trades}")
    print(f"  Total PnL: ${total_pnl:,.2f}")
    
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    if len(wins) > 0:
        print(f"  Winning Trades: {len(wins)}")
        print(f"  Average Win: ${wins['pnl'].mean():,.2f}")
    
    if len(losses) > 0:
        print(f"  Losing Trades: {len(losses)}")
        print(f"  Average Loss: ${losses['pnl'].mean():,.2f}")
    
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
    print(f"  Win Rate: {win_rate:.1f}%")
    
    # By exit reason
    print("\n[By Exit Reason]")
    for reason in df['exit_reason'].unique():
        r_df = df[df['exit_reason'] == reason]
        print(f"  {reason}: {len(r_df)} exits, PnL=${r_df['pnl'].sum():,.2f}")
    
    # Monthly
    df['month'] = pd.to_datetime(df['exit_time']).dt.to_period('M')
    monthly = df.groupby('month')['pnl'].sum()
    neg_months = (monthly < 0).sum()
    
    print(f"\n[Monthly]")
    print(f"  Negative Months: {neg_months}")
    print(f"  Best Month: ${monthly.max():,.2f}")
    print(f"  Worst Month: ${monthly.min():,.2f}")
    
    print("=" * 70)
    
    return df


def run_backtest():
    """Main backtest function."""
    
    print("=" * 70)
    print("MTF V2 BACKTEST - Three-Position Bracket Strategy")
    print("=" * 70)
    
    # Load config
    config = load_mtf_v2_config()
    print_mtf_v2_config(config)
    
    # Load data
    df = load_and_prepare_data(config)
    
    # Calculate features
    print("\nCalculating features...")
    df = calculate_features(df)
    print(f"After feature calculation: {len(df)} bars")
    
    # Load model
    model_path = PROJECT_ROOT / config.model_path
    model = load(model_path)
    print(f"Loaded model from {model_path}")
    
    # Run simulation
    print("\nRunning V2 simulation...")
    trades = simulate_v2_strategy(df, config, model)
    
    # Analyze
    results_df = analyze_results(trades, config)
    
    # Save results
    if results_df is not None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_{timestamp}"
        results_dir.mkdir(parents=True, exist_ok=True)
        
        results_df.to_csv(results_dir / "trades.csv", index=False)
        
        with open(results_dir / "log.txt", "w") as f:
            f.write("\n".join(log_buffer))
        
        print(f"\nResults saved to: {results_dir}")
    
    return results_df


if __name__ == "__main__":
    run_backtest()
