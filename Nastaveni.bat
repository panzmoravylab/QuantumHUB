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
echo       QUANTUM HUD  -  Setup / Nastaveni
echo  ============================================================
echo.
echo  Language / Jazyk: [C] Czech  [E] English
choice /C CE /M "Select language / Vyberte jazyk"
if errorlevel 2 (
    set "HUD_UI_LANG=EN"
    set "HUD_LANG=EN"
    title Quantum HUD - Settings
) else (
    set "HUD_UI_LANG=CZ"
    set "HUD_LANG=CZ"
    title Quantum HUD - Nastaveni
)

call "%~dp0_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC

echo.
if "!HUD_LANG!"=="EN" (
    echo  Starting setup wizard ...
) else (
    echo  Spoustim pruvodce nastavenim ...
)
echo.

"%VPY%" setup_env.py
if !errorlevel! neq 0 (
    if "!HUD_LANG!"=="EN" (echo  [ERROR] Setup wizard failed.) else (echo  [CHYBA] Pruvodce selhal.)
    goto :KONEC
)

echo.
if "!HUD_LANG!"=="EN" (echo  Setup complete.) else (echo  Nastaveni dokonceno.)

:KONEC
echo.
pause
