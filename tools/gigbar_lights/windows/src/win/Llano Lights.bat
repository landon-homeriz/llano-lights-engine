@echo off
rem Opens the Llano Lights window. "Llano Lights.bat menu" gives the old text menu.
cd /d "%~dp0app"
if "%~1"=="" (
    start "" "%~dp0runtime\pythonw.exe" gigbar_app.py
    exit /b 0
)
title Llano Lights
"%~dp0runtime\python.exe" gigbar_app.py %*
if errorlevel 1 pause
