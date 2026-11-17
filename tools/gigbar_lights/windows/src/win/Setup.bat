@echo off
title Llano Lights setup
rem Runs setup.ps1, which does the work and ends on an "installed" or "did not finish" box.
rem Any non-zero exit is a failure: PowerShell's own errors (setup.ps1 not found, blocked) come
rem back negative, which "if errorlevel 1" misses, so 1.2.1 could say "finished" after doing nothing.
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%~dp0setup.ps1" goto notunzipped
if not exist "%~dp0runtime\pythonw.exe" goto notunzipped
if not exist "%PS%" (
    color 4F
    echo.
    echo  SETUP DID NOT RUN: Windows PowerShell is missing at %PS%
    echo.
    pause
    exit /b 1
)
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "RC=%errorlevel%"
if "%RC%"=="0" goto ok
if "%RC%"=="3" goto installednotopen
color 4F
echo.
echo  ==============================================================
echo   SETUP DID NOT FINISH (code %RC%). The lines above say why.
echo   Setup's record: %LOCALAPPDATA%\Llano Lights\setup.log
echo  ==============================================================
echo.
pause
exit /b 1

:installednotopen
color 6F
echo.
echo  Llano Lights is installed, but it didn't open. Try the Start menu.
echo.
pause
exit /b 3

:ok
color 2F
echo.
echo  ==============================================================
echo   INSTALLED. Open Llano Lights from the Start menu or desktop.
echo  ==============================================================
echo.
pause
exit /b 0

:notunzipped
color 4F
echo.
echo  SETUP CAN'T RUN FROM HERE.
echo  It was opened from inside the zip, or from a folder missing its files.
echo  Right-click Llano-Lights-*.zip, choose Extract All, open the new
echo  Llano-Lights folder and double-click Setup.bat there.
echo.
pause
exit /b 1
