@echo off
echo Starting Server Manager...

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0

REM Launch the Python launcher script
python "%SCRIPT_DIR%scripts\launcher.py"

echo Server Manager started.
