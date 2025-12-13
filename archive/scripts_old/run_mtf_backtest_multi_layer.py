#!/usr/bin/env python3
"""
Enhanced MTF ML Strategy Backtest with MULTI-LAYER EXIT support.

This is an experimental version that supports multiple partial close layers.
Enable by setting MTF_MULTI_LAYER_ENABLED=true in .env.mtf

Multi-Layer Exit Features:
- Support for 2-4 exit layers
- Each layer can have different trigger conditions:
  * ATR-based profit (e.g., 2.5 = close at 2.5x ATR profit)
  * Breakeven (0.0 = close when at entry price)
  * Final exit (close at TP/SL/TRAIL)
- Configurable position sizes for each layer
- Optional move SL to breakeven after first layer

Example configurations:
- Conservative (70/20/10): Lock in 70% early, 20% at breakeven, 10% continues
- Balanced (30/30/40): Three equal stages with more runner
- Aggressive (20/20/60): Small early exits, let 60% run

Falls back to standard partial close if multi-layer is disabled.
Uses .env.mtf configuration file.
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

from config.mtf_config import load_mtf_config, validate_mtf_config, print_mtf_config

def load_and_prepare_data(config):
    """Load 15-minute data from Parquet catalog based on config dates."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    # Load from Parquet catalog
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from Parquet catalog...")
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type} in catalog")
    
    # Convert to DataFrame
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
    
    # Filter to configured date range
    df = df[config.backtest_start_date:config.backtest_end_date]
    
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

def calculate_commission(position_size):
    """
    Calculate IBKR commission for forex trade.
    
    Formula: max($1.00, position_size * 0.00002)
    
    Args:
        position_size: Position size in base currency
        
    Returns:
        Commission in USD
    """
    commission = position_size * 0.00002
    return max(1.00, commission)

def update_trailing_stop(position, current_price, atr, config):
    """Update trailing stop exactly like live trading.
    
    Args:
        position: Current position dictionary
        current_price: Current bar's price
        atr: ATR value for trailing calculations
        config: Configuration object with trailing parameters
    """
    # Calculate profit in ATR units
    if position['side'] == 'LONG':
        profit = current_price - position['entry']
    else:  # SHORT
        profit = position['entry'] - current_price
    
    profit_atr = profit / atr
    
    # Check if we should activate trailing (use config parameter)
    if not position['trailing_active'] and profit_atr >= config.trailing_activation_atr_mult:
        position['trailing_active'] = True
    
    # Update trailing stop if active
    if position['trailing_active']:
        trail_distance = atr * config.trailing_distance_atr_mult  # Use config parameter
        
        if position['side'] == 'LONG':
            new_stop = current_price - trail_distance
            if position['last_stop_price'] is None or new_stop > position['last_stop_price']:
                position['sl'] = new_stop
                position['last_stop_price'] = new_stop
        else:  # SHORT
            new_stop = current_price + trail_distance
            if position['last_stop_price'] is None or new_stop < position['last_stop_price']:
                position['sl'] = new_stop
                position['last_stop_price'] = new_stop

def simulate_strategy(df, config, model, logger=None):
    """Simulate trading with detailed tracking."""
    trades = []
    position = None
    last_trade_time = None
    cooldown = pd.Timedelta(minutes=config.cooldown_minutes)
    position_size = config.position_size
    
    # Helper to log with bar timestamp instead of real-time
    def log_info(msg, bar_time=None):
        if logger:
            if bar_time:
                # Format: [Bar Time] Message
                logger.info(f"[{bar_time}] {msg}")
            else:
                logger.info(msg)
    
    for idx, row in df.iterrows():
        # Manage existing position
        if position is not None:
            # Update trailing stop first (if enabled)
            if config.trailing_stop_enabled:
                old_trailing_active = position.get('trailing_active', False)
                old_sl = position['sl']
                update_trailing_stop(position, row['close'], position['atr_value'], config)
                
                # Log trailing stop activation
                if not old_trailing_active and position.get('trailing_active', False):
                    log_info(f"[TRAILING ACTIVATED] {position['side']} trailing stop activated, new SL={position['sl']:.5f}", 
                            bar_time=idx)
                # Log trailing stop update
                elif position.get('trailing_active', False) and position['sl'] != old_sl:
                    log_info(f"[TRAILING UPDATE] {position['side']} SL moved from {old_sl:.5f} to {position['sl']:.5f}", 
                            bar_time=idx)
            
            # Multi-layer or standard partial close
            if config.multi_layer_enabled:
                # Multi-layer exit logic
                if position['side'] == 'LONG':
                    profit = row['close'] - position['entry']
                else:  # SHORT
                    profit = position['entry'] - row['close']
                
                atr_value = position['atr_value']
                profit_atr = profit / atr_value
                
                # Check each layer
                for layer_idx in range(config.multi_layer_count):
                    layer_key = f'layer_{layer_idx}_closed'
                    
                    # Skip if already closed
                    if position.get(layer_key, False):
                        continue
                    
                    trigger = config.multi_layer_triggers[layer_idx]
                    size_fraction = config.multi_layer_sizes[layer_idx]
                    
                    # Check if trigger condition met
                    should_close = False
                    
                    if trigger == "final":
                        # This layer closes at final exit (TP/SL/TRAIL)
                        continue
                    elif trigger == 0.0:
                        # Breakeven trigger - close when at or above entry
                        if profit_atr >= 0:
                            should_close = True
                    else:
                        # ATR-based trigger
                        if profit_atr >= trigger:
                            should_close = True
                    
                    if should_close:
                        # Close this layer
                        layer_size = position['initial_size'] * size_fraction
                        layer_pnl = profit * layer_size
                        
                        # Add commission for this partial close
                        layer_commission = calculate_commission(layer_size)
                        position['total_commission'] += layer_commission
                        
                        # Track layer closure
                        position[layer_key] = True
                        position['size'] -= layer_size
                        
                        # Accumulate partial P&L
                        if 'partial_pnl' not in position:
                            position['partial_pnl'] = 0
                        position['partial_pnl'] += layer_pnl
                        
                        # Mark that we had partial closes
                        position['partial_closed'] = True
                        
                        # Log partial close
                        log_info(f"[PARTIAL CLOSE] Layer {layer_idx+1}/{config.multi_layer_count} closed at {row['close']:.5f}, "
                                f"profit={profit_atr:.2f}xATR, layer_pnl=${layer_pnl:.2f}, remaining_size={position['size']:.0f}", 
                                bar_time=idx)
                        
                        # Move SL to breakeven after first layer (if configured)
                        if layer_idx == 0 and config.multi_layer_move_sl_to_be:
                            position['sl'] = position['entry']
                            log_info(f"[SL MOVED] Stop moved to breakeven at {position['entry']:.5f}", bar_time=idx)
            
            elif config.partial_close_enabled and not position.get('partial_closed', False):
                # Standard single partial close (original logic)
                if position['side'] == 'LONG':
                    profit = row['close'] - position['entry']
                    atr_value = position['atr_value']
                    if profit >= atr_value * config.partial_close_atr_mult:
                        partial_size = position['size'] * config.partial_close_fraction
                        partial_pnl = profit * partial_size
                        # Add commission for partial close
                        partial_commission = calculate_commission(partial_size)
                        position['total_commission'] += partial_commission
                        position['size'] -= partial_size
                        position['partial_closed'] = True
                        position['partial_pnl'] = partial_pnl
                        profit_atr = profit / atr_value
                        log_info(f"[PARTIAL CLOSE] Standard close at {row['close']:.5f}, "
                                f"profit={profit_atr:.2f}xATR, pnl=${partial_pnl:.2f}, remaining_size={position['size']:.0f}", 
                                bar_time=idx)
                        if config.partial_close_move_sl_to_be:
                            log_info(f"[SL MOVED] Stop moved to breakeven at {position['entry']:.5f}", bar_time=idx)
                else:  # SHORT
                    profit = position['entry'] - row['close']
                    atr_value = position['atr_value']
                    if profit >= atr_value * config.partial_close_atr_mult:
                        partial_size = position['size'] * config.partial_close_fraction
                        partial_pnl = profit * partial_size
                        # Add commission for partial close
                        partial_commission = calculate_commission(partial_size)
                        position['total_commission'] += partial_commission
                        position['size'] -= partial_size
                        position['partial_closed'] = True
                        position['partial_pnl'] = partial_pnl
                        profit_atr = profit / atr_value
                        log_info(f"[PARTIAL CLOSE] Standard close at {row['close']:.5f}, "
                                f"profit={profit_atr:.2f}xATR, pnl=${partial_pnl:.2f}, remaining_size={position['size']:.0f}", 
                                bar_time=idx)
                        if config.partial_close_move_sl_to_be:
                            log_info(f"[SL MOVED] Stop moved to breakeven at {position['entry']:.5f}", bar_time=idx)
            
            # Check stop loss / take profit
            if position['side'] == 'LONG':
                if row['low'] <= position['sl']:
                    pnl = (position['sl'] - position['entry']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    # Add final exit commission and subtract total commissions
                    final_commission = calculate_commission(position['size'])
                    total_commission = position['total_commission'] + final_commission
                    pnl -= total_commission
                    # Determine if this was trailing stop or regular SL
                    exit_type = 'TRAILING_STOP' if position.get('trailing_active', False) else 'SL'
                    duration = (idx - position['entry_time']).total_seconds() / 900
                    log_info(f"[EXIT {exit_type}] Long closed at {position['sl']:.5f}, "
                            f"entry={position['entry']:.5f}, pnl=${pnl:.2f}, duration={duration:.0f} bars, "
                            f"partial_closed={position.get('partial_closed', False)}", 
                            bar_time=idx)
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'LONG',
                        'entry': position['entry'],
                        'exit': position['sl'],
                        'pnl': pnl,
                        'exit_reason': exit_type,
                        'partial_closed': position.get('partial_closed', False),
                        'entry_hour': position['entry_time'].hour,
                        'entry_weekday': position['entry_time'].dayofweek,
                        'duration_bars': duration
                    })
                    position = None
                elif row['high'] >= position['tp']:
                    pnl = (position['tp'] - position['entry']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    # Add final exit commission and subtract total commissions
                    final_commission = calculate_commission(position['size'])
                    total_commission = position['total_commission'] + final_commission
                    pnl -= total_commission
                    duration = (idx - position['entry_time']).total_seconds() / 900
                    log_info(f"[EXIT TP] Long closed at {position['tp']:.5f}, "
                            f"entry={position['entry']:.5f}, pnl=${pnl:.2f}, duration={duration:.0f} bars, "
                            f"partial_closed={position.get('partial_closed', False)}", 
                            bar_time=idx)
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'LONG',
                        'entry': position['entry'],
                        'exit': position['tp'],
                        'pnl': pnl,
                        'exit_reason': 'TP',
                        'partial_closed': position.get('partial_closed', False),
                        'entry_hour': position['entry_time'].hour,
                        'entry_weekday': position['entry_time'].dayofweek,
                        'duration_bars': duration
                    })
                    position = None
            else:  # SHORT
                if row['high'] >= position['sl']:
                    pnl = (position['entry'] - position['sl']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    # Add final exit commission and subtract total commissions
                    final_commission = calculate_commission(position['size'])
                    total_commission = position['total_commission'] + final_commission
                    pnl -= total_commission
                    # Determine if this was trailing stop or regular SL
                    exit_type = 'TRAILING_STOP' if position.get('trailing_active', False) else 'SL'
                    duration = (idx - position['entry_time']).total_seconds() / 900
                    log_info(f"[EXIT {exit_type}] Short closed at {position['sl']:.5f}, "
                            f"entry={position['entry']:.5f}, pnl=${pnl:.2f}, duration={duration:.0f} bars, "
                            f"partial_closed={position.get('partial_closed', False)}", 
                            bar_time=idx)
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'SHORT',
                        'entry': position['entry'],
                        'exit': position['sl'],
                        'pnl': pnl,
                        'exit_reason': exit_type,
                        'partial_closed': position.get('partial_closed', False),
                        'entry_hour': position['entry_time'].hour,
                        'entry_weekday': position['entry_time'].dayofweek,
                        'duration_bars': duration
                    })
                    position = None
                elif row['low'] <= position['tp']:
                    pnl = (position['entry'] - position['tp']) * position['size']
                    if 'partial_pnl' in position:
                        pnl += position['partial_pnl']
                    # Add final exit commission and subtract total commissions
                    final_commission = calculate_commission(position['size'])
                    total_commission = position['total_commission'] + final_commission
                    pnl -= total_commission
                    duration = (idx - position['entry_time']).total_seconds() / 900
                    log_info(f"[EXIT TP] Short closed at {position['tp']:.5f}, "
                            f"entry={position['entry']:.5f}, pnl=${pnl:.2f}, duration={duration:.0f} bars, "
                            f"partial_closed={position.get('partial_closed', False)}", 
                            bar_time=idx)
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': 'SHORT',
                        'entry': position['entry'],
                        'exit': position['tp'],
                        'pnl': pnl,
                        'exit_reason': 'TP',
                        'partial_closed': position.get('partial_closed', False),
                        'entry_hour': position['entry_time'].hour,
                        'entry_weekday': position['entry_time'].dayofweek,
                        'duration_bars': duration
                    })
                    position = None
            
            # Check if we would have had a valid signal (blocked by existing position)
            if position is not None:
                # Quick check: do we have enough features for prediction?
                if not np.isnan([row['log_ret'], row['mama_diff'], row['atr']]).any():
                    features = np.array([
                        row['log_ret'], row['mama_diff'], row['dmp_30m'], row['dmn_30m'],
                        row['stoch_k_30m'], row['stoch_d_30m'], row['wma_diff_30m'],
                        row['atr'], row['hour'], row['day_of_week']
                    ]).reshape(1, -1)
                    if not np.isnan(features).any():
                        probs = model.predict_proba(features)[0]
                        prediction = model.predict(features)[0]
                        confidence = float(probs[1] if prediction == 1 else probs[0])
                        # Check if this would have passed filters
                        if (confidence >= config.prediction_threshold and 
                            row['atr'] >= config.min_atr and row['atr'] <= config.max_atr):
                            signal_type = "LONG" if prediction == 1 else "SHORT"
                            log_info(f"[BLOCKED] {signal_type} signal blocked by open {position['side']} position "
                                    f"(conf={confidence:.3f}, opened at {position['entry_time']})", 
                                    bar_time=idx)
            continue
        
        # If we reach here, no position is open and we can evaluate new signals
        
        # Check cooldown
        if last_trade_time is not None:
            time_since_last = idx - last_trade_time
            if time_since_last < cooldown:
                # Only log cooldown on predictions (not every bar)
                continue
        
        # Check weekday-specific hour exclusions
        current_hour = idx.hour
        current_weekday = idx.dayofweek  # 0=Monday, 6=Sunday
        
        # Check weekday-specific excluded hours (config uses integer keys 0-6)
        if config.excluded_hours_by_weekday:
            excluded_hours_today = config.excluded_hours_by_weekday.get(current_weekday, [])
            if current_hour in excluded_hours_today:
                continue
        elif config.excluded_hours:
            # Fallback to global exclusions
            if current_hour in config.excluded_hours:
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
        
        # Log prediction
        log_info(f"[PREDICTION] prediction={prediction}, confidence={confidence:.3f}, "
                f"ATR={row['atr']:.5f}, mama_diff={row['mama_diff']:.5f}, stoch_k_30m={row['stoch_k_30m']:.3f}", 
                bar_time=idx)
        
        # Apply filters
        if confidence < config.prediction_threshold:
            log_info(f"[FILTERED] Confidence too low: {confidence:.3f} < {config.prediction_threshold} "
                    f"(prediction={prediction})", bar_time=idx)
            continue
        
        if row['atr'] < config.min_atr:
            log_info(f"[FILTERED] ATR too low: {row['atr']:.5f} < {config.min_atr}", bar_time=idx)
            continue
        
        if row['atr'] > config.max_atr:
            log_info(f"[FILTERED] ATR too high: {row['atr']:.5f} > {config.max_atr}", bar_time=idx)
            continue
        
        # Signal passed all filters
        signal_type = "LONG" if prediction == 1 else "SHORT"
        log_info(f"[SIGNAL PASSED] {signal_type} signal - prediction={prediction}, confidence={confidence:.3f}, ATR={row['atr']:.5f}", 
                bar_time=idx)
        
        # Enter trade
        entry_price = row['close']
        atr_value = row['atr'] * row['close']
        
        if prediction == 1:  # LONG
            sl_price = entry_price - (atr_value * config.sl_atr_mult)
            tp_price = entry_price + (atr_value * config.tp_atr_mult)
            sl_atr_dist = (entry_price - sl_price) / atr_value
            tp_atr_dist = (tp_price - entry_price) / atr_value
            
            log_info(f"[ORDER] Long entry at {entry_price:.5f}, confidence={confidence:.3f}, "
                    f"SL: {sl_price:.5f} ({sl_atr_dist:.2f}xATR), TP: {tp_price:.5f} ({tp_atr_dist:.2f}xATR), "
                    f"Trailing: {'Enabled' if config.trailing_stop_enabled else 'Disabled'}", 
                    bar_time=idx)
            
            position = {
                'side': 'LONG',
                'entry': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'size': position_size,
                'initial_size': position_size,  # For multi-layer tracking
                'entry_time': idx,
                'atr_value': atr_value,
                'partial_closed': False,
                'trailing_active': False,  # For trailing stop
                'last_stop_price': None,   # Track last trailing level
                'total_commission': calculate_commission(position_size)  # Entry commission
            }
        else:  # SHORT
            sl_price = entry_price + (atr_value * config.sl_atr_mult)
            tp_price = entry_price - (atr_value * config.tp_atr_mult)
            sl_atr_dist = (sl_price - entry_price) / atr_value
            tp_atr_dist = (entry_price - tp_price) / atr_value
            
            log_info(f"[ORDER] Short entry at {entry_price:.5f}, confidence={confidence:.3f}, "
                    f"SL: {sl_price:.5f} ({sl_atr_dist:.2f}xATR), TP: {tp_price:.5f} ({tp_atr_dist:.2f}xATR), "
                    f"Trailing: {'Enabled' if config.trailing_stop_enabled else 'Disabled'}", 
                    bar_time=idx)
            
            position = {
                'side': 'SHORT',
                'entry': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'size': position_size,
                'initial_size': position_size,  # For multi-layer tracking
                'entry_time': idx,
                'atr_value': atr_value,
                'partial_closed': False,
                'trailing_active': False,  # For trailing stop
                'last_stop_price': None,   # Track last trailing level
                'total_commission': calculate_commission(position_size)  # Entry commission
            }
        
        last_trade_time = idx
    
    return trades

def analyze_by_hour(df_trades):
    """Analyze performance by hour of day."""
    print("\n" + "="*80)
    print("PERFORMANCE BY HOUR")
    print("="*80)
    
    hour_stats = []
    for hour in range(24):
        hour_trades = df_trades[df_trades['entry_hour'] == hour]
        if len(hour_trades) == 0:
            continue
        
        winning = hour_trades[hour_trades['pnl'] > 0]
        total_pnl = hour_trades['pnl'].sum()
        win_rate = len(winning) / len(hour_trades) * 100
        
        hour_stats.append({
            'hour': hour,
            'trades': len(hour_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': hour_trades['pnl'].mean()
        })
    
    df_hour = pd.DataFrame(hour_stats)
    df_hour = df_hour.sort_values('total_pnl', ascending=False)
    
    print(f"\n{'Hour':<6} {'Trades':<8} {'Win Rate':<12} {'Total P&L':<15} {'Avg P&L':<12}")
    print("-"*60)
    for _, row in df_hour.iterrows():
        print(f"{int(row['hour']):02d}:00  {int(row['trades']):<8} {row['win_rate']:>10.1f}%  ${row['total_pnl']:>12,.2f}  ${row['avg_pnl']:>10,.2f}")
    
    return df_hour

def analyze_by_weekday(df_trades):
    """Analyze performance by day of week."""
    print("\n" + "="*80)
    print("PERFORMANCE BY WEEKDAY")
    print("="*80)
    
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    weekday_stats = []
    for day in range(7):
        day_trades = df_trades[df_trades['entry_weekday'] == day]
        if len(day_trades) == 0:
            continue
        
        winning = day_trades[day_trades['pnl'] > 0]
        total_pnl = day_trades['pnl'].sum()
        win_rate = len(winning) / len(day_trades) * 100
        
        weekday_stats.append({
            'weekday': weekday_names[day],
            'trades': len(day_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': day_trades['pnl'].mean()
        })
    
    df_weekday = pd.DataFrame(weekday_stats)
    df_weekday = df_weekday.sort_values('total_pnl', ascending=False)
    
    print(f"\n{'Weekday':<12} {'Trades':<8} {'Win Rate':<12} {'Total P&L':<15} {'Avg P&L':<12}")
    print("-"*65)
    for _, row in df_weekday.iterrows():
        print(f"{row['weekday']:<12} {int(row['trades']):<8} {row['win_rate']:>10.1f}%  ${row['total_pnl']:>12,.2f}  ${row['avg_pnl']:>10,.2f}")
    
    return df_weekday

def analyze_by_month(df_trades):
    """Analyze performance by month."""
    print("\n" + "="*80)
    print("PERFORMANCE BY MONTH")
    print("="*80)
    
    # Add month column (suppress timezone warning)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df_trades['entry_month'] = pd.to_datetime(df_trades['entry_time']).dt.to_period('M')
    
    month_stats = []
    for month in df_trades['entry_month'].unique():
        month_trades = df_trades[df_trades['entry_month'] == month]
        winning = month_trades[month_trades['pnl'] > 0]
        total_pnl = month_trades['pnl'].sum()
        win_rate = len(winning) / len(month_trades) * 100
        
        month_stats.append({
            'month': str(month),
            'trades': len(month_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': month_trades['pnl'].mean()
        })
    
    df_month = pd.DataFrame(month_stats)
    df_month = df_month.sort_values('month')
    
    print(f"\n{'Month':<12} {'Trades':<8} {'Win Rate':<12} {'Total P&L':<15} {'Avg P&L':<12}")
    print("-"*65)
    for _, row in df_month.iterrows():
        print(f"{row['month']:<12} {int(row['trades']):<8} {row['win_rate']:>10.1f}%  ${row['total_pnl']:>12,.2f}  ${row['avg_pnl']:>10,.2f}")
    
    return df_month

def save_detailed_report(df_trades, df_hour, df_weekday, df_month, report_dir):
    """Save detailed report to file."""
    # report_dir is now passed in, so we use it directly
    report_dir.mkdir(parents=True, exist_ok=True)
    
    # Save trades CSV
    df_trades.to_csv(report_dir / "trades.csv", index=False)
    
    # Save hour analysis
    df_hour.to_csv(report_dir / "performance_by_hour.csv", index=False)
    
    # Save weekday analysis
    df_weekday.to_csv(report_dir / "performance_by_weekday.csv", index=False)
    
    # Save monthly analysis
    df_month.to_csv(report_dir / "performance_by_month.csv", index=False)
    
    # Create hour × weekday matrices (for optimization analysis)
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # P&L matrix
    pnl_matrix = pd.pivot_table(
        df_trades,
        values='pnl',
        index='entry_hour',
        columns='entry_weekday',
        aggfunc='sum',
        fill_value=0
    )
    pnl_matrix.columns = [weekday_names[int(col)] for col in pnl_matrix.columns]
    pnl_matrix.to_csv(report_dir / "hour_weekday_pnl_matrix.csv")
    
    # Trades count matrix
    trades_matrix = pd.pivot_table(
        df_trades,
        values='pnl',
        index='entry_hour',
        columns='entry_weekday',
        aggfunc='count',
        fill_value=0
    )
    trades_matrix.columns = [weekday_names[int(col)] for col in trades_matrix.columns]
    trades_matrix.to_csv(report_dir / "hour_weekday_trades_matrix.csv")
    
    # Win rate matrix
    def win_rate(x):
        return (x > 0).sum() / len(x) * 100 if len(x) > 0 else 0
    
    winrate_matrix = pd.pivot_table(
        df_trades,
        values='pnl',
        index='entry_hour',
        columns='entry_weekday',
        aggfunc=win_rate,
        fill_value=0
    )
    winrate_matrix.columns = [weekday_names[int(col)] for col in winrate_matrix.columns]
    winrate_matrix.to_csv(report_dir / "hour_weekday_winrate_matrix.csv")
    
    # Save summary report
    with open(report_dir / "summary.txt", 'w') as f:
        f.write("="*80 + "\n")
        f.write("MTF ML STRATEGY - DETAILED BACKTEST REPORT\n")
        f.write("="*80 + "\n\n")
        
        f.write(f"Period: 2025-01-01 to 2025-12-31\n")
        f.write(f"Total Trades: {len(df_trades)}\n")
        f.write(f"Total P&L: ${df_trades['pnl'].sum():,.2f}\n")
        f.write(f"Win Rate: {len(df_trades[df_trades['pnl'] > 0]) / len(df_trades) * 100:.1f}%\n\n")
        
        f.write("="*80 + "\n")
        f.write("TOP 5 HOURS BY P&L\n")
        f.write("="*80 + "\n")
        for _, row in df_hour.head(5).iterrows():
            f.write(f"{int(row['hour']):02d}:00 - ${row['total_pnl']:,.2f} ({int(row['trades'])} trades, {row['win_rate']:.1f}% win rate)\n")
        
        f.write("\n" + "="*80 + "\n")
        f.write("TOP 3 WEEKDAYS BY P&L\n")
        f.write("="*80 + "\n")
        for _, row in df_weekday.head(3).iterrows():
            f.write(f"{row['weekday']} - ${row['total_pnl']:,.2f} ({int(row['trades'])} trades, {row['win_rate']:.1f}% win rate)\n")
    
    # Copy .env.mtf file to preserve exact configuration used
    import shutil
    env_source = report_dir.parent.parent / ".env.mtf"
    if env_source.exists():
        shutil.copy2(env_source, report_dir / ".env.mtf")
        print(f"Configuration saved: .env.mtf")
    
    print(f"\nDetailed report saved to: {report_dir}")

def main():
    """Run detailed MTF backtest."""
    print("="*80)
    print("MTF ML STRATEGY - DETAILED BACKTEST")
    print("="*80)
    
    # Load configuration from .env.mtf
    print("\nLoading configuration from .env.mtf...")
    config = load_mtf_config()
    print_mtf_config(config)
    
    if not validate_mtf_config(config):
        print("\nConfiguration validation failed!")
        return 1
    
    # Load model
    model = load(PROJECT_ROOT / config.model_path)
    print(f"\nModel loaded from {config.model_path}")
    
    # Load and prepare data
    # Debug: Print exact config being used
    print("\n" + "="*80)
    print("CONFIGURATION DEBUG")
    print("="*80)
    print(f"Partial Close ATR Mult: {config.partial_close_atr_mult}")
    print(f"Trailing Activation ATR Mult: {config.trailing_activation_atr_mult}")
    print(f"Trailing Distance ATR Mult: {config.trailing_distance_atr_mult}")
    print(f"Trailing Enabled: {config.trailing_stop_enabled}")
    print(f"Partial Close Enabled: {config.partial_close_enabled}")
    print(f"Prediction Threshold: {config.prediction_threshold}")
    print(f"Min ATR: {config.min_atr}")
    print(f"Max ATR: {config.max_atr}")
    print(f"Cooldown Minutes: {config.cooldown_minutes}")
    print(f"Excluded Hours by Weekday: {config.excluded_hours_by_weekday}")
    print(f"Excluded Hours (global): {config.excluded_hours}")
    print("="*80)
    
    print("\nLoading and preparing data...")
    df = load_and_prepare_data(config)
    df = calculate_features(df)
    print(f"Data prepared: {len(df)} bars")
    
    # Setup logger for strategy decisions (will be saved to report directory)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "backtest_results"
    report_dir = output_dir / f"MTF_ML_{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    # Create strategy logger (no timestamp - we use bar time instead)
    strategy_logger = logging.getLogger('backtest_strategy')
    strategy_logger.setLevel(logging.INFO)
    strategy_handler = logging.FileHandler(report_dir / "strategy_decisions.log")
    strategy_handler.setFormatter(logging.Formatter('%(message)s'))  # Only message, bar time is in the message
    strategy_logger.addHandler(strategy_handler)
    strategy_logger.info("="*80)
    strategy_logger.info("BACKTEST STRATEGY DECISIONS LOG")
    strategy_logger.info("="*80)
    strategy_logger.info(f"Backtest period: {config.backtest_start_date} to {config.backtest_end_date}")
    strategy_logger.info(f"Prediction threshold: {config.prediction_threshold}")
    strategy_logger.info(f"ATR range: {config.min_atr} - {config.max_atr}")
    strategy_logger.info("="*80)
    
    # Run backtest
    print(f"\nRunning backtest...")
    trades = simulate_strategy(df, config, model, logger=strategy_logger)
    
    if not trades:
        print("\nNo trades executed!")
        return
    
    df_trades = pd.DataFrame(trades)
    
    # Overall statistics
    print("\n" + "="*80)
    print("OVERALL PERFORMANCE")
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
    print(f"Average Win: ${winning_trades['pnl'].mean():,.2f}")
    print(f"Average Loss: ${losing_trades['pnl'].mean():,.2f}")
    
    if len(winning_trades) > 0 and len(losing_trades) > 0:
        rr_ratio = abs(winning_trades['pnl'].mean() / losing_trades['pnl'].mean())
        print(f"Reward/Risk Ratio: {rr_ratio:.2f}")
    
    gross_profit = winning_trades['pnl'].sum()
    gross_loss = abs(losing_trades['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    print(f"Profit Factor: {profit_factor:.2f}")
    
    # Partial close stats
    partial_closed = len(df_trades[df_trades['partial_closed'] == True])
    print(f"\nPartial Closes: {partial_closed} ({partial_closed/len(df_trades)*100:.1f}% of trades)")
    
    # Duration stats
    print(f"\nAverage Trade Duration: {df_trades['duration_bars'].mean():.1f} bars ({df_trades['duration_bars'].mean() * 15:.0f} minutes)")
    
    # Analyze by hour, weekday, and month
    df_hour = analyze_by_hour(df_trades)
    df_weekday = analyze_by_weekday(df_trades)
    df_month = analyze_by_month(df_trades)
    
    # Save detailed report (reuse the report_dir we already created)
    save_detailed_report(df_trades, df_hour, df_weekday, df_month, report_dir)
    
    # Close logger handler
    strategy_handler.close()
    strategy_logger.removeHandler(strategy_handler)

    print("\n" + "="*80)
    print("BACKTEST COMPLETE")
    print("="*80)
    print(f"\nReport saved to: {report_dir}")
    print("\nFiles created:")
    print("  - strategy_decisions.log (similar to live strategy.log)")
    print("  - trades.csv")
    print("  - performance_by_hour.csv")
    print("  - performance_by_weekday.csv")
    print("  - performance_by_month.csv")
    print("  - hour_weekday_pnl_matrix.csv")
    print("  - hour_weekday_trades_matrix.csv")
    print("  - hour_weekday_winrate_matrix.csv")
    print("  - summary.txt")
    print("  - .env.mtf (configuration backup)")

if __name__ == "__main__":
    main()
