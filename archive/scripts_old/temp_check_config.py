import os
from config.backtest_config import get_backtest_config
os.environ['BACKTEST_SYMBOL']='EUR/USD'
os.environ['BACKTEST_START_DATE']='2025-01-01'
os.environ['BACKTEST_END_DATE']='2025-01-02'
os.environ['STRATEGY_REGIME_DETECTION_ENABLED']='true'
os.environ['STRATEGY_REGIME_TP_MULTIPLIER_RANGING']='0.5'
cfg = get_backtest_config()
print('regime_detection_enabled:', cfg.regime_detection_enabled)
print('regime_tp_multiplier_ranging:', cfg.regime_tp_multiplier_ranging)
