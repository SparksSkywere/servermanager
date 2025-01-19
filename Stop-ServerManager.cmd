@echo off
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "& '%~dp0/Scripts/kill-webserver.ps1'"
