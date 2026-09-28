@echo off
setlocal
chcp 65001 >nul 2>nul
title OCR Engine - foreground

set "ROOT=%~dp0"
set "PY="
if exist "C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe" set "PY=C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe"
if not defined PY for %%P in (python.exe) do if exist "%%~$PATH:P" set "PY=%%~$PATH:P"
if not defined PY (
  echo.
  echo   [error] Python not found. Install Python 3.9 or later first.
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting local OCR engine (foreground, logs visible^)
echo   Listening on 127.0.0.1:17801
echo   Keep this window open. Press Ctrl+C to stop.
echo.

"%PY%" "%ROOT%driver.py" --port 17801
echo.
echo   Engine stopped.
pause
exit /b 0
