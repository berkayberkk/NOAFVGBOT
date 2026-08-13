@echo off
REM NOAFVGBOT V2 — MT5 Visual Replay Launcher Helper
echo ===================================================
echo NOAFVGBOT V2 — MT5 Visual Replay Helper
echo ===================================================

cd /d "%~dp0trade-bot"
python -m research.v2.mt5.export_replay --copy-to-mt5

echo.
echo NEXT STEPS:
echo 1. Open MetaTrader 5
echo 2. Open Strategy Tester (Ctrl+R)
echo 3. Select Expert: TradeBot_NOA_V2_Viewer
echo 4. Symbol: GOLD (or XAUUSD) | Model: Every tick based on real ticks
echo 5. Enable Visual Mode and click Start!
echo ===================================================
pause
