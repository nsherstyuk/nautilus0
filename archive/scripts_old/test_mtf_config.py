#!/usr/bin/env python3
"""Test MTF configuration loading."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.mtf_config import load_mtf_config, validate_mtf_config, print_mtf_config

def main():
    print("Testing MTF Configuration...")
    print("Loading from: .env.mtf\n")
    
    config = load_mtf_config()
    print_mtf_config(config)
    
    if validate_mtf_config(config):
        print("\n✅ Configuration is valid and ready to use!")
        return 0
    else:
        print("\n❌ Configuration has errors!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
