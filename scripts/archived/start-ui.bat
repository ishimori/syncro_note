@echo off
rem Double-click to start the SynchroniNote local UI.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-ui.ps1" %*
pause
