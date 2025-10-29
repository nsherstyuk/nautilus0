# Optimization Scripts Directory

This directory contains execution and validation scripts for the optimization phases.

## Overview

The scripts directory provides automated execution and validation tools for the optimization process, reducing manual errors and ensuring consistent execution across different environments.

## Available Scripts

### Phase 3 Execution Scripts

#### run_phase3.sh (Bash)
**Description**: Automated Phase 3 execution for Linux/Mac/WSL  
**Prerequisites**: bash, python, required environment variables  
**Usage**: 
```bash
cd c:/nautilus0
bash optimization/scripts/run_phase3.sh
```

**Features**:
- Environment setup with all required variables
- Pre-flight validation (Python, config files, catalog path, date ranges)
- Automatic archiving of old results with timestamps
- Post-execution validation and result summary
- Error handling and troubleshooting guidance

#### run_phase3.ps1 (PowerShell)
**Description**: Automated Phase 3 execution for Windows  
**Prerequisites**: PowerShell 5.1+, python  
**Usage**: 
```powershell
cd c:/nautilus0
.\optimization\scripts\run_phase3.ps1

# With custom parameters
.\optimization\scripts\run_phase3.ps1 -Workers 12
.\optimization\scripts\run_phase3.ps1 -DryRun
```

**Parameters**:
- `-Workers`: Number of parallel workers (default: 8)
- `-NoArchive`: Skip archiving old results
- `-DryRun`: Validate only, don't execute optimization

**Features**:
- Same features as bash script plus Windows-specific error handling
- Better integration with PowerShell environment
- Structured error reporting and progress tracking

### Phase 4 Execution Scripts

#### run_phase4.ps1 (PowerShell)
**Description**: Automated Phase 4 execution for Windows  
**Purpose**: Optimize risk management parameters (stop loss, take profit, trailing stops) using Phase 3 best MA parameters  
**Prerequisites**: PowerShell 5.1+, Python 3.8+, Phase 3 results available  
**Usage**: 
```powershell
# Standard execution with 8 workers
.\optimization\scripts\run_phase4.ps1

# Use 12 workers for faster execution
.\optimization\scripts\run_phase4.ps1 -Workers 12

# Dry run to validate configuration
.\optimization\scripts\run_phase4.ps1 -DryRun

# Skip archiving old results
.\optimization\scripts\run_phase4.ps1 -NoArchive
```

**Parameters**:
- `-Workers <int>`: Number of parallel workers (default: 8)
- `-NoArchive`: Skip archiving old results
- `-DryRun`: Validate only, don't execute

**Features**:
- Environment variable setup and validation
- Pre-flight checks (Python, config files, data catalog)
- Automatic archiving of old results
- Progress monitoring and ETA calculation
- Post-execution validation
- Comparison with Phase 3 baseline
- Error handling and recovery suggestions

**Expected runtime**: 8-10 hours with 8 workers (500 combinations)

**Output files**:
- `phase4_risk_management_results.csv`
- `phase4_risk_management_results_top_10.json`
- `phase4_risk_management_results_summary.json`

#### run_phase4.sh (Bash)
**Description**: Automated Phase 4 execution for Linux/Mac/WSL  
**Purpose**: Same as PowerShell version  
**Prerequisites**: bash, Python 3.8+, Phase 3 results available  
**Usage**: 
```bash
# Standard execution
bash optimization/scripts/run_phase4.sh

# Make executable and run
chmod +x optimization/scripts/run_phase4.sh
./optimization/scripts/run_phase4.sh
```

**Features**: Same as PowerShell version with Unix-specific error handling

**Exit codes**:
- 0: Success
- 1: Configuration error
- 2: Validation error
- 3: Execution error
- 4: Post-validation error

### Phase 5 Execution Scripts

#### run_phase5.ps1 (PowerShell)
**Description**: Automated Phase 5 execution for Windows  
**Purpose**: Optimize DMI and Stochastic filter parameters using Phase 3 best MA parameters and Phase 4 best risk management parameters  
**Prerequisites**: PowerShell 5.1+, Python 3.8+, Phase 3 and Phase 4 results available  
**Usage**: 
```powershell
# Standard execution with 8 workers (2,400 combinations, ~40 hours)
.\optimization\scripts\run_phase5.ps1

# Use reduced configuration (108 combinations, ~2 hours)
.\optimization\scripts\run_phase5.ps1 -UseReduced

# Use 12 workers for faster execution
.\optimization\scripts\run_phase5.ps1 -Workers 12

# Dry run to validate configuration
.\optimization\scripts\run_phase5.ps1 -DryRun

# Skip archiving old results
.\optimization\scripts\run_phase5.ps1 -NoArchive
```

**Parameters**:
- `-Workers <int>`: Number of parallel workers (default: 8)
- `-UseReduced`: Use reduced parameter ranges (108 combinations vs 2,400)
- `-NoArchive`: Skip archiving old results
- `-DryRun`: Validate only, don't execute

**Features**:
- Environment variable setup and validation
- Pre-flight checks (Python, config files, data catalog, Phase 3 & 4 results)
- Automatic archiving of old results
- Progress monitoring and ETA calculation
- Post-execution validation
- Comparison with Phase 3 and Phase 4 baselines
- Filter impact analysis
- Error handling and recovery suggestions

**Expected runtime**: 40 hours (full) / 2 hours (reduced) with 8 workers

**Output files**:
- `phase5_filters_results.csv` (or `phase5_filters_reduced_results.csv`)
- `phase5_filters_results_top_10.json` (or `phase5_filters_reduced_results_top_10.json`)
- `phase5_filters_results_summary.json` (or `phase5_filters_reduced_results_summary.json`)

#### run_phase5.sh (Bash)
**Description**: Automated Phase 5 execution for Linux/Mac/WSL  
**Purpose**: Same as PowerShell version  
**Prerequisites**: bash, Python 3.8+, Phase 3 and Phase 4 results available  
**Usage**: 
```bash
# Standard execution (2,400 combinations, ~40 hours)
bash optimization/scripts/run_phase5.sh

# Use reduced configuration (108 combinations, ~2 hours)
bash optimization/scripts/run_phase5.sh --use-reduced

# Make executable and run
chmod +x optimization/scripts/run_phase5.sh
./optimization/scripts/run_phase5.sh
```

**Features**: Same as PowerShell version with Unix-specific error handling

**Exit codes**:
- 0: Success
- 1: Configuration error
- 2: Validation error
- 3: Execution error
- 4: Post-validation error

### Validation Scripts

#### validate_phase3_results.py
**Description**: Comprehensive validation of Phase 3 results  
**Usage**: 
```bash
# Basic validation
python optimization/scripts/validate_phase3_results.py

# With custom Phase 2 baseline
python optimization/scripts/validate_phase3_results.py --phase2-sharpe 0.350

# Strict mode (fail on warnings)
python optimization/scripts/validate_phase3_results.py --strict
```

**Validations Performed**:
- **Parameter Ranges**: Verify all parameters within expected ranges (36-44, 230-270, 0.35-0.65)
- **Sharpe Ratio Quality**: Check for non-zero values and reasonable ranges
- **Output Directory Uniqueness**: Verify microsecond precision timestamps and no duplicates
- **Completion Rate**: Analyze success/failure statistics and patterns
- **Phase 2 Comparison**: Compare performance against Phase 2 baseline
- **Parameter Stability**: Analyze clustering of top results and boundary warnings

**Exit Codes**:
- `0`: All validations passed
- `1`: Critical validation failures (wrong parameter ranges, zero Sharpe ratios, duplicates)
- `2`: Warning-level issues (low success rate, no improvement over Phase 2)

#### validate_phase4_results.py
**Description**: Comprehensive validation of Phase 4 risk management optimization results  
**Purpose**: Verify data quality, parameter ranges, and performance improvements before Phase 5  
**Usage**: 
```bash
# Standard validation
python optimization/scripts/validate_phase4_results.py

# Validate with custom Phase 3 baseline
python optimization/scripts/validate_phase4_results.py --phase3-sharpe 0.280

# Strict mode (fail on warnings)
python optimization/scripts/validate_phase4_results.py --strict

# Verbose output with custom paths
python optimization/scripts/validate_phase4_results.py --csv optimization/results/phase4_risk_management_results.csv --json-output validation.json --verbose
```

**Command-line options**:
- `--csv <path>`: Path to Phase 4 results CSV (default: `optimization/results/phase4_risk_management_results.csv`)
- `--phase3-sharpe <float>`: Phase 3 baseline Sharpe ratio (default: 0.272)
- `--strict`: Fail on warnings (exit code 2 becomes 1)
- `--json-output <path>`: Path to save validation report JSON
- `--no-color`: Disable colored console output
- `--verbose`: Enable verbose logging

**Validations performed**:
- **Parameter ranges**: Verify all risk management parameters are within expected ranges (stop_loss: 15-35, take_profit: 30-75, trailing_activation: 10-25, trailing_distance: 10-20)
- **MA parameters fixed**: Confirm all runs use Phase 3 best MA parameters (fast=42, slow=270, threshold=0.35)
- **Sharpe ratio quality**: Check for non-zero values, reasonable ranges, outlier detection
- **Output directory uniqueness**: Verify microsecond-precision timestamps and no collisions
- **Completion rate**: Ensure >= 95% success rate (475+ of 500 completed)
- **Phase 3 comparison**: Calculate improvement percentage, verify Sharpe ratio >= baseline
- **Risk/reward pattern analysis**: Identify optimal RR ratios, analyze trailing stop impact
- **Parameter stability**: Check top 10 results cluster around similar values

**Exit codes**:
- 0: All validations passed
- 1: Critical failures (wrong ranges, <90% success rate, all zero Sharpe ratios)
- 2: Warnings (90-95% success rate, no improvement over Phase 3, high instability)
- 3: File not found or parsing errors

**Output files**:
- `optimization/results/phase4_validation_report.json` (detailed validation results)
- `optimization/results/PHASE4_VALIDATION_SUMMARY.md` (human-readable summary)

#### validate_phase5_results.py
**Description**: Comprehensive validation of Phase 5 filter optimization results  
**Purpose**: Verify data quality, parameter ranges, and performance improvements before Phase 6  
**Usage**: 
```bash
# Standard validation (full configuration)
python optimization/scripts/validate_phase5_results.py

# Validate reduced configuration
python optimization/scripts/validate_phase5_results.py --expected-combinations 108

# Validate with custom Phase 4 baseline
python optimization/scripts/validate_phase5_results.py --phase4-sharpe 0.450

# Strict mode (fail on warnings)
python optimization/scripts/validate_phase5_results.py --strict

# Verbose output with custom paths
python optimization/scripts/validate_phase5_results.py --csv optimization/results/phase5_filters_results.csv --json-output validation.json --verbose
```

**Command-line options**:
- `--csv <path>`: Path to Phase 5 results CSV (default: `optimization/results/phase5_filters_results.csv`)
- `--expected-combinations <int>`: Expected number of combinations (default: 2400, use 108 for reduced)
- `--phase4-sharpe <float>`: Phase 4 baseline Sharpe ratio (default: 0.428)
- `--strict`: Fail on warnings (exit code 2 becomes 1)
- `--json-output <path>`: Path to save validation report JSON
- `--no-color`: Disable colored console output
- `--verbose`: Enable verbose logging

**Validations performed**:
- **Parameter ranges**: Verify all filter parameters are within expected ranges (dmi_period: 10-18, stoch_period_k: 10-18, stoch_period_d: 3-7, stoch_bullish_threshold: 20-35, stoch_bearish_threshold: 65-80)
- **MA and risk parameters fixed**: Confirm all runs use Phase 3 best MA parameters (fast=42, slow=270, threshold=0.35) and Phase 4 best risk parameters (SL=35, TP=50, TA=22, TD=12)
- **Sharpe ratio quality**: Check for non-zero values, reasonable ranges, outlier detection
- **Output directory uniqueness**: Verify microsecond-precision timestamps and no collisions
- **Completion rate**: Ensure >= 95% success rate (2280+ of 2400 completed, or 103+ of 108 for reduced)
- **Phase 4 comparison**: Calculate improvement percentage, verify Sharpe ratio >= baseline
- **Filter impact analysis**: Compare DMI enabled vs disabled, identify optimal filter parameters
- **Parameter stability**: Check top 10 results cluster around similar values
- **Trade quality vs quantity analysis**: Analyze filter impact on trade count and win rate

**Exit codes**:
- 0: All validations passed
- 1: Critical failures (wrong ranges, <90% success rate, all zero Sharpe ratios)
- 2: Warnings (90-95% success rate, no improvement over Phase 4, high instability)
- 3: File not found or parsing errors

**Output files**:
- `optimization/results/phase5_validation_report.json` (detailed validation results)
- `optimization/results/PHASE5_VALIDATION_SUMMARY.md` (human-readable summary)

## Phase 4 Workflow

**Step-by-step workflow for Phase 4 execution:**

1. **Verify Phase 3 completed successfully**
   ```bash
   # Check Phase 3 results exist
   ls optimization/results/phase3_fine_grid_results_top_10.json
   ```

2. **Review Phase 3 best parameters**
   - fast=42, slow=270, threshold=0.35, Sharpe=0.272
   - These will be fixed in Phase 4

3. **Set environment variables**
   ```bash
   # Bash/Linux/Mac
   export BACKTEST_SYMBOL="EUR/USD"
   export BACKTEST_VENUE="IDEALPRO"
   export BACKTEST_START_DATE="2025-01-01"
   export BACKTEST_END_DATE="2025-07-31"
   export BACKTEST_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
   export CATALOG_PATH="data/historical"
   export OUTPUT_DIR="logs/backtest_results"
   ```

4. **Run Phase 4 optimization**
   ```bash
   # Windows
   .\optimization\scripts\run_phase4.ps1
   
   # Linux/Mac
   bash optimization/scripts/run_phase4.sh
   ```

5. **Monitor progress** (8-10 hours runtime)

6. **Validate results**
   ```bash
   python optimization/scripts/validate_phase4_results.py
   ```

7. **Review top 10 results**
   ```bash
   cat optimization/results/phase4_risk_management_results_top_10.json
   ```

8. **Document findings** in `PHASE4_EXECUTION_LOG.md`

9. **Prepare Phase 5** configuration with Phase 4 best risk parameters

## Phase 5 Workflow

**Step-by-step workflow for Phase 5 execution:**

1. **Verify Phase 3 and Phase 4 completed successfully**
   ```bash
   # Check Phase 3 results exist
   ls optimization/results/phase3_fine_grid_results_top_10.json
   
   # Check Phase 4 results exist
   ls optimization/results/phase4_risk_management_results_top_10.json
   ```

2. **Review Phase 3 and Phase 4 best parameters**
   - Phase 3: fast=42, slow=270, threshold=0.35, Sharpe=0.272
   - Phase 4: SL=35, TP=50, TA=22, TD=12, Sharpe=0.428
   - These will be fixed in Phase 5

3. **Choose configuration (Full vs Reduced)**
   ```bash
   # Full configuration (2,400 combinations, ~40 hours)
   .\optimization\scripts\run_phase5.ps1
   
   # Reduced configuration (108 combinations, ~2 hours)
   .\optimization\scripts\run_phase5.ps1 -UseReduced
   ```

4. **Set environment variables**
   ```bash
   # Bash/Linux/Mac
   export BACKTEST_SYMBOL="EUR/USD"
   export BACKTEST_VENUE="IDEALPRO"
   export BACKTEST_START_DATE="2025-01-01"
   export BACKTEST_END_DATE="2025-07-31"
   export BACKTEST_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
   export CATALOG_PATH="data/historical"
   export OUTPUT_DIR="logs/backtest_results"
   ```

5. **Run Phase 5 optimization**
   ```bash
   # Windows (full configuration)
   .\optimization\scripts\run_phase5.ps1
   
   # Windows (reduced configuration)
   .\optimization\scripts\run_phase5.ps1 -UseReduced
   
   # Linux/Mac (full configuration)
   bash optimization/scripts/run_phase5.sh
   
   # Linux/Mac (reduced configuration)
   bash optimization/scripts/run_phase5.sh --use-reduced
   ```

6. **Monitor progress** (40 hours full / 2 hours reduced runtime)

7. **Validate results**
   ```bash
   # Full configuration
   python optimization/scripts/validate_phase5_results.py
   
   # Reduced configuration
   python optimization/scripts/validate_phase5_results.py --expected-combinations 108
   ```

8. **Review top 10 results**
   ```bash
   cat optimization/results/phase5_filters_results_top_10.json
   ```

9. **Document findings** in `PHASE5_EXECUTION_LOG.md`

10. **Prepare Phase 6** configuration with Phase 3 MA + Phase 4 risk + Phase 5 filter parameters

## Manual Execution Instructions

If you prefer to run Phase 3 manually without the scripts:

### Environment Setup

**Bash/Linux/Mac**:
```bash
export BACKTEST_SYMBOL="EUR/USD"
export BACKTEST_VENUE="IDEALPRO"
export BACKTEST_START_DATE="2025-01-01"
export BACKTEST_END_DATE="2025-07-31"
export BACKTEST_BAR_SPEC="15-MINUTE-MID-EXTERNAL"
export CATALOG_PATH="data/historical"
export OUTPUT_DIR="logs/backtest_results"
```

**PowerShell/Windows**:
```powershell
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"
```

### Grid Search Command

```bash
python optimization/grid_search.py \
  --config optimization/configs/phase3_fine_grid.yaml \
  --objective sharpe_ratio \
  --workers 8 \
  --no-resume \
  --verbose
```

### Post-Execution Validation

```bash
python optimization/scripts/validate_phase3_results.py
```

## Troubleshooting

### Common Issues and Solutions

**"Environment variable not set"**
- **Solution**: Check .env file or export commands in your shell
- **Verify**: Run `echo $BACKTEST_SYMBOL` (bash) or `echo $env:BACKTEST_SYMBOL` (PowerShell)

**"Catalog path not found"**
- **Solution**: Verify `data/historical` directory exists
- **Check**: Ensure historical data has been ingested properly

**"All Sharpe ratios are 0.0"**
- **Cause**: Bug fix not applied to run_backtest.py
- **Solution**: Verify microsecond timestamp generation and non-zero Sharpe calculation
- **Check**: Look for "Bug fix verification" in logs

**"Parameters outside expected ranges"**
- **Cause**: Wrong configuration file used
- **Solution**: Verify using `optimization/configs/phase3_fine_grid.yaml`
- **Check**: Config should have fast=[36,38,40,42,44], slow=[230,240,250,260,270]

**"Low success rate"**
- **Cause**: Backtest timeout or data issues
- **Solution**: Check timeout settings in backtest configuration
- **Investigate**: Review individual backtest logs for error patterns

**Phase 4 Specific Issues:**

**"Try statement missing Catch or Finally block" error when running run_phase4.ps1**
- **Symptoms**: PowerShell throws parser error before script execution begins; Error message: "The Try statement is missing its Catch or Finally block"; Error points to line 168 or nearby lines; Script cannot be loaded or executed
- **Cause**: Extra closing brace `}` at line 170 (orphaned, no matching opening brace); This is a syntax error, not a logical error; Likely introduced during script creation or modification
- **Solution**: 
  1. Open `optimization/scripts/run_phase4.ps1` in a text editor
  2. Navigate to line 170
  3. Delete the entire line (should contain only `}`)
  4. Save the file
  5. Verify fix: `powershell -NoProfile -Command "& { . .\optimization\scripts\run_phase4.ps1 -DryRun }"`
- **Alternative automated fix**:
  ```powershell
  $content = Get-Content "optimization/scripts/run_phase4.ps1"
  $newContent = $content[0..168] + $content[170..($content.Length - 1)]
  $newContent | Set-Content "optimization/scripts/run_phase4.ps1"
  ```
- **Prevention**: Use a text editor with brace matching (VS Code, Notepad++); Run syntax checks before committing script changes; Compare with working scripts (e.g., run_phase3.ps1) for structure consistency

**"Phase 3 results not found"**
- **Cause**: Phase 3 not completed or results file missing
- **Solution**: Complete Phase 3 first, verify `optimization/results/phase3_fine_grid_results_top_10.json` exists
- **Check**: Ensure Phase 3 completed successfully with >90% success rate

**"All Sharpe ratios are 0.0"**
- **Cause**: Bug fix not applied to run_backtest.py
- **Solution**: Verify microsecond timestamp generation and non-zero Sharpe calculation
- **Check**: Look for "Bug fix verification" in logs

**"Low success rate (<95%)"**
- **Cause**: Backtest timeout or data issues
- **Solution**: Check backtest timeout settings, verify data catalog integrity
- **Investigate**: Review individual backtest logs for error patterns

**"Parameters outside expected ranges"**
- **Cause**: Wrong config file used
- **Solution**: Verify using `optimization/configs/phase4_risk_management.yaml`
- **Check**: Config should have stop_loss=[15,20,25,30,35], take_profit=[30,40,50,60,75]

**"No improvement over Phase 3"**
- **Cause**: Risk management may not be the bottleneck, baseline parameters already near-optimal
- **Solution**: Review Phase 3 trade analysis, consider filter optimization (Phase 5), analyze individual trade outcomes

**"High parameter instability"**
- **Cause**: Top 10 results scattered across parameter space
- **Solution**: Consider expanding search space, analyze market regime impact

## Phase 4 Autonomous Execution

### Overview

**Purpose**: Execute Phase 4 optimization without user interaction  
**Duration**: 8-10 hours (500 combinations with 8 workers)  
**Output**: Comprehensive execution report with insights and recommendations

### Scripts

#### run_phase4_autonomous.ps1
**Description**: Fully autonomous Phase 4 execution with monitoring and reporting  
**Prerequisites**: Phase 3 completed, Python 3.8+, PowerShell 5.1+  
**Usage**: 
```powershell
# Standard autonomous execution
.\optimization\scripts\run_phase4_autonomous.ps1

# With custom worker count
.\optimization\scripts\run_phase4_autonomous.ps1 -Workers 12

# Skip validation checks (use with caution)
.\optimization\scripts\run_phase4_autonomous.ps1 -SkipValidation

# Continue on errors
.\optimization\scripts\run_phase4_autonomous.ps1 -ContinueOnError
```

**Parameters**:
- `-Workers <int>`: Number of parallel workers (default: 8)
- `-SkipValidation`: Skip pre-flight checks (use with caution)
- `-ContinueOnError`: Continue even if some backtests fail

**Features**:
- No user prompts (fully autonomous)
- Real-time progress monitoring
- Automatic validation script execution
- Automatic report generation
- Comprehensive logging to file
- Enhanced error handling

**Output files**:
- `phase4_risk_management_results.csv` (500 results)
- `phase4_risk_management_results_top_10.json` (best 10)
- `phase4_risk_management_results_summary.json` (statistics)
- `phase4_validation_report.json` (validation results)
- `PHASE4_EXECUTION_REPORT.md` (comprehensive report)
- `optimization/logs/phase4/phase4_execution_[timestamp].log` (execution log)

#### generate_phase4_report.ps1
**Description**: Generate comprehensive PHASE4_EXECUTION_REPORT.md from execution data  
**Called automatically by run_phase4_autonomous.ps1**  
**Can be run manually to regenerate report from existing results**  
**Usage**: 
```powershell
.\optimization\scripts\generate_phase4_report.ps1 -ExecutionData $data
```
**Output**: `optimization/results/PHASE4_EXECUTION_REPORT.md`

#### fix_phase4_encoding.ps1
**Description**: Normalize PowerShell script encoding to UTF-8 (no BOM) with CRLF line endings  
**Purpose**: Fix encoding issues that may cause script execution failures  
**Usage**: 
```powershell
# Fix encoding with backup
.\optimization\scripts\fix_phase4_encoding.ps1 -BackupOriginal

# Verify encoding only (no changes)
.\optimization\scripts\fix_phase4_encoding.ps1 -Verify

# Fix specific file
.\optimization\scripts\fix_phase4_encoding.ps1 -FilePath optimization/scripts/run_phase3.ps1 -BackupOriginal
```

**Features**:
- Detects and removes BOM
- Normalizes line endings to CRLF
- Removes hidden characters (zero-width spaces, control characters)
- Validates PowerShell syntax after fix
- Creates backup before modifying

### Autonomous Execution Workflow

```
Step 1: Fix encoding (if needed)
.\optimization\scripts\fix_phase4_encoding.ps1 -BackupOriginal

Step 2: Run autonomous execution
.\optimization\scripts\run_phase4_autonomous.ps1

Step 3: Monitor progress (optional - script logs automatically)
tail -f optimization/logs/phase4/phase4_execution_[timestamp].log

Step 4: Review report after completion
cat optimization/results/PHASE4_EXECUTION_REPORT.md
```

### Success Criteria

- Success rate >= 90% (450+ of 500 backtests complete)
- Best Sharpe ratio documented and compared to Phase 3 (0.272)
- Comprehensive report generated automatically
- No user intervention required during execution

### Troubleshooting

**Issue**: "Script fails with encoding error"  
**Solution**: Run `fix_phase4_encoding.ps1 -BackupOriginal` first

**Issue**: "Execution stalls (no progress for 30+ minutes)"  
**Solution**: Check checkpoint file for partial results, review logs for errors

**Issue**: "Success rate < 90%"  
**Solution**: Review failed backtests in checkpoint file, check for systematic issues

**Issue**: "Report generation fails"  
**Solution**: Manually run `generate_phase4_report.ps1` with collected data

### Comparison: Manual vs Autonomous Execution

**Manual (run_phase4.ps1)**:
- Requires user confirmation prompt
- No automatic validation
- No automatic report generation
- Basic console output only
- Use for: Interactive execution, testing, debugging

**Autonomous (run_phase4_autonomous.ps1)**:
- No user interaction required
- Automatic validation and reporting
- Comprehensive logging to file
- Real-time progress monitoring
- Use for: Production runs, overnight execution, CI/CD integration

## Phase 5 Autonomous Execution

### Overview

**Purpose**: Execute Phase 5 filter optimization without user interaction  
**Duration**: 40 hours (full) / 2 hours (reduced) with 8 workers  
**Output**: Comprehensive execution report with filter impact analysis and recommendations

### Scripts

#### run_phase5_autonomous.ps1
**Description**: Fully autonomous Phase 5 execution with monitoring and reporting  
**Prerequisites**: Phase 3 and Phase 4 completed, Python 3.8+, PowerShell 5.1+  
**Usage**: 
```powershell
# Standard autonomous execution (full configuration)
.\optimization\scripts\run_phase5_autonomous.ps1

# Reduced configuration (108 combinations, ~2 hours)
.\optimization\scripts\run_phase5_autonomous.ps1 -UseReduced

# With custom worker count
.\optimization\scripts\run_phase5_autonomous.ps1 -Workers 12

# Skip validation checks (use with caution)
.\optimization\scripts\run_phase5_autonomous.ps1 -SkipValidation

# Continue on errors
.\optimization\scripts\run_phase5_autonomous.ps1 -ContinueOnError
```

**Parameters**:
- `-Workers <int>`: Number of parallel workers (default: 8)
- `-UseReduced`: Use reduced parameter ranges (108 combinations vs 2,400)
- `-SkipValidation`: Skip pre-flight checks (use with caution)
- `-ContinueOnError`: Continue even if some backtests fail

**Features**:
- No user prompts (fully autonomous)
- Real-time progress monitoring
- Automatic validation script execution
- Automatic report generation
- Comprehensive logging to file
- Enhanced error handling
- Filter impact analysis

**Output files**:
- `phase5_filters_results.csv` (2,400 results) or `phase5_filters_reduced_results.csv` (108 results)
- `phase5_filters_results_top_10.json` (best 10)
- `phase5_filters_results_summary.json` (statistics)
- `phase5_validation_report.json` (validation results)
- `PHASE5_EXECUTION_REPORT.md` (comprehensive report)
- `optimization/logs/phase5/phase5_execution_[timestamp].log` (execution log)

#### generate_phase5_report.ps1
**Description**: Generate comprehensive PHASE5_EXECUTION_REPORT.md from execution data  
**Called automatically by run_phase5_autonomous.ps1**  
**Can be run manually to regenerate report from existing results**  
**Usage**: 
```powershell
.\optimization\scripts\generate_phase5_report.ps1 -ExecutionData $data
```
**Output**: `optimization/results/PHASE5_EXECUTION_REPORT.md`

### Autonomous Execution Workflow

```
Step 1: Run autonomous execution (full configuration)
.\optimization\scripts\run_phase5_autonomous.ps1

Step 2: Run autonomous execution (reduced configuration)
.\optimization\scripts\run_phase5_autonomous.ps1 -UseReduced

Step 3: Monitor progress (optional - script logs automatically)
tail -f optimization/logs/phase5/phase5_execution_[timestamp].log

Step 4: Review report after completion
cat optimization/results/PHASE5_EXECUTION_REPORT.md
```

### Success Criteria

- Success rate >= 95% (2,280+ of 2,400 backtests complete for full, 103+ of 108 for reduced)
- Best Sharpe ratio documented and compared to Phase 4 (0.428)
- Comprehensive report generated automatically
- No user intervention required during execution
- Filter impact analysis completed

### Troubleshooting

**Issue**: "Script fails with encoding error"  
**Solution**: Run `fix_phase4_encoding.ps1 -BackupOriginal` first

**Issue**: "Execution stalls (no progress for 30+ minutes)"  
**Solution**: Check checkpoint file for partial results, review logs for errors

**Issue**: "Success rate < 95%"  
**Solution**: Review failed backtests in checkpoint file, check for systematic issues

**Issue**: "Report generation fails"  
**Solution**: Manually run `generate_phase5_report.ps1` with collected data

### Comparison: Manual vs Autonomous Execution

**Manual (run_phase5.ps1)**:
- Requires user confirmation prompt
- No automatic validation
- No automatic report generation
- Basic console output only
- Use for: Interactive execution, testing, debugging

**Autonomous (run_phase5_autonomous.ps1)**:
- No user interaction required
- Automatic validation and reporting
- Comprehensive logging to file
- Real-time progress monitoring
- Filter impact analysis
- Use for: Production runs, overnight execution, CI/CD integration

## Expected Outputs

### Files Created by Phase 3

- `optimization/results/phase3_fine_grid_results.csv` (125 rows expected)
- `optimization/results/phase3_fine_grid_results_top_10.json`
- `optimization/results/phase3_fine_grid_results_summary.json`
- `optimization/checkpoints/phase3_fine_grid_checkpoint.csv` (during execution)

### Files Created by Phase 4

- `optimization/results/phase4_risk_management_results.csv` (500 rows expected)
- `optimization/results/phase4_risk_management_results_top_10.json`
- `optimization/results/phase4_risk_management_results_summary.json`
- `optimization/results/phase4_validation_report.json`
- `optimization/results/PHASE4_VALIDATION_SUMMARY.md`
- `optimization/results/PHASE4_EXECUTION_LOG.md`
- `optimization/checkpoints/phase4_risk_management_checkpoint.csv` (during execution)

### Files Created by Phase 5

- `optimization/results/phase5_filters_results.csv` (2,400 rows expected) or `optimization/results/phase5_filters_reduced_results.csv` (108 rows expected)
- `optimization/results/phase5_filters_results_top_10.json` (or `phase5_filters_reduced_results_top_10.json`)
- `optimization/results/phase5_filters_results_summary.json` (or `phase5_filters_reduced_results_summary.json`)
- `optimization/results/phase5_validation_report.json`
- `optimization/results/PHASE5_VALIDATION_SUMMARY.md`
- `optimization/results/PHASE5_EXECUTION_LOG.md`
- `optimization/results/PHASE5_EXECUTION_REPORT.md`
- `optimization/checkpoints/phase5_filters_checkpoint.csv` (or `phase5_filters_reduced_checkpoint.csv`) (during execution)

### Performance Expectations

**Phase 3:**
- **Runtime**: 2-3 hours with 8 workers
- **Expected Best Sharpe Ratio**: > 0.30 (target: > 0.344 from Phase 2)
- **Success Rate**: > 90% of backtests should complete successfully
- **Parameter Stability**: Top 10 results should cluster around similar values

**Phase 4:**
- **Runtime**: 8-10 hours with 8 workers
- **Expected Best Sharpe Ratio**: > 0.272 (Phase 3 baseline), target: 0.28-0.35 range
- **Success Rate**: > 95% of backtests should complete successfully
- **Parameter Stability**: Top 10 results should show clear risk/reward patterns

**Phase 5:**
- **Runtime**: 40 hours (full) / 2 hours (reduced) with 8 workers
- **Expected Best Sharpe Ratio**: > 0.428 (Phase 4 baseline), target: 0.45-0.55 range
- **Success Rate**: > 95% of backtests should complete successfully
- **Parameter Stability**: Top 10 results should show clear filter parameter patterns
- **Filter Impact**: DMI and Stochastic filters should improve trade quality vs quantity

## Next Steps After Phase 3

1. **Review Results**: Examine top 10 results in `phase3_fine_grid_results_top_10.json`
2. **Identify Best Parameters**: Select optimal parameter set for Phase 4 risk management optimization
3. **Update Phase 4 Config**: Use Phase 3 best MA parameters as fixed values in Phase 4
4. **Document Findings**: Update `PHASE3_EXECUTION_LOG.md` with execution details and insights
5. **Prepare Phase 4**: Configure risk management parameter ranges around Phase 3 best MA parameters

## Next Steps After Phase 4

1. **Review Results**: Examine top 10 results in `phase4_risk_management_results_top_10.json`
2. **Identify Best Risk Parameters**: Select optimal risk management parameter set for Phase 5 filter optimization
3. **Update Phase 5 Config**: Use Phase 3 MA + Phase 4 risk parameters as fixed values in Phase 5
4. **Document Findings**: Update `PHASE4_EXECUTION_LOG.md` with execution details and insights
5. **Prepare Phase 5**: Configure filter parameter ranges (DMI, Stochastic) with Phase 3 MA + Phase 4 risk parameters fixed

## Phase 6 Execution Scripts

### run_phase6.ps1 (PowerShell)
**Description**: Automated Phase 6 execution for Windows with multi-objective Pareto analysis  
**Purpose**: Selective refinement of most sensitive parameters from Phases 3-5 using Pareto optimization  
**Prerequisites**: PowerShell 5.1+, Python 3.8+, Phase 5 results available, numpy and scipy packages  
**Usage**: 
```powershell
.\optimization\scripts\run_phase6.ps1

# With custom parameters
.\optimization\scripts\run_phase6.ps1 -Workers 12
.\optimization\scripts\run_phase6.ps1 -DryRun
```

**Parameters**:
- `-Workers`: Number of parallel workers (default: 8)
- `-NoArchive`: Skip archiving old results
- `-DryRun`: Validate only, don't execute optimization

**Features**:
- Multi-objective optimization with --pareto flag
- Automatic sensitivity analysis execution
- Automatic Pareto top 5 selection
- Automatic comprehensive report generation
- Pareto frontier validation
- Expected runtime: 4-6 hours with 8 workers (~200-300 combinations)

**Output files**:
- `phase6_refinement_results.csv`
- `phase6_refinement_results_top_10.json`
- `phase6_refinement_results_summary.json`
- `phase6_refinement_results_pareto_frontier.json` (from --pareto flag)
- `phase6_sensitivity_analysis.json` (from analysis tool)
- `phase6_top_5_parameters.json` (for Phase 7)
- `PHASE6_ANALYSIS_REPORT.md` (comprehensive report)

### run_phase6.sh (Bash)
**Description**: Automated Phase 6 execution for Linux/Mac/WSL  
**Purpose**: Same as PowerShell version for Linux/Mac  
**Prerequisites**: bash, Python 3.8+, Phase 5 results available, numpy and scipy packages  
**Usage**: 
```bash
bash optimization/scripts/run_phase6.sh

# With custom parameters
bash optimization/scripts/run_phase6.sh --workers 12
bash optimization/scripts/run_phase6.sh --dry-run
```

**Parameters**:
- `--workers`: Number of parallel workers (default: 8)
- `--no-archive`: Skip archiving old results
- `--dry-run`: Validate only, don't execute optimization

### run_phase6_autonomous.ps1
**Description**: Fully autonomous Phase 6 execution without user prompts  
**Purpose**: Execute Phase 6 refinement optimization without user interaction  
**Prerequisites**: Phase 5 completed, Python 3.8+, PowerShell 5.1+  
**Usage**: 
```powershell
.\optimization\scripts\run_phase6_autonomous.ps1

# With custom parameters
.\optimization\scripts\run_phase6_autonomous.ps1 -Workers 12
```

**Features**:
- Same as manual version plus autonomous execution and comprehensive logging
- Automatic analysis tools execution
- Progress monitoring and checkpoint tracking
- Comprehensive execution summary generation

### validate_phase6_results.py
**Description**: Comprehensive validation of Phase 6 refinement optimization results including Pareto frontier quality  
**Purpose**: Verify data quality, parameter ranges, Pareto frontier quality, and top 5 parameter set exports  
**Usage**: 
```bash
# Standard validation
python optimization/scripts/validate_phase6_results.py

# Custom paths
python optimization/scripts/validate_phase6_results.py --csv optimization/results/phase6_refinement_results.csv --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json --top5-json optimization/results/phase6_top_5_parameters.json

# Strict mode
python optimization/scripts/validate_phase6_results.py --strict
```

**Validations performed**:
- Parameter ranges (within ±10% of Phase 5 best)
- Fixed parameters (at Phase 5 best values)
- Sharpe ratio quality
- Completion rate (>= 95%)
- Phase 5 comparison
- **Pareto frontier validation** (NEW):
  - Frontier size >= 5
  - Correct objectives
  - Non-dominated verification
  - Diversity metrics
- **Top 5 export validation** (NEW):
  - Exactly 5 parameter sets
  - All required fields present
  - Parameter set diversity
- Parameter stability

**Command-line options**:
- `--csv <path>`: Path to Phase 6 results CSV (default: `optimization/results/phase6_refinement_results.csv`)
- `--phase5-sharpe <float>`: Phase 5 baseline Sharpe ratio (default: 0.4779)
- `--pareto-json <path>`: Path to Pareto frontier JSON
- `--top5-json <path>`: Path to top 5 parameters JSON
- `--strict`: Fail on warnings (exit code 2 becomes 1)
- `--verbose`: Enable verbose logging

**Exit codes**:
- 0: All validations passed
- 1: Critical failures
- 2: Warnings
- 3: File errors

## Phase 6 Analysis Scripts

### run_phase6_analysis.ps1 (PowerShell)
**Description**: Orchestrate execution of all three Phase 6 analysis tools  
**Purpose**: Automate the post-execution analysis workflow for Phase 6, generating 6 output files required for Phase 7 preparation  
**Prerequisites**: Phase 6 grid search must be completed successfully  
**Usage**: 
```powershell
# Standard execution
.\optimization\scripts\run_phase6_analysis.ps1

# With verbose logging
.\optimization\scripts\run_phase6_analysis.ps1 -Verbose

# Continue execution if individual tools fail
.\optimization\scripts\run_phase6_analysis.ps1 -ContinueOnError

# Custom results directory
.\optimization\scripts\run_phase6_analysis.ps1 -ResultsDir custom/results
```

**Parameters**:
- `-ResultsDir <string>`: Results directory (default: `optimization/results`)
- `-Verbose`: Enable verbose logging for analysis tools
- `-ContinueOnError`: Continue execution if individual tools fail

**Features**:
- Validates Phase 6 execution prerequisites (CSV, Pareto JSON, top 10 JSON, summary JSON)
- Executes parameter sensitivity analysis
- Executes Pareto frontier top 5 selection
- Executes comprehensive report generation
- Verifies all 6 output files are created
- Color-coded progress output
- Error handling with troubleshooting guidance
- Execution time tracking

**Output files** (6 total):
- `phase6_sensitivity_analysis.json` (sensitivity analysis data)
- `phase6_sensitivity_summary.md` (sensitivity analysis summary)
- `phase6_correlation_matrix.csv` (correlation matrix)
- `phase6_top_5_parameters.json` (top 5 parameter sets for Phase 7)
- `phase6_pareto_selection_report.md` (Pareto selection rationale)
- `PHASE6_ANALYSIS_REPORT.md` (comprehensive analysis report)

**Expected runtime**: < 5 minutes

**Exit codes**:
- 0: Success
- 1: Prerequisites not met
- 2: Sensitivity analysis failed
- 3: Pareto selection failed
- 4: Comprehensive report failed

### run_phase6_analysis.sh (Bash)
**Description**: Orchestrate execution of all three Phase 6 analysis tools (Linux/Mac)  
**Purpose**: Same as PowerShell version for Linux/Mac systems  
**Prerequisites**: Phase 6 grid search must be completed successfully  
**Usage**: 
```bash
# Standard execution
bash optimization/scripts/run_phase6_analysis.sh

# With verbose logging
bash optimization/scripts/run_phase6_analysis.sh --verbose

# Continue execution if individual tools fail
bash optimization/scripts/run_phase6_analysis.sh --continue-on-error

# Custom results directory
bash optimization/scripts/run_phase6_analysis.sh --results-dir custom/results

# Make executable and run
chmod +x optimization/scripts/run_phase6_analysis.sh
./optimization/scripts/run_phase6_analysis.sh
```

**Parameters**:
- `--results-dir <path>`: Results directory (default: `optimization/results`)
- `--verbose`: Enable verbose logging for analysis tools
- `--continue-on-error`: Continue execution if individual tools fail
- `--help`: Show usage information

**Features**: Same as PowerShell version with Unix-specific error handling

**Exit codes**: Same as PowerShell version

### Phase 6 Analysis Workflow
**Step-by-step workflow for Phase 6 analysis:**

1. **Verify Phase 6 grid search completed successfully**
   ```bash
   # Check Phase 6 results exist
   ls optimization/results/phase6_refinement_results.csv
   ls optimization/results/phase6_refinement_results_pareto_frontier.json
   ls optimization/results/phase6_refinement_results_top_10.json
   ls optimization/results/phase6_refinement_results_summary.json
   ```

2. **Run Phase 6 analysis tools**
   ```bash
   # Windows - Run all analysis tools
   .\optimization\scripts\run_phase6_analysis.ps1
   
   # Linux/Mac - Run all analysis tools
   bash optimization/scripts/run_phase6_analysis.sh
   ```

3. **Verify all 6 analysis output files were created**
   ```bash
   ls optimization/results/phase6_sensitivity_analysis.json
   ls optimization/results/phase6_sensitivity_summary.md
   ls optimization/results/phase6_correlation_matrix.csv
   ls optimization/results/phase6_top_5_parameters.json
   ls optimization/results/phase6_pareto_selection_report.md
   ls optimization/results/PHASE6_ANALYSIS_REPORT.md
   ```

4. **Review comprehensive analysis report**
   ```bash
   cat optimization/results/PHASE6_ANALYSIS_REPORT.md
   ```

5. **Review top 5 parameter sets for Phase 7**
   ```bash
   cat optimization/results/phase6_top_5_parameters.json
   ```

6. **Run validation**
   ```bash
   python optimization/scripts/validate_phase6_results.py --verbose
   ```

7. **Prepare for Phase 7 walk-forward validation**
   - Top 5 parameter sets are ready for Phase 7
   - Review trade-offs between parameter sets
   - Document findings in execution log

### Troubleshooting Phase 6 Analysis
**Common issues and solutions:**

**Issue**: "Analysis script fails with 'Phase 6 results not found' error"
- **Cause**: Phase 6 grid search not completed or results files missing
- **Solution**: Run Phase 6 grid search first using `run_phase6.ps1`, verify CSV and Pareto JSON exist

**Issue**: "Sensitivity analysis shows all parameters with low correlation"
- **Cause**: Parameters may be well-optimized, insufficient variance in Phase 6 results
- **Solution**: Review Phase 6 parameter ranges, check if results are too similar, consider this a success indicator

**Issue**: "Pareto top 5 selection fails with 'frontier too small' error"
- **Cause**: Pareto frontier has fewer than 5 non-dominated solutions
- **Solution**: Review Pareto frontier JSON, if frontier is small (2-4 points), parameters may be well-optimized, proceed with available points

**Issue**: "Comprehensive report generation fails with missing data"
- **Cause**: Sensitivity analysis or Pareto selection outputs missing
- **Solution**: Run individual analysis tools first, verify all prerequisite files exist, use `--continue-on-error` flag

**Issue**: "Top 5 parameter sets are too similar"
- **Cause**: Pareto frontier lacks diversity, parameters may be near-optimal
- **Solution**: Review Pareto frontier diversity, consider this a success indicator (stable optimum found), proceed to Phase 7

## Phase 6 Analysis Tools

### analyze_parameter_sensitivity.py
**Description**: Comprehensive parameter sensitivity analysis across multiple objectives  
**Location**: `optimization/tools/analyze_parameter_sensitivity.py`  
**Usage**: 
```bash
# Standard sensitivity analysis
python optimization/tools/analyze_parameter_sensitivity.py

# Custom objectives and threshold
python optimization/tools/analyze_parameter_sensitivity.py --objectives sharpe_ratio total_pnl profit_factor --threshold 0.15

# Verbose output
python optimization/tools/analyze_parameter_sensitivity.py --verbose
```

**Features**:
- Pearson and Spearman correlation analysis
- Variance decomposition (within-group vs between-group)
- Sensitivity ranking (identify most impactful parameters)
- Parameter stability analysis (CV in top 10)
- Auto-generated insights and recommendations

**Output files**:
- `phase6_sensitivity_analysis.json` (full analysis data)
- `phase6_sensitivity_summary.md` (human-readable summary)
- `phase6_correlation_matrix.csv` (correlation matrix)

### select_pareto_top5.py
**Description**: Select 5 diverse parameter sets from Pareto frontier for Phase 7 walk-forward validation  
**Location**: `optimization/tools/select_pareto_top5.py`  
**Usage**: 
```bash
# Standard top 5 selection
python optimization/tools/select_pareto_top5.py

# Select top 7 instead of 5
python optimization/tools/select_pareto_top5.py --n 7

# Custom paths
python optimization/tools/select_pareto_top5.py --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json --output optimization/results/phase6_top_5_parameters.json
```

**Selection Strategy** (diversity-based):
1. **Best Sharpe**: Point with highest sharpe_ratio (risk-adjusted returns)
2. **Best PnL**: Point with highest total_pnl (absolute returns)
3. **Best Drawdown**: Point with lowest max_drawdown (capital preservation)
4. **Balanced 1**: Point closest to ideal (1,1,1) in normalized objective space
5. **Balanced 2**: Point with maximum diversity (furthest from already selected points)

**Output files**:
- `phase6_top_5_parameters.json` (for Phase 7 walk-forward validation)
- `phase6_pareto_selection_report.md` (selection explanation and trade-offs)

### generate_phase6_analysis_report.py
**Description**: Generate comprehensive PHASE6_ANALYSIS_REPORT.md combining sensitivity analysis, Pareto frontier analysis, and top 5 parameter set recommendations  
**Location**: `optimization/tools/generate_phase6_analysis_report.py`  
**Usage**: 
```bash
# Generate comprehensive analysis report
python optimization/tools/generate_phase6_analysis_report.py

# Custom output path
python optimization/tools/generate_phase6_analysis_report.py --output reports/phase6_analysis.md
```

**Input Files** (all automatically loaded):
- `phase6_refinement_results.csv`
- `phase6_refinement_results_top_10.json`
- `phase6_refinement_results_summary.json`
- `phase6_refinement_results_pareto_frontier.json`
- `phase6_sensitivity_analysis.json`
- `phase6_top_5_parameters.json`

**Output**: `PHASE6_ANALYSIS_REPORT.md`

**Report Sections**:
- Executive summary (key findings at a glance)
- Parameter sensitivity analysis (correlations, variance contributions, rankings)
- Pareto frontier analysis (trade-offs, frontier visualization)
- Top 5 parameter sets (detailed descriptions with trade-offs)
- Recommendations for Phase 7 walk-forward validation
- Appendix (output files, methodology notes)

## Phase 6 Workflow

**Step-by-step workflow for Phase 6 execution:**

1. **Verify Phase 5 completed successfully**
   ```bash
   ls optimization/results/phase5_filters_results_top_10.json
   ```

2. **Review Phase 5 best parameters and sensitivity**
   - Phase 5: Sharpe=0.4779, all parameters from rank 1
   - Key insight: DMI has minimal impact, Stochastic parameters show strong consensus

3. **Set environment variables**
   ```bash
   # PowerShell
   $env:BACKTEST_SYMBOL = "EUR/USD"
   $env:BACKTEST_VENUE = "IDEALPRO"
   $env:BACKTEST_START_DATE = "2025-01-01"
   $env:BACKTEST_END_DATE = "2025-07-31"
   $env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
   $env:CATALOG_PATH = "data/historical"
   $env:OUTPUT_DIR = "logs/backtest_results"
   ```

4. **Run Phase 6 refinement with Pareto analysis**
   ```bash
   # Windows
   .\optimization\scripts\run_phase6.ps1
   
   # Linux/Mac
   bash optimization/scripts/run_phase6.sh
   
   # Autonomous (no prompts)
   .\optimization\scripts\run_phase6_autonomous.ps1
   ```

5. **Monitor execution** (4-6 hours runtime)

6. **Automatic analysis tools execute**:
   - Sensitivity analysis
   - Pareto top 5 selection
   - Comprehensive report generation

7. **Validate results**
   ```bash
   python optimization/scripts/validate_phase6_results.py
   ```

8. **Review comprehensive analysis report**
   ```bash
   cat optimization/results/PHASE6_ANALYSIS_REPORT.md
   ```

9. **Review top 5 parameter sets for Phase 7**
   ```bash
   cat optimization/results/phase6_top_5_parameters.json
   ```

10. **Prepare for Phase 7 walk-forward validation**

## Next Steps After Phase 5

1. **Review Results**: Examine top 10 results in `phase5_filters_results_top_10.json`
2. **Identify Best Filter Parameters**: Select optimal filter parameter set for Phase 6 refinement optimization
3. **Update Phase 6 Config**: Use Phase 3 MA + Phase 4 risk + Phase 5 filter parameters as fixed values in Phase 6
4. **Document Findings**: Update `PHASE5_EXECUTION_LOG.md` with execution details and insights
5. **Prepare Phase 6**: Configure refinement parameter ranges around Phase 5 best filter parameters

## Next Steps After Phase 6

1. **Review Results**: Examine comprehensive analysis in `PHASE6_ANALYSIS_REPORT.md`
2. **Review Top 5 Parameter Sets**: Examine `phase6_top_5_parameters.json` for Phase 7 walk-forward validation
3. **Understand Trade-offs**: Review trade-offs between 5 selected parameter sets
4. **Document Findings**: Update `PHASE6_EXECUTION_LOG.md` with execution details and insights
5. **Prepare Phase 7**: Configure walk-forward validation with 5 diverse parameter sets

## Script Dependencies

- **Python**: Required for all scripts
- **Pandas**: For CSV processing and data analysis
- **PyYAML**: For configuration file parsing
- **PowerShell 5.1+**: For Windows execution script
- **Bash**: For Linux/Mac execution script

## File Structure

```
optimization/scripts/
├── README.md                    # This documentation
├── run_phase3.sh               # Bash execution script
├── run_phase3.ps1              # PowerShell execution script
├── run_phase4.sh               # Bash execution script for Phase 4
├── run_phase4.ps1              # PowerShell execution script for Phase 4
├── run_phase4_autonomous.ps1   # Autonomous Phase 4 execution
├── generate_phase4_report.ps1  # Phase 4 report generation
├── run_phase5.sh               # Bash execution script for Phase 5
├── run_phase5.ps1              # PowerShell execution script for Phase 5
├── run_phase5_autonomous.ps1   # Autonomous Phase 5 execution
├── generate_phase5_report.ps1  # Phase 5 report generation
├── validate_phase3_results.py  # Results validation script
├── validate_phase4_results.py # Results validation script for Phase 4
└── validate_phase5_results.py # Results validation script for Phase 5
```

---

**Purpose**: Centralized documentation for all Phase 3 execution and validation procedures, ensuring consistent and reliable optimization execution.
