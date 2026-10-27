"""OpenAI multipart STT bridge: arbitrary audio -> PCM16 WAV -> NeMo-Speech."""

from __future__ import annotations

import asyncio
import os
import tempfile
import subprocess
from pathlib import Path

import imageio_ffmpeg
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

NEMO_URL = os.getenv("NEMO_URL", "http://127.0.0.1:8003")
DEFAULT_LANGUAGE = os.getenv("ASR_LANGUAGE", "ru-RU")
AUDIO_FILTER = os.getenv("ASR_AUDIO_FILTER", "dynaudnorm=f=500:g=10:p=0.95")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
app = FastAPI(title="Nemotron OpenAI STT bridge")


@app.get("/health")
async def health():
    return {"status": "ok", "upstream": NEMO_URL}


@app.get("/v1/models")
async def models():
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        upstream = await client.get(f"{NEMO_URL}/v1/models")
        upstream.raise_for_status()
        return upstream.json()


@app.post("/v1/audio/transcriptions")
async def transcribe(request: Request):
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="multipart field 'file' is required")
        source = await upload.read()
        if not source:
            raise HTTPException(status_code=400, detail="uploaded audio is empty")

        with tempfile.TemporaryDirectory(prefix="nemotron-audio-") as temp_dir:
            wav_path = Path(temp_dir) / "converted.wav"
            ffmpeg_args = [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            ]
            if AUDIO_FILTER:
                ffmpeg_args.extend(["-af", AUDIO_FILTER])
            ffmpeg_args.extend(["-y", str(wav_path)])
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate(source)
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=f"audio decode failed: {err.decode(errors='replace')[-1200:]}")
            wav = wav_path.read_bytes()

        fields = {k: str(v) for k, v in form.multi_items() if k != "file" and not hasattr(v, "read")}
        # Open WebUI's OpenAI STT client does not send a language field. NeMo defaults
        # this multilingual model to en-US, so use Russian unless explicitly overridden.
        fields.setdefault("language", DEFAULT_LANGUAGE)
        fields["file"] = ("audio.wav", wav, "audio/wav")
        # Windows environments may define an HTTP proxy; loopback ASR calls must bypass it.
        async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
            upstream = await client.post(f"{NEMO_URL}/v1/audio/transcriptions", data={k: v for k, v in fields.items() if k != "file"}, files={"file": fields["file"]})
        return Response(content=upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type", "application/json"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ASR bridge failed: {exc}") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8004)
