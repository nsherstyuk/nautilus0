"""
Data loader for Trading System v4.
Handles historical and live data ingestion.
"""
import pandas as pd
from pathlib import Path

def load_csv(path):
    return pd.read_csv(path)

# TODO: Add live data streaming support
