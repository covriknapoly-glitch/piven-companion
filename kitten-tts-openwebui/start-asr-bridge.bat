@echo off
setlocal
cd /d "%~dp0"
set "BRIDGE_URL=http://127.0.0.1:8004/health"
powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; try { $null = Invoke-RestMethod -Uri '%BRIDGE_URL%' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
    echo ASR audio bridge is already running at http://127.0.0.1:8004
    pause
    exit /b 0
)
"%~dp0.venv\Scripts\python.exe" "%~dp0asr-bridge.py"
pause
