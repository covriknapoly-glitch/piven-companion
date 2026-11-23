import base64
import io
import json
import queue
import tempfile
import threading
import unittest
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from app.chat import engine
from app.models import integrations, media
from app.voice import turns

import numpy as np
from PIL import Image


class CloudMedia(unittest.TestCase):
    def setUp(self):
        png = io.BytesIO()
        Image.new("RGB", (2, 2)).save(png, "PNG")
        self.wav = turns.to_wav(np.zeros((160, 1)), 16000, np)
        self.requests = []
        replies = {
            "/v1/images/generations": json.dumps({"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]}).encode(),
            "/v1/audio/transcriptions": b'{"text":" hello "}',
            "/v1/audio/speech": self.wav,
        }
        received = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, self.headers, self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(replies[self.path])

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.connection = {"enabled": True, "key": "test-only", "url": f"http://127.0.0.1:{server.server_port}/v1"}
        config = mock.patch.object(integrations, "settings_of", return_value=self.connection)
        config.start()
        self.addCleanup(config.stop)
        self.app = engine.CompanionCore.__new__(engine.CompanionCore)
        self.app.settings = {"integrations_enabled": {"comfyui": False}}
        self.app.asr_process = self.app.tts_process = None
        self.app.tts_cancel = threading.Event()
        self.app.events = queue.Queue()
        self.app._chat_cancels = {}

    def test_image_is_attached_without_starting_comfyui(self):
        self.app.settings["image_media"] = {"provider": "openai", "model": "gpt-image-2"}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(engine, "DATA_DIR", Path(folder)):
            self.app.generate_image("Город")
            events = list(self.app.events.queue)
            self.assertEqual(events[-1], ("request_done", None))
            with Image.open(dict(events)["generated_image"]) as image:
                self.assertEqual(image.size, (2, 2))
        path, headers, body = self.requests[0]
        self.assertEqual(path, "/v1/images/generations")
        self.assertEqual(headers["Authorization"], "Bearer test-only")
        self.assertEqual(json.loads(body), {"model": "gpt-image-2", "prompt": "Город", "n": 1})

    def test_call_and_dictation_upload_a_mono_wav_with_the_selected_model(self):
        self.app.settings["asr_media"] = {"provider": "custom", "model": "my-asr"}
        self.assertIsNone(self.app._ensure_asr())
        self.assertEqual(self.app._recognize_phrase(np.zeros(160), np), "hello")
        path, headers, body = self.requests[0]
        self.assertEqual(path, "/v1/audio/transcriptions")
        form = BytesParser(policy=policy.default).parsebytes(
            f'Content-Type: {headers["Content-Type"]}\r\n\r\n'.encode() + body)
        fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in form.iter_parts()}
        self.assertEqual(fields, {"file": self.wav, "model": b"my-asr", "response_format": b"json"})

    def test_long_speech_plays_in_order_without_sending_a_local_voice_sample(self):
        self.app.settings.update(tts_media={"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "nova"},
                                 voice_sample="private.wav")
        self.app._ensure_tts()
        words = "a" * 4050 + " " + "b" * 300
        pieces = list(self.app._synthesize_stream(words))
        self.assertEqual([(len(frames), rate) for frames, rate in pieces], [(160, 16000)] * 2)
        for (path, _, body), phrase in zip(self.requests, words.split()):
            self.assertEqual(path, "/v1/audio/speech")
            self.assertEqual(json.loads(body), {"input": phrase, "model": "gpt-4o-mini-tts", "voice": "nova", "response_format": "wav"})

    def test_disabled_service_never_sends_audio(self):
        self.connection["enabled"] = False
        with self.assertRaisesRegex(ValueError, "Интеграции"):
            media.transcribe({"provider": "custom", "model": "asr"}, self.wav)
        self.assertEqual(self.requests, [])
