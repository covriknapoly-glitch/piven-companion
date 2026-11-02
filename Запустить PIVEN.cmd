@echo off
cd /d "%~dp0"
if exist "runtime\Python311\pythonw.exe" (
  start "" "runtime\Python311\pythonw.exe" "app\window\main.pyw"
) else (
  start "" pythonw "app\window\main.pyw"
)
