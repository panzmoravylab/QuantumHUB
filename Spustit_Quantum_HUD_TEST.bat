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
echo       QUANTUM HUD  -  TEST MODE
echo  ============================================================
echo.
echo  Language / Jazyk: [C] Czech  [E] English
choice /C CE /M "Select language / Vyberte jazyk"
if errorlevel 2 (
    set "HUD_UI_LANG=EN"
    set "HUD_LANG=EN"
    title Quantum HUD - TEST
) else (
    set "HUD_UI_LANG=CZ"
    set "HUD_LANG=CZ"
    title Quantum HUD - TEST REZIM
)

echo.
if "!HUD_LANG!"=="EN" (
    echo  Display: [M] MAIN wide  [P] PORTRAIT vertical 1080x1920
) else (
    echo  Zobrazeni: [M] HLAVNI siroky  [P] PORTRAIT monitor na vysku 1080x1920
)
choice /C MP /M "Layout / Zobrazeni"
if errorlevel 2 (set "HUD_LAYOUT=portrait") else (set "HUD_LAYOUT=main")

if "!HUD_LANG!"=="EN" (
    echo   Replay from test_data\default_snapshot.json
    echo   MetaTrader 5 NOT required.
) else (
    echo   Replay ze souboru test_data\default_snapshot.json
    echo   MT5 terminal NENI potreba.
)
echo.

if "!HUD_LANG!"=="EN" (echo  [0/3] Checking port 8050 ...) else (echo  [0/3] Kontroluji port 8050 ...)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8050" ^| findstr LISTENING') do (
    taskkill /F /PID %%P >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_hud.ps1"
timeout /t 2 /nobreak >nul

if not exist "test_data\default_snapshot.json" (
    if "!HUD_LANG!"=="EN" (
        echo  [!] Missing test_data\default_snapshot.json
        echo      Run Save_test_data.bat while MT5 is connected.
        choice /C PC /M "Continue or Cancel"
    ) else (
        echo  [!] Snapshot test_data\default_snapshot.json neexistuje.
        echo      Spustte: Ulozit_test_data.bat
        choice /C PC /M "Pokracovat nebo Zrusit"
    )
    if !errorlevel! equ 2 goto :KONEC
)

if exist ".env.test" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env.test") do (
        set "line=%%A"
        if not "!line!"=="" if not "!line:~0,1!"=="#" set "%%A=%%B"
    )
)

if "!HUD_LANG!"=="EN" (echo  [1/3] Preparing Python environment ...) else (echo  [1/3] Pripravuji Python prostredi ...)
call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

for /f "usebackq delims=" %%V in (`"%VPY%" -c "from config import HUD_VERSION; print(HUD_VERSION)"`) do set "HUD_VER=%%V"

set "HUD_MODE=test"
if not defined TEST_SNAPSHOT set "TEST_SNAPSHOT=test_data\default_snapshot.json"
if not defined TEST_M1_BAR_SECONDS set "TEST_M1_BAR_SECONDS=30"
if not defined TEST_REPLAY_SPEED set "TEST_REPLAY_SPEED=1"
if not defined TEST_REPLAY_LOOP set "TEST_REPLAY_LOOP=true"
if not defined TEST_SCENARIO set "TEST_SCENARIO=healthy"

if "!HUD_LANG!"=="EN" (echo  [2/3] TEST settings:) else (echo  [2/3] Nastaveni TEST rezimu:)
echo       HUD_MODE=%HUD_MODE%
echo       TEST_SNAPSHOT=%TEST_SNAPSHOT%
echo       TEST_M1_BAR_SECONDS=%TEST_M1_BAR_SECONDS%
echo       HUD_UI_LANG=%HUD_UI_LANG%

if "!HUD_LANG!"=="EN" (echo  [3/3] Starting Quantum HUD TEST ...) else (echo  [3/3] Spoustim Quantum HUD TEST ...)
echo.
echo  ============================================================
echo   Dashboard:  http://127.0.0.1:8050/?build=!HUD_VER!
if "!HUD_LANG!"=="EN" (
    echo   Version:    v!HUD_VER!
    echo   Mode:       TEST replay
    echo   Stop:       Ctrl+C
) else (
    echo   Verze:      v!HUD_VER!
    echo   Rezim:      TEST ^(replay^)
    echo   Ukonceni:   Ctrl+C
)
echo  ============================================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8050/?build=!HUD_VER!"

"%VPY%" app.py

echo.
if "!HUD_LANG!"=="EN" (echo  Quantum HUD TEST stopped.) else (echo  Quantum HUD TEST ukoncen.)

:KONEC
echo.
pause
