from __future__ import annotations

import io
import os
import threading
import wave

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROLE = os.environ["VOICE_ROLE"]
ENGINE = os.environ["VOICE_ENGINE"]
MODEL = os.environ["VOICE_MODEL"]
LANGUAGE = os.getenv("VOICE_LANGUAGE", "ru")
SAMPLE = os.getenv("VOICE_SAMPLE", "")
SAMPLE_TEXT = os.getenv("VOICE_SAMPLE_TEXT", "")
LANGUAGE_NAMES = {"ru": "russian", "en": "english", "de": "german", "fr": "french", "es": "spanish", "it": "italian",
                  "pt": "portuguese", "ja": "japanese", "zh": "chinese", "ko": "korean", "uk": "ukrainian"}
LANGUAGE = {name: code for code, name in LANGUAGE_NAMES.items()}.get(LANGUAGE.lower(), LANGUAGE)

app = FastAPI(title="PIVEN voice model")


def _local(repo):
    if os.path.isdir(repo):
        return repo
    from huggingface_hub import snapshot_download
    return snapshot_download(repo, local_files_only=True)


def _device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


class Engine:
    rate = 24000

    def speak(self, text, voice, speed):
        raise HTTPException(status_code=404, detail="This model does not speak")

    def listen(self, audio, rate):
        raise HTTPException(status_code=404, detail="This model does not listen")


def _sample(voice):
    return SAMPLE if SAMPLE and os.path.isfile(SAMPLE) and voice in ("sample", "", "default") else None


class Transformers(Engine):
    def __init__(self):
        import torch
        from transformers import pipeline
        cuda = torch.cuda.is_available()
        task = "automatic-speech-recognition" if ROLE == "asr" else "text-to-speech"
        self.pipe = pipeline(task, model=_local(MODEL), device=0 if cuda else -1,
                             torch_dtype=torch.float16 if cuda and ROLE == "asr" else None)

    def listen(self, audio, rate):
        sample = {"raw": audio, "sampling_rate": rate}
        try:
            return self.pipe(sample, generate_kwargs={"language": LANGUAGE_NAMES.get(LANGUAGE, LANGUAGE), "task": "transcribe"})["text"]
        except Exception:
            return self.pipe(sample)["text"]

    def speak(self, text, voice, speed):
        result = self.pipe(text)
        self.rate = result["sampling_rate"]
        return result["audio"]


class Piper(Engine):
    def __init__(self):
        from piper import PiperVoice
        config = MODEL + ".json" if os.path.isfile(MODEL + ".json") else os.path.join(os.path.dirname(MODEL), "config.json")
        self.voice = PiperVoice.load(MODEL, config_path=config)

    def speak(self, text, voice, speed):
        from piper import SynthesisConfig
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            self.voice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig(length_scale=1.0 / speed))
        return output.getvalue()


class FasterWhisper(Engine):
    def __init__(self):
        from faster_whisper import WhisperModel
        path = _local(MODEL)
        try:
            self.model = WhisperModel(path, device="cuda", compute_type="float16")
            list(self.model.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])
        except Exception as error:
            print(f"faster-whisper: CUDA unavailable ({error}), using the processor", flush=True)
            self.model = WhisperModel(path, device="cpu", compute_type="int8")

    def listen(self, audio, rate):
        if rate != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)
        segments, _ = self.model.transcribe(audio, language=LANGUAGE[:2], beam_size=5, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments)


class QwenAsr(Engine):
    def __init__(self):
        import torch
        from qwen_asr import Qwen3ASRModel
        self.model = Qwen3ASRModel.from_pretrained(_local(MODEL), dtype=torch.bfloat16, device_map=f"{_device()}:0" if _device() == "cuda" else "cpu")

    def listen(self, audio, rate):
        result = self.model.transcribe((audio, rate), language=None)
        return result[0].text if result else ""


class Kokoro(Engine):
    def __init__(self):
        from kokoro import KModel
        path = _local(MODEL)
        config = os.path.join(path, "config.json")
        weights = next((os.path.join(path, name) for name in os.listdir(path) if name.endswith(".pth")), None)
        self.model = KModel(repo_id="hexgrad/Kokoro-82M", config=config if os.path.isfile(config) else None, model=weights).to(_device()).eval()
        self.voices = os.path.join(path, "voices")
        self.pipelines = {}

    def speak(self, text, voice, speed):
        from kokoro import KPipeline
        names = sorted(name[:-3] for name in os.listdir(self.voices) if name.endswith(".pt")) if os.path.isdir(self.voices) else []
        voice = voice if voice in names else ("af_heart" if "af_heart" in names else names[0])
        lang = voice[0]
        if lang not in self.pipelines:
            self.pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=False)
        pipeline = self.pipelines[lang]
        pack = pipeline.load_voice(os.path.join(self.voices, voice + ".pt"))
        parts = []
        for result in pipeline(text, voice=voice, speed=speed):
            if result.phonemes:
                audio = self.model(result.phonemes, pack[len(result.phonemes) - 1], speed)
                parts.append(audio.detach().cpu().numpy())
        return np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)


class Chatterbox(Engine):
    def __init__(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self.model = ChatterboxMultilingualTTS.from_local(_local(MODEL), _device())
        self.rate = self.model.sr

    def speak(self, text, voice, speed):
        audio = self.model.generate(text, language_id=LANGUAGE[:2], audio_prompt_path=_sample(voice))
        return audio.squeeze().detach().cpu().numpy()


class F5(Engine):
    EXAMPLE_TEXT = "Some call me nature, others call me mother nature."

    def __init__(self):
        from f5_tts.api import F5TTS
        import f5_tts
        path = _local(MODEL)
        found = [os.path.join(root, name) for root, _, names in os.walk(path) for name in names]
        weights = sorted((item for item in found if item.endswith(".safetensors")), key=lambda item: ("inference" not in item, item)) \
            or sorted(item for item in found if item.endswith(".pt"))
        vocab = next((item for item in found if os.path.basename(item) == "vocab.txt" and os.path.dirname(item) == os.path.dirname(weights[0])),
                     next((item for item in found if item.endswith("vocab.txt")), ""))
        kind = "F5TTS_v1_Base" if "v1" in weights[0] or "_v" in weights[0] else "F5TTS_Base"
        self.model = F5TTS(model="E2TTS_Base" if "e2" in MODEL.lower() else kind, ckpt_file=weights[0], vocab_file=vocab, device=_device())
        self.example = os.path.join(os.path.dirname(f5_tts.__file__), "infer", "examples", "basic", "basic_ref_en.wav")

    def speak(self, text, voice, speed):
        reference = _sample(voice) or self.example
        reference_text = SAMPLE_TEXT if reference == SAMPLE else self.EXAMPLE_TEXT
        audio, self.rate, _ = self.model.infer(reference, reference_text, text, speed=speed, show_info=lambda *args: None)
        return audio


class Coqui(Engine):
    def __init__(self):
        from TTS.api import TTS
        path = _local(MODEL)
        self.model = TTS(model_path=path, config_path=os.path.join(path, "config.json"), progress_bar=False, gpu=_device() == "cuda")
        self.rate = self.model.synthesizer.output_sample_rate

    def speak(self, text, voice, speed):
        kwargs = {}
        if getattr(self.model, "is_multi_lingual", False):
            kwargs["language"] = LANGUAGE[:2]
        sample = _sample(voice)
        speakers = list(getattr(self.model, "speakers", None) or [])
        if sample:
            kwargs["speaker_wav"] = sample
        elif speakers:
            kwargs["speaker"] = voice if voice in speakers else speakers[0]
        return np.asarray(self.model.tts(text, **kwargs), dtype=np.float32)


class VoxCPM(Engine):
    def __init__(self):
        from voxcpm import VoxCPM as Model
        self.model = Model.from_pretrained(_local(MODEL), load_denoiser=False, local_files_only=True)
        self.rate = self.model.tts_model.sample_rate

    def speak(self, text, voice, speed):
        sample = _sample(voice)
        return self.model.generate(text=text, prompt_wav_path=sample, prompt_text=SAMPLE_TEXT if sample else None)


class Parler(Engine):
    DESCRIPTION = ("A male speaker delivers a calm, friendly speech at a moderate speed and pitch. "
                   "The recording is of very high quality, with the voice clear and close up.")

    def __init__(self):
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer
        path = _local(MODEL)
        self.model = ParlerTTSForConditionalGeneration.from_pretrained(path).to(_device())
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        try:
            self.description_tokenizer = AutoTokenizer.from_pretrained(self.model.config.text_encoder._name_or_path, local_files_only=True)
        except Exception:
            self.description_tokenizer = self.tokenizer
        self.rate = self.model.config.sampling_rate

    def speak(self, text, voice, speed):
        description = self.description_tokenizer(self.DESCRIPTION if voice in ("", "default") else voice, return_tensors="pt").to(self.model.device)
        prompt = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        audio = self.model.generate(input_ids=description.input_ids, attention_mask=description.attention_mask,
                                    prompt_input_ids=prompt.input_ids, prompt_attention_mask=prompt.attention_mask)
        return audio.cpu().numpy().squeeze()


class OmniVoice(Engine):
    def __init__(self):
        import torch
        from omnivoice import OmniVoice as Model
        self.model = Model.from_pretrained(_local(MODEL), device_map=f"{_device()}:0" if _device() == "cuda" else "cpu", dtype=torch.float16)
        self.rate = getattr(self.model, "sampling_rate", None) or getattr(getattr(self.model, "config", None), "sampling_rate", 24000)

    def speak(self, text, voice, speed):
        sample = _sample(voice)
        audio = self.model.generate(text=text, language=LANGUAGE[:2], ref_audio=sample, ref_text=SAMPLE_TEXT if sample else None, speed=speed)
        return np.asarray(audio[0], dtype=np.float32).squeeze()


ENGINES = {"transformers": Transformers, "piper": Piper, "faster-whisper": FasterWhisper, "qwen-asr": QwenAsr, "kokoro": Kokoro,
           "chatterbox": Chatterbox, "f5-tts": F5, "coqui": Coqui, "voxcpm": VoxCPM, "parler": Parler, "omnivoice": OmniVoice}
MODEL_ENGINE = ENGINES[ENGINE]()


def _wav(audio, rate):
    if isinstance(audio, (bytes, bytearray)):
        return bytes(audio)
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    samples = np.clip(np.asarray(audio, dtype=np.float32).squeeze(), -1.0, 1.0)
    output = io.BytesIO()
    sf.write(output, samples, int(rate), format="WAV", subtype="PCM_16")
    return output.getvalue()


@app.get("/health")
def health():
    return {"status": "ok", "role": ROLE, "engine": ENGINE, "model": MODEL}


@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile = File(...), language: str = Form(""), response_format: str = Form("json")):
    data, rate = sf.read(io.BytesIO(await file.read()), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return {"text": str(MODEL_ENGINE.listen(data, rate) or "").strip()}


class SpeechRequest(BaseModel):
    input: str = Field(min_length=1, max_length=12000)
    voice: str = ""
    model: str = ""
    response_format: str = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest):
    try:
        audio = MODEL_ENGINE.speak(request.input, request.voice, request.speed)
        return Response(content=_wav(audio, MODEL_ENGINE.rate), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as error:
        if "CUDA error" in str(error):
            threading.Timer(0.5, os._exit, (1,)).start()
        raise HTTPException(status_code=500, detail=f"Speech generation failed: {error}") from error


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["VOICE_PORT"]))
