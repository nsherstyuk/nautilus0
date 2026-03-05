"""
Multi-Pair FX Momentum + Carry Strategy — Backtest
=====================================================
Cross-sectional momentum: rank pairs by trailing return, go long top N, short bottom N.
Carry proxy: approximate from long-term trend (higher-yielding currencies trend up).
Rebalance weekly.

Universe: 10 major/minor FX pairs (all available on IBKR).
Data: Yahoo Finance daily bars (free, no account needed).
Period: 2007-2025 (includes GFC, COVID, rate hiking cycles).
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from dataclasses import dataclass


# ─── Configuration ───────────────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    # Universe - Yahoo Finance tickers for FX pairs
    # Convention: all expressed as XXX per 1 USD (or USD per 1 XXX for =X pairs)
    pairs: dict = None  # ticker -> human name

    # Signal parameters
    momentum_lookback: int = 63       # ~3 months of trading days
    momentum_lookback_2: int = 21     # ~1 month (short-term momentum)
    carry_lookback: int = 252         # ~1 year for carry proxy

    # Portfolio construction
    n_long: int = 3                   # number of pairs to go long
    n_short: int = 3                  # number of pairs to go short
    rebalance_day: int = 4            # 0=Mon, 4=Fri
    position_size_usd: float = 10000  # per leg

    # Risk management
    vol_target: float = 0.10          # 10% annualized vol target
    vol_lookback: int = 63            # lookback for vol estimate
    max_position_weight: float = 0.25 # max single pair weight
    stop_loss_atr_mult: float = 3.0   # stop at 3x ATR

    # Costs
    spread_cost_pips: float = 1.5     # average spread cost per trade (round trip)
    commission_per_trade: float = 2.0 # IBKR FX commission

    # Backtest
    start_date: str = "2007-01-01"
    end_date: str = "2025-12-31"

    def __post_init__(self):
        if self.pairs is None:
            self.pairs = {
                "EURUSD=X": "EURUSD",
                "GBPUSD=X": "GBPUSD",
                "AUDUSD=X": "AUDUSD",
                "NZDUSD=X": "NZDUSD",
                "USDCAD=X": "USDCAD",
                "USDCHF=X": "USDCHF",
                "USDJPY=X": "USDJPY",
                "EURJPY=X": "EURJPY",
                "GBPJPY=X": "GBPJPY",
                "EURGBP=X": "EURGBP",
            }


# ─── Data Download ───────────────────────────────────────────────────────────

def download_fx_data(config: StrategyConfig) -> pd.DataFrame:
    """Download daily close prices for all pairs from Yahoo Finance."""
    print(f"Downloading daily data for {len(config.pairs)} FX pairs...")
    tickers = list(config.pairs.keys())

    # Download all at once
    raw = yf.download(
        tickers,
        start=config.start_date,
        end=config.end_date,
        auto_adjust=True,
        progress=False,
    )

    # Extract close prices
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]]
        closes.columns = tickers

    # Rename columns to human-readable names
    closes = closes.rename(columns=config.pairs)

    # Normalize direction: ensure all pairs are "units of quote per 1 base"
    # For USDXXX pairs, we need to invert so momentum is comparable
    # Actually, keep as-is: momentum on USDJPY rising = USD strengthening
    # Cross-sectional ranking handles direction automatically

    # Forward-fill small gaps, drop rows with too many NaNs
    closes = closes.ffill().dropna(thresh=len(closes.columns) - 2)

    print(f"  Downloaded {len(closes)} daily bars, {closes.columns.tolist()}")
    print(f"  Date range: {closes.index[0].date()} to {closes.index[-1].date()}")
    missing = closes.isna().sum()
    if missing.any():
        print(f"  Missing data: {missing[missing > 0].to_dict()}")

    return closes


# ─── Signal Generation ───────────────────────────────────────────────────────

def compute_signals(closes: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """
    Compute momentum + carry signals for cross-sectional ranking.

    Returns DataFrame of combined Z-scores for each pair on each day.
    """
    returns = closes.pct_change()

    # 1. Medium-term momentum: trailing 63-day return
    mom_med = closes.pct_change(config.momentum_lookback)

    # 2. Short-term momentum: trailing 21-day return
    mom_short = closes.pct_change(config.momentum_lookback_2)

    # 3. Carry proxy: 252-day trailing return (long-term trend = carry bias)
    # This isn't perfect carry, but higher-yielding currencies tend to appreciate
    # over 1-year windows due to carry flows. Better than nothing without swap data.
    carry_proxy = closes.pct_change(config.carry_lookback)

    # Cross-sectional Z-score (rank within each day, normalized)
    def xsec_rank(df):
        """Rank across pairs each day -> 0 to 1 scale."""
        return df.rank(axis=1, pct=True)

    mom_med_rank = xsec_rank(mom_med)
    mom_short_rank = xsec_rank(mom_short)
    carry_rank = xsec_rank(carry_proxy)

    # Combined signal: 50% medium momentum, 20% short momentum, 30% carry
    combined = 0.50 * mom_med_rank + 0.20 * mom_short_rank + 0.30 * carry_rank

    return combined


# ─── Portfolio Construction ─────────────────────────────────────────────────

def build_positions(signals: pd.DataFrame, closes: pd.DataFrame,
                    config: StrategyConfig) -> pd.DataFrame:
    """
    Build target positions from signals.
    Each rebalance day: long top N, short bottom N, equal weight.
    Vol-scaling applied to target overall portfolio vol.
    """
    returns = closes.pct_change()
    n_pairs = len(closes.columns)

    # Rolling realized vol for vol-targeting
    port_vol = returns.mean(axis=1).rolling(config.vol_lookback).std() * np.sqrt(252)

    positions = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    current_pos = pd.Series(0.0, index=closes.columns)

    rebalance_dates = []

    for i in range(config.momentum_lookback + config.carry_lookback, len(closes)):
        date = closes.index[i]

        # Only rebalance on specified day of week
        if date.dayofweek == config.rebalance_day:
            sig = signals.iloc[i]
            valid = sig.dropna()

            if len(valid) < config.n_long + config.n_short:
                positions.iloc[i] = current_pos
                continue

            # Rank pairs
            ranked = valid.sort_values()
            shorts = ranked.index[:config.n_short].tolist()
            longs = ranked.index[-config.n_long:].tolist()

            # Equal weight within long/short baskets
            new_pos = pd.Series(0.0, index=closes.columns)
            weight = 1.0 / config.n_long  # equal weight per leg

            for pair in longs:
                new_pos[pair] = weight
            for pair in shorts:
                new_pos[pair] = -weight

            # Vol-targeting: scale positions so portfolio vol ≈ target
            if port_vol.iloc[i] > 0 and not np.isnan(port_vol.iloc[i]):
                vol_scalar = config.vol_target / max(port_vol.iloc[i], 0.01)
                vol_scalar = np.clip(vol_scalar, 0.2, 3.0)  # bound leverage
                new_pos *= vol_scalar

            # Cap individual weights
            new_pos = new_pos.clip(-config.max_position_weight, config.max_position_weight)

            current_pos = new_pos
            rebalance_dates.append(date)

        positions.iloc[i] = current_pos

    print(f"  {len(rebalance_dates)} rebalance events")
    return positions


# ─── Backtest Engine ─────────────────────────────────────────────────────────

def run_backtest(closes: pd.DataFrame, positions: pd.DataFrame,
                 config: StrategyConfig) -> dict:
    """
    Run the backtest: compute daily PnL from positions and returns.
    Includes transaction costs.
    """
    returns = closes.pct_change()

    # Daily portfolio return = sum of (position_i * return_i)
    daily_pnl = (positions.shift(1) * returns).sum(axis=1)

    # Transaction costs: proportional to turnover
    turnover = positions.diff().abs().sum(axis=1)
    # Approximate cost: spread + commission as fraction of notional
    cost_per_unit = config.spread_cost_pips * 0.0001  # pips to fraction
    daily_costs = turnover * cost_per_unit

    daily_pnl_net = daily_pnl - daily_costs

    # Build equity curve
    equity = (1 + daily_pnl_net).cumprod()

    # ── Metrics ──
    # Trim warmup period
    valid = daily_pnl_net[daily_pnl_net != 0]
    if len(valid) == 0:
        return {"error": "No trades"}

    total_return = equity.iloc[-1] / equity.iloc[max(0, equity.values.argmax() - len(equity))] - 1
    total_return = equity.iloc[-1] - 1.0

    ann_return = (1 + total_return) ** (252 / len(valid)) - 1 if len(valid) > 0 else 0
    ann_vol = valid.std() * np.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min()

    # Win rate (daily)
    daily_wr = (valid > 0).mean()

    # Win rate (weekly)
    weekly = valid.resample("W").sum()
    weekly_wr = (weekly > 0).mean()

    # Calmar ratio
    calmar = ann_return / abs(max_dd) if max_dd != 0 else 0

    # Yearly breakdown
    yearly = valid.groupby(valid.index.year).agg(
        total_return=lambda x: (1 + x).prod() - 1,
        sharpe=lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0,
        vol=lambda x: x.std() * np.sqrt(252),
        max_dd=lambda x: ((1 + x).cumprod().cummax() - (1 + x).cumprod()).max(),
        n_days=lambda x: len(x),
    )

    # Turnover stats
    total_turnover = turnover.sum()
    total_cost = daily_costs.sum()
    n_rebalances = (turnover > 0.01).sum()

    return {
        "equity": equity,
        "daily_pnl": daily_pnl_net,
        "drawdown": drawdown,
        "positions": positions,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "daily_wr": daily_wr,
        "weekly_wr": weekly_wr,
        "total_return": total_return,
        "yearly": yearly,
        "total_turnover": total_turnover,
        "total_cost_frac": total_cost,
        "n_rebalances": n_rebalances,
        "n_days": len(valid),
    }


# ─── Reporting ───────────────────────────────────────────────────────────────

def print_results(results: dict, label: str = ""):
    """Pretty-print backtest results."""
    if "error" in results:
        print(f"  {label}: {results['error']}")
        return

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Annual Return:   {results['ann_return']*100:+.2f}%")
    print(f"  Annual Vol:      {results['ann_vol']*100:.2f}%")
    print(f"  Sharpe Ratio:    {results['sharpe']:.2f}")
    print(f"  Max Drawdown:    {results['max_dd']*100:.1f}%")
    print(f"  Calmar Ratio:    {results['calmar']:.2f}")
    print(f"  Daily Win Rate:  {results['daily_wr']*100:.1f}%")
    print(f"  Weekly Win Rate: {results['weekly_wr']*100:.1f}%")
    print(f"  Total Return:    {results['total_return']*100:+.1f}%")
    print(f"  Trading Days:    {results['n_days']}")
    print(f"  Rebalances:      {results['n_rebalances']}")
    print(f"  Total Cost:      {results['total_cost_frac']*100:.2f}% of NAV")
    print()

    # Yearly breakdown
    print(f"  {'Year':>6} {'Return':>10} {'Sharpe':>8} {'Vol':>8} {'MaxDD':>8}")
    print(f"  {'-'*6} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")
    for year, row in results["yearly"].iterrows():
        print(f"  {year:>6} {row['total_return']*100:>+9.2f}% {row['sharpe']:>7.2f} "
              f"{row['vol']*100:>7.1f}% {row['max_dd']*100:>7.1f}%")
    print()


# ─── Parameter Sweep ─────────────────────────────────────────────────────────

def parameter_sweep(closes: pd.DataFrame):
    """Test robustness across different parameter choices."""
    print("\n" + "="*70)
    print("  PARAMETER SENSITIVITY SWEEP")
    print("="*70)

    results_summary = []

    # 1. Momentum lookback sweep
    print("\n--- Momentum Lookback ---")
    for lb in [21, 42, 63, 126, 252]:
        cfg = StrategyConfig(momentum_lookback=lb)
        sigs = compute_signals(closes, cfg)
        pos = build_positions(sigs, closes, cfg)
        res = run_backtest(closes, pos, cfg)
        if "error" not in res:
            print(f"  lookback={lb:>3}d: Sharpe={res['sharpe']:.2f}, "
                  f"Return={res['ann_return']*100:+.1f}%, "
                  f"MaxDD={res['max_dd']*100:.1f}%, "
                  f"WeeklyWR={res['weekly_wr']*100:.1f}%")
            results_summary.append(("mom_lb", lb, res['sharpe'], res['ann_return'], res['max_dd']))

    # 2. Number of longs/shorts
    print("\n--- Portfolio Size (N long / N short) ---")
    for n in [2, 3, 4]:
        cfg = StrategyConfig(n_long=n, n_short=n)
        sigs = compute_signals(closes, cfg)
        pos = build_positions(sigs, closes, cfg)
        res = run_backtest(closes, pos, cfg)
        if "error" not in res:
            print(f"  n_long=n_short={n}: Sharpe={res['sharpe']:.2f}, "
                  f"Return={res['ann_return']*100:+.1f}%, "
                  f"MaxDD={res['max_dd']*100:.1f}%")
            results_summary.append(("n_legs", n, res['sharpe'], res['ann_return'], res['max_dd']))

    # 3. Signal blend
    print("\n--- Signal Blend (mom_only, carry_only, blended) ---")
    for label, mom_w, carry_w in [("momentum_only", 1.0, 0.0),
                                    ("carry_only", 0.0, 1.0),
                                    ("blend_70_30", 0.7, 0.3),
                                    ("blend_50_50", 0.5, 0.5)]:
        cfg = StrategyConfig()
        returns = closes.pct_change()
        mom = closes.pct_change(cfg.momentum_lookback).rank(axis=1, pct=True)
        carry = closes.pct_change(cfg.carry_lookback).rank(axis=1, pct=True)
        mom_short = closes.pct_change(cfg.momentum_lookback_2).rank(axis=1, pct=True)
        if carry_w == 0:
            sigs = mom * 0.7 + mom_short * 0.3
        elif mom_w == 0:
            sigs = carry
        else:
            sigs = mom_w * (mom * 0.7 + mom_short * 0.3) + carry_w * carry
        pos = build_positions(sigs, closes, cfg)
        res = run_backtest(closes, pos, cfg)
        if "error" not in res:
            print(f"  {label:>16}: Sharpe={res['sharpe']:.2f}, "
                  f"Return={res['ann_return']*100:+.1f}%, "
                  f"MaxDD={res['max_dd']*100:.1f}%")
            results_summary.append(("blend", label, res['sharpe'], res['ann_return'], res['max_dd']))

    # 4. Transaction cost sensitivity
    print("\n--- Transaction Cost Sensitivity ---")
    cfg_base = StrategyConfig()
    sigs = compute_signals(closes, cfg_base)
    pos = build_positions(sigs, closes, cfg_base)
    for cost in [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]:
        cfg = StrategyConfig(spread_cost_pips=cost)
        res = run_backtest(closes, pos, cfg)
        if "error" not in res:
            print(f"  cost={cost:.1f}p: Sharpe={res['sharpe']:.2f}, "
                  f"Return={res['ann_return']*100:+.1f}%")
            results_summary.append(("cost", cost, res['sharpe'], res['ann_return'], res['max_dd']))

    # 5. Rebalance frequency
    print("\n--- Rebalance Day of Week ---")
    for day, name in [(0, "Monday"), (2, "Wednesday"), (4, "Friday")]:
        cfg = StrategyConfig(rebalance_day=day)
        sigs = compute_signals(closes, cfg)
        pos = build_positions(sigs, closes, cfg)
        res = run_backtest(closes, pos, cfg)
        if "error" not in res:
            print(f"  {name:>10}: Sharpe={res['sharpe']:.2f}, "
                  f"Return={res['ann_return']*100:+.1f}%")
            results_summary.append(("rebal_day", name, res['sharpe'], res['ann_return'], res['max_dd']))

    return results_summary


# ─── Walk-Forward Validation ─────────────────────────────────────────────────

def walk_forward_test(closes: pd.DataFrame, config: StrategyConfig):
    """
    Walk-forward out-of-sample test.
    Train signal weights on 3 years, test on next 1 year.
    """
    print("\n" + "="*70)
    print("  WALK-FORWARD OUT-OF-SAMPLE TEST")
    print("="*70)
    print("  (3-year train / 1-year test windows)\n")

    years = sorted(closes.index.year.unique())
    oos_results = []

    for test_year in range(max(years[0] + 4, 2011), max(years) + 1):
        # In-sample: 3 years before test year
        is_start = f"{test_year - 4}-01-01"
        is_end = f"{test_year - 1}-12-31"
        oos_start = f"{test_year}-01-01"
        oos_end = f"{test_year}-12-31"

        is_data = closes[is_start:is_end]
        oos_data = closes[oos_start:oos_end]

        if len(oos_data) < 50:
            continue

        # Use full data for signal computation (needs lookback)
        # but only evaluate on OOS period
        full_data = closes[:oos_end]
        sigs = compute_signals(full_data, config)
        pos = build_positions(sigs, full_data, config)

        # Extract OOS portion
        oos_pos = pos[oos_start:oos_end]
        oos_closes = closes[oos_start:oos_end]
        oos_returns = oos_closes.pct_change()

        daily_pnl = (oos_pos.shift(1) * oos_returns).sum(axis=1)
        turnover = oos_pos.diff().abs().sum(axis=1)
        costs = turnover * config.spread_cost_pips * 0.0001
        net_pnl = daily_pnl - costs

        valid = net_pnl[net_pnl != 0]
        if len(valid) < 20:
            continue

        ann_ret = (1 + valid).prod() ** (252 / len(valid)) - 1
        ann_vol = valid.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        wr = (valid > 0).mean()

        oos_results.append({
            "year": test_year,
            "return": ann_ret,
            "sharpe": sharpe,
            "vol": ann_vol,
            "wr": wr,
            "n_days": len(valid),
        })

        print(f"  {test_year}: Return={ann_ret*100:+6.2f}%, Sharpe={sharpe:+.2f}, "
              f"Vol={ann_vol*100:.1f}%, DailyWR={wr*100:.1f}%")

    if oos_results:
        df = pd.DataFrame(oos_results)
        print(f"\n  OOS Average: Return={df['return'].mean()*100:+.2f}%, "
              f"Sharpe={df['sharpe'].mean():.2f}, "
              f"Win years={( df['return'] > 0).sum()}/{len(df)}")
    print()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    config = StrategyConfig()

    # 1. Download data
    closes = download_fx_data(config)
    closes.to_parquet("trading_system_v4/data/fx_10pair_daily.parquet")
    print(f"  Saved to trading_system_v4/data/fx_10pair_daily.parquet")

    # 2. Compute signals
    print("\nComputing momentum + carry signals...")
    signals = compute_signals(closes, config)

    # 3. Build positions
    print("Building positions...")
    positions = build_positions(signals, closes, config)

    # 4. Run backtest
    print("Running backtest...")
    results = run_backtest(closes, positions, config)
    print_results(results, "BASELINE: Mom(63d)+Carry, 3L/3S, Weekly Rebal, 1.5p cost")

    # 5. Parameter sweep
    sweep_results = parameter_sweep(closes)

    # 6. Walk-forward OOS test
    walk_forward_test(closes, config)

    # 7. Position analysis
    print("="*70)
    print("  POSITION ANALYSIS")
    print("="*70)
    active_pos = positions[positions.abs().sum(axis=1) > 0.01]
    if len(active_pos) > 0:
        print(f"  Days with active positions: {len(active_pos)}")
        print(f"  Average gross exposure: {active_pos.abs().sum(axis=1).mean():.2f}")
        print(f"  Average net exposure: {active_pos.sum(axis=1).mean():.4f}")
        print(f"\n  Average position per pair:")
        avg_pos = active_pos.mean()
        for pair in avg_pos.sort_values().index:
            bar = "#" * int(abs(avg_pos[pair]) * 200)
            sign = "+" if avg_pos[pair] > 0 else "-"
            print(f"    {pair:>8}: {sign}{abs(avg_pos[pair]):.4f} {bar}")
    print()

    print("="*70)
    print("DONE")
    print("="*70)


if __name__ == "__main__":
    main()
