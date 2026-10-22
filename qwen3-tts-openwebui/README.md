# Qwen3-TTS 12Hz 1.7B for Open WebUI

This local OpenAI-compatible TTS service uses Qwen3-TTS 12Hz 1.7B VoiceDesign on CUDA with a Russian native-speaker voice description.

## Start

Run `start-qwen-tts.bat`. The first synthesis downloads and initializes the model; weights are cached under `models\hf`.

## Open WebUI

- Engine: OpenAI
- Base URL: `http://127.0.0.1:8002/v1`
- Model: `qwen3-tts-12hz-1.7b`
- Voice: `Russian`
- Response splitting: Paragraphs

The service is local and exposes `/v1/audio/speech`, `/v1/models`, `/v1/audio/models`, `/v1/audio/voices`, and `/health`.
