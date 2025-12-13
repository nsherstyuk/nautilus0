"""
Fast simulation of different position split strategies.

Uses historical price data + ML model to generate signals,
then simulates different split configurations without full backtest.
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
import joblib
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')


@dataclass
class TradeResult:
    """Result of a single trade."""
    entry_time: pd.Timestamp
    entry_price: float
    direction: str  # LONG or SHORT
    atr: float
    
    # Exit info for each layer
    layer_exits: Dict[str, dict]  # {layer_name: {exit_price, exit_type, pnl}}
    total_pnl: float


@dataclass 
class SplitConfig:
    """Position split configuration."""
    name: str
    layers: List[Tuple[float, float]]  # [(size_fraction, tp_atr_mult), ...]
    sl_atr_mult: float = 1.4
    
    def __str__(self):
        if len(self.layers) == 1:
            return f"1-POS: 100% @ TP={self.layers[0][1]}x"
        elif len(self.layers) == 2:
            return f"2-POS: {int(self.layers[0][0]*100)}/{int(self.layers[1][0]*100)} @ TP={self.layers[0][1]}x/{self.layers[1][1]}x"
        else:
            sizes = "/".join([f"{int(l[0]*100)}" for l in self.layers])
            tps = "/".join([f"{l[1]}x" for l in self.layers])
            return f"3-POS: {sizes} @ TP={tps}"


def load_data(catalog_path: str, instrument_id: str = "EUR/USD.IDEALPRO") -> pd.DataFrame:
    """Load 15m bar data using NautilusTrader catalog."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.model.data import Bar
    
    catalog = ParquetDataCatalog(catalog_path)
    
    # Load bars
    bars = catalog.bars(
        instrument_ids=[instrument_id],
        bar_types=["EUR/USD.IDEALPRO-15-MINUTE-MID-EXTERNAL"],
    )
    
    if not bars:
        raise ValueError(f"No bars found for {instrument_id}")
    
    # Convert to DataFrame
    data = []
    for bar in bars:
        data.append({
            'timestamp': pd.Timestamp(bar.ts_init, unit='ns', tz='UTC'),
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': float(bar.volume),
        })
    
    df = pd.DataFrame(data)
    df = df.sort_values('timestamp').reset_index(drop=True)
    df = df.drop_duplicates(subset=['timestamp'])
    return df


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate ML features matching the model's expectations."""
    
    # Make a copy
    df = df.copy()
    
    # Ensure numeric columns (convert from Decimal if needed)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = df[col].astype(float)
    
    # 15m features
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
    
    # HL2 for MAMA
    df['hl2'] = (df['high'] + df['low']) / 2
    mama = ta.mama(df['hl2'], fastlimit=0.5, slowlimit=0.05)
    if mama is not None and len(mama.columns) >= 2:
        df['mama_diff'] = mama.iloc[:, 0] - mama.iloc[:, 1]
    else:
        df['mama_diff'] = 0
    
    # ATR
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['atr'] = atr
    df['atr_norm'] = df['atr'] / df['close']
    
    # Resample to 30m for some indicators
    df_30m = df.set_index('timestamp').resample('30min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    
    # 30m DMI
    adx = ta.adx(df_30m['high'], df_30m['low'], df_30m['close'], length=14)
    if adx is not None:
        df_30m['dmp_30m'] = adx['DMP_14']
        df_30m['dmn_30m'] = adx['DMN_14']
    
    # 30m Stochastic
    stoch = ta.stoch(df_30m['high'], df_30m['low'], df_30m['close'], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df_30m['stoch_k_30m'] = stoch.iloc[:, 0]
        df_30m['stoch_d_30m'] = stoch.iloc[:, 1]
    
    # 30m WMA diff
    wma_fast = ta.wma(df_30m['close'], length=9)
    wma_slow = ta.wma(df_30m['close'], length=23)
    df_30m['wma_diff_30m'] = (wma_fast - wma_slow) / df_30m['close']
    
    # Merge back
    df_30m = df_30m[['dmp_30m', 'dmn_30m', 'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m']]
    df = df.set_index('timestamp')
    df = df.join(df_30m, how='left')
    df = df.ffill()  # Forward fill 30m features
    
    # Time features
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    df = df.reset_index()
    
    return df


def generate_signals(df: pd.DataFrame, model_path: str, threshold: float = 0.55) -> pd.DataFrame:
    """Generate trade signals using ML model."""
    
    model = joblib.load(model_path)
    
    feature_cols = ['log_ret', 'mama_diff', 'dmp_30m', 'dmn_30m', 
                    'stoch_k_30m', 'stoch_d_30m', 'wma_diff_30m',
                    'atr_norm', 'hour', 'day_of_week']
    
    # Filter to valid rows
    df_valid = df.dropna(subset=feature_cols + ['atr_norm']).copy()
    
    if len(df_valid) == 0:
        print("No valid rows for prediction")
        return df
    
    # Get features
    X = df_valid[feature_cols].values
    
    # Predict
    predictions = model.predict(X)
    probas = model.predict_proba(X)
    confidences = probas.max(axis=1)
    
    # Add to dataframe
    df_valid['prediction'] = predictions
    df_valid['confidence'] = confidences
    
    # Signal: only where confidence > threshold
    df_valid['signal'] = 0
    df_valid.loc[(df_valid['prediction'] == 1) & (df_valid['confidence'] >= threshold), 'signal'] = 1  # LONG
    df_valid.loc[(df_valid['prediction'] == 0) & (df_valid['confidence'] >= threshold), 'signal'] = -1  # SHORT
    
    # Session filter (7-20 UTC)
    df_valid['in_session'] = (df_valid['hour'] >= 7) & (df_valid['hour'] < 20)
    df_valid.loc[~df_valid['in_session'], 'signal'] = 0
    
    # ATR filter
    df_valid.loc[(df_valid['atr_norm'] < 0.0003) | (df_valid['atr_norm'] > 0.005), 'signal'] = 0
    
    return df_valid


def simulate_trade(entry_bar: pd.Series, future_bars: pd.DataFrame, 
                   config: SplitConfig, direction: str) -> TradeResult:
    """Simulate a single trade with given position split."""
    
    entry_price = entry_bar['close']
    atr = entry_bar['atr']
    atr_norm = entry_bar['atr_norm']
    
    # Calculate SL distance
    sl_distance = entry_price * atr_norm * config.sl_atr_mult
    
    if direction == "LONG":
        sl_price = entry_price - sl_distance
    else:
        sl_price = entry_price + sl_distance
    
    # Track each layer
    layer_exits = {}
    total_pnl = 0.0
    
    for i, (size_frac, tp_mult) in enumerate(config.layers):
        layer_name = f"POS{i+1}"
        
        # Calculate TP for this layer
        tp_distance = entry_price * atr_norm * tp_mult
        if direction == "LONG":
            tp_price = entry_price + tp_distance
        else:
            tp_price = entry_price - tp_distance
        
        # Simulate through future bars
        exit_price = None
        exit_type = None
        
        for _, bar in future_bars.iterrows():
            if direction == "LONG":
                # Check SL
                if bar['low'] <= sl_price:
                    exit_price = sl_price
                    exit_type = "SL"
                    break
                # Check TP
                if bar['high'] >= tp_price:
                    exit_price = tp_price
                    exit_type = "TP"
                    break
            else:  # SHORT
                # Check SL
                if bar['high'] >= sl_price:
                    exit_price = sl_price
                    exit_type = "SL"
                    break
                # Check TP
                if bar['low'] <= tp_price:
                    exit_price = tp_price
                    exit_type = "TP"
                    break
        
        # If no exit, use last bar's close
        if exit_price is None:
            exit_price = future_bars.iloc[-1]['close']
            exit_type = "TIMEOUT"
        
        # Calculate PnL for this layer
        position_size = 100000 * size_frac
        if direction == "LONG":
            layer_pnl = (exit_price - entry_price) * position_size
        else:
            layer_pnl = (entry_price - exit_price) * position_size
        
        layer_exits[layer_name] = {
            'exit_price': exit_price,
            'exit_type': exit_type,
            'pnl': layer_pnl,
            'size_frac': size_frac,
        }
        total_pnl += layer_pnl
    
    return TradeResult(
        entry_time=entry_bar['timestamp'],
        entry_price=entry_price,
        direction=direction,
        atr=atr,
        layer_exits=layer_exits,
        total_pnl=total_pnl,
    )


def run_simulation(df: pd.DataFrame, config: SplitConfig, 
                   max_bars_in_trade: int = 96) -> List[TradeResult]:
    """Run full simulation with given config."""
    
    trades = []
    in_trade = False
    trade_end_idx = 0
    
    for idx in range(len(df)):
        if idx < 30:  # Skip warmup
            continue
        if idx <= trade_end_idx:  # Still in previous trade
            continue
            
        row = df.iloc[idx]
        
        if row['signal'] == 0:
            continue
        
        direction = "LONG" if row['signal'] == 1 else "SHORT"
        
        # Get future bars for simulation
        future_start = idx + 1
        future_end = min(idx + 1 + max_bars_in_trade, len(df))
        future_bars = df.iloc[future_start:future_end]
        
        if len(future_bars) == 0:
            continue
        
        # Simulate trade
        trade = simulate_trade(row, future_bars, config, direction)
        trades.append(trade)
        
        # Estimate when trade ends (simplified - use max of layer exits)
        # In reality we'd track each layer separately
        trade_end_idx = future_end - 1
    
    return trades


def analyze_trades(trades: List[TradeResult], config: SplitConfig) -> Dict:
    """Analyze trade results."""
    
    if not trades:
        return {
            'config': str(config),
            'num_trades': 0,
            'total_pnl': 0,
            'win_rate': 0,
            'avg_win': 0,
            'avg_loss': 0,
        }
    
    pnls = [t.total_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    # Daily PnL
    df_trades = pd.DataFrame([{
        'date': t.entry_time.date(),
        'pnl': t.total_pnl,
    } for t in trades])
    
    daily_pnl = df_trades.groupby('date')['pnl'].sum()
    negative_days = (daily_pnl < 0).sum()
    
    # Monthly PnL
    df_trades['month'] = pd.to_datetime(df_trades['date']).dt.to_period('M')
    monthly_pnl = df_trades.groupby('month')['pnl'].sum()
    negative_months = (monthly_pnl < 0).sum()
    
    # Layer analysis
    layer_stats = {}
    for layer_name in config.layers:
        layer_idx = int(layer_name[0]) - 1 if isinstance(layer_name, str) else 0
    
    # TP hit rates per layer
    tp_rates = {}
    for i, _ in enumerate(config.layers):
        layer_name = f"POS{i+1}"
        tp_hits = sum(1 for t in trades if t.layer_exits.get(layer_name, {}).get('exit_type') == 'TP')
        tp_rates[layer_name] = tp_hits / len(trades) if trades else 0
    
    return {
        'config': config.name,
        'config_str': str(config),
        'num_layers': len(config.layers),
        'num_trades': len(trades),
        'total_pnl': sum(pnls),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
        'negative_days': negative_days,
        'total_days': len(daily_pnl),
        'negative_months': negative_months,
        'total_months': len(monthly_pnl),
        'tp_rates': tp_rates,
        'max_drawdown': min(np.minimum.accumulate(np.cumsum(pnls))) if pnls else 0,
    }


def generate_configs() -> List[SplitConfig]:
    """Generate all configurations to test."""
    configs = []
    
    # ==========================================================================
    # 1. SINGLE POSITION BASELINES
    # ==========================================================================
    for tp in [0.75, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0]:
        configs.append(SplitConfig(
            name=f"1POS_TP{tp}",
            layers=[(1.0, tp)],
        ))
    
    # ==========================================================================
    # 2. TWO-POSITION SPLITS
    # ==========================================================================
    two_pos_sizes = [
        (0.75, 0.25),
        (0.70, 0.30),
        (0.80, 0.20),
        (0.65, 0.35),
        (0.85, 0.15),
    ]
    
    two_pos_tps = [
        (0.9, 1.75),   # Similar to current
        (0.9, 2.0),
        (1.0, 1.75),
        (0.75, 1.5),
        (0.9, 1.5),
        (1.0, 2.0),
    ]
    
    for (s1, s2) in two_pos_sizes:
        for (tp1, tp2) in two_pos_tps:
            configs.append(SplitConfig(
                name=f"2POS_{int(s1*100)}_{int(s2*100)}_TP{tp1}_{tp2}",
                layers=[(s1, tp1), (s2, tp2)],
            ))
    
    # ==========================================================================
    # 3. THREE-POSITION SPLITS  
    # ==========================================================================
    three_pos_configs = [
        # Current best
        ((0.70, 0.9), (0.25, 1.75), (0.05, 1.75)),
        # Size variations
        ((0.70, 0.9), (0.20, 1.75), (0.10, 1.75)),
        ((0.65, 0.9), (0.25, 1.75), (0.10, 1.75)),
        ((0.75, 0.9), (0.20, 1.75), (0.05, 1.75)),
        ((0.60, 0.9), (0.30, 1.75), (0.10, 1.75)),
        # TP variations
        ((0.70, 0.9), (0.25, 2.0), (0.05, 2.5)),
        ((0.70, 1.0), (0.25, 1.75), (0.05, 2.0)),
    ]
    
    for layers in three_pos_configs:
        sizes = "_".join([f"{int(l[0]*100)}" for l in layers])
        tps = "_".join([f"{l[1]}" for l in layers])
        configs.append(SplitConfig(
            name=f"3POS_{sizes}_TP{tps}",
            layers=list(layers),
        ))
    
    return configs


def main():
    """Run the simulation."""
    
    print("=" * 80)
    print("POSITION SPLIT SIMULATION")
    print("=" * 80)
    
    # Configuration
    model_path = "models/ml_model_mtf.pkl"
    catalog_path = "data/historical"  # NautilusTrader catalog
    
    # Load and prepare data
    print(f"\nLoading data from catalog: {catalog_path}")
    try:
        df = load_data(catalog_path)
        print(f"Loaded {len(df)} bars")
        print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    except Exception as e:
        print(f"Error loading data: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("Calculating features...")
    df = calculate_features(df)
    
    print("Generating signals...")
    df = generate_signals(df, model_path)
    
    signal_count = (df['signal'] != 0).sum()
    print(f"Generated {signal_count} trade signals")
    
    # Generate configs
    configs = generate_configs()
    print(f"\nTesting {len(configs)} configurations:")
    print(f"  - Single position: {sum(1 for c in configs if len(c.layers) == 1)}")
    print(f"  - Two positions: {sum(1 for c in configs if len(c.layers) == 2)}")
    print(f"  - Three positions: {sum(1 for c in configs if len(c.layers) == 3)}")
    
    # Run simulations
    results = []
    for i, config in enumerate(configs):
        print(f"\n[{i+1}/{len(configs)}] {config.name}...", end=" ")
        trades = run_simulation(df, config)
        analysis = analyze_trades(trades, config)
        results.append(analysis)
        print(f"PnL: ${analysis['total_pnl']:,.0f}, WR: {analysis['win_rate']:.1%}, NegDays: {analysis['negative_days']}")
    
    # Create results DataFrame
    df_results = pd.DataFrame(results)
    
    # Sort by PnL
    df_results = df_results.sort_values('total_pnl', ascending=False)
    
    # Print summary
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    
    print("\n### TOP 10 BY PNL ###")
    cols = ['config', 'num_layers', 'total_pnl', 'win_rate', 'negative_days', 'negative_months']
    print(df_results[cols].head(10).to_string(index=False))
    
    print("\n### BEST BY NUMBER OF POSITIONS ###")
    for n in [1, 2, 3]:
        subset = df_results[df_results['num_layers'] == n]
        if not subset.empty:
            best = subset.iloc[0]
            print(f"\n{n}-POSITION BEST: {best['config']}")
            print(f"   PnL: ${best['total_pnl']:,.0f}")
            print(f"   Win Rate: {best['win_rate']:.1%}")
            print(f"   Neg Days: {best['negative_days']}/{best['total_days']}")
            print(f"   Neg Months: {best['negative_months']}/{best['total_months']}")
    
    # Save results
    output_file = f"position_split_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df_results.to_csv(output_file, index=False)
    print(f"\n\nResults saved to: {output_file}")
    
    return df_results


if __name__ == "__main__":
    main()
