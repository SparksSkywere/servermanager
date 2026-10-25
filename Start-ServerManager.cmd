@echo off
setlocal
set "ROOT=%~dp0"
set "ServerManager__RootPath=%ROOT%runtime"
cd /d "%ROOT%"
if exist "%ROOT%artifacts\publish\win-x64\ServerManager.exe" (
  start "" "%ROOT%artifacts\publish\win-x64\ServerManager.exe"
) else (
  echo ServerManager.exe not found. Run build.ps1 first.
  exit /b 1
)
