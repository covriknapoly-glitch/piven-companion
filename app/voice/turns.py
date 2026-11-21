"""Turn taking in a call: when the user starts and stops talking, and whether the voice heard over PIVEN's own speech is
the user's or PIVEN's echo from the speakers.

Sound is looked at in blocks of a tenth of a second. The pieces here only count loudness, so they are cheap and testable
without a microphone; the capture loop in the engine feeds them.
"""
from __future__ import annotations

import collections
import io
import time
import wave

BLOCK_SECONDS = 0.1
BLOCK_FRAMES = 1600  # a tenth of a second at 16 kHz


class TurnDetector:
    """Start of a phrase: two loud blocks in a row. End: `end_silence` seconds of quiet, or `max_seconds` of talking.

    "Loud" is measured against the room: the threshold rises over a steady background noise (a fan, the street) up to
    four times the user's own setting and never drops below it. The room's noise is the quietest block of the last four
    seconds: speech always has gaps between words, a fan does not.
    """

    def __init__(self, base_threshold, start_blocks=2, end_silence=0.7, max_seconds=20.0):
        self.base = float(base_threshold)
        self.start_blocks = start_blocks
        self.end_silence = end_silence
        self.max_seconds = max_seconds
        self.recent = collections.deque(maxlen=40)
        self.noise = None
        self.reset()

    def reset(self):
        self.in_speech = False
        self.voiced_run = 0
        self.quiet = 0.0
        self.length = 0.0

    def threshold(self):
        if self.noise is None:
            return self.base
        return max(self.base, min(self.noise * 2.5, self.base * 4))

    def voiced(self, rms):
        return rms >= self.threshold()

    def begin(self, blocks=1):
        """A phrase that started while another rule was listening (talking over PIVEN)."""
        self.in_speech, self.voiced_run, self.quiet, self.length = True, 0, 0.0, blocks * BLOCK_SECONDS

    def feed(self, rms):
        """One block. Returns "start" when a phrase begins, "end" when it is over, otherwise None."""
        self.recent.append(rms)
        self.noise = min(self.recent)
        voiced = self.voiced(rms)
        if not self.in_speech:
            self.voiced_run = self.voiced_run + 1 if voiced else 0
            if self.voiced_run >= self.start_blocks:
                self.begin(self.voiced_run)
                return "start"
            return None
        self.length += BLOCK_SECONDS
        self.quiet = 0.0 if voiced else self.quiet + BLOCK_SECONDS
        if self.quiet >= self.end_silence - 1e-9 or self.length >= self.max_seconds - 1e-9:
            self.reset()
            return "end"
        return None


class EchoGate:
    """Tells the user's voice from PIVEN's own voice coming back through the microphone.

    While PIVEN speaks, the gate knows how loud the played sound is at every moment and learns how much of it reaches the
    microphone (with headphones almost nothing, with loud speakers a lot). The user counts as talking only when the
    microphone is clearly louder than that echo.
    """

    LATENCY = 0.3  # the speakers and the microphone run up to 0.3 s behind the playback clock

    def __init__(self, ratio=1.5):
        self.ratio = ratio
        self.segments = collections.deque(maxlen=2000)  # (start, end, loudness) of what went to the speakers
        self.end = 0.0

    def playing(self, levels, started=None):
        """A whole phrase starting now, as loudness per tenth of a second."""
        self.stopped()
        moment = time.monotonic() if started is None else started
        for level in levels:
            self.segments.append((moment, moment + BLOCK_SECONDS, level))
            moment += BLOCK_SECONDS
        self.end = moment

    def add(self, seconds, level, now=None):
        """A slice handed to the speakers: it sounds right after what is already queued, or now if nothing is."""
        start = max(time.monotonic() if now is None else now, self.end)
        self.segments.append((start, start + seconds, level))
        self.end = start + seconds

    def stopped(self):
        self.segments.clear()
        self.end = 0.0

    def expected(self, now=None):
        """How loud PIVEN's own sound is around this moment (the loudest slice it could still be hearing)."""
        now = time.monotonic() if now is None else now
        low, high = now - self.LATENCY, now + BLOCK_SECONDS
        return max((level for start, end, level in self.segments if end > low and start < high), default=0.0)

    def is_user(self, rms, threshold, now=None):
        echo = self.ratio * self.expected(now)
        return rms >= threshold * 1.3 and rms > echo * 2.5 + threshold * 0.5

    def learn(self, rms, now=None):
        """A block that is not the user: whatever the microphone heard was the echo."""
        played = self.expected(now)
        if played < 0.005:
            return
        seen = min(3.0, max(0.02, rms / played))
        self.ratio = self.ratio * 0.9 + seen * 0.1


def levels(samples, rate, np):
    """Loudness of each tenth of a second of `samples` (mono floats)."""
    step = max(1, int(rate * BLOCK_SECONDS))
    count = len(samples) // step + (1 if len(samples) % step else 0)
    return [float(np.sqrt(np.mean(np.square(samples[i * step:(i + 1) * step])))) if len(samples[i * step:(i + 1) * step]) else 0.0
            for i in range(count)]


def read_wav(audio, np):
    """WAV bytes to (frames as float32 [n, channels], rate)."""
    with wave.open(io.BytesIO(audio), "rb") as source:
        channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
        raw = source.readframes(source.getnframes())
    if not channels or not rate or width not in (1, 2, 4):
        raise RuntimeError("Озвучка вернула WAV с неподдерживаемыми параметрами.")
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    else:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    return data.reshape(-1, channels), rate


def pcm_frames(data, channels, width, np):
    """Raw little-endian PCM bytes (whole frames) to float32 [n, channels]."""
    if width == 2:
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
    elif width == 4:
        samples = np.frombuffer(data, dtype="<i4").astype(np.float32) / 2147483648
    else:
        samples = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128) / 128
    return samples.reshape(-1, channels)


def to_wav(frames, rate, np):
    """float32 [n, channels] back to 16-bit WAV bytes (for playing through Windows when the speakers can't be opened directly)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(frames.shape[1]); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes((np.clip(frames, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


class Speaker:
    """One open output for a whole answer, so its pieces play back to back without gaps or clicks.
    Sound goes out a tenth of a second at a time: `cancel` stops it at once."""

    def __init__(self):
        self.player = None
        self.format = None

    def play(self, frames, rate, cancel):
        import soundcard as sc
        if self.format != (rate, frames.shape[1]):
            self.close()
            player = sc.default_speaker().player(samplerate=rate, channels=frames.shape[1])
            player.__enter__()
            self.player, self.format = player, (rate, frames.shape[1])
        step = max(1, rate // 10)
        for start in range(0, len(frames), step):
            if cancel.is_set():
                return False
            self.player.play(frames[start:start + step])
        return True

    def close(self):
        player, self.player, self.format = self.player, None, None
        if player is not None:
            player.__exit__(None, None, None)


def worth_answering(text):
    """A transcript with at least one real word: "да" and "нет" count, a lone "э" or a dot does not."""
    letters = [char for char in str(text) if char.isalpha()]
    return len(letters) >= 2
