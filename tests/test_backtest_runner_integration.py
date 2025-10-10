import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from backtest.run_backtest import (
    create_instrument,
    create_backtest_run_config,
    generate_reports,
)


class DummyEngine:
    def __init__(self):
        self.trader = MagicMock()
        self.portfolio = MagicMock()

        self.trader.generate_orders_report.return_value = pd.DataFrame(
            [{"order_id": 1, "status": "FILLED"}]
        )
        self.trader.generate_fills_report.return_value = pd.DataFrame(
            [{"fill_id": 1, "price": 1.0, "quantity": 1}]
        )
        self.trader.generate_positions_report.return_value = pd.DataFrame(
            [{"instrument_id": "EUR/USD.IDEALPRO", "quantity": 0}]
        )
        self.trader.generate_account_report.return_value = pd.DataFrame(
            [{"timestamp": pd.Timestamp("2024-01-01"), "net_liquidation": 10_000}]
        )

        analyzer = MagicMock()
        analyzer.get_performance_stats_pnls.return_value = {"return": 0.01}
        analyzer.get_performance_stats_general.return_value = {"sharpe": 1.0}
        self.portfolio.analyzer = analyzer

    def add_instrument(self, instrument):
        self.instrument = instrument


class BacktestRunnerIntegrationTest(unittest.TestCase):
    def test_create_config_and_generate_reports_for_fx(self):
        symbol = "EUR/USD"
        venue = "IDEALPRO"

        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_dir = Path(tmpdir) / "catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)

            run_cfg = create_backtest_run_config(
                symbol=symbol,
                venue=venue,
                start_date="2024-01-01",
                end_date="2024-01-31",
                catalog_path=str(catalog_dir),
                fast_period=10,
                slow_period=20,
                trade_size=100,
                bar_spec="1-DAY-MID",
                starting_capital=10000.0,
                enforce_position_limit=True,
                allow_position_reversal=False,
            )

            self.assertEqual(run_cfg.venues[0].name, "IDEALPRO")

            instrument = create_instrument(symbol, venue)
            self.assertEqual(str(instrument.id), "EUR/USD.IDEALPRO")

            engine = DummyEngine()
            output_dir = Path(tmpdir) / "reports"
            from types import SimpleNamespace

            mock_cfg = SimpleNamespace(fast_period=10, slow_period=20)
            stats = generate_reports(
                engine,
                output_dir,
                symbol,
                venue,
                strategy=None,
                processed_bars=0,
                config=mock_cfg,
            )

            self.assertTrue((output_dir / "account.csv").exists())
            self.assertIn("pnls", stats)
            self.assertIn("general", stats)


if __name__ == "__main__":
    unittest.main()
