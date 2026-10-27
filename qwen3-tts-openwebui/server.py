"""OpenAI-compatible Qwen3-TTS 12Hz 1.7B server for Open WebUI."""

from __future__ import annotations

import io
import os
import subprocess
from functools import lru_cache

import imageio_ffmpeg
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

# The companion picks the model through these variables; VoiceDesign speaks with VOICE_INSTRUCTION,
# CustomVoice models with one of their built-in speakers (the request's `voice`).
MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
MODE = os.getenv("QWEN_MODE") or ("custom" if "CustomVoice" in MODEL_ID else "design")
MODEL_NAME = "qwen3-tts-12hz-1.7b"
VOICE_INSTRUCTION = (
    "A natural adult male voice, native Russian speaker, neutral standard Russian accent, "
    "warm medium-low pitch, clear conversational delivery, calm and friendly, "
    "slightly brisk conversational pacing with short natural pauses and clear intonation, not an announcer voice."
)

app = FastAPI(title="Qwen3-TTS 12Hz 1.7B for Open WebUI")


class SpeechRequest(BaseModel):
    model: str = MODEL_NAME
    input: str = Field(min_length=1, max_length=12000)
    voice: str = "Russian"
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@lru_cache(maxsize=1)
def get_model():
    from qwen_tts import Qwen3TTSModel

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; Qwen3-TTS requires the RTX GPU runtime")
    return Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "repo": MODEL_ID,
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    }


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]}


@app.get("/v1/audio/models")
def audio_models():
    return {"data": [{"id": MODEL_NAME, "name": "Qwen3-TTS 12Hz 1.7B"}]}


@app.get("/v1/audio/voices")
def voices():
    if MODE == "custom":
        return {"voices": sorted(get_model().model.get_supported_speakers())}
    return {"voices": ["Russian"]}


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest):
    if not request.input.strip():
        raise HTTPException(status_code=400, detail="input must not be blank")
    if request.response_format not in {"wav", "mp3"}:
        raise HTTPException(status_code=400, detail="Supported response_format: mp3 or wav")
    try:
        model = get_model()
        with torch.inference_mode():
            if MODE == "custom":
                speakers = sorted(model.model.get_supported_speakers())
                speaker = request.voice.lower() if request.voice.lower() in speakers else ("ryan" if "ryan" in speakers else speakers[0])
                wavs, sample_rate = model.generate_custom_voice(text=request.input, language="Russian", speaker=speaker)
            else:
                wavs, sample_rate = model.generate_voice_design(
                    text=request.input,
                    language="Russian",
                    instruct=VOICE_INSTRUCTION,
                )
        output = io.BytesIO()
        sf.write(output, wavs[0], sample_rate, format="WAV", subtype="PCM_16")
        wav = output.getvalue()
        if request.speed != 1.0:
            result = subprocess.run(
                [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                 "-i", "pipe:0", "-filter:a", f"atempo={request.speed}",
                 "-f", "wav", "pipe:1"],
                input=wav, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=120,
            )
            if result.returncode != 0 or not result.stdout:
                detail = result.stderr.decode(errors="replace")[-1200:]
                raise RuntimeError(f"WAV tempo adjustment failed: {detail}")
            wav = result.stdout
        if request.response_format == "wav":
            return Response(content=wav, media_type="audio/wav")

        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                "-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3", "pipe:1",
            ],
            input=wav,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
        if result.returncode != 0 or not result.stdout:
            detail = result.stderr.decode(errors="replace")[-1200:]
            raise RuntimeError(f"MP3 encoding failed: {detail}")
        return Response(content=result.stdout, media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Qwen TTS generation failed: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("QWEN_HOST", "127.0.0.1"),
        port=int(os.getenv("QWEN_PORT", "8002")),
    )
