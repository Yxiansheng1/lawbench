@echo off
setlocal enabledelayedexpansion
title Retainer Workbench Launcher

set "ROOT=%~dp0"
set "DRIVER=%ROOT%tools\ocr-driver\driver.py"
set "PORT=17801"
set "CHECK=0"
if "%OCR_CHECK%"=="1" set "CHECK=1"
if /i "%~1"=="--check" set "CHECK=1"
if "%CHECK%"=="1" set "NOPAUSE=1"

echo.
echo   ============================================
echo     Retainer Workbench
echo     local OCR engine auto-start
echo   ============================================
echo.

rem ---- locate the workbench page without non-ASCII literals ----
set "PAGE="
for %%F in ("%ROOT%*.html") do if not defined PAGE set "PAGE=%%F"

rem ---- locate python ----
set "PYW="
set "PY="
if exist "C:\Users\0\AppData\Local\Programs\Python\Python312\pythonw.exe" set "PYW=C:\Users\0\AppData\Local\Programs\Python\Python312\pythonw.exe"
if exist "C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe" set "PY=C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe"
if not defined PYW for %%P in (pythonw.exe) do if exist "%%~$PATH:P" set "PYW=%%~$PATH:P"
if not defined PY for %%P in (python.exe) do if exist "%%~$PATH:P" set "PY=%%~$PATH:P"

if "%CHECK%"=="1" (
  echo   [check] page    = %PAGE%
  echo   [check] pythonw = %PYW%
  echo   [check] python  = %PY%
  echo   [check] driver  = %DRIVER%
)

if not exist "%DRIVER%" (
  echo   [warn] OCR driver not found; opening the page only.
  if "%CHECK%"=="1" exit /b 0
  goto openpage
)

rem ---- is the engine already listening? ----
set "ALIVE=0"
netstat -ano | findstr /C:":%PORT%" | findstr /C:"LISTENING" >nul 2>nul
if not errorlevel 1 set "ALIVE=1"
if "%CHECK%"=="1" echo   [check] port %PORT% listening = %ALIVE%

if "%ALIVE%"=="1" (
  echo   [ok] OCR engine is already running.
  if "%CHECK%"=="1" exit /b 0
  goto openpage
)

rem ---- start the engine ----
if "%CHECK%"=="1" (
  echo   [check] engine not running; would start it now.
  exit /b 0
)

if defined PYW (
  echo   Starting OCR engine in background...
  start "" "%PYW%" "%DRIVER%" --port %PORT%
) else (
  if defined PY (
    echo   Starting OCR engine ^(minimized window^)...
    start "OCR engine" /min "%PY%" "%DRIVER%" --port %PORT%
  ) else (
    echo   [warn] Python not found; OCR recognition is unavailable.
    echo          Other features are unaffected.
    if "%CHECK%"=="1" exit /b 0
    goto openpage
  )
)

echo   Waiting for the engine ^(up to about 20 seconds^)
set "ALIVE=0"
for /l %%I in (1,1,20) do (
  if "!ALIVE!"=="0" (
    netstat -ano | findstr /C:":%PORT%" | findstr /C:"LISTENING" >nul 2>nul
    if not errorlevel 1 set "ALIVE=1"
    if "!ALIVE!"=="0" (
      <nul set /p "=."
      ping -n 2 127.0.0.1 >nul
    )
  )
)
echo.

if "!ALIVE!"=="1" (
  echo   [ok] OCR engine is ready.
) else (
  echo   [warn] Engine is slow or failed to start.
  echo          The page still works and reconnects automatically.
)

if "%CHECK%"=="1" exit /b 0

:openpage
echo.
if defined PAGE (
  echo   Opening the workbench page...
  start "" "%PAGE%"
) else (
  echo   [warn] No .html page found next to this script.
)

echo.
echo   --------------------------------------------
echo    The engine keeps running in the background.
echo    You can close this window safely.
echo    To stop the engine, run:
echo      tools\ocr-driver\stop-engine.bat
echo   --------------------------------------------
echo.
pause
exit /b 0
