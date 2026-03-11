"""
download_bi5_direct.py -- Download .bi5 tick files directly from Dukascopy CDN.
No tick-vault metadata DB needed.

Dukascopy URL format:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH_0}/{DAY}/{HOUR}h_ticks.bi5
  Month is 0-indexed: 00=Jan, 01=Feb, ..., 11=Dec
  Day is 1-indexed (01, 02, ...)

Downloads to: C:/nautilus0/tick_vault_data/downloads/XAUUSD/{year}/{month_0}/{day}/{hour}h_ticks.bi5
"""
import sys
import time
import argparse
import calendar
import concurrent.futures
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://datafeed.dukascopy.com/datafeed"

MISSING_MONTHS = [
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

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def download_hour(symbol, year, month, day, hour):
    """Download one hour of tick data. Returns (success_bool, out_path)."""
    month_0 = month - 1
    
    out_dir = Path(OUT_DIR) / str(year) / f"{month_0:02d}" / f"{day:02d}"
    out_path = out_dir / f"{hour:02d}h_ticks.bi5"
    
    if out_path.exists() and out_path.stat().st_size > 0:
        return True, out_path

    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{symbol}/{year}/{month_0:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 0:
                out_path.write_bytes(resp.content)
                return True, out_path
            elif resp.status_code == 404:
                # No data for this hour (weekend, holiday)
                return False, None
            else:
                time.sleep(1)
        except Exception:
            time.sleep(2)

    return False, None


def download_month(symbol, year, month):
    """Download all .bi5 files for a given month in parallel."""
    month_0 = month - 1
    days_in_month = calendar.monthrange(year, month)[1]
    
    # We will submit up to 24 * days_in_month jobs
    jobs = []
    
    for day in range(1, days_in_month + 1):
        if year == 2026 and month == 3 and day > 7:
            continue
            
        day_dir = OUT_DIR / str(year) / f"{month_0:02d}" / f"{day:02d}"
        day_dir.mkdir(parents=True, exist_ok=True)
        
        for hour in range(24):
            url = f"{BASE_URL}/{symbol}/{year}/{month_0:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
            out_path = day_dir / f"{hour:02d}h_ticks.bi5"
            jobs.append((url, out_path))
            
    downloaded = 0
    skipped = 0
    already = 0

    # Use thread pool for parallel downloads
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(download_hour, symbol, year, month, day, hour): (url, out_path) for url, out_path in jobs}
        for future in concurrent.futures.as_completed(futures):
            ok, path = future.result()
            if ok and path:
                if path.stat().st_size > 0:
                    downloaded += 1
            else:
                skipped += 1

    return downloaded, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('symbol', type=str, help='e.g. XAUUSD or EURUSD')
    parser.add_argument('--all', action='store_true', help='Download all months 2018-2026 (not just missing)')
    args = parser.parse_args()

    symbol = args.symbol.upper()
    global OUT_DIR
    OUT_DIR = Path(r"C:\nautilus0\tick_vault_data\downloads") / symbol

    if args.all:
        months_to_dl = []
        for y in range(2018, 2027):
            for m in range(1, 13):
                if y == 2026 and m > 3: continue
                months_to_dl.append((y, m))
    else:
        months_to_dl = MISSING_MONTHS

    print(f"Downloading {len(months_to_dl)} months of {symbol} tick data from Dukascopy")
    print(f"Output: {OUT_DIR}")
    print()

    total_downloaded = 0
    for i, (year, month) in enumerate(months_to_dl):
        tag = f"{year}-{month:02d}"
        sys.stdout.write(f"  [{i+1}/{len(months_to_dl)}] {tag}: ")
        sys.stdout.flush()

        dl, sk = download_month(symbol, year, month)
        total_downloaded += dl
        print(f"{dl} files downloaded, {sk} skipped (weekend/empty)")

    print(f"\nDone! Total files downloaded: {total_downloaded:,}")
    total_files = sum(1 for _ in OUT_DIR.rglob("*.bi5"))
    print(f"Total .bi5 files on disk: {total_files:,}")
    print(f"\nNow run: python build_1m_from_bi5.py --start 2018 --end 2026")


if __name__ == "__main__":
    main()
