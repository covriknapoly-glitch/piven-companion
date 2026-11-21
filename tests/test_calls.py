import io
import queue
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat import engine as core
from app.voice import turns


class TurnTaking(unittest.TestCase):
    def feed(self, detector, levels):
        return [detector.feed(level) for level in levels]

    def test_a_phrase_starts_on_two_loud_blocks_and_ends_after_a_short_pause(self):
        detector = turns.TurnDetector(0.02)
        events = self.feed(detector, [0.005] * 5 + [0.1, 0.1] + [0.1] * 10 + [0.005] * 7)
        self.assertEqual(events.index("start"), 6)
        self.assertEqual(events.index("end"), len(events) - 1)
        self.assertEqual(events.count("end"), 1)

    def test_a_click_is_not_a_phrase(self):
        detector = turns.TurnDetector(0.02)
        self.assertEqual(self.feed(detector, [0.005, 0.2, 0.005, 0.005]), [None] * 4)

    def test_a_short_breath_inside_a_phrase_does_not_end_it(self):
        detector = turns.TurnDetector(0.02)
        events = self.feed(detector, [0.1, 0.1] + [0.005] * 5 + [0.1] * 3)
        self.assertNotIn("end", events)

    def test_a_steady_noise_is_not_a_phrase_and_raises_the_bar_up_to_four_times(self):
        detector = turns.TurnDetector(0.01)
        self.assertEqual(self.feed(detector, [0.03] * 60), [None] * 60)  # a loud fan, louder than the user's setting
        self.assertAlmostEqual(detector.threshold(), 0.04, places=3)
        self.assertEqual(self.feed(detector, [0.08, 0.08]), [None, "start"])

    def test_gaps_between_words_keep_the_bar_low_while_talking(self):
        detector = turns.TurnDetector(0.02)
        events = self.feed(detector, [0.005] * 10 + [0.1, 0.1, 0.006, 0.1, 0.1] * 8)
        self.assertEqual(detector.threshold(), 0.02)
        self.assertEqual(events.count("start"), 1)
        self.assertNotIn("end", events)

    def test_a_very_long_phrase_is_cut_into_parts(self):
        detector = turns.TurnDetector(0.02, max_seconds=2.0)
        events = self.feed(detector, [0.1] * 25)
        self.assertEqual(events.count("end"), 1)


class EchoGate(unittest.TestCase):
    def test_the_echo_of_its_own_voice_is_not_the_user(self):
        gate = turns.EchoGate()
        gate.playing([0.1] * 100, started=0.0)
        for step in range(20):
            now = 0.5 + step * 0.1
            self.assertFalse(gate.is_user(0.1, 0.02, now))
            gate.learn(0.1, now)
        self.assertAlmostEqual(gate.ratio, 1.0, delta=0.1)
        self.assertTrue(gate.is_user(0.4, 0.02, 3.0))

    def test_with_headphones_a_normal_voice_interrupts(self):
        gate = turns.EchoGate()
        gate.playing([0.1] * 100, started=0.0)
        for step in range(40):
            gate.learn(0.002, 0.5 + step * 0.1)
        self.assertTrue(gate.is_user(0.03, 0.02, 5.0))

    def test_the_echo_is_expected_a_little_after_the_sound(self):
        gate = turns.EchoGate()
        gate.playing([0, 0, 0.2, 0, 0, 0, 0, 0], started=0.0)
        self.assertEqual(gate.expected(0.45), 0.2)
        self.assertEqual(gate.expected(0.65), 0)
        gate.stopped()
        self.assertEqual(gate.expected(0.45), 0)

    def test_short_answers_count_but_noise_does_not(self):
        self.assertTrue(turns.worth_answering("Да."))
        self.assertFalse(turns.worth_answering("э"))
        self.assertFalse(turns.worth_answering(" . "))


class StreamedEcho(unittest.TestCase):
    def test_slices_line_up_one_after_another(self):
        gate = turns.EchoGate()
        gate.add(0.08, 0.3, now=10.0)
        gate.add(0.08, 0.0, now=10.01)  # handed over early: it sounds after the first slice
        self.assertAlmostEqual(gate.end, 10.16)
        self.assertEqual(gate.expected(10.05), 0.3)
        self.assertEqual(gate.expected(10.5), 0.0)
        gate.add(0.08, 0.2, now=20.0)  # a slice long after the last one starts when it is handed over
        self.assertEqual(gate.expected(20.04), 0.2)


class SpeechRequests(unittest.TestCase):
    def test_cosyvoice_uses_saved_sample_and_matching_template(self):
        info = {"engine": "audiocpp", "family": "cosyvoice3", "title": "CosyVoice3"}
        voice = types.SimpleNamespace(settings={"tts_model": "cosyvoice", "voice": "default"})
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(core.install, "tts_model", return_value=info):
            with self.assertRaisesRegex(RuntimeError, "образец голоса"):
                core.CompanionCore._tts_request(voice, "Привет")
            sample = Path(folder) / "reference.wav"
            sample.touch()
            voice.settings.update(voice_sample=str(sample), voice_sample_text="Слова из образца")
            body = core.CompanionCore._tts_request(voice, "Привет")
            self.assertEqual(body["voice_ref"], str(sample))
            self.assertEqual(body["reference_text"], "Слова из образца")
            self.assertNotIn("options", body)
            voice.settings["voice_sample_text"] = ""
            body = core.CompanionCore._tts_request(voice, "Привет")
            self.assertEqual(body["options"], {"template_name": "cross_lingual"})

    def test_audio_server_error_prefers_model_message(self):
        error = urllib.error.HTTPError("http://localhost", 500, "Internal Server Error", {},
                                       io.BytesIO(b'{"error":{"message":"reference audio required"}}'))
        with mock.patch.object(core.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "^reference audio required$"):
                core._open_speech_response(object())


class StreamedSpeech(unittest.TestCase):
    """A fake voice server: a one-word WAV tells the format, then the speech comes as raw PCM in odd-sized pieces."""

    def setUp(self):
        import http.server
        import io
        import json
        import threading
        import wave
        self.frames = 1000
        pcm = bytes(range(256)) * (self.frames * 4 // 256) + bytes(self.frames * 4 % 256)

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if body.get("stream_format") == "audio":
                    self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.end_headers()
                    for start in range(0, len(pcm), 777):
                        self.wfile.write(pcm[start:start + 777]); self.wfile.flush()
                    return
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as out:
                    out.setnchannels(2); out.setsampwidth(2); out.setframerate(48000); out.writeframes(b"\0" * 400)
                self.send_response(200); self.send_header("Content-Type", "audio/wav"); self.end_headers()
                self.wfile.write(buffer.getvalue())

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        names = ("_synthesize_stream", "_tts_format", "_synthesize")
        Voice = type("Voice", (), {name: getattr(core.CompanionCore, name) for name in names})
        self.voice = Voice()
        self.voice.__dict__.update(_tts_streams=True, _tts_url=f"http://127.0.0.1:{self.server.server_address[1]}", _tts_key=("audiocpp", "x"),
                                   tts_cancel=threading.Event(), _active_tts_response=None, voice_used_at=0.0,
                                   _tts_request=lambda text: {"model": "m", "input": text})

    def tearDown(self):
        self.server.shutdown()

    def test_slices_are_whole_frames_and_add_up_to_the_phrase(self):
        slices = list(self.voice._synthesize_stream("Привет"))
        self.assertGreater(len(slices), 1)
        self.assertTrue(all(rate == 48000 and frames.shape[1] == 2 for frames, rate in slices))
        self.assertEqual(sum(len(frames) for frames, _ in slices), self.frames)

    def test_an_interruption_stops_the_stream(self):
        stream = self.voice._synthesize_stream("Привет")
        next(stream)
        self.voice.tts_cancel.set()
        with self.assertRaises(InterruptedError):
            list(stream)


class QuietStream(core.SpeechStream):
    def _run(self):
        pass


class FirstWords(unittest.TestCase):
    def pieces(self, stream):
        found = []
        while not stream.texts.empty():
            found.append(stream.texts.get())
        return [piece for piece in found if piece is not None]

    def test_in_a_call_the_first_piece_may_end_at_a_comma(self):
        stream = QuietStream(types.SimpleNamespace(), paragraphs=False)
        stream.feed("Ну смотри, сегодня в Москве солнечно и тепло, до двадцати градусов")
        self.assertEqual(self.pieces(stream), ["Ну смотри, сегодня в Москве солнечно и тепло,"])
        stream.feed("Ну смотри, сегодня в Москве солнечно и тепло, до двадцати градусов. А завтра дождь.", final=True)
        self.assertEqual(self.pieces(stream), ["до двадцати градусов. А завтра дождь."])

    def test_reading_aloud_keeps_whole_paragraphs(self):
        stream = QuietStream(types.SimpleNamespace(), paragraphs=True)
        stream.feed("Ну смотри, сегодня в Москве солнечно и тепло, до двадцати градусов")
        self.assertEqual(self.pieces(stream), [])


class ContinuedPhrase(unittest.TestCase):
    def test_the_second_half_joins_the_first(self):
        events = queue.Queue()
        state = types.SimpleNamespace(events=events, busy=False, running=False)
        core.CompanionCore.handle_transcript(state, ("микрофон", "завтра в Москве", "А какая погода"), "m")
        self.assertEqual(events.get_nowait(), ("user_merge", ("А какая погода", "А какая погода завтра в Москве")))

    def test_a_plain_phrase_is_a_new_message(self):
        events = queue.Queue()
        state = types.SimpleNamespace(events=events, busy=False, running=False)
        core.CompanionCore.handle_transcript(state, ("микрофон", "Да"), "m")
        self.assertEqual(events.get_nowait(), ("message", ("user", "Да", False)))


if __name__ == "__main__":
    unittest.main()
