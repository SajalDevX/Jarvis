"""Speech-to-text. OpenAI Whisper API (online) → faster-whisper (offline)."""
from __future__ import annotations

import io

from logger import log

_FW_MODEL = None  # lazy-loaded faster-whisper instance


def transcribe(wav_bytes: bytes, language: str | None = None) -> str:
    """Try cloud Whisper first, fall back to local faster-whisper."""
    if not wav_bytes:
        return ""

    from config import OPENAI_API_KEY
    from llm.client import is_online

    if is_online() and OPENAI_API_KEY:
        try:
            return _whisper_api(wav_bytes, language)
        except Exception as e:
            log.warning(f"Whisper API failed: {e} — trying local")

    return _whisper_local(wav_bytes, language)


def _whisper_api(wav_bytes: bytes, language: str | None) -> str:
    from openai import OpenAI
    from config import OPENAI_API_KEY

    client = OpenAI(api_key=OPENAI_API_KEY)
    fp = io.BytesIO(wav_bytes)
    fp.name = "audio.wav"

    kwargs = {"model": "whisper-1", "file": fp}
    if language:
        kwargs["language"] = language

    resp = client.audio.transcriptions.create(**kwargs)
    text = resp.text.strip()
    log.info(f"STT (whisper-1): {text!r}")
    return text


def _whisper_local(wav_bytes: bytes, language: str | None) -> str:
    global _FW_MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.error("faster-whisper not installed — pip install faster-whisper")
        return ""

    if _FW_MODEL is None:
        log.info("Loading faster-whisper tiny.en (first use)...")
        _FW_MODEL = WhisperModel("tiny.en", device="cpu", compute_type="int8")

    fp = io.BytesIO(wav_bytes)
    segments, _ = _FW_MODEL.transcribe(fp, language=language or "en")
    text = " ".join(s.text for s in segments).strip()
    log.info(f"STT (local): {text!r}")
    return text
