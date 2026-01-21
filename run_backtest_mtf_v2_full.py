"""
MTF V2 Backtest with Full Reporting.

Generates the same output files as the reference backtest:
- summary.txt
- trades.csv
- performance_by_hour.csv
- performance_by_weekday.csv
- performance_by_month.csv
- hour_weekday_pnl_matrix.csv
- hour_weekday_trades_matrix.csv
- hour_weekday_winrate_matrix.csv
- strategy_decisions.log
"""

import sys
from pathlib import Path
from datetime import datetime
import shutil

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
import pandas_ta as ta
from joblib import load
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from config.mtf_v2_config import load_mtf_v2_config, print_mtf_v2_config


def load_and_prepare_data(start_date: str, end_date: str) -> pd.DataFrame:
    """Load 15-minute bar data from catalog."""
    catalog = ParquetDataCatalog(str(PROJECT_ROOT / "data" / "historical"))
    
    # Load 15-minute bars specifically
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type}...")
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type}")
    
    df = pd.DataFrame({
        'timestamp': [pd.Timestamp(b.ts_init, unit='ns', tz='UTC') for b in bars],
        'open': [float(b.open) for b in bars],
        'high': [float(b.high) for b in bars],
        'low': [float(b.low) for b in bars],
        'close': [float(b.close) for b in bars],
        'volume': [float(b.volume) for b in bars],
    })
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    
    # Filter to date range
    df = df[start_date:end_date]
    return df


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate MTF features matching the model's training."""
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
    """IBKR forex commission."""
    return max(1.00, position_size * 0.00002)


def utc_to_est(utc_timestamp):
    """
    Convert UTC timestamp to US Eastern time (handles EST/EDT automatically).
    Uses zoneinfo for proper DST handling.
    """
    import zoneinfo
    
    try:
        # Convert to Eastern time (handles DST automatically)
        eastern = zoneinfo.ZoneInfo('America/New_York')
        eastern_dt = utc_timestamp.astimezone(eastern)
        return eastern_dt.hour, eastern_dt.weekday()
    except Exception:
        # Fallback to simple -5 offset if zoneinfo fails
        est_hour = utc_timestamp.hour - 5
        est_weekday = utc_timestamp.weekday()
        if est_hour < 0:
            est_hour += 24
            est_weekday = (est_weekday - 1) % 7
        return est_hour, est_weekday


def simulate_2pos_strategy(df: pd.DataFrame, model, config: dict, log_file=None) -> list:
    """
    Simulate 2-position bracket strategy matching optimize_2pos_sim.py exactly.
    """
    trades = []
    position = None
    position_size = config['position_size']
    entry_cooldown_bars = int(config.get('entry_cooldown_bars', 0) or 0)
    cooldown_remaining_bars = 0
    
    # Get excluded hours by weekday
    excluded_hours_mode = config.get('excluded_hours_mode', 'simple')
    config_timezone = config.get('config_timezone', 'UTC').upper()
    excluded_hours = {
        0: config.get('excluded_hours_monday', []),
        1: config.get('excluded_hours_tuesday', []),
        2: config.get('excluded_hours_wednesday', []),
        3: config.get('excluded_hours_thursday', []),
        4: config.get('excluded_hours_friday', []),
        5: config.get('excluded_hours_saturday', []),
        6: config.get('excluded_hours_sunday', []),
    }
    
    for idx, row in df.iterrows():
        # Entry cooldown (after any trade exit)
        if position is None and cooldown_remaining_bars > 0:
            cooldown_remaining_bars -= 1
            continue

        # Manage existing position
        if position is not None:
            current_price = row['close']
            atr_value = position['atr_value']
            
            # Calculate profit in ATR units
            if position['side'] == 'LONG':
                profit = current_price - position['entry']
            else:
                profit = position['entry'] - current_price
            
            profit_atr = profit / atr_value
            
            # Update stall detection tracking
            position['bars_in_trade'] += 1
            if profit_atr > position['max_profit_atr']:
                position['max_profit_atr'] = profit_atr
            
            # Stall detection: tighten SL if not progressing to TP1
            if (config.get('stall_detection_enabled', False) and 
                not position.get('pos1_closed', False) and 
                not position.get('stall_sl_applied', False)):
                
                stall_check_bars = config.get('stall_check_bars', 6)
                stall_min_profit_atr = config.get('stall_min_profit_atr', 0.2)
                stall_sl_atr = config.get('stall_sl_atr', 0.2)
                tp1_atr = config['pos1_tp_atr_mult']
                
                # Check if trade has been open long enough and is in stall zone
                if (position['bars_in_trade'] >= stall_check_bars and
                    stall_min_profit_atr <= position['max_profit_atr'] < tp1_atr):
                    
                    # Tighten SL to lock in some profit
                    new_sl_distance = atr_value * stall_sl_atr
                    if position['side'] == 'LONG':
                        new_sl = position['entry'] + new_sl_distance
                        if new_sl > position['sl']:
                            position['sl'] = new_sl
                            position['stall_sl_applied'] = True
                            if log_file:
                                log_file.write(f"{idx} | STALL detected: max={position['max_profit_atr']:.2f} ATR, SL tightened to {stall_sl_atr} ATR\n")
                    else:
                        new_sl = position['entry'] - new_sl_distance
                        if new_sl < position['sl']:
                            position['sl'] = new_sl
                            position['stall_sl_applied'] = True
                            if log_file:
                                log_file.write(f"{idx} | STALL detected: max={position['max_profit_atr']:.2f} ATR, SL tightened to {stall_sl_atr} ATR\n")
            
            # Check POS1 TP (if not closed)
            if not position.get('pos1_closed', False):
                if profit_atr >= config['pos1_tp_atr_mult']:
                    # Close POS1
                    layer_size = position['initial_size'] * config['pos1_fraction']
                    layer_pnl = profit * layer_size
                    layer_commission = calculate_commission(layer_size)
                    
                    position['pos1_closed'] = True
                    position['pos1_pnl'] = layer_pnl - layer_commission
                    position['size'] -= layer_size
                    
                    # Move POS2 SL to breakeven + 1 pip
                    position['sl'] = position['entry'] + (0.0001 if position['side'] == 'LONG' else -0.0001)
                    
                    # Activate trailing for POS2
                    position['trailing_active'] = True
                    
                    if log_file:
                        log_file.write(f"{idx} | POS1 TP hit, profit_atr={profit_atr:.2f}, SL->BE, trailing ON\n")
            
            # Update trailing stop for POS2 (if active)
            if position.get('trailing_active', False):
                trail_distance = atr_value * config['trailing_distance_atr_mult']
                
                if position['side'] == 'LONG':
                    new_sl = current_price - trail_distance
                    if new_sl > position['sl']:
                        position['sl'] = new_sl
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < position['sl']:
                        position['sl'] = new_sl
            
            # Check POS2 TP (only if there's remaining position size)
            if not position.get('pos2_closed', False) and position.get('pos1_closed', False) and position['size'] > 0:
                if profit_atr >= config['pos2_tp_atr_mult']:
                    # Close POS2 at TP
                    layer_size = position['size']
                    layer_pnl = profit * layer_size
                    layer_commission = calculate_commission(layer_size)
                    
                    total_pnl = position.get('pos1_pnl', 0) + layer_pnl - layer_commission
                    
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': idx,
                        'side': position['side'],
                        'entry': position['entry'],
                        'exit': current_price,
                        'pnl': total_pnl,
                        'exit_reason': 'TP',
                        'partial_closed': True,
                        'entry_hour': position['entry_hour'],  # Use stored config timezone value
                        'entry_weekday': position['entry_weekday'],  # Use stored config timezone value
                        'duration_bars': 0,
                        'entry_month': position['entry_time'].strftime('%Y-%m'),
                    })
                    
                    if log_file:
                        log_file.write(f"{idx} | TRADE CLOSED {position['side']} TP PnL=${total_pnl:.2f}\n")
                    
                    position = None
                    if entry_cooldown_bars > 0:
                        cooldown_remaining_bars = entry_cooldown_bars
                    continue
            
            # Check SL hit (for remaining position) using high/low
            sl_hit = False
            exit_price = position['sl']
            if position['side'] == 'LONG':
                if row['low'] <= position['sl']:
                    sl_hit = True
                    exit_price = position['sl']
            else:
                if row['high'] >= position['sl']:
                    sl_hit = True
                    exit_price = position['sl']
            
            if sl_hit:
                # Calculate remaining PnL
                if position['side'] == 'LONG':
                    remaining_profit = exit_price - position['entry']
                else:
                    remaining_profit = position['entry'] - exit_price
                
                remaining_pnl = remaining_profit * position['size']
                remaining_commission = calculate_commission(position['size'])
                
                total_pnl = position.get('pos1_pnl', 0) + remaining_pnl - remaining_commission
                
                exit_type = 'TRAILING_STOP' if position.get('trailing_active', False) else 'SL'
                
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': idx,
                    'side': position['side'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': total_pnl,
                    'exit_reason': exit_type,
                    'partial_closed': position.get('pos1_closed', False),
                    'entry_hour': position['entry_hour'],  # Use stored config timezone value
                    'entry_weekday': position['entry_weekday'],  # Use stored config timezone value
                    'duration_bars': 0,
                    'entry_month': position['entry_time'].strftime('%Y-%m'),
                })
                
                if log_file:
                    log_file.write(f"{idx} | TRADE CLOSED {position['side']} {exit_type} PnL=${total_pnl:.2f}\n")
                
                position = None
                if entry_cooldown_bars > 0:
                    cooldown_remaining_bars = entry_cooldown_bars
                continue
            
            # Skip new signal evaluation if in position
            continue
        
        # No position - evaluate new signal
        # Get hour/weekday in config timezone for filtering
        if config_timezone == 'EST':
            current_hour, current_weekday = utc_to_est(idx)
        else:
            current_hour = idx.hour
            current_weekday = idx.weekday()
        
        # Session filter (always in UTC for trading hours)
        utc_hour = idx.hour
        if not (config['trade_start_hour'] <= utc_hour < config['trade_end_hour']):
            continue
        
        # Weekday-specific exclusions (in config timezone)
        if excluded_hours_mode == 'weekday':
            if current_hour in excluded_hours.get(current_weekday, []):
                continue
        
        # Prepare features
        try:
            features = np.array([
                row['log_ret'], row['mama_diff'], row['dmp_30m'], row['dmn_30m'],
                row['stoch_k_30m'], row['stoch_d_30m'], row['wma_diff_30m'],
                row['atr'], row['hour'], row['day_of_week']
            ]).reshape(1, -1)
            
            if np.isnan(features).any():
                continue
        except:
            continue
        
        # ATR filter
        atr = row['atr']
        if atr < config['min_atr'] or atr > config['max_atr']:
            continue
        
        # Get prediction
        probs = model.predict_proba(features)[0]
        prediction = model.predict(features)[0]
        confidence = float(probs[1] if prediction == 1 else probs[0])
        
        if confidence < config['prediction_threshold']:
            continue
        
        # Open position
        entry_price = row['close']
        atr_value = atr * entry_price  # Convert normalized ATR to absolute
        
        if prediction == 1:  # LONG
            sl = entry_price - (atr_value * config['sl_atr_mult'])
            side = 'LONG'
        else:  # SHORT
            sl = entry_price + (atr_value * config['sl_atr_mult'])
            side = 'SHORT'
        
        entry_commission = calculate_commission(position_size)
        
        position = {
            'entry_time': idx,
            'entry': entry_price,
            'side': side,
            'sl': sl,
            'initial_size': position_size,
            'size': position_size,
            'atr_value': atr_value,
            'trailing_active': False,
            'pos1_closed': False,
            'pos2_closed': False,
            'pos1_pnl': 0,
            'entry_commission': entry_commission,
            # Store hour/weekday in config timezone for reporting
            'entry_hour': current_hour,
            'entry_weekday': current_weekday,
            # Stall detection tracking
            'bars_in_trade': 0,
            'max_profit_atr': 0,
            'stall_sl_applied': False,
        }
        
        if log_file:
            log_file.write(f"{idx} | ENTRY {side} @ {entry_price:.5f} | SL={sl:.5f} | Conf={confidence:.3f}\n")
    
    return trades


def generate_reports(trades: list, output_dir: Path, config: dict):
    """Generate all report files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Always copy .env file, even with 0 trades
    shutil.copy(PROJECT_ROOT / '.env.mtf_v2', output_dir / '.env.mtf_v2')
    print(f"Saved: .env.mtf_v2")
    
    if not trades:
        print("No trades to analyze")
        return
    
    df = pd.DataFrame(trades)
    
    # === trades.csv ===
    df.to_csv(output_dir / 'trades.csv', index=False)
    print(f"Saved: trades.csv ({len(df)} trades)")
    
    # === Basic stats ===
    total_pnl = df['pnl'].sum()
    win_rate = (df['pnl'] > 0).mean() * 100
    total_trades = len(df)
    
    # === performance_by_hour.csv ===
    # Note: Hours are in config timezone (EST or UTC)
    config_tz = config.get('config_timezone', 'UTC').upper()

    # Include all hours, not just those with trades.
    try:
        trade_start_hour = int(config.get('trade_start_hour', 0))
        trade_end_hour = int(config.get('trade_end_hour', 24))
        if not (0 <= trade_start_hour <= 23 and 1 <= trade_end_hour <= 24 and trade_start_hour < trade_end_hour):
            raise ValueError("Invalid trade hour range")
        all_hours = list(range(trade_start_hour, trade_end_hour))
    except Exception:
        all_hours = list(range(24))

    hour_stats = df.groupby('entry_hour').agg({
        'pnl': ['sum', 'count', lambda x: (x > 0).mean() * 100]
    }).round(2)
    hour_stats.columns = ['pnl', 'trades', 'win_rate']
    hour_stats = hour_stats.reindex(all_hours, fill_value=0)
    hour_stats.index.name = f'hour_{config_tz}'
    hour_stats.to_csv(output_dir / 'performance_by_hour.csv')
    print(f"Saved: performance_by_hour.csv (hours in {config_tz})")
    
    # === performance_by_weekday.csv ===
    weekday_names = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
    all_weekdays = list(range(7))
    weekday_stats = df.groupby('entry_weekday').agg({
        'pnl': ['sum', 'count', lambda x: (x > 0).mean() * 100]
    }).round(2)
    weekday_stats.columns = ['pnl', 'trades', 'win_rate']
    weekday_stats = weekday_stats.reindex(all_weekdays, fill_value=0)
    weekday_stats.index = weekday_stats.index.map(weekday_names)
    weekday_stats.to_csv(output_dir / 'performance_by_weekday.csv')
    print(f"Saved: performance_by_weekday.csv")
    
    # === performance_by_month.csv ===
    month_stats = df.groupby('entry_month').agg({
        'pnl': ['sum', 'count', lambda x: (x > 0).mean() * 100]
    }).round(2)
    month_stats.columns = ['pnl', 'trades', 'win_rate']
    month_stats.to_csv(output_dir / 'performance_by_month.csv')
    print(f"Saved: performance_by_month.csv")
    
    # === hour_weekday matrices ===
    # Note: Hours are in config timezone (EST or UTC)
    config_timezone = config.get('config_timezone', 'UTC').upper()
    print(f"Hour statistics are in {config_timezone} timezone")
    
    pivot_pnl = df.pivot_table(values='pnl', index='entry_hour', columns='entry_weekday', aggfunc='sum', fill_value=0)
    pivot_pnl = pivot_pnl.reindex(index=all_hours, columns=all_weekdays, fill_value=0)
    pivot_pnl.columns = [weekday_names.get(c, c) for c in pivot_pnl.columns]
    pivot_pnl.index.name = f'hour_{config_timezone}'
    pivot_pnl.to_csv(output_dir / 'hour_weekday_pnl_matrix.csv', float_format='%.1f')
    print(f"Saved: hour_weekday_pnl_matrix.csv")
    
    pivot_trades = df.pivot_table(values='pnl', index='entry_hour', columns='entry_weekday', aggfunc='count', fill_value=0)
    pivot_trades = pivot_trades.reindex(index=all_hours, columns=all_weekdays, fill_value=0)
    pivot_trades.columns = [weekday_names.get(c, c) for c in pivot_trades.columns]
    pivot_trades.index.name = f'hour_{config_timezone}'
    pivot_trades.to_csv(output_dir / 'hour_weekday_trades_matrix.csv')
    print(f"Saved: hour_weekday_trades_matrix.csv")
    
    # Win rate matrix
    def win_rate_agg(x):
        return (x > 0).mean() * 100 if len(x) > 0 else 0
    
    pivot_wr = df.pivot_table(values='pnl', index='entry_hour', columns='entry_weekday', aggfunc=win_rate_agg, fill_value=0)
    pivot_wr = pivot_wr.reindex(index=all_hours, columns=all_weekdays, fill_value=0)
    pivot_wr.columns = [weekday_names.get(c, c) for c in pivot_wr.columns]
    pivot_wr.index.name = f'hour_{config_timezone}'
    pivot_wr.to_csv(output_dir / 'hour_weekday_winrate_matrix.csv')
    print(f"Saved: hour_weekday_winrate_matrix.csv")
    
    # === Calculate Drawdown Metrics ===
    # Filter out trades with invalid exit times
    df_valid = df[df['exit_time'].notna()].copy()
    df_sorted = df_valid.sort_values('exit_time').reset_index(drop=True)
    df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()
    df_sorted['running_max'] = df_sorted['cumulative_pnl'].cummax()
    df_sorted['drawdown'] = df_sorted['cumulative_pnl'] - df_sorted['running_max']
    
    max_drawdown = df_sorted['drawdown'].min()
    max_drawdown_pct = (max_drawdown / df_sorted['running_max'].max() * 100) if df_sorted['running_max'].max() > 0 else 0
    
    # Find max drawdown period
    max_dd_idx = df_sorted['drawdown'].idxmin()
    max_dd_end = df_sorted.loc[max_dd_idx, 'exit_time']
    
    # Find when the peak before drawdown occurred
    peak_mask = df_sorted.index <= max_dd_idx
    peak_before_dd = df_sorted.loc[peak_mask, 'running_max'].idxmax()
    max_dd_start = df_sorted.loc[peak_before_dd, 'exit_time']
    max_dd_duration_days = (max_dd_end - max_dd_start).days
    
    # Calculate average drawdown (only negative values)
    negative_drawdowns = df_sorted[df_sorted['drawdown'] < 0]['drawdown']
    avg_drawdown = negative_drawdowns.mean() if len(negative_drawdowns) > 0 else 0
    
    # Recovery time (if recovered)
    recovery_duration_days = None
    if df_sorted['drawdown'].iloc[-1] == 0:
        recovery_mask = (df_sorted.index > max_dd_idx) & (df_sorted['drawdown'] == 0)
        if recovery_mask.any():
            recovery_idx = df_sorted[recovery_mask].index[0]
            recovery_time = df_sorted.loc[recovery_idx, 'exit_time']
            recovery_duration_days = (recovery_time - max_dd_end).days
    
    # === Calculate Daily Statistics ===
    df['exit_date'] = pd.to_datetime(df['exit_time']).dt.date
    daily_pnl = df.groupby('exit_date')['pnl'].sum()
    
    # Get all trading days in the period
    start_date = pd.to_datetime(config['backtest_start']).date()
    end_date = pd.to_datetime(config['backtest_end']).date()
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
    trading_dates = all_dates[all_dates.dayofweek < 5]  # Weekdays only
    
    # Calculate statistics
    zero_trade_days = len([d for d in trading_dates if d.date() not in daily_pnl.index])
    negative_days = (daily_pnl < 0).sum()
    positive_days = (daily_pnl > 0).sum()
    total_trading_days = len(trading_dates)
    days_with_trades = len(daily_pnl)
    
    # === summary.txt ===
    top_hours = hour_stats.nlargest(5, 'pnl')
    top_weekdays = weekday_stats.nlargest(3, 'pnl')
    
    with open(output_dir / 'summary.txt', 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("MTF V2 STRATEGY - DETAILED BACKTEST REPORT\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"Period: {config['backtest_start']} to {config['backtest_end']}\n")
        f.write(f"Total Trades: {total_trades}\n")
        f.write(f"Total P&L: ${total_pnl:,.2f}\n")
        f.write(f"Win Rate: {win_rate:.1f}%\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("DAILY STATISTICS\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total Trading Days (Weekdays): {total_trading_days}\n")
        f.write(f"Days with Trades: {days_with_trades}\n")
        f.write(f"Zero Trade Days: {zero_trade_days} ({zero_trade_days/total_trading_days*100:.1f}%)\n")
        f.write(f"Positive Days: {positive_days} ({positive_days/days_with_trades*100:.1f}% of trading days)\n")
        f.write(f"Negative Days: {negative_days} ({negative_days/days_with_trades*100:.1f}% of trading days)\n")
        if days_with_trades > 0:
            f.write(f"Average Daily P&L: ${daily_pnl.mean():,.2f}\n")
            f.write(f"Best Day: ${daily_pnl.max():,.2f}\n")
            f.write(f"Worst Day: ${daily_pnl.min():,.2f}\n")
        f.write("\n")
        
        f.write("=" * 80 + "\n")
        f.write("DRAWDOWN ANALYSIS\n")
        f.write("=" * 80 + "\n")
        f.write(f"Max Drawdown: ${max_drawdown:,.2f} ({max_drawdown_pct:.1f}%)\n")
        f.write(f"Max Drawdown Period: {max_dd_start.strftime('%Y-%m-%d')} to {max_dd_end.strftime('%Y-%m-%d')} ({max_dd_duration_days} days)\n")
        f.write(f"Average Drawdown: ${avg_drawdown:,.2f}\n")
        if recovery_duration_days is not None:
            f.write(f"Recovery Time: {recovery_duration_days} days\n")
        else:
            f.write(f"Recovery Time: Not yet recovered\n")
        f.write(f"Current Drawdown: ${df_sorted['drawdown'].iloc[-1]:,.2f}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write(f"TOP 5 HOURS BY P&L ({config_timezone})\n")
        f.write("=" * 80 + "\n")
        for hour, row in top_hours.iterrows():
            f.write(f"{hour:02d}:00 {config_timezone} - ${row['pnl']:,.2f} ({int(row['trades'])} trades, {row['win_rate']:.1f}% win rate)\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("TOP 3 WEEKDAYS BY P&L\n")
        f.write("=" * 80 + "\n")
        for weekday, row in top_weekdays.iterrows():
            f.write(f"{weekday} - ${row['pnl']:,.2f} ({int(row['trades'])} trades, {row['win_rate']:.1f}% win rate)\n")
    
    print(f"Saved: summary.txt")
    
    # Print summary
    print("\n" + "=" * 80)
    print("BACKTEST SUMMARY")
    print("=" * 80)
    print(f"Total Trades: {total_trades}")
    print(f"Total P&L: ${total_pnl:,.2f}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Output Directory: {output_dir}")


def main():
    """Run the V2 backtest with full reporting."""
    print("=" * 80)
    print("MTF V2 BACKTEST - FULL REPORTING")
    print("=" * 80)
    
    # Load config
    config = load_mtf_v2_config()
    print_mtf_v2_config(config)
    
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "backtest_results" / f"MTF_V2_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load model
    print("\nLoading model...")
    model = load(PROJECT_ROOT / config.model_path)
    print(f"Model loaded from {config.model_path}")
    
    # Load data
    print(f"\nLoading data: {config.backtest_start} to {config.backtest_end}...")
    df = load_and_prepare_data(config.backtest_start, config.backtest_end)
    df = calculate_features(df)
    print(f"Data loaded: {len(df)} bars")
    
    # Build simulation config
    sim_config = {
        'position_size': config.total_position_size,
        'pos1_fraction': config.pos1_fraction,
        'pos2_fraction': config.pos2_fraction,
        'sl_atr_mult': config.sl_atr_mult,
        'pos1_tp_atr_mult': config.pos1_tp_atr_mult,
        'pos2_tp_atr_mult': config.pos2_tp_atr_mult,
        'trailing_distance_atr_mult': config.trailing_distance_atr_mult,
        'prediction_threshold': config.prediction_threshold,
        'trade_start_hour': config.trade_start_hour,
        'trade_end_hour': config.trade_end_hour,
        'min_atr': config.min_atr,
        'max_atr': config.max_atr,
        'config_timezone': config.config_timezone,  # EST or UTC for hour statistics
        'excluded_hours_mode': config.excluded_hours_mode,
        'excluded_hours_monday': config.excluded_hours_monday,
        'excluded_hours_tuesday': config.excluded_hours_tuesday,
        'excluded_hours_wednesday': config.excluded_hours_wednesday,
        'excluded_hours_thursday': config.excluded_hours_thursday,
        'excluded_hours_friday': config.excluded_hours_friday,
        'excluded_hours_saturday': config.excluded_hours_saturday,
        'excluded_hours_sunday': config.excluded_hours_sunday,
        'entry_cooldown_bars': config.entry_cooldown_bars,
        'backtest_start': config.backtest_start,
        'backtest_end': config.backtest_end,
        # Stall detection
        'stall_detection_enabled': config.stall_detection_enabled,
        'stall_check_bars': config.stall_check_bars,
        'stall_min_profit_atr': config.stall_min_profit_atr,
        'stall_sl_atr': config.stall_sl_atr,
    }
    
    # Run simulation with logging
    print("\nRunning simulation...")
    log_file_path = output_dir / 'strategy_decisions.log'
    with open(log_file_path, 'w') as log_file:
        log_file.write(f"MTF V2 Backtest Log - {timestamp}\n")
        log_file.write("=" * 80 + "\n\n")
        trades = simulate_2pos_strategy(df, model, sim_config, log_file)
    
    print(f"Simulation complete: {len(trades)} trades")
    print(f"Saved: strategy_decisions.log")
    
    # Generate reports
    print("\nGenerating reports...")
    generate_reports(trades, output_dir, sim_config)
    
    print("\n" + "=" * 80)
    print(f"BACKTEST COMPLETE - Results saved to: {output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
