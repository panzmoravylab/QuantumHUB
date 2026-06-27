@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title Quantum HUD - Ulozeni test dat

cd /d "%~dp0"

if /i not "%~1"=="RUN" (
    cmd /k "%~f0" RUN
    exit /b
)

echo.
echo  ============================================================
echo       QUANTUM HUD  -  Ulozeni snapshotu pro TEST rezim
echo  ============================================================
echo.
echo   Vyzaduje bezici MT5 terminal + prihlaseny ucet.
echo   Vytvori / prepise:  test_data\default_snapshot.json
echo.

if not exist ".env" (
    echo  [!] Chybi .env — spustte Nastaveni.bat
    goto :KONEC
)

call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

set "MT5_OK=0"
tasklist /FI "IMAGENAME eq terminal64.exe" 2>nul | find /I "terminal64.exe" >nul
if !errorlevel! equ 0 set "MT5_OK=1"

if "!MT5_OK!"=="0" (
    echo  [CHYBA] MetaTrader 5 nebezi — spustte terminal a zkuste znovu.
    goto :KONEC
)

echo  Zachytavam data z MT5 ...
"%VPY%" capture_test_snapshot.py --bars 300 --positions 2
if !errorlevel! neq 0 (
    echo  [CHYBA] Capture selhal.
    goto :KONEC
)

echo.
echo  Hotovo. Snapshot ulozen do test_data\default_snapshot.json
echo  Ted spustte:  Spustit_Quantum_HUD_TEST.bat

:KONEC
echo.
pause
