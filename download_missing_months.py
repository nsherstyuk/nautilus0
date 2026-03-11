"""Download missing months of XAUUSD tick data from Dukascopy via tick-vault."""
import asyncio
import os
import sys
from datetime import datetime
from tick_vault import download_range, reload_config

TICK_VAULT_DIR = r"C:\nautilus0\tick_vault_data"

MISSING = [
    (2018, 1), (2018, 4), (2018, 5), (2018, 6), (2018, 12),
    (2019, 8), (2019, 9),
    (2020, 1),
    (2021, 4), (2021, 5), (2021, 6), (2021, 8), (2021, 11),
    (2022, 7),
    (2023, 2), (2023, 7), (2023, 8),
    (2024, 4),
    (2025, 2), (2025, 5), (2025, 8), (2025, 11),
    (2026, 1),
]


async def main():
    reload_config(base_directory=TICK_VAULT_DIR, worker_per_proxy=15)

    for i, (year, month) in enumerate(MISSING):
        start = datetime(year, month, 1)
        end = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
        tag = f"{year}-{month:02d}"
        sys.stdout.write(f"[{i+1}/{len(MISSING)}] {tag}: downloading... ")
        sys.stdout.flush()
        try:
            await download_range(symbol="XAUUSD", start=start, end=end)
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")

    print("\nAll missing months downloaded. Now re-run build_1m_from_bi5.py")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
