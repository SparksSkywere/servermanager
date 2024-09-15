@echo off
@cd /d "%~dp0"
mode con: cols=60 lines=8
color 02
powershell "PATH.ps1"