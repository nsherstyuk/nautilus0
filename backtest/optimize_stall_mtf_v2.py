
import logging
import os
import sys
import re
import pandas as pd
from pathlib import Path
from datetime import datetime
from decimal import Decimal
import itertools
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
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

# Configure logging to be less verbose
logging.getLogger("nautilus_trader").setLevel(logging.WARNING)
logging.getLogger("strategies.ml_strategy_mtf_v2").setLevel(logging.WARNING)
logging.getLogger("MLSignalStrategy_V2").setLevel(logging.WARNING)

_MONEY_RE = re.compile(r"(-?\d+(?:\.\d+)?)")

def _parse_pnl(value):
    if pd.isna(value):
        return 0.0
    match = _MONEY_RE.search(str(value))
    return float(match.group(1)) if match else 0.0

def run_backtest_iteration(cfg, stall_params, iteration_idx, total_iterations, enabled=True):
    """Run a single backtest with specific stall parameters."""
    
    # Setup paths
    catalog_path = Path("data") / "historical"
    
    # Configure Instrument
    catalog_instrument_id = f"{cfg.symbol}.{cfg.venue}"
    bar_spec = cfg.bar_spec
    if isinstance(bar_spec, str) and bar_spec.upper().endswith("-EXTERNAL"):
        bar_spec = bar_spec[: -len("-EXTERNAL")]
    catalog_bar_type = f"{catalog_instrument_id}-{bar_spec}-EXTERNAL"

    # Strategy Config with Overrides
    strategy_config_dict = {
        "order_id_tag": f"OPT_{iteration_idx}",
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
        "max_positions": cfg.max_positions,
        
        # === OPTIMIZATION PARAMETERS ===
        "stall_detection_enabled": enabled,
        "stall_check_bars": stall_params.get("check_bars", 6),
        "stall_min_profit_atr": stall_params.get("min_profit_atr", 0.1),
        "stall_sl_atr": stall_params.get("sl_atr", 0.2),
        
        "meta_filter_mama_enabled": cfg.meta_filter_mama_enabled,
        "meta_filter_mama_min_diff": cfg.meta_filter_mama_min_diff,
        "meta_filter_dmi_enabled": cfg.meta_filter_dmi_enabled,
        "meta_filter_dmi_min_dmp": cfg.meta_filter_dmi_min_dmp,
    }

    strategy_config = ImportableStrategyConfig(
        strategy_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2",
        config_path="strategies.ml_strategy_mtf_v2:MLSignalStrategyV2Config",
        config=strategy_config_dict,
    )

    # Fill Model
    fill_model = ImportableFillModelConfig(
        fill_model_path="nautilus_trader.backtest.models:BestPriceFillModel",
        config_path="nautilus_trader.backtest.config:FillModelConfig",
        config={
            "prob_fill_on_limit": 0.95,
            "prob_fill_on_stop": 1.0,
            "prob_slippage": 0.4,
            "random_seed": 42,
        },
    )

    # Venue
    is_fx = "/" in str(cfg.symbol)
    starting_balances = [f"{float(cfg.initial_balance):.2f} USD"]
    base_currency = "USD"
    if is_fx:
        base_currency = None
        # Simplified FX handling for this script
        pass

    venue_config = BacktestVenueConfig(
        name=cfg.venue,
        oms_type="NETTING",
        account_type="MARGIN",
        base_currency=base_currency,
        starting_balances=starting_balances,
        fill_model=fill_model,
        bar_execution=True,
    )

    # Data Configs
    start_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_start, tz="UTC").to_pydatetime())
    end_ns = dt_to_unix_nanos(pd.Timestamp(cfg.backtest_end, tz="UTC").to_pydatetime())

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

    # Run Config
    run_config = BacktestRunConfig(
        engine=BacktestEngineConfig(strategies=[strategy_config]),
        venues=[venue_config],
        data=[data_config_15m, data_config_1m],
        raise_exception=True,
        dispose_on_completion=True,
    )

    # Execute
    print(f"[{iteration_idx}/{total_iterations}] Running: {stall_params} ... ", end="", flush=True)
    node = BacktestNode(configs=[run_config])
    try:
        node.run()
        engine = node.get_engine(run_config.id)
        
        # Calculate Metrics from Positions
        positions_df = engine.trader.generate_positions_report()
        
        total_pnl = 0.0
        win_rate = 0.0
        num_trades = 0
        
        if not positions_df.empty:
            # Parse PnL strings (e.g., "150.00 USD") to floats
            realized_pnls = positions_df["realized_pnl"].apply(_parse_pnl)
            total_pnl = realized_pnls.sum()
            
            # Count closed trades
            # Nautilus positions always have a row, check if closed
            closed_mask = positions_df["ts_closed"].notna()
            closed_pnls = realized_pnls[closed_mask]
            
            num_trades = len(closed_pnls)
            if num_trades > 0:
                wins = closed_pnls[closed_pnls > 0]
                win_rate = len(wins) / num_trades
            
        print(f"PnL: ${total_pnl:,.2f} | WR: {win_rate:.1%} ({num_trades} trades)")
        
        return {
            **stall_params,
            "pnl": total_pnl,
            "win_rate": win_rate,
            "trades": num_trades,
        }
        
    except Exception as e:
        print(f"FAILED: {e}")
        # Print full traceback for debugging if needed, but keeping it simple for now
        import traceback
        traceback.print_exc()
        return None
    finally:
        node.dispose()

def main():
    # Load Base Config
    load_dotenv(PROJECT_ROOT / ".env.mtf_v2", override=True)
    cfg = load_mtf_v2_config()
    
    print("="*60)
    print(" MTF V2 POSITIVE STALL OPTIMIZATION")
    print("="*60)
    print(f"Period: {cfg.backtest_start} to {cfg.backtest_end}")
    print(f"Base Strategy PnL (approx target to beat): Run without stall first to verify.")
    
    # Define Parameter Grid
    # We want to find a sweet spot where we cut losers early but don't choke winners
    
    param_grid = {
        # How long to wait before checking (15m bars)
        # 2 = 30m, 4 = 1h, 8 = 2h
        "check_bars": [2, 3, 4, 6], 
        
        # Minimum profit (ATR) required to trigger the tightening
        # If too low (0.1), we tighten on noise. If too high (0.5), we miss the stall.
        "min_profit_atr": [0.1, 0.2, 0.3, 0.4],
        
        # The New SL distance (ATR)
        # If too small (0.1), we surely get stopped out. If large (0.8), it's loose protection.
        # Original SL is 1.2.
        "sl_atr": [0.2, 0.4, 0.6, 0.8]
    }
    
    # Generate combinations
    keys, values = zip(*param_grid.items())
    combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    print(f"Total Combinations: {len(combinations)}")
    print("-" * 60)
    
    results = []
    
    # Run Baseline (Disabled)
    print("[0/0] BASELINE (Stall Disabled) ... ", end="", flush=True)
    baseline_res = run_backtest_iteration(cfg, {
        "check_bars": 0, "min_profit_atr": 0, "sl_atr": 0
    }, 0, len(combinations), enabled=False)
    
    if baseline_res:
        results.append({**baseline_res, "label": "BASELINE"})
    
    # Run Grid
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"stall_optimization_{timestamp}.csv"
    
    for i, params in enumerate(combinations, 1):
        res = run_backtest_iteration(cfg, params, i, len(combinations))
        if res:
            res["label"] = "TEST"
            results.append(res)
            
            # Incremental Save
            pd.DataFrame(results).to_csv(output_file, index=False)
            
    # Analysis
    df = pd.DataFrame(results)
    if df.empty:
        print("No results collected.")
        return

    print("\n" + "="*60)
    print(" TOP 10 RESULTS BY PnL")
    print("="*60)
    
    df_sorted = df.sort_values("pnl", ascending=False)
    
    print(df_sorted[[
        "check_bars", "min_profit_atr", "sl_atr", 
        "pnl", "win_rate", "trades", "label"
    ]].head(10).to_string(index=False))
    
    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"stall_optimization_{timestamp}.csv"
    df_sorted.to_csv(output_file, index=False)
    print(f"\nFull results saved to: {output_file}")

if __name__ == "__main__":
    main()
