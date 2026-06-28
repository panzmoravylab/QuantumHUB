@echo off
chcp 65001 >nul 2>&1
setlocal
set "HUD_LAYOUT=portrait"
call "%~dp0Spustit_Quantum_HUD.bat" RUN
endlocal
