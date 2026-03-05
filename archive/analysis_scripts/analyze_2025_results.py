import pandas as pd
import numpy as np
from datetime import date, timedelta

trades_path = r"c:\nautilus0\backtest_results\MTF_V2_REPLAY_20251228_113704\trades.csv"

try:
    df = pd.read_csv(trades_path)
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    # Convert to EST/New York for "Daily" logic if needed, but usually UTC is fine for backtest aggregation unless strictly session based.
    # The summary uses EST for hours. Let's convert to US/Eastern for day grouping to match user's perspective.
    df['exit_time'] = df['exit_time'].dt.tz_convert('US/Eastern')
    df['date'] = df['exit_time'].dt.date
    
    # Daily PnL (Trading Days only)
    daily_pnl = df.groupby('date')['pnl'].sum()
    
    # Calendar analysis
    start_date = date(2025, 1, 1)
    end_date = date(2025, 12, 30)
    all_dates = pd.date_range(start_date, end_date, freq='B').date # Business days
    
    # Reindex to include all business days (filling 0 for no trades)
    daily_pnl_all = daily_pnl.reindex(all_dates, fill_value=0)
    
    total_business_days = len(daily_pnl_all)
    trading_days = len(daily_pnl) # Days with actual trades
    
    negative_days = daily_pnl[daily_pnl < 0]
    positive_days = daily_pnl[daily_pnl > 0]
    flat_days = daily_pnl[daily_pnl == 0] # Days with trades but 0 PnL sum
    
    # "Zero days" interpretation: User likely asks about days with NO profit (loss) OR days with NO trades.
    # Usually "Zero days" in common parlance might mean days with 0 PnL (no trades).
    no_trade_days = len(all_dates) - len(daily_pnl)
    
    print(f"Analysis Period: {start_date} to {end_date}")
    print(f"Total Business Days: {total_business_days}")
    print(f"Days With Trades: {trading_days}")
    print("-" * 30)
    print(f"Positive Days: {len(positive_days)}")
    print(f"Negative Days: {len(negative_days)}")
    print(f"Flat Days (Trading PnL = 0): {len(flat_days)}")
    print(f"Idle Days (No Trades): {no_trade_days}")
    
    # Consecutive Negative Days (on days with trades)
    # We usually count consecutive LOSING trading days.
    is_loss = daily_pnl < 0
    # Group consecutive Trues
    loss_streaks = is_loss.ne(is_loss.shift()).cumsum()
    consecutive_loss_counts = is_loss.groupby(loss_streaks).apply(lambda x: x.sum() if x.any() else 0)
    max_consecutive_losses = consecutive_loss_counts.max()
    
    print("-" * 30)
    print(f"Max Consecutive Negative Trading Days: {max_consecutive_losses}")
    
    # Max Drawdown (Daily Close Basis) - just for comparison
    cumulative_pnl = daily_pnl_all.cumsum()
    running_max = cumulative_pnl.cummax()
    drawdown = cumulative_pnl - running_max
    max_dd_daily = drawdown.min()
    
    print(f"Max Drawdown (Daily Close): ${max_dd_daily:.2f}")
    
    # Detailed stats
    print("-" * 30)
    print(f"Total PnL: ${daily_pnl.sum():.2f}")
    print(f"Worst Day: ${daily_pnl.min():.2f} on {daily_pnl.idxmin()}")
    print(f"Best Day: ${daily_pnl.max():.2f} on {daily_pnl.idxmax()}")

except Exception as e:
    print(f"Error: {e}")
