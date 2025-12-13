"""
Minimal subprocess test to verify backtest can run via subprocess.
"""
import subprocess
import sys
from pathlib import Path

print("Testing subprocess execution of backtest...")
print("="*80)

# Modify .env.mtf to a known configuration
env_file = Path('.env.mtf')
with open(env_file, 'r') as f:
    original = f.read()

# Backup
backup = Path('.env.mtf.backup_test')
with open(backup, 'w') as f:
    f.write(original)

print("✅ Backed up .env.mtf")

# Set to simple configuration
lines = original.split('\n')
new_lines = []
for line in lines:
    if line.startswith('MTF_MULTI_LAYER_ENABLED='):
        new_lines.append('MTF_MULTI_LAYER_ENABLED=true')
    elif line.startswith('MTF_MULTI_LAYER_SIZES='):
        new_lines.append('MTF_MULTI_LAYER_SIZES=0.7,0.2,0.1')
    elif line.startswith('MTF_MULTI_LAYER_TRIGGERS='):
        new_lines.append('MTF_MULTI_LAYER_TRIGGERS=2.5,0.0,final')
    elif line.startswith('MTF_TP_ATR_MULT='):
        new_lines.append('MTF_TP_ATR_MULT=8.0')
    else:
        new_lines.append(line)

with open(env_file, 'w') as f:
    f.write('\n'.join(new_lines))

print("✅ Modified .env.mtf")
print("\nRunning backtest via subprocess...")
print("-"*80)

# Try different subprocess approaches
approaches = [
    {
        'name': 'Approach 1: Basic capture_output',
        'kwargs': {
            'capture_output': True,
            'text': True
        }
    },
    {
        'name': 'Approach 2: UTF-8 encoding',
        'kwargs': {
            'capture_output': True,
            'text': True,
            'encoding': 'utf-8',
            'errors': 'replace'
        }
    },
    {
        'name': 'Approach 3: Redirect to file',
        'kwargs': {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
            'text': True,
            'encoding': 'utf-8',
            'errors': 'ignore'
        }
    },
]

for approach in approaches:
    print(f"\n{approach['name']}")
    print("-"*80)
    
    try:
        result = subprocess.run(
            [sys.executable, 'run_mtf_backtest_multi_layer.py'],
            **approach['kwargs'],
            timeout=120  # 2 minute timeout
        )
        
        if result.returncode == 0:
            print(f"✅ SUCCESS!")
            print(f"   Return code: {result.returncode}")
            
            # Try to extract P&L from output
            if hasattr(result, 'stdout') and result.stdout:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Total P&L' in line or 'OVERALL' in line:
                        print(f"   {line.strip()}")
            
            print(f"\n✅ This approach works! Use it for optimization.")
            
            # Restore and exit
            with open(env_file, 'w') as f:
                f.write(original)
            print(f"\n✅ Restored .env.mtf")
            sys.exit(0)
        else:
            print(f"❌ FAILED")
            print(f"   Return code: {result.returncode}")
            if hasattr(result, 'stderr') and result.stderr:
                print(f"   Error: {result.stderr[:200]}")
    
    except subprocess.TimeoutExpired:
        print(f"❌ TIMEOUT (>2 minutes)")
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")

# Restore original
with open(env_file, 'w') as f:
    f.write(original)

print(f"\n{'='*80}")
print("All approaches failed!")
print("Try running backtest directly to see actual error.")
