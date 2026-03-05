"""
Optimize Positive Stall Detection Parameters using Replay Backtest.

This script:
1. Uses the realistic replay backtest (not fast simulation)
2. Tests different positive stall detection parameter combinations
3. Scores results using weighted metrics: PnL, Win Rate, and Drawdown
4. Identifies the best parameter set for improved trading results

Expected runtime: ~5-10 minutes per parameter combination
"""

import logging
import os
import sys
import re
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import shutil

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    ImportableFillModelConfig,
)
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar

from config.mtf_v2_config import load_mtf_v2_config

# Suppress verbose logging during optimization
logging.getLogger("nautilus_trader").setLevel(logging.ERROR)
logging.getLogger("strategies.ml_strategy_mtf_v2").setLevel(logging.ERROR)
logging.getLogger("MLSignalStrategy_V2").setLevel(logging.ERROR)

_MONEY_RE = re.compile(r"(-?\d+(?:\.\d+)?)")

def _parse_money(value):
    """Parse money string to float."""
    if pd.isna(value):
        return 0.0
    match = _MONEY_RE.search(str(value))
    return float(match.group(1)) if match else 0.0


def calculate_weighted_score(pnl, win_rate, max_drawdown, total_trades):
    """
    Calculate weighted score combining PnL, win rate, and drawdown.
    
    Weights:
    - PnL: 40% (normalized to $10k baseline)
    - Win Rate: 30% (normalized to 50% baseline)
    - Drawdown: 30% (penalty, normalized to $1k baseline)
    
    Higher score is better.
    """
    if total_trades == 0:
        return -999999  # Penalize no trades
    
    # Normalize metrics
    pnl_score = (pnl / 10000) * 100  # $10k = 100 points
    wr_score = (win_rate - 50) * 2   # 50% = 0, 60% = 20, 70% = 40
    dd_penalty = (abs(max_drawdown) / 1000) * 100  # $1k DD = -100 points
    
    # Weighted combination
    score = (pnl_score * 0.4) + (wr_score * 0.3) - (dd_penalty * 0.3)
    
    return score


def run_single_backtest(cfg, stall_enabled, check_bars, min_profit_atr, sl_atr, iteration_name):
    """Run a single replay backtest with specific stall parameters."""
    
    print(f"\n{'='*80}")
    print(f"Running: {iteration_name}")
    print(f"  Stall Enabled: {stall_enabled}")
    if stall_enabled:
        print(f"  Check Bars: {check_bars}")
        print(f"  Min Profit ATR: {min_profit_atr}")
        print(f"  SL ATR: {sl_atr}")
    print(f"{'='*80}")
    
    # Setup paths
    catalog_path = Path("data") / "historical"
    catalog_instrument_id = f"{cfg.symbol}.{cfg.venue}"
    
    bar_spec = cfg.bar_spec
    if isinstance(bar_spec, str) and bar_spec.upper().endswith("-EXTERNAL"):
        bar_spec = bar_spec[: -len("-EXTERNAL")]
    catalog_bar_type = f"{catalog_instrument_id}-{bar_spec}-EXTERNAL"
    
    start_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_start, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_end, tz="UTC").to_pydatetime())
    
    # Strategy configuration with stall parameters
    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2",
        config_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2Config",
        config={
            "order_id_tag": "STALL_OPT",
            "instrument_id": catalog_instrument_id,
            "bar_type": catalog_bar_type,
            "model_path": str((PROJECT_ROOT / cfg.model_path).resolve()),
            "total_position_size": cfg.total_position_size,
            "pos1_fraction": cfg.pos1_fraction,
            "pos2_fraction": cfg.pos2_fraction,
            "pos3_fraction": cfg.pos3_fraction,
            "sl_atr_mult": cfg.sl_atr_mult,
            "pos1_tp_atr_mult": cfg.pos1_tp_atr_mult,
            "pos2_tp_atr_mult": cfg.pos2_tp_atr_mult,
            "pos3_tp_atr_mult": cfg.pos3_tp_atr_mult,
            "trailing_activation_atr_mult": cfg.trailing_activation_atr_mult,
            "trailing_distance_atr_mult": cfg.trailing_distance_atr_mult,
            "trade_start_hour": cfg.trade_start_hour,
            "trade_end_hour": cfg.trade_end_hour,
            "entry_cooldown_bars": cfg.entry_cooldown_bars,
            "prediction_threshold": cfg.prediction_threshold,
            "min_atr": cfg.min_atr,
            "max_atr": cfg.max_atr,
            "excluded_hours_mode": cfg.excluded_hours_mode,
            "config_timezone": cfg.config_timezone,
            "excluded_hours_monday": ",".join(map(str, cfg.excluded_hours_monday)),
            "excluded_hours_tuesday": ",".join(map(str, cfg.excluded_hours_tuesday)),
            "excluded_hours_wednesday": ",".join(map(str, cfg.excluded_hours_wednesday)),
            "excluded_hours_thursday": ",".join(map(str, cfg.excluded_hours_thursday)),
            "excluded_hours_friday": ",".join(map(str, cfg.excluded_hours_friday)),
            "excluded_hours_saturday": ",".join(map(str, cfg.excluded_hours_saturday)),
            "excluded_hours_sunday": ",".join(map(str, cfg.excluded_hours_sunday)),
            "stall_detection_enabled": stall_enabled,
            "stall_check_bars": check_bars,
            "stall_min_profit_atr": min_profit_atr,
            "stall_sl_atr": sl_atr,
            "meta_filter_mama_enabled": cfg.meta_filter_mama_enabled,
            "meta_filter_mama_min_diff": cfg.meta_filter_mama_min_diff,
            "meta_filter_dmi_enabled": cfg.meta_filter_dmi_enabled,
            "meta_filter_dmi_min_dmp": cfg.meta_filter_dmi_min_dmp,
        },
    )
    
    # Venue configuration
    venue_config = BacktestVenueConfig(
        name="IDEALPRO",
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency="USD",
        starting_balances=["50000 USD"],
        bar_execution=True,
    )
    
    # Data configs (15-minute for strategy, 1-minute for execution)
    data_config_15m = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec=bar_spec,
        start_time=start_ns,
        end_time=end_ns,
    )
    
    data_config_1m = BacktestDataConfig(
        catalog_path=str(catalog_path),
        data_cls=Bar,
        instrument_id=catalog_instrument_id,
        bar_spec="1-MINUTE-MID",
        start_time=start_ns,
        end_time=end_ns,
    )
    
    engine_config = BacktestEngineConfig(strategies=[strategy_config])
    
    run_config = BacktestRunConfig(
        engine=engine_config,
        venues=[venue_config],
        data=[data_config_15m, data_config_1m],
        raise_exception=True,
        dispose_on_completion=True,
    )
    
    # Run backtest
    try:
        node = BacktestNode(configs=[run_config])
        node.build()
        node.run()
        
        engine = node.get_engine(run_config.id)
        positions_df = engine.trader.generate_positions_report()
        
        if len(positions_df) == 0:
            print("  Result: No trades")
            return None
        
        # Calculate metrics
        positions_df['realized_pnl_parsed'] = positions_df['realized_pnl'].apply(_parse_money)
        total_pnl = positions_df['realized_pnl_parsed'].sum()
        winning_trades = (positions_df['realized_pnl_parsed'] > 0).sum()
        total_trades = len(positions_df)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate drawdown
        positions_df = positions_df.sort_values('ts_closed')
        positions_df['cumulative_pnl'] = positions_df['realized_pnl_parsed'].cumsum()
        positions_df['peak'] = positions_df['cumulative_pnl'].cummax()
        positions_df['drawdown'] = positions_df['cumulative_pnl'] - positions_df['peak']
        max_drawdown = positions_df['drawdown'].min()
        
        # Calculate weighted score
        score = calculate_weighted_score(total_pnl, win_rate, max_drawdown, total_trades)
        
        result = {
            'iteration': iteration_name,
            'stall_enabled': stall_enabled,
            'check_bars': check_bars if stall_enabled else None,
            'min_profit_atr': min_profit_atr if stall_enabled else None,
            'sl_atr': sl_atr if stall_enabled else None,
            'total_trades': total_trades,
            'pnl': total_pnl,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'weighted_score': score,
        }
        
        print(f"  Trades: {total_trades}, P&L: ${total_pnl:,.2f}, WR: {win_rate:.1f}%, DD: ${max_drawdown:,.2f}")
        print(f"  Weighted Score: {score:.2f}")
        
        return result
        
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def main():
    """Run stall detection parameter optimization."""
    
    print("\n" + "="*80)
    print("POSITIVE STALL DETECTION OPTIMIZATION - REPLAY BACKTEST")
    print("="*80)
    print("\nThis optimization uses the realistic replay backtest engine.")
    print("Each iteration takes ~5-10 minutes for accurate results.\n")
    
    # Load configuration
    load_dotenv(PROJECT_ROOT / ".env.mtf_v2", override=True)
    cfg = load_mtf_v2_config()
    
    print(f"Backtest Period: {cfg.backtest_start} to {cfg.backtest_end}")
    print(f"Model: {cfg.model_path}")
    print(f"Position Size: ${cfg.total_position_size:,}")
    
    # Define parameter grid
    param_grid = {
        'check_bars': [2, 4, 6],
        'min_profit_atr': [0.1, 0.15, 0.2, 0.3],
        'sl_atr': [0.05, 0.1, 0.15, 0.2],
    }
    
    # Generate all combinations
    combinations = []
    for check_bars in param_grid['check_bars']:
        for min_profit in param_grid['min_profit_atr']:
            for sl_atr in param_grid['sl_atr']:
                # Skip invalid combinations (SL should be less than min profit)
                if sl_atr >= min_profit:
                    continue
                combinations.append((check_bars, min_profit, sl_atr))
    
    print(f"\nTotal parameter combinations to test: {len(combinations) + 1}")
    print(f"Estimated total time: {(len(combinations) + 1) * 7} minutes\n")
    
    input("Press Enter to start optimization (or Ctrl+C to cancel)...")
    
    results = []
    
    # Test baseline (stall detection disabled)
    print("\n" + "="*80)
    print("BASELINE TEST (Stall Detection DISABLED)")
    print("="*80)
    
    baseline_result = run_single_backtest(
        cfg=cfg,
        stall_enabled=False,
        check_bars=6,
        min_profit_atr=0.2,
        sl_atr=0.2,
        iteration_name="BASELINE"
    )
    
    if baseline_result:
        results.append(baseline_result)
        baseline_score = baseline_result['weighted_score']
        baseline_pnl = baseline_result['pnl']
        print(f"\nBaseline Score: {baseline_score:.2f}")
    else:
        print("\nERROR: Baseline test failed!")
        return
    
    # Test all parameter combinations
    for idx, (check_bars, min_profit, sl_atr) in enumerate(combinations, 1):
        iteration_name = f"Test_{idx:02d}"
        
        result = run_single_backtest(
            cfg=cfg,
            stall_enabled=True,
            check_bars=check_bars,
            min_profit_atr=min_profit,
            sl_atr=sl_atr,
            iteration_name=iteration_name
        )
        
        if result:
            results.append(result)
            improvement = result['weighted_score'] - baseline_score
            pnl_diff = result['pnl'] - baseline_pnl
            marker = " *** BETTER" if improvement > 0 else ""
            print(f"  Score vs Baseline: {improvement:+.2f} (P&L: ${pnl_diff:+,.2f}){marker}")
    
    # Save and display results
    print("\n" + "="*80)
    print("OPTIMIZATION RESULTS")
    print("="*80)
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('weighted_score', ascending=False)
    
    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = PROJECT_ROOT / f"stall_optimization_results_{timestamp}.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
    
    # Display top 10
    print("\nTOP 10 CONFIGURATIONS (by Weighted Score):")
    print("-" * 80)
    
    display_cols = ['iteration', 'stall_enabled', 'check_bars', 'min_profit_atr', 
                    'sl_atr', 'total_trades', 'pnl', 'win_rate', 'max_drawdown', 'weighted_score']
    print(results_df[display_cols].head(10).to_string(index=False))
    
    # Best configuration
    best = results_df.iloc[0]
    baseline = results_df[results_df['iteration'] == 'BASELINE'].iloc[0]
    
    print("\n" + "="*80)
    print("BEST CONFIGURATION:")
    print("="*80)
    print(f"Iteration: {best['iteration']}")
    print(f"Stall Enabled: {best['stall_enabled']}")
    if best['stall_enabled']:
        print(f"Check Bars: {best['check_bars']}")
        print(f"Min Profit ATR: {best['min_profit_atr']}")
        print(f"SL ATR: {best['sl_atr']}")
    print(f"\nMetrics:")
    print(f"  Total Trades: {best['total_trades']}")
    print(f"  P&L: ${best['pnl']:,.2f}")
    print(f"  Win Rate: {best['win_rate']:.1f}%")
    print(f"  Max Drawdown: ${best['max_drawdown']:,.2f}")
    print(f"  Weighted Score: {best['weighted_score']:.2f}")
    
    print(f"\nVS BASELINE:")
    print(f"  P&L Difference: ${best['pnl'] - baseline['pnl']:+,.2f}")
    print(f"  Win Rate Difference: {best['win_rate'] - baseline['win_rate']:+.1f}%")
    print(f"  Drawdown Difference: ${best['max_drawdown'] - baseline['max_drawdown']:+,.2f}")
    print(f"  Score Improvement: {best['weighted_score'] - baseline['weighted_score']:+.2f}")
    
    if best['weighted_score'] > baseline['weighted_score']:
        print("\n*** STALL DETECTION IMPROVES RESULTS ***")
        print("\nRecommended .env.mtf_v2 settings:")
        print(f"MTF2_STALL_DETECTION_ENABLED=true")
        print(f"MTF2_STALL_CHECK_BARS={int(best['check_bars'])}")
        print(f"MTF2_STALL_MIN_PROFIT_ATR={best['min_profit_atr']}")
        print(f"MTF2_STALL_SL_ATR={best['sl_atr']}")
    else:
        print("\n*** BASELINE IS BETTER - KEEP STALL DETECTION DISABLED ***")
    
    print("="*80)


if __name__ == "__main__":
    main()
