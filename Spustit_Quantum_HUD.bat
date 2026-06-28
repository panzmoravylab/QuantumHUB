@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

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
echo  Language / Jazyk: [C] Czech  [E] English
choice /C CE /M "Select language / Vyberte jazyk"
if errorlevel 2 (
    set "HUD_UI_LANG=EN"
    set "HUD_LANG=EN"
    title Quantum HUD - Launch
) else (
    set "HUD_UI_LANG=CZ"
    set "HUD_LANG=CZ"
    title Quantum HUD - Spousteni
)

echo.
if "!HUD_LANG!"=="EN" (
    echo  Display: [M] MAIN wide  [P] PORTRAIT vertical 1080x1920
) else (
    echo  Zobrazeni: [M] HLAVNI siroky  [P] PORTRAIT monitor na vysku 1080x1920
)
choice /C MP /M "Layout / Zobrazeni"
if errorlevel 2 (set "HUD_LAYOUT=portrait") else (set "HUD_LAYOUT=main")

if "!HUD_LANG!"=="EN" goto :EN_BLOCK
goto :CZ_BLOCK

:CZ_BLOCK
echo.
echo  [0/4] Kontroluji port 8050 a stare instance HUD ...
goto :CHECK_PORT

:EN_BLOCK
echo.
echo  [0/4] Checking port 8050 and old HUD instances ...
goto :CHECK_PORT

:CHECK_PORT
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8050" ^| findstr LISTENING') do (
    if "!HUD_LANG!"=="EN" (echo       Stopping process on port 8050 PID %%P) else (echo       Ukoncuji proces na portu 8050 PID %%P)
    taskkill /F /PID %%P >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_hud.ps1"
timeout /t 2 /nobreak >nul

if not exist ".env" (
    if "!HUD_LANG!"=="EN" (
        echo  [!] Configuration file .env not found.
        echo      Run Settings.bat first.
        choice /C YN /M "Open settings now"
    ) else (
        echo  [!] Konfigurace .env neexistuje.
        echo      Nejdriv spustte:  Nastaveni.bat
        choice /C AN /M "Spustit nastaveni ted"
    )
    if !errorlevel! equ 1 call "%~dp0Nastaveni.bat" RUN
    if not exist ".env" (
        if "!HUD_LANG!"=="EN" (echo  [ERROR] Cannot continue without .env.) else (echo  [CHYBA] Bez .env nelze pokracovat.)
        goto :KONEC
    )
)

if "!HUD_LANG!"=="EN" (echo  [1/4] Preparing Python environment ...) else (echo  [1/4] Pripravuji Python prostredi ...)
call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

for /f "usebackq delims=" %%V in (`"%VPY%" -c "from config import HUD_VERSION; print(HUD_VERSION)"`) do set "HUD_VER=%%V"

if "!HUD_LANG!"=="EN" (echo  [2/4] Checking MetaTrader 5 ...) else (echo  [2/4] Kontroluji MetaTrader 5 ...)
set "MT5_OK=0"
tasklist /FI "IMAGENAME eq terminal64.exe" 2>nul | find /I "terminal64.exe" >nul
if !errorlevel! equ 0 set "MT5_OK=1"
tasklist /FI "IMAGENAME eq terminal.exe" 2>nul | find /I "terminal.exe" >nul
if !errorlevel! equ 0 set "MT5_OK=1"

if "!MT5_OK!"=="0" (
    echo.
    if "!HUD_LANG!"=="EN" (
        echo  [!] MetaTrader 5 is not running!
        echo      Start MT5 and log in. Dashboard may run offline.
        choice /C PC /M "Continue or Cancel"
    ) else (
        echo  [!] MetaTrader 5 nebezi!
        echo      Spustte MT5 terminal a prihlaste se k uctu.
        choice /C PC /M "Pokracovat nebo Zrusit"
    )
    if !errorlevel! equ 2 goto :KONEC
) else (
    if "!HUD_LANG!"=="EN" (echo       MetaTrader 5 is running.) else (echo       MetaTrader 5 bezi.)
)

if "!HUD_LANG!"=="EN" (echo  [3/4] Starting Quantum HUD ...) else (echo  [3/4] Spoustim Quantum HUD ...)
echo.
echo  ============================================================
echo   Dashboard:  http://127.0.0.1:8050/?build=!HUD_VER!
if "!HUD_LANG!"=="EN" (
    echo   Version:    v!HUD_VER!  ^(hard-refresh if layout looks stale^)
    echo   Stop:       Ctrl+C in this window
) else (
    echo   Verze:      v!HUD_VER!  ^(hard refresh pri zastaralem layoutu^)
    echo   Ukonceni:   Ctrl+C v tomto okne
)
echo  ============================================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8050/?build=!HUD_VER!"

set "HUD_MODE=live"
"%VPY%" app.py

echo.
if "!HUD_LANG!"=="EN" (echo  Quantum HUD stopped.) else (echo  Quantum HUD ukoncen.)

:KONEC
echo.
pause
