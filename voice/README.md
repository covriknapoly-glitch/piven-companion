# voice

Голосовые движки PIVEN Companion. Ставятся и обновляются из настроек программы; в git лежат только скрипты.

- `.venv` — общее окружение: PyTorch, Transformers, Qwen3-TTS, Piper и другие пакеты, нужные многим движкам.
- `engines/<движок>/.venv` — окружение отдельного движка (faster-whisper, Kokoro, Chatterbox, F5-TTS, XTTS и др.). Общие пакеты подключаются файлом `piven_shared.pth` с относительным путём, поэтому папку программы можно переносить.
- `engines/audiocpp` — сервер audio.cpp и его модели.
- `nemo-speech` — NVIDIA NeMo-Speech для распознавания Parakeet и Nemotron.
- `models`, `hf-models` — скачанные модели распознавания и голосовые модели.

Скрипты: `asr-bridge.py` (перекодирует звук в WAV 16 кГц для NeMo-Speech), `start-parakeet-asr.bat`, `start-asr-bridge.bat` для ручного запуска.
