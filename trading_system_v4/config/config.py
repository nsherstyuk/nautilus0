"""
Configuration loader for Trading System v4.
Reads from .env or environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv(dotenv_path=Path(__file__).parent / '.env')

def get_config(key: str, default=None, cast_type=str):
    val = os.getenv(key, default)
    if val is not None and cast_type is not str:
        try:
            return cast_type(val)
        except Exception:
            return default
    return val
