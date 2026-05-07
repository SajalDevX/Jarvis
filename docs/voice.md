# Voice Mode

Jarvis can run as a voice assistant — speak to it, hear it reply. All existing capabilities (open apps, vision Q&A, OCR, window inspection) work identically; only the I/O channels change from terminal to mic + speakers.

## Quick start

```bash
# 1. System packages (one time)
sudo apt install portaudio19-dev libsndfile1 ffmpeg

# 2. Python deps
.venv/bin/pip install openai elevenlabs sounddevice numpy webrtcvad pynput openwakeword faster-whisper

# 3. API keys in .env
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM   # or your cloned voice

# 4. Run
.venv/bin/python main.py --voice both
```

## Modes

```bash
.venv/bin/python main.py --voice off       # text only (default)
.venv/bin/python main.py --voice hotkey    # press Ctrl+Space, talk, release
.venv/bin/python main.py --voice wake      # say "Hey Jarvis", talk
.venv/bin/python main.py --voice both      # both wake word + hotkey
```

Or set `JARVIS_VOICE_MODE` in `.env`.

## How a voice turn works

```
mic ─► VAD capture ─► Whisper STT ─► orchestrator ─► reply ─► ElevenLabs TTS ─► speakers
        (sounddevice)   (~500ms)      (cache→router    (text)   (streaming, ~400ms
        (silence cut     online        →agent, same as          first chunk)
         after 600ms)    Whisper-1)    text mode)
                         offline:
                         faster-whisper
```

Every existing tool — `smart_open_app`, `describe_screen`, `ocr_screen`, `active_window`, `find_ui_element`, `run_command`, etc. — runs unchanged. Only the input/output is voice.

## Latency targets

| Path | Speak-finish → first audible syllable |
|---|---|
| Cached intent ("open firefox" repeat) | ~1.5s |
| Pattern fast-path ("what app is open") | ~2s |
| Vision LLM ("what's on my screen") | ~4s |
| App open via `smart_open_app` | ~3.5s |
| Cold chat (router + chat_agent) | ~3s |
| **Offline** (faster-whisper + Piper) | 3-7s |

Breakdown for online turn:
- VAD silence cutoff: 600ms
- STT (Whisper API): ~500ms
- Pipeline: 500-2500ms
- TTS first chunk: ~400ms

## Voice-friendly replies

When in voice mode, Jarvis appends an addendum to every system prompt:
> Reply in 1–2 short natural sentences. No markdown, no parentheticals like "(PID 123)", no code, no lists.

This shapes the LLM output for spoken delivery — no awkward "PID 12345" being read aloud.

## Wake word

Uses [`openWakeWord`](https://github.com/dscripka/openWakeWord) — local, free, ~50MB model. Default keyword: `hey_jarvis_v0.1`. Custom wake words can be trained; set `JARVIS_WAKE_MODEL` to a different model name.

## Push-to-talk

Default: `Ctrl+Space`. Tap (not hold) to start a turn. Override via `JARVIS_HOTKEY` env (pynput format, e.g. `<ctrl>+<alt>+j`).

## Barge-in

Triggering a new turn (wake word or hotkey) while Jarvis is speaking calls `tts.request_stop()` which immediately ends the current playback so a new turn can start. (Best-effort — in-flight LLM/STT calls aren't cancelled mid-flight; only audio out.)

## Offline fallback

When `is_online()` returns False or API keys are missing, the system falls back automatically:

| Component | Online | Offline fallback |
|---|---|---|
| LLM | OpenRouter (tiered) | Ollama (`qwen3.5:4b`) |
| STT | OpenAI Whisper-1 | `faster-whisper` (tiny.en, CPU, int8) |
| TTS | ElevenLabs streaming | `piper` binary (`en_US-lessac-medium`) |

The first offline call lazy-loads `faster-whisper` (~30s download, then cached). Piper requires the binary in PATH — install from [rhasspy/piper](https://github.com/rhasspy/piper).

## Configuration reference

| Env var | Default | Purpose |
|---|---|---|
| `JARVIS_VOICE_MODE` | `off` | `off` / `hotkey` / `wake` / `both` |
| `JARVIS_HOTKEY` | `<ctrl>+<space>` | pynput hotkey string |
| `JARVIS_WAKE_MODEL` | `hey_jarvis_v0.1` | openWakeWord model name |
| `JARVIS_VOICE_LANG` | `en` | hint for Whisper |
| `JARVIS_VAD_SILENCE_MS` | `600` | silence to cut off recording |
| `OPENAI_API_KEY` | — | required for online STT |
| `ELEVENLABS_API_KEY` | — | required for online TTS |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | voice identity (Rachel) |
| `ELEVENLABS_MODEL` | `eleven_flash_v2_5` | streaming-fastest model |

## File layout

```
voice/
├── __init__.py
├── capture.py       # mic + webrtcvad → wav bytes
├── stt.py           # Whisper API → faster-whisper fallback
├── tts.py           # ElevenLabs streaming → Piper fallback (with barge-in)
├── hotkey.py        # pynput global hotkey
├── wake.py          # openWakeWord listener
└── runtime.py       # ties hotkey/wake → capture → STT → orchestrator → TTS
```

## Verification

```bash
# 1. Mic capture only
.venv/bin/python -c "from voice.capture import record_until_silence; print(len(record_until_silence()), 'wav bytes')"

# 2. STT only (provide a wav file)
.venv/bin/python -c "
from voice.capture import record_until_silence
from voice.stt import transcribe
print(transcribe(record_until_silence()))
"

# 3. TTS only
.venv/bin/python -c "from voice.tts import speak; speak('Hello, Jarvis online.')"

# 4. End-to-end
.venv/bin/python main.py --voice hotkey
# Press Ctrl+Space, say 'open firefox', release.
# Expected: Firefox launches AND Jarvis says 'Opened Firefox.' aloud.
```

## Troubleshooting

- **`OSError: PortAudio library not found`** — install system package: `sudo apt install portaudio19-dev`.
- **Hotkey doesn't fire** — pynput on X11 needs to read all input devices; some compositors block this. Try logging out/in or running as root once to test.
- **Whisper returns empty** — input clip may be too short or too quiet. Check `JARVIS_VAD_SILENCE_MS` (smaller = more aggressive cutoff).
- **TTS lags** — switch `ELEVENLABS_MODEL=eleven_flash_v2_5` (already default) — fastest streaming variant.
- **Barge-in cuts off too eagerly** — wake word can re-trigger from your own speakers if mic is omnidirectional. Use a directional mic or raise wake threshold in `voice/wake.py`.

## What's next

- **Streaming TTS during LLM generation** — start synthesizing the first sentence as soon as the LLM emits it, not after the full reply.
- **Multilingual** — Hindi via Sarvam STT/TTS.
- **Voice cloning** — clone user-preferred voice into ElevenLabs and set its ID.
- **Continuous mode** — no wake word between turns, just keep the conversation going.
