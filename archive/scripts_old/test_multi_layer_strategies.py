"""
Test different multi-layer exit strategies and compare with current setup.

Tests:
1. Current (50/50) - baseline
2. Conservative (70/20/10) - lock in more profit early
3. Balanced (30/30/40) - three equal stages
4. Aggressive (20/20/60) - let most position run

Each test runs full backtest and compares results.
"""
import subprocess
import os
from pathlib import Path

# Test configurations
strategies = [
    {
        'name': 'Current (50/50 Standard)',
        'enabled': 'false',
        'description': 'Baseline - standard 50% partial close'
    },
    {
        'name': 'Conservative (70/20/10)',
        'enabled': 'true',
        'count': 3,
        'sizes': '0.7,0.2,0.1',
        'triggers': '2.5,0.0,final',
        'description': '70% at 2.5 ATR, 20% at breakeven, 10% continues'
    },
    {
        'name': 'Balanced (30/30/40)',
        'enabled': 'true',
        'count': 3,
        'sizes': '0.3,0.3,0.4',
        'triggers': '2.5,3.5,final',
        'description': '30% at 2.5 ATR, 30% at 3.5 ATR, 40% continues'
    },
    {
        'name': 'Aggressive (20/20/60)',
        'enabled': 'true',
        'count': 3,
        'sizes': '0.2,0.2,0.6',
        'triggers': '2.5,3.5,final',
        'description': '20% at 2.5 ATR, 20% at 3.5 ATR, 60% continues'
    },
    {
        'name': 'Four-Layer (25/25/25/25)',
        'enabled': 'true',
        'count': 4,
        'sizes': '0.25,0.25,0.25,0.25',
        'triggers': '2.0,2.5,3.0,final',
        'description': '25% at each of 4 levels'
    }
]

print("="*80)
print("MULTI-LAYER EXIT STRATEGY TESTING")
print("="*80)

print("\nStrategies to test:")
for i, strat in enumerate(strategies, 1):
    print(f"{i}. {strat['name']}")
    print(f"   {strat['description']}")

print("\n" + "="*80)
print("RUNNING BACKTESTS")
print("="*80)

# Load current .env.mtf
env_file = Path('.env.mtf')
with open(env_file, 'r') as f:
    env_content = f.read()

# Backup original
backup_file = Path('.env.mtf.backup_multi_layer')
with open(backup_file, 'w') as f:
    f.write(env_content)

print(f"\n✅ Backed up .env.mtf to {backup_file}")

results = []

for strat in strategies:
    print(f"\n{'='*80}")
    print(f"TESTING: {strat['name']}")
    print(f"{'='*80}")
    
    # Modify .env.mtf for this strategy
    lines = env_content.split('\n')
    new_lines = []
    
    for line in lines:
        if line.startswith('MTF_MULTI_LAYER_ENABLED='):
            new_lines.append(f"MTF_MULTI_LAYER_ENABLED={strat['enabled']}")
        elif line.startswith('MTF_MULTI_LAYER_COUNT=') and 'count' in strat:
            new_lines.append(f"MTF_MULTI_LAYER_COUNT={strat['count']}")
        elif line.startswith('MTF_MULTI_LAYER_SIZES=') and 'sizes' in strat:
            new_lines.append(f"MTF_MULTI_LAYER_SIZES={strat['sizes']}")
        elif line.startswith('MTF_MULTI_LAYER_TRIGGERS=') and 'triggers' in strat:
            new_lines.append(f"MTF_MULTI_LAYER_TRIGGERS={strat['triggers']}")
        else:
            new_lines.append(line)
    
    # Write modified config
    with open(env_file, 'w') as f:
        f.write('\n'.join(new_lines))
    
    print(f"Configuration:")
    if strat['enabled'] == 'true':
        print(f"  Layers: {strat.get('count', 3)}")
        print(f"  Sizes: {strat.get('sizes', 'N/A')}")
        print(f"  Triggers: {strat.get('triggers', 'N/A')}")
    else:
        print(f"  Standard partial close (50/50)")
    
    # Run backtest
    print(f"\nRunning backtest...")
    result = subprocess.run(
        ['python', 'run_mtf_backtest_multi_layer.py'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("✅ Backtest completed successfully")
        
        # Parse results from output
        output = result.stdout
        
        # Extract key metrics (you'll need to parse the actual output)
        # For now, just indicate success
        results.append({
            'strategy': strat['name'],
            'status': 'Success',
            'description': strat['description']
        })
    else:
        print(f"❌ Backtest failed")
        print(f"Error: {result.stderr}")
        results.append({
            'strategy': strat['name'],
            'status': 'Failed',
            'description': strat['description']
        })

# Restore original config
with open(backup_file, 'r') as f:
    original_content = f.read()

with open(env_file, 'w') as f:
    f.write(original_content)

print(f"\n✅ Restored original .env.mtf")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)

for result in results:
    print(f"\n{result['strategy']}: {result['status']}")
    print(f"  {result['description']}")

print("\n" + "="*80)
print("NEXT STEPS")
print("="*80)

print("""
1. Review backtest results in logs/backtest_results/
2. Compare P&L, win rates, and drawdowns
3. Check Oct-Nov performance specifically
4. Choose best strategy for deployment

To manually test a specific strategy:
1. Edit .env.mtf
2. Set MTF_MULTI_LAYER_ENABLED=true
3. Configure sizes and triggers
4. Run: python run_mtf_backtest_multi_layer.py
""")
