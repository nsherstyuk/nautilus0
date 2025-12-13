import json
import numpy as np

config = json.load(open('eurusd_regime_optimization.json'))
counts = {k: len(v) if isinstance(v, list) else 1 
          for k, v in config.items() 
          if k not in ['description', 'comment']}
total = np.prod(list(counts.values()))

print(f'Total combinations: {total:,}')
print(f'\nParameter counts:')
for k, v in sorted(counts.items()):
    print(f'  {k}: {v}')
    
# Estimate runtime
minutes_per_run = 0.5  # Conservative estimate
total_minutes = total * minutes_per_run
hours = total_minutes / 60
print(f'\nEstimated runtime: ~{hours:.1f} hours ({total_minutes:.0f} minutes)')
