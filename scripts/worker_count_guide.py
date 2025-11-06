"""
Guide: Optimizing Worker Count for Grid Search

Your system has 16 CPU cores, so you can use more workers to speed up optimization!

WORKER COUNT RECOMMENDATIONS:
- Safe: CPU cores - 1 = 15 workers (leaves 1 core for system)
- Aggressive: CPU cores = 16 workers (uses all cores)
- Conservative: CPU cores ÷ 2 = 8 workers (if system needs more resources)

SPEEDUP WITH MORE WORKERS:
- 8 workers: ~10-12 hours for 625 combinations
- 15 workers: ~5-6 hours for 625 combinations (2x faster!)
- 16 workers: ~4.5-5.5 hours for 625 combinations

HOW TO SET WORKERS:
1. Via command line (recommended - overrides config):
   python optimization/grid_search.py `
     --config optimization/configs/tp_sl_optimization.yaml `
     --workers 15 `
     --objective sharpe_ratio

2. Via config file (edit YAML):
   optimization:
     workers: 15

3. Check current setting:
   Look at config file or use --workers flag to override

BEST PRACTICES:
- Start with 15 workers (cores - 1)
- Monitor CPU usage: if consistently at 100%, reduce workers
- Monitor memory: each worker runs a backtest, so ensure enough RAM
- For large optimizations (1000+ combinations), use more workers
- For small tests (<100 combinations), 8 workers is fine

EXAMPLE COMMANDS:
# Use 15 workers (recommended for your 16-core system)
python optimization/grid_search.py `
  --config optimization/configs/tp_sl_optimization.yaml `
  --workers 15 `
  --objective sharpe_ratio `
  --output optimization/results/tp_sl_results.csv

# Use all 16 cores (maximum speed)
python optimization/grid_search.py `
  --config optimization/configs/tp_sl_optimization.yaml `
  --workers 16 `
  --objective sharpe_ratio `
  --output optimization/results/tp_sl_results.csv
"""

print(__doc__)

