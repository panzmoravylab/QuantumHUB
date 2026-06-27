@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title Quantum HUD - TEST REZIM

cd /d "%~dp0"

if /i not "%~1"=="RUN" (
    cmd /k "%~f0" RUN
    exit /b
)

echo.
echo  ============================================================
echo       QUANTUM HUD  -  TEST REZIM (bez MT5)
echo  ============================================================
echo.
echo   Replay ze souboru test_data\default_snapshot.json
echo   MT5 terminal NENI potreba.
echo.

:: --- Ukonceni stare instance ---
echo  [0/3] Kontroluji port 8050 ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8050" ^| findstr LISTENING') do (
    taskkill /F /PID %%P >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_hud.ps1"
timeout /t 2 /nobreak >nul

if not exist "test_data\default_snapshot.json" (
    echo  [!] Snapshot test_data\default_snapshot.json neexistuje.
    echo      Spustte nejdriv:  Ulozit_test_data.bat  ^(s behem MT5^)
    echo      nebo zkopirujte vlastni JSON do test_data\
    echo.
    choice /C PC /M "Pokracovat nebo Zrusit"
    if !errorlevel! equ 2 goto :KONEC
)

if exist ".env.test" (
    echo  [i] Nactu volitelnou konfiguraci .env.test
    for /f "usebackq tokens=1,* delims==" %%A in (".env.test") do (
        set "line=%%A"
        if not "!line!"=="" if not "!line:~0,1!"=="#" (
            set "%%A=%%B"
        )
    )
)

echo  [1/3] Pripravuji Python prostredi ...
call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

for /f "usebackq delims=" %%V in (`"%VPY%" -c "from config import HUD_VERSION; print(HUD_VERSION)"`) do set "HUD_VER=%%V"

:: --- TEST rezim ---
set "HUD_MODE=test"
if not defined TEST_SNAPSHOT set "TEST_SNAPSHOT=test_data\default_snapshot.json"
if not defined TEST_M1_BAR_SECONDS set "TEST_M1_BAR_SECONDS=60"
if not defined TEST_REPLAY_SPEED set "TEST_REPLAY_SPEED=5"
if not defined TEST_REPLAY_LOOP set "TEST_REPLAY_LOOP=true"
if not defined TEST_SCENARIO set "TEST_SCENARIO=healthy"

echo  [2/3] Nastaveni TEST rezimu:
echo       HUD_MODE=%HUD_MODE%
echo       TEST_SNAPSHOT=%TEST_SNAPSHOT%
echo       TEST_M1_BAR_SECONDS=%TEST_M1_BAR_SECONDS%  ^(1 M1 svicka^)
echo       TEST_REPLAY_SPEED=%TEST_REPLAY_SPEED%  ^(nasobitel^)
echo       TEST_SCENARIO=%TEST_SCENARIO%

echo  [3/3] Spoustim Quantum HUD TEST ...
echo.
echo  ============================================================
echo   Dashboard:  http://127.0.0.1:8050/?build=!HUD_VER!
echo   Verze:      v!HUD_VER!  ^(zavrit stare zalozky 8050^)
echo   Rezim:      TEST ^(replay^) — badge TEST v hlavicce
echo   Ukonceni:   Ctrl+C v tomto okne
echo  ============================================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8050/?build=!HUD_VER!"

"%VPY%" app.py

echo.
echo  Quantum HUD TEST ukoncen.

:KONEC
echo.
pause
