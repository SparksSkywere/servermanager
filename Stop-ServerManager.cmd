@echo off
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0/Scripts/kill-webserver.ps1'"
