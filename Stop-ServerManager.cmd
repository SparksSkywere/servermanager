@echo off
echo Stopping Server Manager...

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0

REM Run the stop script
python "%SCRIPT_DIR%scripts\stop_servermanager.py"

echo Server Manager stopped.
