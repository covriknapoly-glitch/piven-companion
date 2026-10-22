@echo off
rem Starts the web interface (modern-ui in a pywebview window).
cd /d "%~dp0"
if exist "runtime\Python311\pythonw.exe" (
  start "" "runtime\Python311\pythonw.exe" "web_companion.pyw"
) else (
  start "" pythonw "web_companion.pyw"
)
