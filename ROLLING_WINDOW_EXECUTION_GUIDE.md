# ROLLING WINDOW ML TRAINING - EXECUTION GUIDE

## Overview
This guide provides complete instructions for running the rolling window (walk-forward) ML model training analysis.

## What is Rolling Window Analysis?
Rolling window training simulates realistic trading conditions by:
- Training models on historical windows (6 months)
- Testing on out-of-sample periods (1 month)
- Moving forward in time and repeating
- Evaluating model stability across market conditions

## Quick Start

### 1. INITIAL SETUP
```powershell
cd C:\nautilus0
```

### 2. ACTIVATE VIRTUAL ENVIRONMENT
```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. RUN THE ANALYSIS
```powershell
python research/train_model_mtf_rolling.py
```

## Configuration

### Training Parameters
- **Training window**: 6 months
- **Test window**: 1 month
- **Date range**: 2024-01-01 to 2025-11-28
- **Expected windows**: ~17 models
- **Estimated runtime**: 30-45 minutes

### Data Requirements
- **Source**: Parquet data catalog in `data/historical/`
- **Timeframes**: 15-minute and 30-minute bars
- **Format**: NautilusTrader Parquet format

## Expected Output

### File Structure
```
models/rolling/
├── ml_model_mtf_window_01.pkl
├── ml_model_mtf_window_02.pkl
├── ...
├── ml_model_mtf_window_17.pkl
└── rolling_window_results.csv
```

### Results CSV Columns
- `window_id`: Window number (1-17)
- `train_start` / `train_end`: Training period dates
- `test_start` / `test_end`: Test period dates
- `train_samples`: Number of training samples
- `test_samples`: Number of test samples
- `train_accuracy`: Training accuracy
- `test_accuracy`: Test (out-of-sample) accuracy
- `model_path`: Path to saved model file

### Console Output
The script provides real-time progress including:
- Window dates and sample counts
- Training/test accuracy for each window
- Classification reports (precision, recall, F1)
- Summary statistics at completion

## Resource Requirements

### System Resources
- **RAM**: ~4GB recommended
- **CPU**: Medium load (will use all available cores)
- **Disk space**: ~500MB for models and results
- **Network**: Not required (uses local data)

### Time Requirements
- Per window: ~2-3 minutes
- Total: 30-45 minutes for 17 windows
- Varies based on CPU and data size

## Dependencies

### Python Version
- Python 3.8 or higher

### Required Packages
All dependencies are in `requirements.txt`:
- pandas
- numpy
- scikit-learn
- nautilus_trader
- joblib

### Verify Installation
```powershell
python -c "import pandas, numpy, sklearn, nautilus_trader, joblib; print('All dependencies OK')"
```

## Safety Notes

### What This Script DOES:
✅ Creates new models in `models/rolling/`  
✅ Generates results CSV  
✅ Uses existing Parquet data (read-only)  
✅ Logs progress to console and log file  

### What This Script DOES NOT:
❌ Modify existing models in `models/ml_model_mtf.pkl`  
❌ Affect live trading configuration  
❌ Modify source data files  
❌ Connect to any external services  
❌ Execute any trades  

## Troubleshooting

### Issue: "No data found for bar_type"
**Solution**: Ensure Parquet data exists in `data/historical/data/bar/`
```powershell
ls data/historical/data/bar/
```

### Issue: "Module not found"
**Solution**: Activate virtual environment and install dependencies
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Issue: Out of memory
**Solution**: Reduce number of windows or increase system RAM
- Edit script: Change `train_window_months` to 3 months
- Restart and re-run

### Issue: Slow performance
**Solution**: Normal for first run, subsequent runs use cached data
- Expected: 2-3 min per window
- Check CPU usage (should be 70-90%)

## Interpreting Results

### Good Performance Indicators
- Test accuracy > 0.55 (better than random)
- Stable accuracy across windows (low std deviation)
- No severe degradation in recent windows
- Balanced precision/recall in classification reports

### Red Flags
- Test accuracy < 0.50 (worse than random)
- Large gaps between train and test accuracy (overfitting)
- Declining performance in recent windows (model drift)

### Next Steps After Analysis
1. Review `rolling_window_results.csv`
2. Identify best performing windows
3. Compare with current model performance
4. Decide whether to retrain with different parameters
5. Consider using best window's model for production

## Advanced Usage

### Custom Date Range
Edit the script's `main()` function:
```python
start_date = pd.Timestamp("2023-01-01")  # Earlier start
end_date = pd.Timestamp("2025-12-31")    # Later end
```

### Different Window Sizes
Edit configuration variables:
```python
train_window_months = 3  # Shorter training (faster, less data)
test_window_months = 2   # Longer testing (more validation)
```

### Parallel Execution
For faster execution on multi-core systems:
```python
# Add to imports
from joblib import Parallel, delayed

# Modify main loop
results = Parallel(n_jobs=4)(
    delayed(train_single_window)(...) for i in range(num_windows)
)
```

## Log Files

### Training Logs
Location: `logs/training_rolling_YYYYMMDD_HHMMSS.log`

### What's Logged
- Window configurations
- Data loading progress
- Feature calculation steps
- Model training metrics
- Error messages and stack traces

### Checking Logs
```powershell
# View latest log
Get-Content logs/training_rolling_*.log -Tail 50
```

## Completion Checklist

After running, verify:
- [ ] Script completed without errors
- [ ] `models/rolling/` directory exists
- [ ] 17 `.pkl` model files present
- [ ] `rolling_window_results.csv` exists
- [ ] Results CSV has 17 rows (one per window)
- [ ] Console shows summary statistics
- [ ] Log file created in `logs/`

## Questions?

### Common Questions

**Q: How do I know when it's done?**  
A: Script prints "ROLLING WINDOW TRAINING COMPLETE" and exits

**Q: Can I stop it mid-run?**  
A: Yes (Ctrl+C), completed windows are saved, resume not supported

**Q: Should I use these models for live trading?**  
A: Review results first, compare with current model, test in paper trading

**Q: What if one window fails?**  
A: Script continues to next window, check logs for error details

**Q: How do I pick the best model?**  
A: Look for highest test accuracy with stable train/test gap

## Contact

For issues or questions:
1. Check log files in `logs/`
2. Review error messages carefully
3. Verify data availability
4. Ensure all dependencies installed

---

**Ready to run?** Just execute:
```powershell
cd C:\nautilus0
.\.venv\Scripts\Activate.ps1
python research/train_model_mtf_rolling.py
```

**Estimated completion time**: 30-45 minutes  
**Can run in background**: Yes  
**Safe for production systems**: Yes (read-only operations)
