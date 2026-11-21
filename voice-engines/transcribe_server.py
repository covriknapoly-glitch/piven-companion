from array import array
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import sys
import wave


class TranscribeHandler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok", "model": os.environ["VOICE_MODEL"]})
        else:
            self.reply(404, {"detail": "Unknown endpoint"})

    def read_audio(self):
        length = int(self.headers.get("Content-Length", "0"))
        content_type = self.headers.get("Content-Type", "")
        if not 0 < length <= 20 * 1024 * 1024 or not content_type.startswith("multipart/form-data;"):
            raise ValueError("Expected a multipart WAV upload")
        request = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii") + self.rfile.read(length)
        )
        for part in request.iter_parts():
            if part.get_param("name", header="Content-Disposition") == "file":
                with wave.open(io.BytesIO(part.get_payload(decode=True)), "rb") as wav:
                    if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                        raise ValueError("Expected a mono 16 kHz PCM16 WAV")
                    samples = array("h", wav.readframes(wav.getnframes()))
                return array("f", (sample / 32768 for sample in samples))
        raise ValueError("Missing WAV upload")

    def do_POST(self):
        if self.path != "/v1/audio/transcriptions":
            self.reply(404, {"detail": "Unknown endpoint"})
            return
        try:
            audio = self.read_audio()
        except (EOFError, ValueError, wave.Error) as error:
            self.reply(400, {"detail": str(error)})
            return
        result = self.server.session.run(audio)
        self.reply(200, {"text": result.text.strip()})


if __name__ == "__main__":
    sys.path.insert(0, os.environ["PIVEN_TRANSCRIBE_BINDINGS"])
    with os.add_dll_directory(os.path.dirname(os.environ["TRANSCRIBE_LIBRARY"])):
        from transcribe_cpp import Model

        with Model(os.environ["VOICE_MODEL"]) as model, model.session() as session:
            with HTTPServer(("127.0.0.1", int(os.environ["VOICE_PORT"])), TranscribeHandler) as server:
                server.session = session
                server.serve_forever()
