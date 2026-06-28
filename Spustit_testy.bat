@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d "%~dp0"
call "_python_setup.bat"
if not "!PY_SETUP_OK!"=="1" goto :KONEC
"%VPY%" -m pytest tests/ -q
:KONEC
pause
