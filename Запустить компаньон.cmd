@echo off
rem Starts the classic PIVEN Companion window (PySide6).
cd /d "%~dp0"
if exist "runtime\Python311\pythonw.exe" (
  start "" "runtime\Python311\pythonw.exe" "app\desktop_companion.pyw"
) else (
  start "" pythonw "app\desktop_companion.pyw"
)
