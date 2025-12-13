"""
Check if regime detection is configured correctly and analyze last backtest results.
"""
import pandas as pd
from pathlib import Path
import re

# Find latest backtest folder
results_dir = Path("logs/backtest_results")
folders = sorted([f for f in results_dir.iterdir() if f.is_dir() and f.name.startswith("EUR-USD_")], 
                 key=lambda x: x.stat().st_mtime, reverse=True)

if not folders:
    print("No backtest results found!")
    exit(1)

latest_folder = folders[0]
print(f"Latest backtest folder: {latest_folder.name}")
print("=" * 80)

# Check .env file in results folder
env_file = latest_folder / ".env"
if env_file.exists():
    print("\n1. CONFIGURATION IN BACKTEST RESULTS (.env file):")
    print("=" * 80)
    env_content = env_file.read_text(encoding='utf-8')
    
    # Check for regime detection settings
    regime_enabled = "STRATEGY_REGIME_DETECTION_ENABLED=true" in env_content
    dmi_enabled = "STRATEGY_DMI_ENABLED=true" in env_content
    
    print(f"STRATEGY_DMI_ENABLED: {dmi_enabled}")
    print(f"STRATEGY_REGIME_DETECTION_ENABLED: {regime_enabled}")
    
    # Extract regime parameters
    regime_params = {}
    for line in env_content.split('\n'):
        if 'STRATEGY_REGIME' in line and '=' in line:
            key, value = line.split('=', 1)
            regime_params[key.strip()] = value.strip()
            print(f"{key.strip()}: {value.strip()}")
    
    # Extract DMI settings
    dmi_bar_spec = None
    for line in env_content.split('\n'):
        if 'STRATEGY_DMI_BAR_SPEC=' in line:
            dmi_bar_spec = line.split('=', 1)[1].strip()
            print(f"\nSTRATEGY_DMI_BAR_SPEC: {dmi_bar_spec}")
            break
    
    if not regime_enabled:
        print("\n⚠️  PROBLEM: Regime detection is DISABLED!")
    if not dmi_enabled:
        print("\n⚠️  PROBLEM: DMI is DISABLED (required for regime detection)!")
    
else:
    print("\n⚠️  No .env file found in results folder")

# Check positions.csv for actual TP/SL values
positions_file = latest_folder / "positions.csv"
if positions_file.exists():
    print("\n" + "=" * 80)
    print("2. ANALYZING ACTUAL TRADES:")
    print("=" * 80)
    
    pos_df = pd.read_csv(positions_file)
    
    if len(pos_df) == 0:
        print("No trades found in positions.csv")
    else:
        # Extract PnL
        if pos_df['realized_pnl'].dtype == 'object':
            pos_df['pnl_value'] = pos_df['realized_pnl'].str.replace(' USD', '', regex=False).str.replace('USD', '', regex=False).str.strip().astype(float)
        else:
            pos_df['pnl_value'] = pos_df['realized_pnl'].astype(float)
        
        pos_df['entry_price'] = pos_df['avg_px_open'].astype(float)
        pos_df['exit_price'] = pos_df['avg_px_close'].astype(float)
        
        # Calculate actual TP/SL in pips
        pos_df['price_diff'] = pos_df['exit_price'] - pos_df['entry_price']
        pos_df['price_diff_pips'] = pos_df.apply(
            lambda row: row['price_diff'] * 10000 if row['entry'] == 'BUY' else -row['price_diff'] * 10000,
            axis=1
        )
        
        # Check if TP/SL values are consistent (would indicate regime detection not working)
        tp_values = pos_df[pos_df['pnl_value'] > 0]['price_diff_pips'].abs()
        sl_values = pos_df[pos_df['pnl_value'] < 0]['price_diff_pips'].abs()
        
        print(f"\nTotal Trades: {len(pos_df)}")
        print(f"Winning Trades: {len(tp_values)}")
        print(f"Losing Trades: {len(sl_values)}")
        
        if len(tp_values) > 0:
            print(f"\nTake Profit Values (pips):")
            print(f"  Min: {tp_values.min():.1f}")
            print(f"  Max: {tp_values.max():.1f}")
            print(f"  Mean: {tp_values.mean():.1f}")
            print(f"  Std: {tp_values.std():.1f}")
            
            # Check if all TP values are similar (would indicate no regime adjustment)
            if tp_values.std() < 5:
                print(f"\n⚠️  WARNING: TP values are very consistent (std={tp_values.std():.1f} pips)")
                print(f"   This suggests regime detection may not be adjusting TP!")
            else:
                print(f"\n✓ TP values vary (std={tp_values.std():.1f} pips) - regime detection may be working")
        
        if len(sl_values) > 0:
            print(f"\nStop Loss Values (pips):")
            print(f"  Min: {sl_values.min():.1f}")
            print(f"  Max: {sl_values.max():.1f}")
            print(f"  Mean: {sl_values.mean():.1f}")
            print(f"  Std: {sl_values.std():.1f}")
        
        # Show sample trades
        print(f"\nSample Trades (first 5):")
        for idx, row in pos_df.head(5).iterrows():
            print(f"  {row['ts_opened']}: {row['entry']} - PnL=${row['pnl_value']:.2f}, "
                  f"Price Move={row['price_diff_pips']:.1f} pips")

# Check log files for regime detection messages
log_files = list(latest_folder.glob("*.log"))
if log_files:
    print("\n" + "=" * 80)
    print("3. CHECKING LOGS FOR REGIME DETECTION MESSAGES:")
    print("=" * 80)
    
    regime_messages = []
    for log_file in log_files:
        try:
            content = log_file.read_text(encoding='utf-8', errors='ignore')
            # Look for regime change messages
            matches = re.findall(r'Market regime.*?ADX=([\d.]+)', content)
            if matches:
                regime_messages.extend(matches)
        except:
            pass
    
    if regime_messages:
        print(f"\n✓ Found {len(regime_messages)} regime detection messages in logs")
        print(f"  Sample ADX values: {regime_messages[:10]}")
    else:
        print("\n⚠️  No regime detection messages found in logs!")
        print("   This suggests regime detection is not running or not logging")

print("\n" + "=" * 80)
print("DIAGNOSIS:")
print("=" * 80)

if not dmi_enabled:
    print("\n❌ DMI is DISABLED - Regime detection cannot work!")
    print("   Fix: Set STRATEGY_DMI_ENABLED=true in .env file")

if not regime_enabled:
    print("\n❌ Regime detection is DISABLED!")
    print("   Fix: Set STRATEGY_REGIME_DETECTION_ENABLED=true in .env file")

if dmi_enabled and regime_enabled:
    print("\n✓ Configuration looks correct")
    print("   If PnL is the same with/without regime detection:")
    print("   - Check if ADX values are actually crossing thresholds")
    print("   - Check if trades are hitting TP/SL before regime can help")
    print("   - Verify DMI bars are available in data catalog")



