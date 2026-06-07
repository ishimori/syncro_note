@echo off
rem Double-click to stop the SynchroniNote local UI.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-ui.ps1" %*
pause
