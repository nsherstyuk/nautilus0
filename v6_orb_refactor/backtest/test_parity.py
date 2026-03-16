from pathlib import Path
import logging

from v6_orb_refactor.config.config import StrategyConfig
from v6_orb_refactor.backtest.engine import BacktestRunner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def calculate_metrics(fills):
    if not fills:
        return {"total_pnl": 0, "trades": 0, "win_rate": 0}
        
    trades = []
    current_trade = None
    
    for fill in fills:
        if fill.reason == "ENTRY":
            current_trade = {"entry_price": fill.price, "direction": fill.direction, "entry_time": fill.timestamp}
        elif fill.reason in ("SL", "TP", "MARKET") and current_trade:
            # Calculate PnL (in points/dollars)
            multiplier = 1 if current_trade["direction"] == "LONG" else -1
            pnl = (fill.price - current_trade["entry_price"]) * multiplier
            
            current_trade["exit_price"] = fill.price
            current_trade["exit_time"] = fill.timestamp
            current_trade["reason"] = fill.reason
            current_trade["pnl"] = pnl
            trades.append(current_trade)
            current_trade = None
            
    total_pnl = sum(t["pnl"] for t in trades)
    winning_trades = [t for t in trades if t["pnl"] > 0]
    win_rate = len(winning_trades) / len(trades) if trades else 0
    
    return {
        "total_pnl": total_pnl,
        "trades": len(trades),
        "win_rate": win_rate
    }

def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger('v6_backtest')
    
    config = StrategyConfig(
        instrument="XAUUSD",
        range_start_hour=0,
        range_end_hour=6,
        trade_start_hour=8,
        trade_end_hour=16,
        skip_weekdays=[2],  # Skip Wednesday
        velocity_filter_enabled=True,
        velocity_lookback_minutes=3,
        velocity_threshold=168.0,
        rr_ratio=2.5,
        min_range_size=1.0,
        max_range_size=15.0
    )
    
    data_path = r"c:\nautilus0\data\1m_csv\xauusd_1m_tick.csv"
    
    runner = BacktestRunner(
        data_path=data_path,
        config=config,
        start_date="2018-01-01",
        end_date="2026-02-25"
    )
    
    fills = runner.run()
    metrics = calculate_metrics(fills)
    
    print("\nBacktest Results (V6 Refactor):")
    print(f"Total PnL: ${metrics['total_pnl']:.2f}")
    print(f"Total Trades: {metrics['trades']}")
    print(f"Win Rate: {metrics['win_rate']:.1%}")

if __name__ == "__main__":
    main()
