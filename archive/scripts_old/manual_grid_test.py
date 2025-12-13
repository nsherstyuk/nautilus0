"""
Manual testing of key conservative configurations.
Simpler approach - just modify config and track results manually.
"""
from pathlib import Path

print("="*80)
print("CONSERVATIVE STRATEGY TESTING GUIDE")
print("="*80)

configurations = [
    {
        'name': '70/20/10 - Trigger 2.0 ATR',
        'sizes': '0.7,0.2,0.1',
        'triggers': '2.0,0.0,final',
        'description': 'Early profit taking'
    },
    {
        'name': '70/20/10 - Trigger 2.5 ATR',
        'sizes': '0.7,0.2,0.1',
        'triggers': '2.5,0.0,final',
        'description': 'Current conservative (already tested)'
    },
    {
        'name': '70/20/10 - Trigger 3.0 ATR',
        'sizes': '0.7,0.2,0.1',
        'triggers': '3.0,0.0,final',
        'description': 'Later profit taking'
    },
    {
        'name': '75/15/10 - Trigger 2.5 ATR',
        'sizes': '0.75,0.15,0.1',
        'triggers': '2.5,0.0,final',
        'description': 'Very conservative'
    },
    {
        'name': '60/25/15 - Trigger 2.5 ATR',
        'sizes': '0.6,0.25,0.15',
        'triggers': '2.5,0.0,final',
        'description': 'Moderate conservative'
    },
    {
        'name': '70/20/10 - Trigger 2.5, Second 0.5 ATR',
        'sizes': '0.7,0.2,0.1',
        'triggers': '2.5,0.5,final',
        'description': 'Second layer at small profit instead of BE'
    },
]

print("\nConfigurations to test:")
for i, config in enumerate(configurations, 1):
    print(f"\n{i}. {config['name']}")
    print(f"   {config['description']}")
    print(f"   Sizes: {config['sizes']}")
    print(f"   Triggers: {config['triggers']}")

print("\n" + "="*80)
print("MANUAL TESTING PROCEDURE")
print("="*80)

print("""
For each configuration:

1. Edit .env.mtf:
   - Set MTF_MULTI_LAYER_ENABLED=true
   - Set MTF_MULTI_LAYER_SIZES=<sizes from above>
   - Set MTF_MULTI_LAYER_TRIGGERS=<triggers from above>

2. Run backtest:
   python run_mtf_backtest_multi_layer.py

3. Record results:
   - Total P&L (2024-2025)
   - 2025 P&L
   - Oct-Nov 2025 P&L
   - Negative months
   - Max drawdown

4. Compare with baseline:
   - Current (50/50): $113,697 total, $61,791 (2025), 1 negative month
   - Conservative (70/20/10 @ 2.5): $103,255 total, $55,270 (2025), 0 negative months

5. Look for configuration with:
   - Total P&L > $105,000 (>92% of baseline)
   - Zero negative months
   - Max drawdown < $1,800
   - Oct-Nov 2025 > $0

""")

print("="*80)
print("RESULTS TRACKING TEMPLATE")
print("="*80)

print("""
Copy this template to track results:

Configuration: _______________
Total P&L: $__________
2025 P&L: $__________
Oct-Nov 2025: $__________
Negative Months: ___
Max Drawdown: $__________
Negative Days %: ____%

Notes:
_______________________________________
_______________________________________

""")

print("="*80)
print("RECOMMENDATION")
print("="*80)

print("""
Based on initial testing, focus on these 3:

1. 70/20/10 @ 2.5 ATR (already tested - baseline conservative)
2. 70/20/10 @ 2.0 ATR (earlier profit taking - might improve Oct-Nov)
3. 60/25/15 @ 2.5 ATR (more balanced - might improve total P&L)

Test these 3 first, then decide if others are worth testing.
""")

# Create results tracking file
results_file = Path('conservative_test_results.txt')
with open(results_file, 'w') as f:
    f.write("CONSERVATIVE STRATEGY TEST RESULTS\n")
    f.write("="*80 + "\n\n")
    f.write("Baseline (Current 50/50):\n")
    f.write("  Total P&L: $113,697\n")
    f.write("  2025 P&L: $61,791\n")
    f.write("  Oct-Nov 2025: $1,443\n")
    f.write("  Negative Months: 1\n")
    f.write("  Max Drawdown: -$2,028\n")
    f.write("  Negative Days: 33.2%\n\n")
    f.write("-"*80 + "\n\n")
    
    for config in configurations:
        f.write(f"{config['name']}\n")
        f.write(f"  Description: {config['description']}\n")
        f.write(f"  Sizes: {config['sizes']}\n")
        f.write(f"  Triggers: {config['triggers']}\n")
        f.write(f"  Total P&L: $__________\n")
        f.write(f"  2025 P&L: $__________\n")
        f.write(f"  Oct-Nov 2025: $__________\n")
        f.write(f"  Negative Months: ___\n")
        f.write(f"  Max Drawdown: $__________\n")
        f.write(f"  Negative Days %: ____%\n")
        f.write(f"  Notes: _______________________\n\n")
        f.write("-"*80 + "\n\n")

print(f"\n✅ Results tracking template saved to: {results_file}")
print("\nYou can fill in results as you test each configuration.")
