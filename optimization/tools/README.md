# Optimization Tools

This directory contains utility scripts for analyzing and ranking grid search optimization results.

## Tools

### Phase 6 Analysis Tools

#### `analyze_parameter_sensitivity.py`
**Description**: Comprehensive parameter sensitivity analysis across multiple objectives  
**Purpose**: Identify which parameters have the strongest impact on performance metrics and assess parameter stability  
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
- Pearson and Spearman correlation analysis for all parameters vs all objectives
- Variance decomposition (within-group vs between-group variance)
- Sensitivity ranking (identify top 5 most impactful parameters)
- Parameter stability analysis (coefficient of variation in top 10 results)
- Auto-generated insights and recommendations

**Input**: `phase6_refinement_results.csv`

**Output**:
- `phase6_sensitivity_analysis.json` (full analysis data)
- `phase6_sensitivity_summary.md` (human-readable summary)
- `phase6_correlation_matrix.csv` (correlation matrix for spreadsheet viewing)

**Analysis Methods**:
- **Correlation Analysis**: Measures linear (Pearson) and monotonic (Spearman) relationships between parameters and objectives
- **Variance Contribution**: Quantifies how much each parameter explains variance in objectives
- **Stability Analysis**: Assesses parameter consistency across top-performing results

#### `select_pareto_top5.py`
**Description**: Select 5 diverse parameter sets from Pareto frontier for Phase 7 walk-forward validation  
**Purpose**: Choose representative parameter sets that balance different objectives for robust out-of-sample testing  
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

**Input**: `phase6_refinement_results_pareto_frontier.json`

**Output**:
- `phase6_top_5_parameters.json` (for Phase 7 walk-forward validation)
- `phase6_pareto_selection_report.md` (selection explanation and trade-offs)

**Trade-off Analysis**: Each selected parameter set includes:
- Performance metrics on all objectives
- Strengths (top 25% on objective)
- Weaknesses (bottom 25% on objective)
- Recommended use case

#### `generate_phase6_analysis_report.py`
**Description**: Generate comprehensive PHASE6_ANALYSIS_REPORT.md combining sensitivity analysis, Pareto frontier analysis, and top 5 parameter set recommendations  
**Purpose**: Provide single comprehensive document with all Phase 6 findings for decision-making and Phase 7 preparation  
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

### Phase 6 Workflow Diagram
```
Phase 5 Results → Phase 6 Config (selective refinement) → 
Grid Search (--pareto flag) → 
Pareto Frontier JSON → 
Sensitivity Analysis → 
Top 5 Selection → 
Comprehensive Report → 
Phase 7 Walk-Forward Validation
```

### Phase 6 Best Practices
- Always use --pareto flag for multi-objective analysis
- Review sensitivity analysis before selecting parameters to refine
- Ensure Pareto frontier has sufficient diversity (>= 10 points)
- Select diverse parameter sets (not just best Sharpe) for robust walk-forward testing
- Document trade-offs between objectives clearly

### Phase 6 Troubleshooting
- **Small Pareto frontier**: Expand parameter ranges, increase combination count
- **No improvement over Phase 5**: Parameters may be well-optimized, proceed to Phase 7
- **High sensitivity**: Test robustness in Phase 7

### 1. `emit_phase3_summary.py`
Prints a summary of Phase 3 fine grid optimization configuration.

**Usage:**
```bash
python optimization/tools/emit_phase3_summary.py
```

**Output:**
- Phase 2 best results (reference values)
- Fine-grid parameter ranges
- Configuration summary (total combinations, parameters, etc.)

### 2. `rank_by_pnl.py`
Ranks grid search results by total PnL instead of Sharpe ratio (workaround for missing Sharpe data).

**Usage:**
```bash
# Rank and create new file
python optimization/tools/rank_by_pnl.py --input optimization/results/phase2_coarse_grid.csv --output optimization/results/phase2_coarse_grid_ranked_by_pnl.csv

# Just show summary without creating file
python optimization/tools/rank_by_pnl.py --input optimization/results/phase2_coarse_grid.csv --summary-only
```

**Features:**
- Ranks results by total PnL (descending)
- Preserves all original columns
- Adds a new `pnl_rank` column
- Provides summary statistics
- Shows top 10 results with key metrics
- **Note**: Only generates CSV output, not JSON files required by optimization pipeline

### 3. `regenerate_phase2_json.py`
Regenerates Phase 2 JSON artifacts (top_10.json and summary.json) from corrected CSV data.

**Usage:**
```bash
# Regenerate JSON files from corrected CSV
python optimization/tools/regenerate_phase2_json.py --input optimization/results/phase2_coarse_grid.csv --objective sharpe_ratio

# Verify existing JSON files match CSV data
python optimization/tools/regenerate_phase2_json.py --verify-only

# Rank by PnL instead of Sharpe ratio
python optimization/tools/regenerate_phase2_json.py --objective total_pnl

# Use fallback ranked-by-PnL CSV when Sharpe ratios are all zero
python optimization/tools/regenerate_phase2_json.py --input optimization/results/phase2_coarse_grid.csv \
  --fallback-input optimization/results/phase2_coarse_grid_ranked_by_pnl.csv
```

**Features:**
- Reads corrected CSV with valid Sharpe ratios
- Generates `phase2_coarse_grid_top_10.json` and `phase2_coarse_grid_summary.json`
- Supports ranking by Sharpe ratio or PnL
- Verification mode to check existing JSON files
- Comprehensive summary statistics and parameter sensitivity analysis

### 4. `update_pnl_ranked_csv.py`
Regenerates PnL-ranked CSV with correct Sharpe ratios from the original corrected data.

**Usage:**
```bash
# Regenerate PnL-ranked CSV with correct Sharpe ratios
python optimization/tools/update_pnl_ranked_csv.py

# Compare before overwriting
python optimization/tools/update_pnl_ranked_csv.py --compare
```

**Features:**
- Updates `phase2_coarse_grid_ranked_by_pnl.csv` with correct Sharpe ratios
- Comparison mode to show before/after differences
- Preserves PnL-based ranking while fixing Sharpe ratio data
- Shows top 5 results with corrected metrics

**Example Output:**
```
============================================================
PNL-BASED RANKING SUMMARY
============================================================
Total Results: 120
Positive PnL: 41 (34.2%)
Negative PnL: 75 (62.5%)
Zero PnL: 4 (3.3%)

Best PnL: $6,279.84
Worst PnL: $-6,765.70
Average PnL: $-775.51

TOP 10 RESULTS BY PNL:
------------------------------------------------------------
 1. PnL: $6,279.84 | Trades:  49 | Sharpe:  0.000
 2. PnL: $6,279.84 | Trades:  49 | Sharpe:  0.000
 3. PnL: $5,356.13 | Trades:  50 | Sharpe:  0.000
...
```

## Phase 2 Result Management

### Workflow Diagram
```
phase2_coarse_grid (original, Sharpe-ranked)
        |
        +---> regenerate_phase2_json.py ---> top_10.json + summary.json
        |
        +---> update_pnl_ranked_csv.py ---> phase2_coarse_grid_ranked_by_pnl.csv
```

### Best Practices
- Always regenerate JSON files after re-running backtests
- Use --verify-only to check if regeneration is needed
- Keep both Sharpe-ranked and PnL-ranked CSVs in sync
- Document which objective was used for ranking in file names or comments

### Troubleshooting
- **Missing columns**: Ensure CSV has all required parameter columns
- **Corrupted data**: Use --verify-only to check data consistency
- **Zero Sharpe ratios**: Indicates outdated data, regenerate from corrected source

## Bug Fixes Applied

### Trade Count Extraction Bug
- **Problem**: `performance_stats.json` files missing "Total trades" field
- **Fix**: Added fallback to count trades from `positions.csv` in `grid_search.py`
- **Impact**: Grid search results now show accurate trade counts

### Sharpe Ratio Extraction Bug  
- **Problem**: `performance_stats.json` files missing "Sharpe ratio" field
- **Fix**: Added fallback to calculate Sharpe ratio from `positions.csv` using realized returns
- **Impact**: Grid search results now show accurate Sharpe ratios

## Usage Examples

### Quick Analysis
```bash
# Get Phase 3 configuration summary
python optimization/tools/emit_phase3_summary.py

# Rank existing results by PnL
python optimization/tools/rank_by_pnl.py --input optimization/results/phase2_coarse_grid.csv --summary-only
```

### Create Ranked Results
```bash
# Create a new file with PnL-based ranking
python optimization/tools/rank_by_pnl.py \
  --input optimization/results/phase2_coarse_grid.csv \
  --output optimization/results/phase2_coarse_grid_ranked_by_pnl.csv
```

### Workflow Integration
```bash
# 1. Run grid search (with fixed trade count and Sharpe extraction)
python optimization/grid_search.py --config optimization/configs/phase2_coarse_grid.yaml --objective sharpe_ratio

# 2. If Sharpe ratios are still 0, use PnL ranking as workaround
python optimization/tools/rank_by_pnl.py --input optimization/results/phase2_coarse_grid.csv --output optimization/results/phase2_coarse_grid_ranked_by_pnl.csv

# 3. Review the properly ranked results
# The ranked file will have results sorted by PnL with a new 'pnl_rank' column
```
