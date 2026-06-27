@echo off
setlocal EnableDelayedExpansion

set "PY="
set "PY_CMD="
set "PY_MINOR="
set "VENV_DIR="
set "VPY="

for %%V in (3.11 3.12 3.13) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PY_CMD=py -%%V"
            set "PY_MINOR=%%V"
            for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
        )
    )
)

if not defined PY (
    echo  [CHYBA] Python 3.11+ neni nainstalovany.
    echo  Stahnete Python 3.11 z: https://www.python.org/downloads/
    endlocal & set "PY_SETUP_OK=0"
    exit /b 1
)

echo  Python !PY_MINOR!: !PY!

set "WANT_MINOR=!PY_MINOR:~2!"
if not exist "%LOCALAPPDATA%\QuantumHUD" mkdir "%LOCALAPPDATA%\QuantumHUD" 2>nul
set "VENV_LOCAL=%LOCALAPPDATA%\QuantumHUD\venv311"

:: 1) Platne prostredi: projekt .venv, pak venv mimo projekt (Cursor nezamkne)
call :TRY_USE_VENV ".venv"
if defined VPY goto :ENSURE_DEPS
call :TRY_USE_VENV "%VENV_LOCAL%"
if defined VPY goto :ENSURE_DEPS

:: 2) Vytvorit / obnovit
call :REBUILD_VENV ".venv"
if defined VPY goto :ENSURE_DEPS

echo  [WARN] .venv v projektu je zamceny — pouzivam %VENV_LOCAL%
call :REBUILD_VENV "%VENV_LOCAL%"
if defined VPY goto :ENSURE_DEPS

:: 3) Posledni moznost: systemovy Python (bez venv)
echo  [WARN] Venv selhal — pouzivam systemovy Python 3.!WANT_MINOR!
set "VENV_DIR=system"
set "VPY=!PY!"
goto :ENSURE_DEPS

:ENSURE_DEPS
for /f "delims=" %%M in ('"%VPY%" -c "import sys; print(sys.version_info[1])" 2^>nul') do set "CHECK_MINOR=%%M"
if "!CHECK_MINOR!" geq "14" (
    echo  [CHYBA] Prostredi bezi na Python 3.!CHECK_MINOR! — potrebny Python 3.!WANT_MINOR!
    endlocal & set "PY_SETUP_OK=0"
    exit /b 1
)

if "!VENV_DIR!"=="system" (
    echo  Prostredi: systemovy Python
) else (
    echo  Prostredi: !VENV_DIR!
)

"%VPY%" -c "import dash, MetaTrader5, plotly, pandas, dotenv" >nul 2>&1
if !errorlevel! equ 0 (
    echo  Zavislosti OK
    goto :SUCCESS
)

echo  Kontroluji / instaluji zavislosti ...
"%VPY%" -m pip install --upgrade pip --no-cache-dir -q 2>nul
"%VPY%" "%~dp0install_deps.py"
if !errorlevel! neq 0 (
    echo  [CHYBA] Instalace zavislosti selhala.
    echo  Tip: vypnete VPN/antivirus nebo spustte znovu.
    endlocal & set "PY_SETUP_OK=0"
    exit /b 1
)

echo  Zavislosti OK
goto :SUCCESS

:SUCCESS
endlocal & set "PY_SETUP_OK=1" & set "VPY=%VPY%"
exit /b 0

:: --- Subroutines ---

:TRY_USE_VENV
set "VDIR=%~1"
if not exist "%VDIR%\pyvenv.cfg" exit /b 1
if not exist "%VDIR%\Lib" exit /b 1
if not exist "%VDIR%\Scripts\python.exe" exit /b 1
call :IS_VENV_VALID "%VDIR%"
if !errorlevel! neq 0 exit /b 1
set "VENV_DIR=%VDIR%"
set "VPY=%VDIR%\Scripts\python.exe"
exit /b 0

:REBUILD_VENV
set "VDIR=%~1"
set "VPY="
set "VENV_DIR="

if exist "%VDIR%" (
    call :IS_VENV_VALID "%VDIR%"
    if !errorlevel! equ 0 (
        set "VENV_DIR=%VDIR%"
        set "VPY=%VDIR%\Scripts\python.exe"
        exit /b 0
    )
    echo.
    echo  [WARN] %VDIR% je poskozeny — obnovuji ...
    call :QUARANTINE_DIR "%VDIR%" "%VDIR%_old"
)

if exist "%VDIR%" (
    exit /b 1
)

echo  Vytvarim virtualni prostredi ...
echo  Cesta: %VDIR%
echo  (pouziva systemove balicky — rychlejsi start, mene pip stahovani^)
!PY_CMD! -m venv --system-site-packages "%VDIR%"
if !errorlevel! neq 0 exit /b 1

call :IS_VENV_VALID "%VDIR%"
if !errorlevel! neq 0 exit /b 1

set "VENV_DIR=%VDIR%"
set "VPY=%VDIR%\Scripts\python.exe"
exit /b 0

:IS_VENV_VALID
set "VDIR=%~1"
if not exist "%VDIR%\pyvenv.cfg" exit /b 1
if not exist "%VDIR%\Lib" exit /b 1
if not exist "%VDIR%\Scripts\python.exe" exit /b 1
"%VDIR%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,11) and sys.version_info[1]<14 else 1)" >nul 2>&1
exit /b %errorlevel%

:QUARANTINE_DIR
set "SRC=%~1"
set "DST=%~2"
if exist "%DST%" (
    rmdir /s /q "%DST%" 2>nul
    ping -n 2 127.0.0.1 >nul
)
ren "%SRC%" "%DST%" 2>nul
if exist "%SRC%" (
    powershell -NoProfile -Command "Rename-Item -LiteralPath '%SRC%' -NewName '%DST%' -ErrorAction SilentlyContinue" 2>nul
)
exit /b 0
