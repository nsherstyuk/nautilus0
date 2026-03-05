"""Quick runner for tick-level MM sim with clean output."""
import logging
import os
import sys

os.environ["TQDM_DISABLE"] = "1"
logging.getLogger("tick_vault").setLevel(logging.CRITICAL)

from trading_system_v4.scripts.test_mm_tick_level import (
    MMParams, run_simulation, print_results
)
from datetime import datetime
import numpy as np

def main():
    # Test 1: Base case
    print("=" * 70)
    print("TEST 1: London session, half_spread=2.0p, 100 sampled days 2022-2025")
    print("=" * 70)
    p = MMParams(
        half_spread_pips=2.0, max_inventory=3, inventory_skew_pips=0.3,
        session_start_hour=7, session_end_hour=17,
        spread_kill_pips=1.5, volatility_kill_threshold=3.0,
        cooldown_ticks=200, fill_probability=0.7,
    )
    r = run_simulation(datetime(2022, 1, 1), datetime(2025, 12, 31), p, sample_days=100)
    print_results("London 2.0p", r)
    print()

    # Test 2: Spread sweep
    print("=" * 70)
    print("TEST 2: Half-spread sweep (London, 60 days each)")
    print("=" * 70)
    for hs in [1.0, 1.5, 2.0, 2.5, 3.0]:
        p2 = MMParams(
            half_spread_pips=hs, max_inventory=3, inventory_skew_pips=0.3,
            session_start_hour=7, session_end_hour=17,
            spread_kill_pips=1.5, volatility_kill_threshold=3.0,
            cooldown_ticks=200, fill_probability=0.7,
        )
        r2 = run_simulation(datetime(2022, 1, 1), datetime(2025, 12, 31), p2, sample_days=60)
        print_results(f"hs={hs}p", r2)

    # Test 3: Fill probability sensitivity
    print()
    print("=" * 70)
    print("TEST 3: Fill probability sensitivity (London, 60 days each)")
    print("=" * 70)
    for fp in [0.3, 0.5, 0.7, 1.0]:
        p3 = MMParams(
            half_spread_pips=2.0, max_inventory=3, inventory_skew_pips=0.3,
            session_start_hour=7, session_end_hour=17,
            spread_kill_pips=1.5, volatility_kill_threshold=3.0,
            cooldown_ticks=200, fill_probability=fp,
        )
        r3 = run_simulation(datetime(2022, 1, 1), datetime(2025, 12, 31), p3, sample_days=60)
        print_results(f"fp={fp}", r3)

    # Test 4: Session comparison
    print()
    print("=" * 70)
    print("TEST 4: Session comparison (60 days each)")
    print("=" * 70)
    for name, sh, eh in [
        ("London 7-17", 7, 17),
        ("London AM 7-12", 7, 12),
        ("NY 13-21", 13, 21),
        ("Asian 0-7", 0, 7),
    ]:
        p4 = MMParams(
            half_spread_pips=2.0, max_inventory=3, inventory_skew_pips=0.3,
            session_start_hour=sh, session_end_hour=eh,
            spread_kill_pips=1.5, volatility_kill_threshold=3.0,
            cooldown_ticks=200, fill_probability=0.7,
        )
        r4 = run_simulation(datetime(2022, 1, 1), datetime(2025, 12, 31), p4, sample_days=60)
        print_results(name, r4)

    print("\nDONE")


if __name__ == "__main__":
    main()
