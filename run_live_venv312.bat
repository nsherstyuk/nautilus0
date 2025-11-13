@echo off
echo Activating Python 3.12 virtual environment...
call .venv312\Scripts\activate.bat
echo.
echo Python version:
python --version
echo.
echo NautilusTrader version:
python -c "import nautilus_trader; print('NautilusTrader:', nautilus_trader.__version__)"
echo.
echo Starting live trading...
python live/run_live.py
