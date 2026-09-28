@echo off
setlocal
title Stop OCR Engine

echo.
echo   Stopping the local OCR engine on port 17801...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-engine.ps1"

echo.
pause
exit /b 0
