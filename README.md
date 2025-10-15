# TradingSystem

A comprehensive trading system built with Python and NautilusTrader, featuring Interactive Brokers integration, historical data ingestion, backtesting capabilities, and live trading execution.

## Key Features

- **IBKR Integration**: Direct connection to Interactive Brokers API for real-time and historical data
- **Historical Data Ingestion**: Automated download and catalog management of market data
- **Backtesting Engine**: Comprehensive backtesting with performance analysis
- **Live Trading**: Production-ready live trading execution
- **Strategy Development**: Modular strategy implementations with technical indicators
- **Data Management**: Parquet-based data catalog with overlap detection and cleanup tools

## Technology Stack

- **Python 3.8+**
- **NautilusTrader**: High-performance trading framework
- **Interactive Brokers API**: Market data and order execution
- **Parquet**: Efficient data storage and retrieval
- **Pandas**: Data manipulation and analysis

## Quick Start

### Prerequisites

- Python 3.8 or higher
- Interactive Brokers account with API access
- TWS or IB Gateway running

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd nautilus0

# Install dependencies
pip install -r requirements.txt

# Copy environment configuration
cp .env.example .env
```

### Configuration

Edit `.env` file with your IBKR credentials and trading parameters:

```bash
# IBKR Connection
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1

# Data Ingestion
DATA_SYMBOLS=EUR/USD,SPY
DATA_START_DATE=2024-01-01
DATA_END_DATE=2024-01-31
CATALOG_PATH=data/historical
```

### First Run

```bash
# Basic data ingestion
python data/ingest_historical.py

# With cleanup (recommended for fresh starts)
python data/ingest_historical.py --force-clean

# Verify the data
python data/verify_catalog.py --check-overlaps
```

## Data Ingestion

### Basic Usage

```bash
# Set environment variables
export DATA_SYMBOLS="EUR/USD"
export DATA_START_DATE="2024-01-01"
export DATA_END_DATE="2024-01-31"

# Run ingestion
python data/ingest_historical.py
```

### With Cleanup

```bash
# Clean existing data and ingest fresh
python data/ingest_historical.py --force-clean
```

### Environment Variables

- `DATA_SYMBOLS`: Comma-separated list of symbols (e.g., "EUR/USD,SPY")
- `DATA_START_DATE`: Start date in YYYY-MM-DD format
- `DATA_END_DATE`: End date in YYYY-MM-DD format
- `CATALOG_PATH`: Output directory for data files

For detailed ingestion procedures, see the [Data Ingestion Runbook](docs/DATA_INGESTION_RUNBOOK.md).

## Verification and Troubleshooting

### Verify Data

```bash
# Check catalog contents
python data/verify_catalog.py

# Check for interval overlaps
python data/verify_catalog.py --check-overlaps
```

### Fix Common Issues

```bash
# Fix interval conflicts automatically
python data/fix_parquet_intervals.py --symbol EUR/USD

# Manual cleanup
python data/cleanup_catalog.py --delete-all --confirm --execute
```

### Common Issues

- **"Intervals are not disjoint" error**: Use `--force-clean` or run `fix_parquet_intervals.py`
- **"Catalog dataset missing" warning**: Re-run ingestion with cleanup
- **Connection errors**: Ensure IBKR Gateway/TWS is running

## Project Structure

```
nautilus0/
├── data/                    # Data ingestion and catalog management
│   ├── ingest_historical.py    # Main ingestion script
│   ├── verify_catalog.py       # Catalog verification
│   ├── fix_parquet_intervals.py # Automated cleanup
│   └── cleanup_catalog.py      # Manual cleanup utilities
├── backtest/               # Backtesting engine
│   └── run_backtest.py        # Backtest execution
├── live/                   # Live trading execution
│   └── run_live.py            # Live trading runner
├── strategies/             # Trading strategy implementations
│   └── moving_average_crossover.py
├── config/                 # Configuration files
│   ├── env_variables.md       # Environment variable reference
│   ├── ibkr_config.py         # IBKR connection settings
│   └── live_trading.yaml      # Live trading configuration
├── logs/                   # Application logs and backtest results
├── docs/                   # Documentation and runbooks
│   └── DATA_INGESTION_RUNBOOK.md
└── optimization/           # Strategy optimization tools
    └── grid_search.py         # Grid search optimization
```

## Documentation

- **[Data Ingestion Runbook](docs/DATA_INGESTION_RUNBOOK.md)** - Comprehensive guide for data operations
- **[Configuration Guide](config/env_variables.md)** - Environment variable reference
- **[Optimization Guide](optimization/README.md)** - Strategy optimization procedures

## Contributing

### Code Style

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Document functions and classes
- Write tests for new features

### Testing

```bash
# Run tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_dmi.py
```

### Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

[Add your license information here]

## Support

For issues and questions:
- Check the [Data Ingestion Runbook](docs/DATA_INGESTION_RUNBOOK.md) for troubleshooting
- Review logs in `logs/application.log`
- Ensure IBKR Gateway/TWS is running for live operations

