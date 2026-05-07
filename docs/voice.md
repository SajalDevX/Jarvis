# Voice Mode

Jarvis runs as a voice assistant — speak to it, hear it reply in Tony Stark's-Jarvis style. All existing capabilities (open apps, vision Q&A, OCR, window inspection, system tools) work identically; only the I/O channels change.

There are **two voice runtimes**, picked automatically:

| Runtime | When | Latency target |
|---|---|---|
| **Pipecat** (Phase 4) | online + `GROQ_API_KEY` + `ELEVENLABS_API_KEY` | **600-900ms** speak-end → first syllable |
| **Legacy** (Phase 3) | offline OR keys missing | 3-7s |

## Quick start

```bash
# 1. System packages (one time)
sudo apt install portaudio19-dev libsndfile1 ffmpeg

# 2. Python deps
.venv/bin/pip install -r requirements.txt

# 3. API keys in .env
OPENROUTER_API_KEY=sk-or-v1-...      # Vision + tool-using LLM (Gemini)
GROQ_API_KEY=gsk_...                 # Free tier, sub-300ms TTFT for chat/router
OPENAI_API_KEY=sk-proj-...           # Legacy STT fallback (offline path)
ELEVENLABS_API_KEY=sk_...            # Streaming TTS
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM    # Rachel (or your cloned voice)
ELEVENLABS_MODEL=eleven_turbo_v2_5          # Fastest WS streaming-input variant

# 4. Run
.venv/bin/python main.py --voice hotkey
```

Console boots silently and prints **`Voice runtime: pipecat (Groq STT + Groq LLM + ElevenLabs WS TTS)`** when the fast path is active. After "Listening…" just speak — Pipecat's Smart Turn v3 endpoints semantically (no fixed silence wait).

Set `JARVIS_DEBUG=1` to surface Pipecat / ALSA / loguru chatter when troubleshooting.

## Modes

```bash
.venv/bin/python main.py --voice off       # text only (default)
.venv/bin/python main.py --voice hotkey    # legacy: tap Ctrl+Space; Pipecat: ignored, always-on VAD
.venv/bin/python main.py --voice wake      # legacy: "Hey Jarvis"
.venv/bin/python main.py --voice both
```

(In the Pipecat runtime, the `--voice` value just enables voice mode; the actual gating is done by Smart Turn v3 + Silero VAD — no need to press anything.)

## Pipecat pipeline (the fast path)

```
mic ─► Silero VAD ─► Smart Turn v3 ─► Groq Whisper-large-v3-turbo ─► user aggregator
       (~10ms)       (semantic         (batch, ~250ms)
                      end-of-turn,
                      ~65ms inference)
                                                                       │
                                                                       ▼
                                                         JarvisLLMService
                                                          (custom Pipecat service)
                                                          ├─ Cache check (instant)
                                                          ├─ Direct dispatch:
                                                          │   "open <app>" / "launch <app>"
                                                          │   → smart_open_app, no LLM
                                                          ├─ Quick-classify regex
                                                          ├─ Router LLM (text-only → Groq)
                                                          └─ Agent LLM (with tools → OpenRouter Gemini)
                                                                       │
                                                                       ▼
                                  ElevenLabs Turbo v2 (WebSocket streaming-input) ─► speakers
                                  (~250ms TTFA, accepts LLM tokens as they stream)
```

`JarvisLLMService` runs the existing `Orchestrator` synchronously in `asyncio.to_thread`, sentence-splits the reply, and pushes `LLMTextFrame` chunks so ElevenLabs starts synthesising before the whole reply is ready.

### Provider rationale

| Layer | Provider | Why |
|---|---|---|
| STT | **Groq Whisper-large-v3-turbo** | Free with Groq key, ~250ms batch — faster than network round-trip with OpenAI. |
| Router/Chat LLM (no tools) | **Groq Llama 3.1 8B Instant** | LPU, ~250ms TTFT, ~750 tok/s. |
| Agent LLM (with tools) | **OpenRouter Gemini 2.5 Flash Lite** | Llama 3.1 8B hallucinates tool replies; Gemini is reliable for function calls. |
| Vision LLM | **OpenRouter Gemini 2.5 Flash Lite** | Multimodal; Llama 8B is text-only. |
| TTS | **ElevenLabs Turbo v2.5** WebSocket | Streaming-input — pipes LLM tokens in as they arrive. |
| Endpoint detection | **Pipecat Smart Turn v3 (local ONNX)** | ~65ms semantic+acoustic; no fixed silence wait. |

The dispatch logic in `llm/client.py` routes per-call: text-only → Groq; tools or images → OpenRouter.

## Direct dispatch (zero-LLM path)

`agents/orchestrator.py::_try_direct_dispatch` matches `open|launch|start|run <app>` (with leading "can you" / "could you please" / etc., trailing politeness, STT artifacts like "amen", "now", "thanks", "bro" stripped). On match it calls `smart_open_app` directly and returns a canned, voice-friendly reply: `"<app> is open, sir."`

Bypasses both router AND agent LLMs. Benchmark: **~1ms total** vs ~3-5s on the LLM path. Falls through to the LLM path only when the tool returns ambiguity / not-found.

## Voice persona

`agents.base.Agent.VOICE_ADDENDUM` is appended to every system prompt when `voice=True` is passed (orchestrator does this on every voice turn):

> You are Jarvis — Tony Stark's AI butler from Iron Man. Speak like that: dry, polite, concise, lightly British. Address the user as "sir" occasionally. Reply in 1-2 short natural sentences. No markdown, no parentheticals like "(PID 123)", no code, no lists. When describing the screen, never say "the screenshot shows" — say what's on screen directly.

Vision tool's prompt to the multimodal LLM in `tools/vision.py::DescribeScreenTool.execute` carries the same persona, so screen descriptions sound like "You have VS Code open, sir, with a Python file." not "The screenshot shows a terminal window."

## Latency targets (Phase 4 / Pipecat path)

| Path | Speak-finish → first audible syllable |
|---|---|
| Direct dispatch ("open firefox") | **~600ms** |
| Cached chat reply | **~700ms** |
| New chat (router skipped) | **~900ms** |
| App open via Gemini tool call | **~1100ms** |
| Vision query (`describe_screen`) | **~1400ms** |
| **Legacy fallback** (Whisper-1 + Gemini + ElevenLabs HTTP) | 3-7s |

Breakdown for online turn (Pipecat path):
- Smart Turn v3 endpoint: ~100ms
- STT (Groq Whisper turbo): ~250ms
- Pipeline: 500-2500ms
- TTS first chunk: ~400ms

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
| `ELEVENLABS_MODEL` | `eleven_turbo_v2_5` | streaming-fastest model (Phase 4) |
| `GROQ_API_KEY` | — | enables Pipecat fast-path (STT + chat/router LLM) |
| `GROQ_LLM_MODEL` | `llama-3.1-8b-instant` | text-only / no-tool turns |
| `GROQ_STT_MODEL` | `whisper-large-v3-turbo` | Pipecat STT model |
| `JARVIS_DEBUG` | _unset_ | when `1`, surfaces Pipecat / loguru / ALSA stderr |

## File layout

```
voice/
├── __init__.py
├── capture.py              # legacy: mic + webrtcvad → wav bytes
├── stt.py                  # legacy: Whisper API → faster-whisper fallback
├── tts.py                  # legacy: ElevenLabs HTTP stream → Piper fallback
├── hotkey.py               # legacy: pynput global hotkey
├── wake.py                 # legacy: openWakeWord listener
├── runtime.py              # legacy: capture → STT → orchestrator → TTS
├── pipecat_runtime.py      # Phase 4: Pipecat pipeline + fd-level stderr silencer
└── services/
    └── jarvis_llm.py       # Phase 4: Pipecat LLMService wrapping Orchestrator
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
- **Pipecat path not activated** — banner shows `legacy` (yellow) instead of `pipecat` (green). Check `GROQ_API_KEY` and `ELEVENLABS_API_KEY` in `.env` are non-empty and `is_online()` returns true.
- **`Groq 403: error code 1010`** — Cloudflare blocking urllib's User-Agent. Fixed by routing Groq calls through the official `groq` SDK (already in place); upgrade if you see this on old code.
- **Llama hallucinates tool replies** ("Open: Opened Postman" without actually launching) — Llama 3.1 8B is unreliable at function calls. The dispatcher in `llm/client.py` routes any tool-using turn to OpenRouter Gemini; only text-only turns go to Groq.
- **Direct dispatch missed an `open <app>` request** — STT may have added trailing artifacts ("amen", "thanks", "now"). The trailing-strip loop in `_try_direct_dispatch` handles common ones; add new ones to the regex if needed.
- **Vision sounds robotic** ("the screenshot shows…") — `tools/vision.py::DescribeScreenTool` carries the Jarvis persona prompt; the agent's `VOICE_ADDENDUM` reinforces it. Re-check both if a model regression slips through.
- **Hotkey doesn't fire** (legacy mode only) — pynput on X11 needs to read all input devices; some compositors block this. Try logging out/in or running as root once to test.
- **Boot prints ALSA / JACK / deprecation chatter** — set `JARVIS_DEBUG=1` to see what Pipecat is doing under the hood; in normal mode `voice/pipecat_runtime.py::_run_async` redirects fd 2 → /dev/null for the session, so jarvis.log is your source of truth for runtime errors.
- **Whisper returns empty** (legacy) — input clip may be too short or too quiet. Check `JARVIS_VAD_SILENCE_MS` (smaller = more aggressive cutoff).

## What's next

- **Streaming TTS during LLM generation** — start synthesizing the first sentence as soon as the LLM emits it, not after the full reply.
- **Multilingual** — Hindi via Sarvam STT/TTS.
- **Voice cloning** — clone user-preferred voice into ElevenLabs and set its ID.
- **Continuous mode** — no wake word between turns, just keep the conversation going.
