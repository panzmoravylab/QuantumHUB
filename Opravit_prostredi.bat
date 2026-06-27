@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title Quantum HUD - Oprava prostredi

cd /d "%~dp0"

echo.
echo  ============================================================
echo       Oprava Python prostredi
echo  ============================================================
echo.
echo  Vytvori venv v %%LOCALAPPDATA%%\QuantumHUD\venv311
echo  (mimo projekt — Cursor nezamkne soubory).
echo  Zamcena slozka .venv v projektu se ignoruje.
echo.

call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" (
    echo.
    echo  Oprava selhala.
    goto :KONEC
)

echo.
echo  Hotovo. Python: !VPY!
echo  Spustte: Spustit_Quantum_HUD.bat

:KONEC
echo.
pause
