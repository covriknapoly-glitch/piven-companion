@echo off
setlocal
cd /d "%~dp0"

set "QWEN_HOST=127.0.0.1"
set "QWEN_PORT=8002"
set "HF_HOME=%~dp0models\hf"
set "PYTHONUTF8=1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8002/health' -ErrorAction SilentlyContinue; if ($r.StatusCode -eq 200 -and $r.Content -match 'qwen3-tts-12hz-1.7b') { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo Qwen3-TTS is already running at http://127.0.0.1:8002
    pause
    exit /b 0
)

"%~dp0..\kitten-tts-openwebui\.venv\Scripts\python.exe" -X utf8 -u "%~dp0server.py"
pause
