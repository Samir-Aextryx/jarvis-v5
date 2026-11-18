@echo off
rem Sets Jarvis v5 up from this folder (Electron and a desktop shortcut) and starts it.
cd /d "%~dp0"
set "JARVIS_SETUP=%~dp0app\scripts\install.ps1"
if not exist "%JARVIS_SETUP%" set "JARVIS_SETUP=%~dp0scripts\install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_SETUP%" -Start
if errorlevel 1 (
  echo.
  echo Die Einrichtung ist fehlgeschlagen. Die Meldung oben nennt den Grund.
  pause
  exit /b 1
)
timeout /t 5 >nul
