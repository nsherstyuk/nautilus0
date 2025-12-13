"""
Grid optimization for position split strategy.

Tests different configurations:
1. Single position (baseline)
2. Two-position split
3. Three-position split

Evaluates: PnL, negative days, consistency
"""

import itertools
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# Import backtest components
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import BacktestDataConfig, BacktestEngineConfig, BacktestRunConfig, BacktestVenueConfig
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from strategies.ml_strategy_mtf_v2 import MLSignalStrategyV2, MLSignalStrategyV2Config


@dataclass
class SplitConfig:
    """Configuration for a position split test."""
    name: str
    num_positions: int
    pos1_fraction: float
    pos2_fraction: float
    pos3_fraction: float
    pos1_tp_mult: float
    pos2_tp_mult: float
    pos3_tp_mult: float
    
    def __str__(self):
        if self.num_positions == 1:
            return f"1-POS: 100% @ {self.pos1_tp_mult}x"
        elif self.num_positions == 2:
            return f"2-POS: {int(self.pos1_fraction*100)}/{int(self.pos2_fraction*100)} @ {self.pos1_tp_mult}x/{self.pos2_tp_mult}x"
        else:
            return f"3-POS: {int(self.pos1_fraction*100)}/{int(self.pos2_fraction*100)}/{int(self.pos3_fraction*100)}"


def generate_configs() -> List[SplitConfig]:
    """Generate all configurations to test."""
    configs = []
    
    # ==========================================================================
    # 1. SINGLE POSITION BASELINES
    # ==========================================================================
    for tp in [0.9, 1.0, 1.25, 1.5, 1.75, 2.0]:
        configs.append(SplitConfig(
            name=f"1POS_TP{tp}",
            num_positions=1,
            pos1_fraction=1.0,
            pos2_fraction=0.0,
            pos3_fraction=0.0,
            pos1_tp_mult=tp,
            pos2_tp_mult=0.0,
            pos3_tp_mult=0.0,
        ))
    
    # ==========================================================================
    # 2. TWO-POSITION SPLITS
    # ==========================================================================
    two_pos_sizes = [
        (0.75, 0.25),
        (0.70, 0.30),
        (0.80, 0.20),
        (0.65, 0.35),
        (0.60, 0.40),
    ]
    
    two_pos_tps = [
        (0.9, 1.75),   # Current-like
        (0.9, 2.0),
        (1.0, 1.75),
        (1.0, 2.0),
        (0.75, 1.5),
        (0.9, 1.5),
    ]
    
    for (s1, s2), (tp1, tp2) in itertools.product(two_pos_sizes, two_pos_tps):
        configs.append(SplitConfig(
            name=f"2POS_{int(s1*100)}_{int(s2*100)}_TP{tp1}_{tp2}",
            num_positions=2,
            pos1_fraction=s1,
            pos2_fraction=s2,
            pos3_fraction=0.0,
            pos1_tp_mult=tp1,
            pos2_tp_mult=tp2,
            pos3_tp_mult=0.0,
        ))
    
    # ==========================================================================
    # 3. THREE-POSITION SPLITS (including current best)
    # ==========================================================================
    three_pos_configs = [
        # Current best
        (0.70, 0.25, 0.05, 0.9, 1.75, 1.75),
        # Variations on sizes
        (0.70, 0.20, 0.10, 0.9, 1.75, 1.75),
        (0.65, 0.25, 0.10, 0.9, 1.75, 1.75),
        (0.60, 0.30, 0.10, 0.9, 1.75, 1.75),
        (0.75, 0.20, 0.05, 0.9, 1.75, 1.75),
        # Variations on TPs
        (0.70, 0.25, 0.05, 0.9, 1.75, 2.5),
        (0.70, 0.25, 0.05, 1.0, 1.75, 1.75),
        (0.70, 0.25, 0.05, 0.9, 2.0, 2.5),
    ]
    
    for s1, s2, s3, tp1, tp2, tp3 in three_pos_configs:
        configs.append(SplitConfig(
            name=f"3POS_{int(s1*100)}_{int(s2*100)}_{int(s3*100)}_TP{tp1}_{tp2}_{tp3}",
            num_positions=3,
            pos1_fraction=s1,
            pos2_fraction=s2,
            pos3_fraction=s3,
            pos1_tp_mult=tp1,
            pos2_tp_mult=tp2,
            pos3_tp_mult=tp3,
        ))
    
    return configs


def run_backtest(config: SplitConfig, catalog_path: str, instrument_id: str, 
                 start_date: str, end_date: str) -> dict:
    """Run a single backtest with given configuration."""
    
    catalog = ParquetDataCatalog(catalog_path)
    
    # For single/two position, we set unused positions to 0
    strategy_config = MLSignalStrategyV2Config(
        instrument_id=instrument_id,
        bar_type=f"{instrument_id}-15-MINUTE-MID-EXTERNAL",
        model_path="models/ml_model_mtf.pkl",
        total_position_size=100000,
        pos1_fraction=config.pos1_fraction,
        pos2_fraction=config.pos2_fraction,
        pos3_fraction=config.pos3_fraction,
        pos1_tp_atr_mult=config.pos1_tp_mult,
        pos2_tp_atr_mult=config.pos2_tp_mult if config.num_positions >= 2 else 999.0,  # Never hit
        pos3_tp_atr_mult=config.pos3_tp_mult if config.num_positions >= 3 else 999.0,  # Never hit
        sl_atr_mult=1.4,
        trailing_activation_atr_mult=0.9,
        trailing_distance_atr_mult=0.5,
        prediction_threshold=0.55,
        trade_start_hour=7,
        trade_end_hour=20,
    )
    
    venue = Venue("IDEALPRO")
    
    data_config = BacktestDataConfig(
        catalog_path=catalog_path,
        data_cls_path="nautilus_trader.model.data:Bar",
        instrument_id=instrument_id,
        bar_spec="15-MINUTE-MID-EXTERNAL",
        start_time=start_date,
        end_time=end_date,
    )
    
    venue_config = BacktestVenueConfig(
        name="IDEALPRO",
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=["100000 USD"],
    )
    
    engine_config = BacktestEngineConfig(
        strategies=[strategy_config],
    )
    
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config],
    )
    
    node = BacktestNode(configs=[run_config])
    
    try:
        results = node.run()
        
        if not results:
            return {"error": "No results"}
            
        result = results[0]
        
        # Extract metrics
        stats = result.stats_returns if hasattr(result, 'stats_returns') else {}
        
        # Get account info
        account = result.engine.trader.generate_account_report()
        final_balance = 100000  # Default
        if account:
            try:
                final_balance = float(account.get('balance', 100000))
            except:
                pass
        
        # Try to get PnL from fills
        fills = result.engine.cache.fills() if hasattr(result.engine, 'cache') else []
        
        return {
            "config": config.name,
            "num_positions": config.num_positions,
            "pnl": final_balance - 100000,
            "final_balance": final_balance,
            "stats": stats,
        }
        
    except Exception as e:
        return {"error": str(e), "config": config.name}
    finally:
        node.dispose()


def analyze_results(results: List[dict]) -> pd.DataFrame:
    """Analyze and rank results."""
    
    df = pd.DataFrame(results)
    
    # Filter out errors
    df = df[~df.get('error', pd.Series([None]*len(df))).notna()].copy()
    
    if df.empty:
        print("No valid results to analyze")
        return df
    
    # Sort by PnL
    df = df.sort_values('pnl', ascending=False)
    
    return df


def main():
    """Run the optimization."""
    
    print("=" * 80)
    print("POSITION SPLIT OPTIMIZATION")
    print("=" * 80)
    
    # Configuration
    catalog_path = "catalog"
    instrument_id = "EUR/USD.IDEALPRO"
    start_date = "2024-01-01"
    end_date = "2024-10-31"
    
    # Generate configs
    configs = generate_configs()
    print(f"\nGenerated {len(configs)} configurations to test:")
    print(f"  - Single position: {sum(1 for c in configs if c.num_positions == 1)}")
    print(f"  - Two positions: {sum(1 for c in configs if c.num_positions == 2)}")
    print(f"  - Three positions: {sum(1 for c in configs if c.num_positions == 3)}")
    
    # Run backtests
    results = []
    for i, config in enumerate(configs):
        print(f"\n[{i+1}/{len(configs)}] Testing: {config}")
        result = run_backtest(config, catalog_path, instrument_id, start_date, end_date)
        results.append(result)
        
        if "error" not in result:
            print(f"  PnL: ${result['pnl']:,.2f}")
        else:
            print(f"  ERROR: {result['error']}")
    
    # Analyze
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    
    df = analyze_results(results)
    
    if not df.empty:
        print("\nTop 10 configurations by PnL:")
        print(df[['config', 'num_positions', 'pnl']].head(10).to_string(index=False))
        
        print("\nBest by number of positions:")
        for n in [1, 2, 3]:
            subset = df[df['num_positions'] == n]
            if not subset.empty:
                best = subset.iloc[0]
                print(f"  {n}-position best: {best['config']} -> ${best['pnl']:,.2f}")
        
        # Save results
        output_file = f"position_split_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(output_file, index=False)
        print(f"\nResults saved to: {output_file}")
    
    return df


if __name__ == "__main__":
    main()
