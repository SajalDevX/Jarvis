"""Text-to-speech. ElevenLabs streaming (online) → Piper (offline)."""
from __future__ import annotations

import io
import shutil
import subprocess
import threading
import wave

import numpy as np
import sounddevice as sd

from logger import log


# Stop event to support barge-in. Set externally to interrupt playback.
_stop_event = threading.Event()


def reset_stop():
    _stop_event.clear()


def request_stop():
    _stop_event.set()


def speak(text: str):
    """Synthesize and play. Returns when audio finishes (or stop_event fires)."""
    if not text or not text.strip():
        return

    reset_stop()
    from config import ELEVENLABS_API_KEY
    from llm.client import is_online

    if is_online() and ELEVENLABS_API_KEY:
        try:
            _eleven_stream(text)
            return
        except Exception as e:
            log.warning(f"ElevenLabs failed: {e} — trying local")

    _piper_speak(text)


def _eleven_stream(text: str):
    """Stream MP3 → decode on the fly → play to speakers chunk-by-chunk."""
    from elevenlabs.client import ElevenLabs
    from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    # Use PCM output — direct play, no decode step. 22050 mono is supported.
    audio_iter = client.text_to_speech.stream(
        voice_id=ELEVENLABS_VOICE_ID,
        text=text,
        model_id=ELEVENLABS_MODEL,
        output_format="pcm_22050",
    )

    sample_rate = 22050
    log.info(f"ElevenLabs streaming: {text[:60]!r}")

    with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as out:
        for chunk in audio_iter:
            if _stop_event.is_set():
                log.info("TTS interrupted")
                break
            if chunk:
                out.write(chunk)


def _piper_speak(text: str):
    """Local Piper synth → WAV → play."""
    if not shutil.which("piper"):
        log.error("Piper binary not in PATH. Install: https://github.com/rhasspy/piper")
        return

    log.info(f"Piper synth: {text[:60]!r}")
    proc = subprocess.run(
        ["piper", "--model", "en_US-lessac-medium", "--output-raw"],
        input=text.encode(),
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        log.error(f"Piper failed: {proc.stderr.decode()[:200]}")
        return

    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    sd.play(pcm, samplerate=22050)
    sd.wait()
