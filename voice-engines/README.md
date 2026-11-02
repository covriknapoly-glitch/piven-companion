# voice-engines

Голосовые движки. Программа ставит их из настроек и запускает сама; в git лежат только два сервера.

- `model_server.py` — сервер одной голосовой модели (Transformers, Piper, Kokoro, Chatterbox, F5-TTS, XTTS и др.).
- `qwen-tts/server.py` — озвучка Qwen3-TTS.
- `.venv`, `engines/` — окружения движков; `engines/audiocpp` — audio.cpp.
- `nemo-speech/` — распознавание Parakeet.
- `models/`, `hf-models/`, `qwen-tts/models/` — скачанные модели.
