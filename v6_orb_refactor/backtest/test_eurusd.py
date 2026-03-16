"""
Full backtest on EURUSD 1-minute data to validate V6 architecture.
Tests complete workflow with logging enabled.
"""
from pathlib import Path
import logging

from v6_orb_refactor.config.config import StrategyConfig

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

from v6_orb_refactor.backtest.engine import BacktestRunner

def calculate_metrics(fills):
    if not fills:
        return {"total_pnl": 0, "trades": 0, "win_rate": 0, "sharpe": 0}
        
    trades = []
    current_trade = None
    
    for fill in fills:
        if fill.reason == "ENTRY":
            current_trade = {"entry_price": fill.price, "direction": fill.direction, "entry_time": fill.timestamp}
        elif fill.reason in ("SL", "TP", "MARKET") and current_trade:
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
    losing_trades = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(winning_trades) / len(trades) if trades else 0
    
    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        reason = t["reason"]
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
    
    return {
        "total_pnl": total_pnl,
        "trades": len(trades),
        "winners": len(winning_trades),
        "losers": len(losing_trades),
        "win_rate": win_rate,
        "exit_reasons": exit_reasons,
        "avg_win": sum(t["pnl"] for t in winning_trades) / len(winning_trades) if winning_trades else 0,
        "avg_loss": sum(t["pnl"] for t in losing_trades) / len(losing_trades) if losing_trades else 0
    }

def main():
    logger = logging.getLogger('v6_eurusd_backtest')
    
    # EURUSD ORB configuration (NY session)
    config = StrategyConfig(
        instrument="EURUSD",
        range_start_hour=0,   # Asian range
        range_end_hour=6,
        trade_start_hour=13,  # NY session (13:00-21:00 UTC)
        trade_end_hour=21,
        skip_weekdays=[],     # No skip for EURUSD
        velocity_filter_enabled=True,
        velocity_lookback_minutes=3,
        velocity_threshold=50.0,  # Lower threshold for EURUSD (less volatile)
        rr_ratio=2.0,
        min_range_size=0.0005,  # 5 pips minimum
        max_range_size=0.0050   # 50 pips maximum
    )
    
    data_path = r"c:\nautilus0\data\1m_csv\eurusd_1m_tick.csv"
    
    logger.info("="*60)
    logger.info("V6 EURUSD BACKTEST - Full Dataset")
    logger.info("="*60)
    logger.info(f"Data: {data_path}")
    logger.info(f"Range: {config.range_start_hour}-{config.range_end_hour} UTC")
    logger.info(f"Trade: {config.trade_start_hour}-{config.trade_end_hour} UTC")
    logger.info(f"Velocity threshold: {config.velocity_threshold} ticks/min")
    logger.info(f"RR ratio: {config.rr_ratio}")
    logger.info("="*60)
    
    runner = BacktestRunner(
        data_path=data_path,
        config=config,
        start_date="2018-01-01",  # Full dataset
        end_date="2026-03-01",
        logger=logger
    )
    
    fills = runner.run()
    metrics = calculate_metrics(fills)
    
    print("\n" + "="*60)
    print("V6 BACKTEST RESULTS - EURUSD")
    print("="*60)
    print(f"Total Trades:     {metrics['trades']}")
    
    if metrics['trades'] > 0:
        print(f"Winners:          {metrics['winners']}")
        print(f"Losers:           {metrics['losers']}")
        print(f"Win Rate:         {metrics['win_rate']:.1%}")
        print(f"Total PnL:        {metrics['total_pnl']:.5f} EUR")
        print(f"Avg Win:          {metrics['avg_win']:.5f}")
        print(f"Avg Loss:         {metrics['avg_loss']:.5f}")
        print("\nExit Reasons:")
        for reason, count in sorted(metrics['exit_reasons'].items()):
            print(f"  {reason:10s}: {count:4d} ({100*count/metrics['trades']:.1f}%)")
    else:
        print("No trades executed (check range validation parameters)")
    print("="*60)

if __name__ == "__main__":
    main()
