# Local voice setup for Open WebUI

## Kitten TTS

Start `start-kitten-tts.bat`. It serves local speech synthesis at `http://127.0.0.1:8002`.

## Nemotron 3.5 ASR

Start `start-parakeet-asr.bat` and `start-asr-bridge.bat`. Parakeet serves recognition at `http://127.0.0.1:8003`; the bridge listens on `http://127.0.0.1:8004` and converts Open WebUI audio chunks to mono 16 kHz PCM WAV before forwarding them. This is needed because NeMo-Speech accepts uncompressed WAV uploads, while browser voice chunks may use another audio format. The setup uses NVIDIA NeMo-Speech 0.2.0 and NVIDIA's Parakeet TDT 0.6B v3 Q8_0 model. The bundled Windows CUDA runtime was checked on an RTX 5070. Model files are stored under `models/`.

The bridge dependencies are installed in `.venv` (`imageio-ffmpeg` and `python-multipart`). To restore them, run `\.venv\Scripts\python.exe -m pip install imageio-ffmpeg python-multipart` from this folder.

Parakeet automatically detects Russian and other supported languages. Nemotron is still available via `start-nemotron-asr.bat`; when using that model, the bridge defaults to Russian (`ru-RU`). For another language, set `ASR_LANGUAGE` before starting the bridge (for example `set ASR_LANGUAGE=en-US`).

The bridge applies gentle dynamic volume normalization (`dynaudnorm`) to help with quiet speech. Set `ASR_AUDIO_FILTER=` before starting it to disable the filter if it makes the microphone noise more noticeable.

Open WebUI **Settings → Admin → Audio → Speech-to-Text**:

- Engine: OpenAI
- API Base URL: `http://127.0.0.1:8004/v1`
- API Key: `local-nemotron` (placeholder; local service does not require a key)
- Request Format: Multipart Upload
- Model: `parakeet-tdt-0.6b-v3`

Keep both ASR services running. In Open WebUI, use **Voice mode** for spoken turns; it transcribes your utterance and reads the selected chat model's reply with Kitten TTS. The realtime ASR WebSocket endpoint is available separately at `/v1/audio/transcriptions/realtime`; Open WebUI's OpenAI STT setting sends audio uploads to `/v1/audio/transcriptions`, which the bridge converts for Nemotron.

## Kitten settings

Open WebUI **Settings → Admin → Audio → Text-to-Speech**:

- Engine: OpenAI
- API Base URL: `http://127.0.0.1:8002/v1`
- API Key: `local-kitten-tts` (placeholder)
- Voice: Bruno
- Model: `kitten-tts-2`
