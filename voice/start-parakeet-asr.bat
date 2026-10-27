@echo off
setlocal
cd /d "%~dp0nemo-speech"
set "NEMO_SPEECH_MODEL_DIR=%~dp0models"

powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { $m=Invoke-RestMethod -Uri 'http://127.0.0.1:8003/v1/models' -TimeoutSec 2; if ($m.data[0].id -match 'parakeet') { exit 0 } else { exit 2 } } catch { exit 1 }"
if errorlevel 2 (
    echo Another ASR model is already using port 8003. Close its console, then run this file again.
    pause
    exit /b 1
)
if not errorlevel 1 (
    echo Parakeet ASR is already running at http://127.0.0.1:8003
    pause
    exit /b 0
)

"%~dp0nemo-speech\bin\nemo-speech.exe" serve --host 127.0.0.1 --port 8003 --asr-model "%~dp0models\parakeet-tdt-0.6b-v3.q8_0.gguf" --device cuda --access-log
pause
