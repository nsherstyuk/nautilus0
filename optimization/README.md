# Optimization Framework

This directory contains the multi-phase optimization framework for the moving average crossover trading strategy.

## Overview

The optimization process is structured as a series of phases, each building upon the previous phase's results to systematically improve strategy performance.

## Optimization Phases

### Phase 1: Baseline
**Status**: ✅ Completed  
**Objective**: Establish baseline performance with default parameters  
**Results**: Baseline Sharpe ratio and performance metrics

### Phase 2: Coarse Grid Search (MA Parameters)
**Status**: ✅ Completed  
**Objective**: Broad exploration of MA parameter space  
**Parameters optimized**: fast_period, slow_period, crossover_threshold_pips  
**Results**: Identified promising parameter ranges for fine-tuning

### Phase 3: Fine Grid Search (MA Parameters)
**Status**: ✅ Completed  
**Objective**: Fine-tune MA parameters within promising ranges  
**Parameters optimized**: fast_period, slow_period, crossover_threshold_pips  
**Best results**: fast=42, slow=270, threshold=0.35, Sharpe=0.272  
**Results**: Optimal MA parameters identified for risk management optimization

### Phase 4: Risk Management Parameter Optimization
**Status**: ✅ Completed  
**Objective**: Optimize stop loss, take profit, and trailing stop parameters  
**Fixed parameters**: Phase 3 best MA parameters (fast=42, slow=270, threshold=0.35)  
**Best results**: SL=35, TP=50, TA=22, TD=12, Sharpe=0.428  
**Results**: Optimal risk management parameters identified for filter optimization

### Phase 5: Filter Parameter Optimization
**Status**: ✅ Completed  
**Objective**: Optimize DMI and Stochastic filter parameters  
**Fixed parameters**: Phase 3 best MA parameters (fast=42, slow=270, threshold=0.35) + Phase 4 best risk parameters (SL=35, TP=50, TA=22, TD=12)  
**Parameters being optimized**:
- `dmi_enabled`: [true, false] (2 values)
- `dmi_period`: [10, 12, 14, 16, 18] (5 values)
- `stoch_period_k`: [10, 12, 14, 16, 18] (5 values)
- `stoch_period_d`: [3, 5, 7] (3 values)
- `stoch_bullish_threshold`: [20, 25, 30, 35] (4 values)
- `stoch_bearish_threshold`: [65, 70, 75, 80] (4 values)
**Total combinations**: 2,400 (2×5×5×3×4×4)  
**Expected runtime**: 40 hours with 8 workers  
**Reduced configuration**: 108 combinations (~2 hours) for faster iteration  
**Success criteria**:
- Improve Sharpe ratio over Phase 4 baseline (0.428)
- Identify optimal filter parameters for trade quality vs quantity
- Analyze DMI and Stochastic filter impact on performance
- Top 10 results show clear filter parameter patterns
**Configuration**: `optimization/configs/phase5_filters.yaml` (full) / `optimization/configs/phase5_filters_reduced.yaml` (reduced)  
**Execution scripts**: `optimization/scripts/run_phase5.ps1` (Windows), `optimization/scripts/run_phase5.sh` (Linux/Mac)  
**Validation**: `optimization/scripts/validate_phase5_results.py`  
**Output files**:
- `optimization/results/phase5_filters_results.csv` (or `phase5_filters_reduced_results.csv`)
- `optimization/results/phase5_filters_results_top_10.json`
- `optimization/results/phase5_filters_results_summary.json`
**Next phase**: Phase 5 Sensitivity Analysis → Phase 6 Parameter Refinement

#### Phase 5 Post-Analysis: Parameter Sensitivity Analysis
**Status**: Ready to execute  
**Objective**: Identify the 4 most sensitive parameters for Phase 6 refinement  
**Method**: Correlation analysis, variance decomposition, and stability assessment  
**Prerequisites**: Phase 5 must be completed successfully  
**Analysis approach**:
- Calculate Pearson and Spearman correlations between all 11 parameters and Sharpe ratio
- Compute variance contributions to identify parameters that explain performance differences
- Analyze parameter stability in top 10 results (coefficient of variation)
- Combine metrics to rank parameters by sensitivity: 0.6 × |correlation| + 0.4 × variance_contribution
- Special analysis for boolean parameter (dmi_enabled) using t-test and effect size
**Execution**:
```bash
# Windows
.\optimization\scripts\run_phase5_sensitivity_analysis.ps1

# Linux/Mac
bash optimization/scripts/run_phase5_sensitivity_analysis.sh

# Direct Python execution
python optimization/tools/analyze_phase5_sensitivity.py --csv optimization/results/phase5_filters_results.csv --output-dir optimization/results --verbose
```
**Output files**:
- `optimization/results/phase5_sensitivity_analysis.json` (complete analysis data)
- `optimization/results/PHASE5_SENSITIVITY_REPORT.md` (human-readable report)
- `optimization/results/phase5_correlation_matrix.csv` (correlation data for spreadsheet analysis)
**Expected findings**: 4 parameters for refinement, 7 parameters to fix at Phase 5 best values  
**Next phase**: Phase 6 configuration update → Phase 6 execution

#### Phase 5.5: Update Phase 6 Configuration
**Status**: Ready to execute  
**Objective**: Update Phase 6 YAML configuration based on Phase 5 sensitivity analysis findings  
**Method**: Automated script reads sensitivity JSON and updates YAML configuration  
**Prerequisites**: Phase 5 sensitivity analysis must be completed  
**Purpose**: Configure Phase 6 to refine only the 4 most sensitive parameters identified by sensitivity analysis  
**Execution**:
```bash
# Windows
.\optimization\scripts\run_phase6_config_update.ps1

# Linux/Mac
bash optimization/scripts/run_phase6_config_update.sh

# Direct Python execution
python optimization/tools/update_phase6_config.py --sensitivity-json optimization/results/phase5_sensitivity_analysis.json --phase6-yaml optimization/configs/phase6_refinement.yaml
```
**Outputs**: Updated `phase6_refinement.yaml` with 4 parameters for refinement, 7 parameters fixed  
**Validation**: Combination count reduced from 5.9M to ~200-300  
**Backup**: Original config backed up automatically before modification  
**Next phase**: Phase 6 execution with updated configuration

### Phase 6: Parameter Refinement and Sensitivity Analysis
**Status**: Ready to execute  
**Objective**: Selective refinement of most sensitive parameters with multi-objective Pareto optimization  
**Prerequisites**: Phase 5 sensitivity analysis must be completed, Phase 6 configuration must be updated based on sensitivity analysis  
**Fixed parameters**: Less sensitive parameters at Phase 5 best values (determined by sensitivity analysis and configured by update script)  
**Parameters being refined**: 4 most sensitive parameters (determined by Phase 5 sensitivity analysis and configured by update script) with ±10% ranges around Phase 5 best  
**Phase 5 best baseline**:
  - Sharpe: 0.4779 (11.6% improvement over Phase 4)
  - Parameters: fast=42, slow=270, threshold=0.35, SL=35, TP=50, TA=22, TD=12, dmi_enabled=true, dmi_period=10, stoch_k=18, stoch_d=3, stoch_bullish=30, stoch_bearish=65
**Refinement strategy**: Selective refinement to avoid combinatorial explosion (not full ±10% grid on all 12 parameters)  
**Total combinations**: ~200-300 (selective refinement of 4 parameters)  
**Expected runtime**: 4-6 hours with 8 workers  
**Multi-objective optimization**:
  - Objectives: sharpe_ratio (maximize), total_pnl (maximize), max_drawdown (minimize)
  - Method: Pareto frontier analysis using --pareto flag
  - Expected frontier size: 10-30 non-dominated solutions
**Success criteria**:
  - Maintain or improve Phase 5 Sharpe ratio (0.4779)
  - Generate robust Pareto frontier with diverse solutions
  - Identify 5 diverse parameter sets for Phase 7
  - Comprehensive sensitivity analysis confirms parameter stability
  - Clear trade-offs between objectives documented
**Configuration**: `optimization/configs/phase6_refinement.yaml` (updated based on Phase 5 sensitivity analysis)  
**Execution scripts**: `optimization/scripts/run_phase6.ps1` (Windows), `optimization/scripts/run_phase6.sh` (Linux/Mac)  
**Analysis tools**:
  - `optimization/tools/analyze_parameter_sensitivity.py` (sensitivity analysis)
  - `optimization/tools/select_pareto_top5.py` (Pareto top 5 selection)
  - `optimization/tools/generate_phase6_analysis_report.py` (comprehensive report)
**Validation**: `optimization/scripts/validate_phase6_results.py`  
**Output files**:
  - `optimization/results/phase6_refinement_results.csv`
  - `optimization/results/phase6_refinement_results_pareto_frontier.json`
  - `optimization/results/phase6_sensitivity_analysis.json`
  - `optimization/results/phase6_top_5_parameters.json` (for Phase 7)
  - `optimization/results/PHASE6_ANALYSIS_REPORT.md`
**Next phase**: Phase 7 will perform walk-forward validation on the 5 selected parameter sets

#### Phase 6 Post-Execution: Analysis and Reporting
**Status**: Ready to execute  
**Objective**: Generate comprehensive analysis reports and prepare top 5 parameter sets for Phase 7  
**Prerequisites**: Phase 6 grid search must be completed successfully  
**Method**: Automated wrapper scripts orchestrate execution of three analysis tools  
**Execution**:
```bash
# Windows - Run all analysis tools
.\optimization\scripts\run_phase6_analysis.ps1

# Linux/Mac - Run all analysis tools
bash optimization/scripts/run_phase6_analysis.sh

# Or run individual tools (if needed)
python optimization/tools/analyze_parameter_sensitivity.py --csv optimization/results/phase6_refinement_results.csv
python optimization/tools/select_pareto_top5.py --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json
python optimization/tools/generate_phase6_analysis_report.py --results-dir optimization/results
```
**Outputs**: 6 files (sensitivity JSON/MD/CSV, top 5 JSON, Pareto selection report MD, comprehensive report MD)  
**Expected runtime**: < 5 minutes

### Phase 7: Walk-Forward Analysis (Planned)
**Status**: Planned  
**Objective**: Validate strategy robustness across different market conditions  
**Method**: Rolling window optimization and out-of-sample testing

## Phase Progression

```
Phase 1: Baseline → Phase 2: Coarse Grid (MA) → Phase 3: Fine Grid (MA) → 
Phase 4: Risk Management → Phase 5: Filters → Phase 5 Sensitivity Analysis → Phase 6 Config Update → Phase 6: Refinement → Phase 7: Walk-Forward
```

**Parameter Flow:**
- Phase 2 → Phase 3: Best MA parameters (fast, slow, threshold)
- Phase 3 → Phase 4: Best MA parameters (fixed) + optimize risk management
- Phase 4 → Phase 5: Best MA + risk parameters (fixed) + optimize filters
- Phase 5 → Phase 5 Sensitivity Analysis: Identify 4 most sensitive parameters
- Phase 5 Sensitivity Analysis → Phase 6 Config Update: Update Phase 6 YAML with 4 parameters for refinement + 7 fixed
- Phase 6 Config Update → Phase 6: Execute selective refinement with updated configuration
- Phase 6 → Phase 7: Top 5 diverse parameter sets for walk-forward validation

## Phase 6 Quick Start

```bash
# Prerequisites: Phase 5 and Phase 5 sensitivity analysis must be completed
# Verify Phase 5 results exist
ls optimization/results/phase5_filters_results_top_10.json

# Run Phase 5 sensitivity analysis first (Windows)
.\optimization\scripts\run_phase5_sensitivity_analysis.ps1

# Or run Phase 5 sensitivity analysis (Linux/Mac)
bash optimization/scripts/run_phase5_sensitivity_analysis.sh

# Verify sensitivity analysis results exist
ls optimization/results/phase5_sensitivity_analysis.json

# Review sensitivity analysis report
cat optimization/results/PHASE5_SENSITIVITY_REPORT.md

# Update Phase 6 configuration based on sensitivity analysis findings (Windows)
.\optimization\scripts\run_phase6_config_update.ps1

# Or update Phase 6 configuration (Linux/Mac)
bash optimization/scripts/run_phase6_config_update.sh

# Or direct Python execution
python optimization/tools/update_phase6_config.py --sensitivity-json optimization/results/phase5_sensitivity_analysis.json --phase6-yaml optimization/configs/phase6_refinement.yaml

# Verify Phase 6 YAML has been updated (check file modification timestamp or review parameters section)
Get-Content optimization/configs/phase6_refinement.yaml | Select-String "parameters:" -A 20

# Set environment variables (PowerShell)
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

# Run Phase 6 refinement with Pareto analysis (Windows)
.\optimization\scripts\run_phase6.ps1

# Or run on Linux/Mac
bash optimization/scripts/run_phase6.sh

# Or run autonomous (no prompts)
.\optimization\scripts\run_phase6_autonomous.ps1

# Run Phase 6 analysis tools
.\optimization\scripts\run_phase6_analysis.ps1

# Or run Phase 6 analysis tools (Linux/Mac)
bash optimization/scripts/run_phase6_analysis.sh

# Or run individual tools (if needed)
python optimization/tools/analyze_parameter_sensitivity.py --csv optimization/results/phase6_refinement_results.csv
python optimization/tools/select_pareto_top5.py --pareto-json optimization/results/phase6_refinement_results_pareto_frontier.json
python optimization/tools/generate_phase6_analysis_report.py --results-dir optimization/results

# Verify all 6 analysis output files were created
ls optimization/results/phase6_sensitivity_analysis.json
ls optimization/results/phase6_sensitivity_summary.md
ls optimization/results/phase6_correlation_matrix.csv
ls optimization/results/phase6_top_5_parameters.json
ls optimization/results/phase6_pareto_selection_report.md
ls optimization/results/PHASE6_ANALYSIS_REPORT.md

# Review comprehensive analysis report
cat optimization/results/PHASE6_ANALYSIS_REPORT.md

# Review top 5 parameter sets for Phase 7
cat optimization/results/phase6_top_5_parameters.json
```

## Phase 5 Quick Start

```bash
# Prerequisites: Phase 3 and Phase 4 must be completed
# Verify Phase 3 results exist
ls optimization/results/phase3_fine_grid_results_top_10.json

# Verify Phase 4 results exist
ls optimization/results/phase4_risk_management_results_top_10.json

# Set environment variables (PowerShell)
$env:BACKTEST_SYMBOL = "EUR/USD"
$env:BACKTEST_VENUE = "IDEALPRO"
$env:BACKTEST_START_DATE = "2025-01-01"
$env:BACKTEST_END_DATE = "2025-07-31"
$env:BACKTEST_BAR_SPEC = "15-MINUTE-MID-EXTERNAL"
$env:CATALOG_PATH = "data/historical"
$env:OUTPUT_DIR = "logs/backtest_results"

# Run Phase 5 optimization (full configuration, ~40 hours)
.\optimization\scripts\run_phase5.ps1

# Or run Phase 5 optimization (reduced configuration, ~2 hours)
.\optimization\scripts\run_phase5.ps1 -UseReduced

# Or run Phase 5 optimization (Linux/Mac, full configuration)
bash optimization/scripts/run_phase5.sh

# Or run Phase 5 optimization (Linux/Mac, reduced configuration)
bash optimization/scripts/run_phase5.sh --use-reduced

# Validate results after completion
python optimization/scripts/validate_phase5_results.py

# Review top 10 results
cat optimization/results/phase5_filters_results_top_10.json
```

## Results Summary

### Phase 3 Results
- **Best Sharpe ratio**: 0.272
- **Best MA parameters**: fast=42, slow=270, threshold=0.35
- **Win rate**: 48.3%
- **Trade count**: 60
- **Total PnL**: $5,644.69
- **Source**: `optimization/results/phase3_fine_grid_results_top_10.json`

### Phase 4 Results
- **Best Sharpe ratio**: 0.428
- **Best risk management parameters**:
  - Stop loss: 35 pips
  - Take profit: 50 pips
  - Trailing activation: 22 pips
  - Trailing distance: 12 pips
  - Risk/reward ratio: 1.43:1
- **Performance metrics**:
  - Win rate: [TO BE FILLED]%
  - Trade count: [TO BE FILLED]
  - Total PnL: $[TO BE FILLED]
  - Max drawdown: $[TO BE FILLED]
  - Profit factor: [TO BE FILLED]
- **Improvement over Phase 3**:
  - Sharpe ratio: 57.4% improvement (0.272 → 0.428)
  - PnL: [TO BE CALCULATED]% improvement
- **Key insights**: Risk management optimization significantly improved Sharpe ratio
- **Source**: `optimization/results/phase4_risk_management_results_top_10.json`

### Phase 5 Results
- **Best Sharpe ratio**: 0.4779
- **Best filter parameters**:
  - DMI enabled: true
  - DMI period: 10
  - Stochastic K: 18
  - Stochastic D: 3
  - Bullish threshold: 30
  - Bearish threshold: 65
- **Performance metrics**:
  - Win rate: [TO BE FILLED]%
  - Trade count: [TO BE FILLED]
  - Total PnL: $[TO BE FILLED]
  - Max drawdown: $[TO BE FILLED]
  - Profit factor: [TO BE FILLED]
- **Improvement over Phase 4**:
  - Sharpe ratio: 11.6% improvement (0.428 → 0.4779)
  - PnL: [TO BE CALCULATED]% improvement
- **Filter impact analysis**:
  - DMI filter impact: Minimal (ranks 1-6 have identical Sharpe with dmi_enabled varying)
  - Stochastic filter impact: Significant (all top 10 use stoch_k=18, stoch_d=3, stoch_bearish=65)
  - Trade quality vs quantity: [TO BE FILLED]
- **Key insights**: DMI filter has negligible impact, Stochastic parameters show strong consensus
- **Source**: `optimization/results/phase5_filters_results_top_10.json`

### Phase 6 Results
- **Best Sharpe ratio**: [TO BE FILLED]
- **Pareto frontier size**: [TO BE FILLED] non-dominated solutions
- **Most sensitive parameters**: [TO BE FILLED from sensitivity analysis]
- **Top 5 parameter sets selected**:
  1. Best Sharpe: [parameters]
  2. Best PnL: [parameters]
  3. Best Drawdown: [parameters]
  4. Balanced 1: [parameters]
  5. Balanced 2: [parameters]
- **Parameter stability**: [TO BE FILLED]
- **Key insights**: [TO BE FILLED]
- **Source**: `optimization/results/PHASE6_ANALYSIS_REPORT.md`

## Configuration Files

- `optimization/configs/phase2_coarse_grid.yaml`: Coarse MA parameter optimization (125 combinations)
- `optimization/configs/phase3_fine_grid.yaml`: Fine MA parameter optimization (125 combinations)
- `optimization/configs/phase4_risk_management.yaml`: Risk management parameter optimization (500 combinations)
- `optimization/configs/phase5_filters.yaml`: Filter parameter optimization (2,400 combinations)
- `optimization/configs/phase5_filters_reduced.yaml`: Filter parameter optimization (108 combinations, reduced)
- `optimization/configs/phase6_refinement.yaml`: Parameter refinement with Pareto analysis (~200-300 combinations, automatically configured based on Phase 5 sensitivity analysis)

## File Structure

```
optimization/
├── configs/
│   ├── phase2_coarse_grid.yaml
│   ├── phase3_fine_grid.yaml
│   ├── phase4_risk_management.yaml
│   ├── phase5_filters.yaml
│   ├── phase5_filters_reduced.yaml
│   ├── phase6_refinement.yaml              # NEW
│   └── phase6_refinement.yaml.backup.*     # NEW - backup created before update
├── results/
│   ├── phase2_coarse_grid_top_10.json
│   ├── phase3_fine_grid_results_top_10.json
│   ├── phase4_risk_management_results.csv
│   ├── phase4_risk_management_results_top_10.json
│   ├── phase4_risk_management_results_summary.json
│   ├── phase4_validation_report.json
│   ├── PHASE4_EXECUTION_LOG.md
│   ├── phase5_filters_results.csv
│   ├── phase5_filters_results_top_10.json
│   ├── phase5_filters_results_summary.json
│   ├── phase5_validation_report.json
│   ├── PHASE5_EXECUTION_LOG.md
│   ├── PHASE5_EXECUTION_REPORT.md
│   ├── phase5_sensitivity_analysis.json     # NEW
│   ├── PHASE5_SENSITIVITY_REPORT.md         # NEW
│   ├── phase5_correlation_matrix.csv        # NEW
│   ├── phase6_refinement_results.csv       # NEW
│   ├── phase6_refinement_results_pareto_frontier.json  # NEW
│   ├── phase6_sensitivity_analysis.json    # NEW
│   ├── phase6_top_5_parameters.json         # NEW (for Phase 7)
│   ├── PHASE6_ANALYSIS_REPORT.md           # NEW
│   └── PHASE6_EXECUTION_LOG.md              # NEW
├── scripts/
│   ├── run_phase3.ps1
│   ├── run_phase4.ps1
│   ├── run_phase4.sh
│   ├── run_phase4_autonomous.ps1
│   ├── generate_phase4_report.ps1
│   ├── run_phase5.ps1
│   ├── run_phase5.sh
│   ├── run_phase5_autonomous.ps1
│   ├── generate_phase5_report.ps1
│   ├── run_phase5_sensitivity_analysis.ps1  # NEW
│   ├── run_phase5_sensitivity_analysis.sh   # NEW
│   ├── run_phase6_config_update.ps1         # NEW - Windows wrapper for config update
│   ├── run_phase6_config_update.sh         # NEW - Linux/Mac wrapper for config update
│   ├── run_phase6.ps1                       # NEW
│   ├── run_phase6.sh                        # NEW
│   ├── run_phase6_autonomous.ps1            # NEW
│   ├── run_phase6_analysis.ps1              # NEW - Windows wrapper for Phase 6 analysis tools
│   ├── run_phase6_analysis.sh               # NEW - Linux/Mac wrapper for Phase 6 analysis tools
│   ├── validate_phase3_results.py
│   ├── validate_phase4_results.py
│   ├── validate_phase5_results.py
│   └── validate_phase6_results.py           # NEW
├── tools/
│   ├── analyze_phase5_sensitivity.py       # NEW
│   ├── analyze_parameter_sensitivity.py     # NEW
│   ├── select_pareto_top5.py                # NEW
│   ├── update_phase6_config.py              # NEW - updates Phase 6 YAML based on sensitivity analysis
│   └── generate_phase6_analysis_report.py   # NEW
├── checkpoints/
│   ├── phase3_fine_grid_checkpoint.csv
│   ├── phase4_risk_management_checkpoint.csv
│   ├── phase5_filters_checkpoint.csv
│   └── phase6_refinement_checkpoint.csv    # NEW (during execution)
├── grid_search.py                           # Main optimization engine
└── README.md                                # This file
```

## Best Practices

### General Best Practices
- Always validate results before proceeding to the next phase
- Archive old results before starting new optimization phases
- Monitor execution progress and check for errors
- Document findings and insights in execution logs
- Use version control for configuration files

### Phase 4 Specific Best Practices
- Always verify Phase 3 completed successfully before starting Phase 4
- Use Phase 3 rank 1 parameters (fast=42, slow=270, threshold=0.35) as fixed values
- Test a wide range of risk/reward ratios (1.0:1 to 3.0:1) to find optimal balance
- Monitor profit factor and max drawdown in addition to Sharpe ratio
- Analyze trailing stop impact separately from static stop/target optimization
- Consider trade-offs: tighter stops increase trade count but may reduce profit per trade
- Document risk management insights for future strategy development
- Archive Phase 4 results before proceeding to Phase 5

### Phase 5 Specific Best Practices
- Always verify Phase 3 and Phase 4 completed successfully before starting Phase 5
- Use Phase 3 MA parameters (fast=42, slow=270, threshold=0.35) + Phase 4 risk parameters (SL=35, TP=50, TA=22, TD=12) as fixed values
- Consider using reduced configuration (108 combinations) for initial testing before full run
- Monitor filter impact on trade count vs win rate (quality vs quantity trade-off)
- Analyze DMI enabled vs disabled performance separately
- Test wide range of Stochastic parameters to find optimal sensitivity
- Document filter impact insights for future strategy development
- Archive Phase 5 results before proceeding to Phase 6

### Phase 5 Sensitivity Analysis Best Practices
- Always run sensitivity analysis immediately after Phase 5 completes
- Review correlation matrix to understand parameter impacts
- Verify top 4 parameters make intuitive sense for the strategy
- Check that selected parameters have sufficient variance in Phase 5 results
- Document rationale for parameter selection in execution log
- Archive sensitivity analysis results before proceeding to Phase 6

### Phase 6 Configuration Update Best Practices
- Always run sensitivity analysis before updating Phase 6 config
- Review sensitivity analysis report to understand which parameters were selected
- Backup is created automatically, but consider manual backup for safety
- Verify combination count is in target range (200-300) after update
- Review updated YAML to ensure parameter ranges make sense
- If top 4 parameters seem incorrect, review sensitivity analysis methodology
- Can manually edit YAML after automated update if needed (but document rationale)
- Re-run config update if sensitivity analysis is re-executed with different results

### Phase 6 Specific Best Practices
- Use selective refinement (not full ±10% grid) to avoid combinatorial explosion
- Always use --pareto flag for multi-objective analysis
- Review sensitivity analysis to identify which parameters need refinement
- Ensure Pareto frontier has sufficient diversity (>= 10 points)
- Select 5 diverse parameter sets from Pareto frontier for robust walk-forward validation
- Document trade-offs between objectives (Sharpe vs PnL vs drawdown)
- Archive Phase 6 results before proceeding to Phase 7

### Phase 6 Analysis Best Practices
- Always run analysis tools immediately after Phase 6 grid search completes
- Review sensitivity analysis to understand parameter impacts on multiple objectives
- Verify Pareto frontier has sufficient diversity (≥5 non-dominated solutions)
- Review top 5 parameter sets to ensure they represent diverse trade-offs
- Read comprehensive report before proceeding to validation
- Archive all analysis outputs before proceeding to Phase 7
- If any analysis tool fails, review error messages and check input files
- Can run individual tools separately if wrapper script fails

## Troubleshooting

### Common Issues

**Issue**: "Phase 4 shows no improvement over Phase 3"
- **Possible causes**: Risk management may not be the bottleneck, baseline parameters already near-optimal
- **Solutions**: Review Phase 3 trade analysis, consider filter optimization (Phase 5), analyze individual trade outcomes

**Issue**: "High variance in Phase 4 results"
- **Possible causes**: Risk management parameters interact with market conditions
- **Solutions**: Analyze results by market regime (trending vs ranging), consider adaptive risk management

**Issue**: "Best parameters at range boundaries"
- **Possible causes**: Search space too narrow, optimal values outside tested range
- **Solutions**: Expand parameter ranges, re-run Phase 4 with wider ranges

**Issue**: "Phase 5 shows no improvement over Phase 4"
- **Possible causes**: Filters may not be beneficial for this strategy, baseline parameters already near-optimal
- **Solutions**: Review Phase 4 trade analysis, consider different filter types, analyze market regime impact

**Issue**: "High variance in Phase 5 results"
- **Possible causes**: Filter parameters interact with market conditions, DMI vs Stochastic conflicts
- **Solutions**: Analyze results by market regime, consider adaptive filters, test filters independently

**Issue**: "Best parameters at range boundaries"
- **Possible causes**: Search space too narrow, optimal values outside tested range
- **Solutions**: Expand parameter ranges, re-run Phase 5 with wider ranges

**Issue**: "Pareto frontier too small (< 5 points)"
- **Possible causes**: Parameters may be well-optimized, insufficient diversity in search space
- **Solutions**: Expand parameter ranges, increase combination count, check for parameter interactions

**Issue**: "All Pareto points have similar parameters"
- **Possible causes**: Parameters may be well-optimized, search space too narrow
- **Solutions**: Parameters may be near-optimal, proceed to Phase 7 with available diversity

**Issue**: "No improvement over Phase 5"
- **Possible causes**: Phase 5 parameters may be near-optimal, refinement space too narrow
- **Solutions**: Phase 5 parameters may be well-optimized, use Phase 5 best for Phase 7

**Issue**: "High parameter sensitivity (unstable)"
- **Possible causes**: Parameters interact strongly with market conditions
- **Solutions**: Consider wider ranges in walk-forward validation, test robustness

**Issue**: "All parameters show low sensitivity (< 0.1 correlation)"
- **Possible causes**: Phase 5 parameters may be well-optimized, insufficient variance in results
- **Solutions**: Review Phase 5 parameter ranges, consider expanding search space, check data quality

**Issue**: "Top 4 parameters are all from same category (e.g., all MA parameters)"
- **Possible causes**: Parameter categories may be highly correlated, insufficient diversity in analysis
- **Solutions**: Review parameter interactions, consider manual selection for diversity, expand analysis methodology

**Issue**: "Boolean parameter (dmi_enabled) shows high sensitivity"
- **Possible causes**: DMI filter has significant impact on performance, contradicting Phase 5 observations
- **Solutions**: Review Phase 5 results for DMI impact, consider separate analysis for boolean parameters

**Issue**: "Config update script fails with 'sensitivity analysis not run' error"
- **Possible causes**: JSON file contains placeholder values, sensitivity analysis not executed
- **Solutions**: Run `run_phase5_sensitivity_analysis.ps1` first, verify JSON contains real data

**Issue**: "Updated config has unexpected parameters selected"
- **Possible causes**: Sensitivity analysis identified different parameters than expected
- **Solutions**: Review PHASE5_SENSITIVITY_REPORT.md to understand selection rationale, verify Phase 5 results are correct

**Issue**: "Combination count after update is too high (>600) or too low (<150)"
- **Possible causes**: Parameter ranges may be too wide or too narrow
- **Solutions**: Manually adjust ranges in YAML, ensure ±10% calculation is correct for each parameter type

**Issue**: "grid_search.py fails to load updated YAML"
- **Possible causes**: YAML syntax error or invalid parameter types
- **Solutions**: Validate YAML syntax, check that integers are not floats, verify boolean values are true/false not strings

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

## Next Steps

After Phase 6 analysis completes:
1. Review phase6_sensitivity_summary.md for quick parameter insights
2. Review phase6_pareto_selection_report.md for top 5 selection rationale
3. Review PHASE6_ANALYSIS_REPORT.md for comprehensive analysis
4. Review phase6_top_5_parameters.json for walk-forward validation
5. Understand trade-offs between 5 selected parameter sets
6. Prepare for Phase 7 walk-forward validation (12-month rolling window)
7. Expected Phase 7 approach: Test all 5 parameter sets across different market conditions
8. Expected Phase 7 runtime: varies by walk-forward configuration

---

**Purpose**: Comprehensive documentation for the multi-phase optimization framework, providing clear guidance for each phase and ensuring systematic improvement of the trading strategy.
