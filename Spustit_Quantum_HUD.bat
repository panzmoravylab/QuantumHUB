@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title Quantum HUD - Spousteni

cd /d "%~dp0"

if /i not "%~1"=="RUN" (
    cmd /k "%~f0" RUN
    exit /b
)

echo.
echo  ============================================================
echo       QUANTUM HUD  -  Trading Dashboard
echo  ============================================================
echo.

:: --- Ukonceni stare instance na portu 8050 a app.py ---
echo  [0/4] Kontroluji port 8050 a stare instance HUD ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8050" ^| findstr LISTENING') do (
    echo       Ukoncuji proces na portu 8050 PID %%P
    taskkill /F /PID %%P >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_hud.ps1"
timeout /t 2 /nobreak >nul

:: --- Kontrola .env ---
if not exist ".env" (
    echo  [!] Konfigurace .env neexistuje.
    echo.
    echo  Nejdriv spustte:  Nastaveni.bat
    echo.
    choice /C AN /M "Spustit nastaveni ted"
    if !errorlevel! equ 1 (
        call "%~dp0Nastaveni.bat" RUN
    )
    if not exist ".env" (
        echo  [CHYBA] Bez .env nelze pokracovat.
        goto :KONEC
    )
)

echo  [1/4] Pripravuji Python prostredi ...
call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

:: --- MT5 terminal ---
echo  [2/4] Kontroluji MetaTrader 5 ...
set "MT5_OK=0"
tasklist /FI "IMAGENAME eq terminal64.exe" 2>nul | find /I "terminal64.exe" >nul
if !errorlevel! equ 0 set "MT5_OK=1"
tasklist /FI "IMAGENAME eq terminal.exe" 2>nul | find /I "terminal.exe" >nul
if !errorlevel! equ 0 set "MT5_OK=1"

if "!MT5_OK!"=="0" (
    echo.
    echo  [!] MetaTrader 5 nebezi!
    echo      Spustte MT5 terminal a prihlaste se k uctu.
    echo      Dashboard muze fungovat v offline modu.
    echo.
    choice /C PC /M "Pokracovat nebo Zrusit"
    if !errorlevel! equ 2 goto :KONEC
) else (
    echo       MetaTrader 5 bezi.
)

:: --- Spusteni ---
echo  [3/4] Spoustim Quantum HUD ...
echo.
echo  ============================================================
echo   Dashboard:  http://127.0.0.1:8050
echo   Verze:      v0.07  (v hlavicce musi byt "v0.07")
echo   Ukonceni:   Ctrl+C v tomto okne
echo  ============================================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8050"

"%VPY%" app.py

echo.
echo  Quantum HUD ukoncen.

:KONEC
echo.
pause
