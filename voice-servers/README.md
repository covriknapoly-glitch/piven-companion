# voice-servers

Голосовые серверы PIVEN Companion. Программа запускает их сама, когда нужна озвучка или распознавание.

- `server.py` — озвучка Qwen3-TTS (VoiceDesign и CustomVoice), OpenAI-совместимый `/v1/audio/speech`. Работает в окружении `../voice/.venv`.
- `hf_voice_server.py` — общий сервер для остальных движков (Transformers, Piper, faster-whisper, Qwen3-ASR, Kokoro, Chatterbox, F5-TTS, XTTS, VoxCPM, Parler, OmniVoice). Движок и модель задаются переменными `VOICE_ENGINE`, `VOICE_MODEL`, `VOICE_ROLE`, `VOICE_PORT`.
- `start-qwen-tts.bat` — ручной запуск Qwen3-TTS.
- `models/hf` — кэш моделей Qwen3-TTS и Kokoro (в git не входит).
