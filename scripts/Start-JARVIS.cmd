@echo off
rem Starts Jarvis from source with stock Electron; the backend is WebAssembly.
cd /d "%~dp0.."
if not exist "desktop\node_modules\electron\dist\electron.exe" (
  echo Electron fehlt. Bitte zuerst scripts\install.ps1 ausfuehren.
  pause
  exit /b 1
)
start "" "desktop\node_modules\electron\dist\electron.exe" "%~dp0..\desktop"
