# voice-engines

Голосовые движки. Программа устанавливает и запускает их из настроек.

- `model_server.py` — сервер одной голосовой модели (Transformers, Piper, Kokoro, Chatterbox, F5-TTS, XTTS и др.).
- `transcribe_server.py` — распознавание речи через transcribe.cpp. Библиотека и Python-обвязка скачиваются в `engines/transcribe/`.
- `qwen-tts/server.py` — озвучка Qwen3-TTS.
- `.venv`, `engines/` — окружения движков; `engines/audiocpp` — audio.cpp.
- `nemo-speech/` — распознавание Parakeet.
- `models/`, `hf-models/`, `qwen-tts/models/` — скачанные модели.
