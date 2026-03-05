import pandas as pd
import re
from pathlib import Path

backtest_dir = Path(r"C:\nautilus0\backtest_results\MTF_V2_ENTRY_CONFIRMED_20260109_085706")
log_file = backtest_dir / "strategy_decisions.log"

print("Analyzing MAMA filter impact on trading performance...")
print("=" * 70)

with open(log_file, 'r', encoding='utf-8') as f:
    log_text = f.read()

signal_pattern = re.compile(
    r'\[SIGNAL\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+\d{2}:\d{2}) '
    r'(LONG|SHORT) pred=([\d.]+) conf=([\d.]+) '
    r'mama_diff=([-\d.]+) dmi_plus=([\d.]+)'
)

signals = []
for match in signal_pattern.finditer(log_text):
    timestamp, direction, pred, conf, mama_diff, dmi_plus = match.groups()
    signals.append({
        'timestamp': timestamp,
        'direction': direction,
        'pred': float(pred),
        'conf': float(conf),
        'mama_diff': float(mama_diff),
        'dmi_plus': float(dmi_plus)
    })

df_signals = pd.DataFrame(signals)

if len(df_signals) == 0:
    print("ERROR: No signals found in log file")
    exit(1)

print(f"\nTotal ML signals generated: {len(df_signals)}")
print(f"MAMA diff range: [{df_signals['mama_diff'].min():.6f}, {df_signals['mama_diff'].max():.6f}]")
print(f"Current threshold: 0.0001")

trades_df = pd.read_csv(backtest_dir / "trades.csv")
print(f"\nActual trades executed: {len(trades_df)}")

if len(trades_df) > 0:
    winning_trades = trades_df[trades_df['pnl'] > 0]
    current_winrate = len(winning_trades) / len(trades_df) * 100
    current_pnl = trades_df['pnl'].sum()
    current_avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
    current_avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if len(trades_df[trades_df['pnl'] < 0]) > 0 else 0
    
    print(f"Current performance:")
    print(f"  Win rate: {current_winrate:.1f}%")
    print(f"  Total PnL: ${current_pnl:,.0f}")
    print(f"  Avg win: ${current_avg_win:.2f}")
    print(f"  Avg loss: ${current_avg_loss:.2f}")

print("\n" + "=" * 70)
print("MAMA THRESHOLD SENSITIVITY ANALYSIS")
print("=" * 70)

thresholds = [-0.0005, -0.0003, -0.0001, 0.0, 0.0001, 0.0002, 0.0003, 0.0005]

print(f"\n{'Threshold':<12} {'Signals':<10} {'% of Total':<12} {'Change':<10}")
print("-" * 50)

base_count = len(df_signals[df_signals['mama_diff'] >= 0.0001])

for threshold in thresholds:
    passed = df_signals[df_signals['mama_diff'] >= threshold]
    count = len(passed)
    pct = count / len(df_signals) * 100
    change = count - base_count
    
    marker = " <-- CURRENT" if threshold == 0.0001 else ""
    print(f"{threshold:>10.4f}   {count:<10} {pct:>6.1f}%      {change:+5d}{marker}")

print("\n" + "=" * 70)
print("MAMA DIFF DISTRIBUTION")
print("=" * 70)

bins = [
    (-float('inf'), -0.001, "< -0.001"),
    (-0.001, -0.0005, "-0.001 to -0.0005"),
    (-0.0005, -0.0003, "-0.0005 to -0.0003"),
    (-0.0003, -0.0001, "-0.0003 to -0.0001"),
    (-0.0001, 0.0, "-0.0001 to 0.0"),
    (0.0, 0.0001, "0.0 to 0.0001"),
    (0.0001, 0.0003, "0.0001 to 0.0003"),
    (0.0003, 0.0005, "0.0003 to 0.0005"),
    (0.0005, float('inf'), "> 0.0005")
]

print(f"\n{'Range':<25} {'Count':<10} {'% of Total':<12}")
print("-" * 50)

for low, high, label in bins:
    count = len(df_signals[(df_signals['mama_diff'] >= low) & (df_signals['mama_diff'] < high)])
    pct = count / len(df_signals) * 100
    print(f"{label:<25} {count:<10} {pct:>6.1f}%")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)

print("""
To estimate performance with different MAMA thresholds, you would need to:

1. CONSERVATIVE (threshold = 0.0): 
   - Would allow ~2-3x more signals
   - May reduce win rate slightly but increase total trades
   
2. MODERATE (threshold = -0.0001):
   - Would allow ~4-5x more signals
   - Moderate impact on win rate
   
3. AGGRESSIVE (threshold = -0.0003):
   - Would allow ~6-8x more signals
   - Higher risk of lower win rate

NEXT STEPS:
To get actual performance estimates, you need to:
1. Modify .env.mtf_v2: MTF2_META_MAMA_MIN_DIFF=-0.0001 (or other value)
2. Run backtest: python run_backtest_mtf_v2_entry_confirmed.py
3. Compare results

The meta-filter was added based on historical analysis showing MAMA diff < 0.0001
was a "toxic regime". Relaxing it may increase trades but could hurt win rate.
""")
