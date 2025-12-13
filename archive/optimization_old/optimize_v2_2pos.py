"""
Grid optimization for V2 2-Position Strategy.

Tests different combinations of:
- Position splits (70/30, 75/25, 65/35, etc.)
- TP multipliers for POS1 and POS2
- SL multipliers
- Trailing distance
"""

import itertools
import sys
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional
import pandas as pd

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    ImportableStrategyConfig,
    LoggingConfig,
)


@dataclass
class GridConfig:
    """Configuration for a single grid point."""
    name: str
    pos1_fraction: float
    pos2_fraction: float
    pos1_tp: float
    pos2_tp: float
    sl_mult: float
    trail_dist: float
    
    def __str__(self):
        return f"{int(self.pos1_fraction*100)}/{int(self.pos2_fraction*100)} TP:{self.pos1_tp}/{self.pos2_tp} SL:{self.sl_mult}"


def generate_grid(full: bool = False) -> List[GridConfig]:
    """Generate grid configurations to test.
    
    Args:
        full: If True, generate full grid (540 configs). 
              If False, generate reduced grid (~60 configs).
    """
    
    configs = []
    
    if full:
        # Full grid - 540 combinations
        splits = [(0.70, 0.30), (0.75, 0.25), (0.65, 0.35), (0.80, 0.20), (0.60, 0.40)]
        pos1_tps = [0.75, 0.9, 1.0]
        pos2_tps = [1.5, 1.75, 2.0, 2.5]
        sl_mults = [1.2, 1.4, 1.6]
        trail_dists = [0.4, 0.5, 0.6]
    else:
        # Reduced grid - ~60 combinations (focused on key parameters)
        splits = [(0.70, 0.30), (0.75, 0.25), (0.65, 0.35)]
        pos1_tps = [0.9, 1.0]
        pos2_tps = [1.75, 2.0]
        sl_mults = [1.4]  # Fix SL at known good value
        trail_dists = [0.5]  # Fix trail at known good value
    
    # Generate combinations
    for (p1, p2), tp1, tp2, sl, trail in itertools.product(
        splits, pos1_tps, pos2_tps, sl_mults, trail_dists
    ):
        name = f"S{int(p1*100)}_{int(p2*100)}_TP{tp1}_{tp2}_SL{sl}_TR{trail}"
        configs.append(GridConfig(
            name=name,
            pos1_fraction=p1,
            pos2_fraction=p2,
            pos1_tp=tp1,
            pos2_tp=tp2,
            sl_mult=sl,
            trail_dist=trail,
        ))
    
    # Add some extra promising configs
    extra_configs = [
        # Test wider TPs with 70/30
        GridConfig("S70_30_TP0.9_2.5_SL1.4_TR0.5", 0.70, 0.30, 0.9, 2.5, 1.4, 0.5),
        GridConfig("S70_30_TP1.0_2.5_SL1.4_TR0.5", 0.70, 0.30, 1.0, 2.5, 1.4, 0.5),
        # Test different SL with best split candidates
        GridConfig("S70_30_TP0.9_1.75_SL1.2_TR0.5", 0.70, 0.30, 0.9, 1.75, 1.2, 0.5),
        GridConfig("S70_30_TP0.9_1.75_SL1.6_TR0.5", 0.70, 0.30, 0.9, 1.75, 1.6, 0.5),
        GridConfig("S75_25_TP0.9_1.75_SL1.2_TR0.5", 0.75, 0.25, 0.9, 1.75, 1.2, 0.5),
        GridConfig("S75_25_TP0.9_1.75_SL1.6_TR0.5", 0.75, 0.25, 0.9, 1.75, 1.6, 0.5),
        # Test different trail distances
        GridConfig("S70_30_TP0.9_1.75_SL1.4_TR0.4", 0.70, 0.30, 0.9, 1.75, 1.4, 0.4),
        GridConfig("S70_30_TP0.9_1.75_SL1.4_TR0.6", 0.70, 0.30, 0.9, 1.75, 1.4, 0.6),
    ]
    
    # Add extras, avoiding duplicates
    existing_names = {c.name for c in configs}
    for ec in extra_configs:
        if ec.name not in existing_names:
            configs.append(ec)
    
    return configs


def run_single_backtest(grid_config: GridConfig, catalog_path: str,
                        start_date: str, end_date: str) -> Dict:
    """Run a single backtest with given configuration."""
    
    # Note: Catalog uses EURUSD (no slash), strategy uses EUR/USD (with slash)
    catalog_instrument_id = "EURUSD.IDEALPRO"
    strategy_instrument_id = "EUR/USD.IDEALPRO"
    bar_spec = "15-MINUTE-MID-EXTERNAL"
    
    # Use ImportableStrategyConfig for BacktestNode
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2_2pos:MLSignalStrategyV2_2Pos",
        config_path="strategies.ml_strategy_mtf_v2_2pos:MLSignalStrategyV2_2PosConfig",
        config={
            "instrument_id": strategy_instrument_id,
            "bar_type": f"{strategy_instrument_id}-{bar_spec}",
            "model_path": "models/ml_model_mtf.pkl",
            "total_position_size": 100000,
            "pos1_fraction": grid_config.pos1_fraction,
            "pos2_fraction": grid_config.pos2_fraction,
            "pos1_tp_atr_mult": grid_config.pos1_tp,
            "pos2_tp_atr_mult": grid_config.pos2_tp,
            "sl_atr_mult": grid_config.sl_mult,
            "trailing_distance_atr_mult": grid_config.trail_dist,
            "prediction_threshold": 0.55,
            "trade_start_hour": 7,
            "trade_end_hour": 20,
            "min_atr": 0.0003,
            "max_atr": 0.005,
        }
    )
    
    data_config = BacktestDataConfig(
        catalog_path=catalog_path,
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id=catalog_instrument_id,
        bar_spec=bar_spec,
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
        trader_id=f"GRID-{grid_config.name[:20]}",
        logging=LoggingConfig(log_level="ERROR"),  # Reduce logging noise
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
            return {"config": grid_config.name, "error": "No results"}
        
        result = results[0]
        
        # Get fills for analysis
        fills = list(result.engine.cache.fills())
        
        # Calculate PnL from fills
        total_pnl = 0.0
        trade_pnls = []
        current_trade_pnl = 0.0
        trade_count = 0
        
        for fill in fills:
            # Each fill has commission
            commission = float(fill.commission.as_double()) if fill.commission else 0
            
            # Determine if entry or exit based on position
            fill_value = float(fill.last_qty) * float(fill.last_px)
            
            if "SL" in str(fill.client_order_id) or "TP" in str(fill.client_order_id):
                # Exit fill
                if fill.order_side.name == "BUY":  # Closing short
                    current_trade_pnl -= fill_value
                else:  # Closing long
                    current_trade_pnl += fill_value
                current_trade_pnl -= commission
            else:
                # Entry fill
                if fill.order_side.name == "BUY":  # Opening long
                    current_trade_pnl = -fill_value - commission
                else:  # Opening short
                    current_trade_pnl = fill_value - commission
        
        # Simplified: use account balance change
        try:
            accounts = list(result.engine.cache.accounts())
            if accounts:
                final_balance = float(accounts[0].balance_total().as_double())
                total_pnl = final_balance - 100000
        except:
            total_pnl = 0
        
        # Count trades (rough estimate)
        entry_fills = [f for f in fills if "POS1" in str(f.client_order_id) and "SL" not in str(f.client_order_id) and "TP" not in str(f.client_order_id)]
        num_trades = len(entry_fills)
        
        # Count wins/losses
        wins = 0
        losses = 0
        for i, fill in enumerate(fills):
            if "TP" in str(fill.client_order_id):
                wins += 1
            elif "SL" in str(fill.client_order_id):
                losses += 1
        
        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
        
        return {
            "config": grid_config.name,
            "split": f"{int(grid_config.pos1_fraction*100)}/{int(grid_config.pos2_fraction*100)}",
            "pos1_tp": grid_config.pos1_tp,
            "pos2_tp": grid_config.pos2_tp,
            "sl": grid_config.sl_mult,
            "trail": grid_config.trail_dist,
            "total_pnl": total_pnl,
            "num_trades": num_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "num_fills": len(fills),
        }
        
    except Exception as e:
        return {"config": grid_config.name, "error": str(e)}
    finally:
        node.dispose()


def main():
    """Run grid optimization."""
    
    import argparse
    parser = argparse.ArgumentParser(description="V2 2-Position Grid Optimization")
    parser.add_argument("--full", action="store_true", help="Run full grid (540 configs) instead of reduced (~20)")
    parser.add_argument("--catalog", type=str, default="data/historical", help="Catalog path")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date")
    parser.add_argument("--end", type=str, default="2024-10-31", help="End date")
    args = parser.parse_args()
    
    print("=" * 80)
    print("V2 2-POSITION GRID OPTIMIZATION")
    print("=" * 80)
    
    # Configuration
    catalog_path = args.catalog
    start_date = args.start
    end_date = args.end
    
    # Generate grid
    grid = generate_grid(full=args.full)
    print(f"\nGenerated {len(grid)} configurations to test")
    print(f"Backtest period: {start_date} to {end_date}")
    print(f"Catalog: {catalog_path}")
    
    # Confirm before running
    print(f"\nThis will run {len(grid)} backtests. Continue? (y/n): ", end="")
    
    # For automated runs, default to yes
    import sys
    if not sys.stdin.isatty():
        response = 'y'
        print("y (auto)")
    else:
        response = input().strip().lower()
    
    if response != 'y':
        print("Aborted.")
        return
    
    # Run backtests
    results = []
    for i, config in enumerate(grid):
        print(f"\n[{i+1}/{len(grid)}] Testing: {config}...", end=" ", flush=True)
        
        result = run_single_backtest(config, catalog_path, start_date, end_date)
        results.append(result)
        
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"PnL: ${result['total_pnl']:,.0f}, WR: {result['win_rate']:.1%}")
    
    # Create results DataFrame
    df = pd.DataFrame(results)
    
    # Filter out errors
    df_valid = df[~df['error'].notna()] if 'error' in df.columns else df
    
    if df_valid.empty:
        print("\nNo valid results!")
        return
    
    # Sort by PnL
    df_valid = df_valid.sort_values('total_pnl', ascending=False)
    
    # Print results
    print("\n" + "=" * 80)
    print("OPTIMIZATION RESULTS")
    print("=" * 80)
    
    print("\n### TOP 10 CONFIGURATIONS ###")
    cols = ['config', 'total_pnl', 'win_rate', 'num_trades']
    print(df_valid[cols].head(10).to_string(index=False))
    
    print("\n### WORST 5 CONFIGURATIONS ###")
    print(df_valid[cols].tail(5).to_string(index=False))
    
    # Best by split
    print("\n### BEST BY POSITION SPLIT ###")
    for split in df_valid['split'].unique():
        subset = df_valid[df_valid['split'] == split]
        if not subset.empty:
            best = subset.iloc[0]
            print(f"  {split}: {best['config']} -> ${best['total_pnl']:,.0f}")
    
    # Best by SL
    print("\n### BEST BY SL MULTIPLIER ###")
    for sl in sorted(df_valid['sl'].unique()):
        subset = df_valid[df_valid['sl'] == sl]
        if not subset.empty:
            best = subset.iloc[0]
            print(f"  SL={sl}x: {best['config']} -> ${best['total_pnl']:,.0f}")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"v2_2pos_optimization_{timestamp}.csv"
    df_valid.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
    
    # Print best config details
    best = df_valid.iloc[0]
    print("\n" + "=" * 80)
    print("BEST CONFIGURATION")
    print("=" * 80)
    print(f"  Config: {best['config']}")
    print(f"  Split: {best['split']}")
    print(f"  POS1 TP: {best['pos1_tp']}x ATR")
    print(f"  POS2 TP: {best['pos2_tp']}x ATR")
    print(f"  SL: {best['sl']}x ATR")
    print(f"  Trail: {best['trail']}x ATR")
    print(f"  Total PnL: ${best['total_pnl']:,.2f}")
    print(f"  Win Rate: {best['win_rate']:.1%}")
    print(f"  Trades: {best['num_trades']}")
    
    return df_valid


if __name__ == "__main__":
    main()
