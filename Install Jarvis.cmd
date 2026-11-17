@echo off
rem Sets Jarvis v5 up from this folder: Electron and a desktop shortcut.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
pause
