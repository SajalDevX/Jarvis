"""Mic capture with VAD-based silence cutoff. Returns a 16-bit mono WAV bytes object."""
from __future__ import annotations

import io
import wave
import collections

import numpy as np
import sounddevice as sd
import webrtcvad

from logger import log

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 @ 16k


def record_until_silence(
    silence_ms: int = 600,
    max_seconds: int = 20,
    vad_aggressiveness: int = 2,
) -> bytes:
    """Block until user speaks then stops.

    Returns a WAV bytes object (16-bit PCM mono @ 16kHz).
    Trims leading silence; cuts off after `silence_ms` of silence after speech began.
    """
    vad = webrtcvad.Vad(vad_aggressiveness)
    silence_frames_needed = silence_ms // FRAME_MS
    max_frames = (max_seconds * 1000) // FRAME_MS

    pre_buffer: collections.deque[np.ndarray] = collections.deque(maxlen=10)
    voiced: list[np.ndarray] = []
    triggered = False
    silence_streak = 0
    total_frames = 0

    log.info("Listening...")

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=FRAME_SAMPLES,
    ) as stream:
        while total_frames < max_frames:
            frame, _ = stream.read(FRAME_SAMPLES)
            frame = frame.flatten()
            is_speech = vad.is_speech(frame.tobytes(), SAMPLE_RATE)

            if not triggered:
                pre_buffer.append(frame)
                if is_speech:
                    triggered = True
                    voiced.extend(pre_buffer)
                    log.debug("VAD triggered (speech started)")
            else:
                voiced.append(frame)
                if is_speech:
                    silence_streak = 0
                else:
                    silence_streak += 1
                    if silence_streak >= silence_frames_needed:
                        log.debug(f"VAD ended (silence {silence_ms}ms)")
                        break
            total_frames += 1

    if not voiced:
        log.warning("No speech detected")
        return b""

    pcm = np.concatenate(voiced).astype(np.int16).tobytes()
    return _to_wav_bytes(pcm)


def _to_wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()
