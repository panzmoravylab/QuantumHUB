@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title Quantum HUD - Nastaveni

cd /d "%~dp0"

if /i not "%~1"=="RUN" (
    cmd /k "%~f0" RUN
    exit /b
)

echo.
echo  ============================================================
echo       QUANTUM HUD  -  Nastaveni prihlasovacich udaju
echo  ============================================================
echo.

call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

echo.
echo  Spoustim pruvodce nastavenim ...
echo.

"%VPY%" setup_env.py
if !errorlevel! neq 0 (
    echo.
    echo  [CHYBA] Pruvodce nastavenim selhal.
    goto :KONEC
)

echo.
echo  Nastaveni dokonceno.

:KONEC
echo.
pause
