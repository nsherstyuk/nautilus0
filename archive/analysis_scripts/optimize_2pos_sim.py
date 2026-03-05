"""
Grid optimization for 2-Position Strategy using pure Python simulation.

Uses the same simulation approach as run_mtf_backtest_multi_layer.py
but with only 2 position layers.
"""

import sys
from pathlib import Path
from datetime import datetime
import itertools

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from joblib import load
import pandas_ta as ta

from nautilus_trader.persistence.catalog import ParquetDataCatalog


def load_and_prepare_data(start_date: str, end_date: str):
    """Load 15-minute data from Parquet catalog."""
    catalog_path = PROJECT_ROOT / "data" / "historical"
    catalog = ParquetDataCatalog(str(catalog_path))
    
    bar_type = "EURUSD.IDEALPRO-15-MINUTE-MID-EXTERNAL"
    print(f"Loading {bar_type} from catalog...")
    
    bars = catalog.bars(bar_types=[bar_type])
    
    if len(bars) == 0:
        raise FileNotFoundError(f"No data found for {bar_type}")
    
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
    
    # Filter to date range
    df = df[start_date:end_date]
    
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    return df


def calculate_features(df):
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


def simulate_2pos_strategy(df, model, config):
    """
    Simulate 2-position bracket strategy.
    
    Config should have:
    - pos1_fraction, pos2_fraction (e.g., 0.70, 0.30)
    - pos1_tp_atr, pos2_tp_atr (e.g., 0.9, 1.75)
    - sl_atr_mult (e.g., 1.4)
    - trailing_distance_atr (e.g., 0.5)
    - prediction_threshold (e.g., 0.55)
    - position_size (e.g., 100000)
    - trade_start_hour, trade_end_hour (e.g., 7, 20)
    - min_atr, max_atr
    """
    trades = []
    position = None
    position_size = config['position_size']
    
    for idx, row in df.iterrows():
        # Manage existing position
        if position is not None:
            current_price = row['close']
            atr_value = position['atr_value']
            
            # Calculate profit
            if position['side'] == 'LONG':
                profit = current_price - position['entry']
            else:
                profit = position['entry'] - current_price
            
            profit_atr = profit / atr_value
            
            # Check POS1 TP (if not closed)
            if not position.get('pos1_closed', False):
                if profit_atr >= config['pos1_tp_atr']:
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
            
            # Update trailing stop for POS2 (if active)
            if position.get('trailing_active', False):
                trail_distance = atr_value * config['trailing_distance_atr']
                
                if position['side'] == 'LONG':
                    new_sl = current_price - trail_distance
                    if new_sl > position['sl']:
                        position['sl'] = new_sl
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < position['sl']:
                        position['sl'] = new_sl
            
            # Check POS2 TP
            if not position.get('pos2_closed', False) and position.get('pos1_closed', False):
                if profit_atr >= config['pos2_tp_atr']:
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
                        'pos1_closed': True,
                        'pos2_closed': True,
                    })
                    position = None
                    continue
            
            # Check SL hit (for remaining position)
            sl_hit = False
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
                
                exit_type = 'TRAILING_SL' if position.get('trailing_active', False) else 'SL'
                
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': idx,
                    'side': position['side'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': total_pnl,
                    'exit_reason': exit_type,
                    'pos1_closed': position.get('pos1_closed', False),
                    'pos2_closed': True,
                })
                position = None
                continue
            
            # Skip new signal evaluation if in position
            continue
        
        # No position - evaluate new signal
        
        # Session filter
        current_hour = idx.hour
        if not (config['trade_start_hour'] <= current_hour < config['trade_end_hour']):
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
        atr_value = atr * entry_price  # Convert to absolute
        
        if prediction == 1:  # LONG
            sl = entry_price - (atr_value * config['sl_atr_mult'])
            tp = entry_price + (atr_value * config['pos2_tp_atr'])  # Final TP
            side = 'LONG'
        else:  # SHORT
            sl = entry_price + (atr_value * config['sl_atr_mult'])
            tp = entry_price - (atr_value * config['pos2_tp_atr'])
            side = 'SHORT'
        
        # Entry commission
        entry_commission = calculate_commission(position_size)
        
        position = {
            'entry_time': idx,
            'entry': entry_price,
            'side': side,
            'sl': sl,
            'tp': tp,
            'initial_size': position_size,
            'size': position_size,
            'atr_value': atr_value,
            'trailing_active': False,
            'pos1_closed': False,
            'pos2_closed': False,
            'pos1_pnl': 0,
            'entry_commission': entry_commission,
        }
    
    return trades


def analyze_results(trades, config_name):
    """Analyze trade results with comprehensive metrics."""
    if not trades:
        return {
            'config': config_name,
            'total_pnl': 0,
            'num_trades': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'neg_days': 0,
            'neg_months': 99,
            'sharpe': 0,
            'worst_day': 0,
            'worst_month': 0,
        }
    
    df = pd.DataFrame(trades)
    
    total_pnl = df['pnl'].sum()
    num_trades = len(df)
    wins = (df['pnl'] > 0).sum()
    win_rate = wins / num_trades if num_trades > 0 else 0
    avg_pnl = df['pnl'].mean()
    
    # Daily PnL
    df['date'] = pd.to_datetime(df['exit_time']).dt.date
    daily_pnl = df.groupby('date')['pnl'].sum()
    neg_days = (daily_pnl < 0).sum()
    total_days = len(daily_pnl)
    worst_day = daily_pnl.min()
    
    # Monthly PnL
    df['month'] = pd.to_datetime(df['exit_time']).dt.to_period('M')
    monthly_pnl = df.groupby('month')['pnl'].sum()
    neg_months = (monthly_pnl < 0).sum()
    worst_month = monthly_pnl.min()
    
    # Sharpe ratio (annualized, assuming 252 trading days)
    if len(daily_pnl) > 1 and daily_pnl.std() > 0:
        sharpe = (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252)
    else:
        sharpe = 0
    
    return {
        'config': config_name,
        'total_pnl': total_pnl,
        'num_trades': num_trades,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'neg_days': neg_days,
        'total_days': total_days,
        'neg_months': neg_months,
        'worst_day': worst_day,
        'worst_month': worst_month,
        'sharpe': sharpe,
        'wins': wins,
        'losses': num_trades - wins,
    }


def generate_configs(full=False):
    """Generate 2-position configurations to test."""
    configs = []
    
    # Base config
    base = {
        'position_size': 100000,
        'prediction_threshold': 0.55,
        'trade_start_hour': 7,
        'trade_end_hour': 20,
        'min_atr': 0.0003,
        'max_atr': 0.005,
    }
    
    if full:
        # Full grid - more comprehensive
        splits = [(0.80, 0.20), (0.75, 0.25), (0.70, 0.30), (0.85, 0.15)]
        pos1_tps = [0.6, 0.75, 0.9, 1.0]
        pos2_tps = [1.5, 1.75, 2.0, 2.5]
        sl_mults = [0.8, 1.0, 1.2, 1.4, 1.6]  # Include lower SL values
        trail_dists = [0.4, 0.5, 0.6]
    else:
        # Quick grid
        splits = [(0.70, 0.30), (0.75, 0.25), (0.65, 0.35), (0.80, 0.20)]
        pos1_tps = [0.9, 1.0, 0.75]
        pos2_tps = [1.75, 2.0, 2.5]
        sl_mults = [1.4, 1.2, 1.6]
        trail_dists = [0.5, 0.4, 0.6]
    
    for (p1, p2), tp1, tp2, sl, trail in itertools.product(
        splits, pos1_tps, pos2_tps, sl_mults, trail_dists
    ):
        name = f"S{int(p1*100)}_{int(p2*100)}_TP{tp1}_{tp2}_SL{sl}_TR{trail}"
        cfg = base.copy()
        cfg.update({
            'name': name,
            'pos1_fraction': p1,
            'pos2_fraction': p2,
            'pos1_tp_atr': tp1,
            'pos2_tp_atr': tp2,
            'sl_atr_mult': sl,
            'trailing_distance_atr': trail,
        })
        configs.append(cfg)
    
    return configs


def main():
    import argparse
    parser = argparse.ArgumentParser(description="2-Position Grid Optimization (Simulation)")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date")
    parser.add_argument("--end", type=str, default="2024-10-31", help="End date")
    parser.add_argument("--quick", action="store_true", help="Quick test with reduced configs")
    args = parser.parse_args()
    
    print("=" * 80)
    print("2-POSITION GRID OPTIMIZATION (Simulation-Based)")
    print("=" * 80)
    
    # Load model
    model_path = PROJECT_ROOT / "models" / "ml_model_mtf.pkl"
    print(f"Loading model from {model_path}...")
    model = load(model_path)
    
    # Load data
    print(f"\nLoading data from {args.start} to {args.end}...")
    df = load_and_prepare_data(args.start, args.end)
    
    # Calculate features
    print("Calculating features...")
    df = calculate_features(df)
    print(f"Data ready: {len(df)} bars with features")
    
    # Generate configs
    if args.quick:
        configs = generate_configs(full=False)
        # Further reduce for quick mode
        configs = [c for c in configs if c['sl_atr_mult'] == 1.4 and c['trailing_distance_atr'] == 0.5]
    else:
        configs = generate_configs(full=True)
    
    print(f"\nTesting {len(configs)} configurations...")
    
    # Run simulations
    results = []
    for i, cfg in enumerate(configs):
        print(f"[{i+1}/{len(configs)}] {cfg['name']}...", end=" ", flush=True)
        
        trades = simulate_2pos_strategy(df, model, cfg)
        result = analyze_results(trades, cfg['name'])
        result.update({
            'split': f"{int(cfg['pos1_fraction']*100)}/{int(cfg['pos2_fraction']*100)}",
            'pos1_tp': cfg['pos1_tp_atr'],
            'pos2_tp': cfg['pos2_tp_atr'],
            'sl': cfg['sl_atr_mult'],
            'trail': cfg['trailing_distance_atr'],
        })
        results.append(result)
        
        print(f"PnL: ${result['total_pnl']:,.0f}, WR: {result['win_rate']:.1%}, Trades: {result['num_trades']}")
    
    # Analyze results
    df_results = pd.DataFrame(results)
    
    # Create composite score (higher is better)
    # Normalize each metric to 0-1 range
    df_results['pnl_norm'] = (df_results['total_pnl'] - df_results['total_pnl'].min()) / (df_results['total_pnl'].max() - df_results['total_pnl'].min() + 1)
    df_results['wr_norm'] = df_results['win_rate']
    df_results['sharpe_norm'] = (df_results['sharpe'] - df_results['sharpe'].min()) / (df_results['sharpe'].max() - df_results['sharpe'].min() + 1)
    df_results['neg_days_norm'] = 1 - (df_results['neg_days'] - df_results['neg_days'].min()) / (df_results['neg_days'].max() - df_results['neg_days'].min() + 1)
    df_results['neg_months_norm'] = 1 - (df_results['neg_months'] / df_results['neg_months'].max())
    
    # Composite score: weighted average
    # Priority: 1) Zero neg months, 2) Low neg days, 3) PnL, 4) WR/Sharpe
    df_results['score'] = (
        0.30 * df_results['neg_months_norm'] +  # Zero neg months most important
        0.25 * df_results['neg_days_norm'] +    # Low neg days second
        0.15 * df_results['pnl_norm'] +         # PnL third (willing to sacrifice some)
        0.15 * df_results['wr_norm'] +          # Win rate
        0.15 * df_results['sharpe_norm']        # Sharpe ratio
    )
    
    df_results = df_results.sort_values('score', ascending=False)
    
    print("\n" + "=" * 80)
    print("TOP 15 BALANCED CONFIGURATIONS (by composite score)")
    print("=" * 80)
    cols = ['config', 'total_pnl', 'win_rate', 'sharpe', 'neg_days', 'neg_months', 'score']
    top15 = df_results[cols].head(15).copy()
    top15['total_pnl'] = top15['total_pnl'].apply(lambda x: f"${x:,.0f}")
    top15['win_rate'] = top15['win_rate'].apply(lambda x: f"{x:.1%}")
    top15['sharpe'] = top15['sharpe'].apply(lambda x: f"{x:.2f}")
    top15['score'] = top15['score'].apply(lambda x: f"{x:.3f}")
    print(top15.to_string(index=False))
    
    # Filter to 0 negative months
    df_zero_neg = df_results[df_results['neg_months'] == 0]
    if len(df_zero_neg) > 0:
        print("\n" + "=" * 80)
        print(f"TOP 10 WITH 0 NEGATIVE MONTHS ({len(df_zero_neg)} configs)")
        print("=" * 80)
        top10_zero = df_zero_neg[cols].head(10).copy()
        top10_zero['total_pnl'] = top10_zero['total_pnl'].apply(lambda x: f"${x:,.0f}")
        top10_zero['win_rate'] = top10_zero['win_rate'].apply(lambda x: f"{x:.1%}")
        top10_zero['sharpe'] = top10_zero['sharpe'].apply(lambda x: f"{x:.2f}")
        top10_zero['score'] = top10_zero['score'].apply(lambda x: f"{x:.3f}")
        print(top10_zero.to_string(index=False))
    
    print("\n" + "=" * 80)
    print("BEST BY POSITION SPLIT")
    print("=" * 80)
    for split in sorted(df_results['split'].unique()):
        subset = df_results[df_results['split'] == split]
        best = subset.iloc[0]
        print(f"  {split}: ${best['total_pnl']:,.0f} | WR: {best['win_rate']:.1%} | Sharpe: {best['sharpe']:.2f} | NegDays: {best['neg_days']} | NegMo: {best['neg_months']}")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"2pos_optimization_{timestamp}.csv"
    df_results.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
    
    # Print best config
    best = df_results.iloc[0]
    print("\n" + "=" * 80)
    print("BEST BALANCED CONFIGURATION")
    print("=" * 80)
    print(f"  Config: {best['config']}")
    print(f"  Split: {best['split']}")
    print(f"  POS1 TP: {best['pos1_tp']}x ATR")
    print(f"  POS2 TP: {best['pos2_tp']}x ATR")
    print(f"  SL: {best['sl']}x ATR")
    print(f"  Trail: {best['trail']}x ATR")
    print("-" * 40)
    print(f"  Total PnL: ${best['total_pnl']:,.2f}")
    print(f"  Win Rate: {best['win_rate']:.1%}")
    print(f"  Sharpe Ratio: {best['sharpe']:.2f}")
    print(f"  Trades: {best['num_trades']}")
    print(f"  Negative Days: {best['neg_days']}/{best['total_days']} ({best['neg_days']/best['total_days']*100:.1f}%)")
    print(f"  Negative Months: {best['neg_months']}")
    print(f"  Worst Day: ${best['worst_day']:,.2f}")
    print(f"  Worst Month: ${best['worst_month']:,.2f}")
    print(f"  Composite Score: {best['score']:.3f}")


if __name__ == "__main__":
    main()
