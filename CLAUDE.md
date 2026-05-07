# Jarvis — Project Context

Voice-driven AI desktop assistant for Linux, inspired by Iron Man's Jarvis. CLI-first, multi-agent, multi-LLM, tool-using.

## Current state

- **Branch:** `feat/voice-optimizations` (pushed to origin, PR not yet opened).
- **Phase:** 4 — Pipecat-based sub-second voice latency (shipped, validated end-to-end).
- **Phases 1-3:** all merged to `main` via PRs #1-#3.

## Architecture overview

```
voice in:  mic → Silero VAD → Smart Turn v3 → Groq Whisper-turbo
                                                 ↓ user_text
                            JarvisLLMService (wraps Orchestrator)
                            ├─ IntentCache (full-reply or route-only)
                            ├─ _try_direct_dispatch  ← zero-LLM "open <app>"
                            ├─ Sticky follow-up (yes/no reuses prior agent)
                            ├─ Quick-classify regex (vision / app)
                            ├─ RouterAgent (nano LLM) on cache+regex miss
                            └─ Agent.run() with tools
                                 ↓ reply (sentence-split)
voice out: ElevenLabs Turbo v2 WS streaming-input → speakers
```

Text mode (no `--voice` flag) uses the same Orchestrator without the voice transport.

## Tier system (`config.py`)

| Tier | Model | Provider |
|---|---|---|
| nano | `llama-3.1-8b-instant` | Groq (text-only) → fallback OpenRouter |
| fast | `gemini-2.5-flash-lite` | OpenRouter when tools, Groq when no tools |
| smart | `gemini-2.5-flash` | OpenRouter |
| power | `claude-sonnet-4-6` | OpenRouter |
| vision | `gemini-2.5-flash-lite` | OpenRouter (multimodal) |
| local | `qwen3.5:4b` | Ollama (offline fallback for all tiers) |

`llm/client.py::chat` routes: text-only → Groq SDK; with tools or images → OpenRouter (urllib); offline → Ollama.

**Groq Llama 3.1 8B caveat:** unreliable at function calling — it hallucinates tool replies in prose instead of emitting `tool_calls`. Hence: any turn with `tools=` set goes to Gemini, not Groq.

**Cloudflare 1010:** urllib's default User-Agent is blocked. `_chat_groq` uses the official `groq` SDK (httpx-based) to bypass.

## Voice runtimes

Auto-selected in `main.py`:

| Runtime | When | Latency | File |
|---|---|---|---|
| **Pipecat** (Phase 4) | online + GROQ_API_KEY + ELEVENLABS_API_KEY | ~600-1100ms | `voice/pipecat_runtime.py` |
| **Legacy** (Phase 3) | offline OR keys missing | 3-7s | `voice/runtime.py` |

Pipecat path: always-on VAD (no hotkey gating). Legacy path supports `hotkey` / `wake` / `both` modes.

Quiet by default — fd 2 is dup2'd to /dev/null in `pipecat_runtime._run_async` to silence ALSA/JACK/loguru/deprecation noise. `JARVIS_DEBUG=1` disables.

## Direct dispatch (`agents/orchestrator.py`)

Zero-LLM fast-path for `(can you|please)? (open|launch|start|run) <app> (please|now|thanks|amen|...)?`:

1. Match `_DIRECT_OPEN_RE`.
2. Strip trailing politeness/STT-artifacts (loops until stable).
3. Call `REGISTRY.dispatch("smart_open_app", {"query": target})`.
4. If result starts with `Opened ` → return `"<app> is open, sir."` and short-circuit.
5. Else fall through to LLM path (ambiguous or not-found).

Benchmark: 1ms vs ~3-5s on the LLM path.

## Voice persona

`agents/base.py::Agent.VOICE_ADDENDUM` is appended to every agent's system prompt when `voice=True`. Scripts a Tony-Stark-Jarvis tone: dry, British, "sir", 1-2 sentences, no markdown, no parentheticals.

`tools/vision.py::DescribeScreenTool.execute` carries the same persona in its system prompt to the multimodal LLM, so vision answers stop saying "the screenshot shows…" and describe the screen directly.

## Tool registry (`tools/registry.py`)

| Tool | Purpose | Cost |
|---|---|---|
| `smart_open_app` | search+open atomic, with synonyms / filler stripping | ~10ms |
| `search_app` / `open_app` / `close_app` | granular variants | ~10ms |
| `run_command` | shell exec with safety filter | varies |
| `take_screenshot` / `ocr_screen` | mss + tesseract | 20-500ms |
| `describe_screen` | multimodal LLM Q&A on capture | ~1-3s |
| `find_ui_element` | multimodal LLM, returns approximate position (read-only) | ~2s |
| `active_window` / `list_windows` | xdotool/xprop/wmctrl | ~10ms (no LLM) |

Llama 3.1 8B emits tool names with `default_api.` / `functions.` prefix — `agents/base.py::run` strips any `<namespace>.` before dispatching.

## Key files

| Path | Role |
|---|---|
| `main.py` | Entry. Picks voice runtime, wires console, fd silencer. |
| `config.py` | Env loader, tier registry, voice keys, `SYSTEM_PROMPT`. |
| `llm/client.py` | `chat()` with multi-provider routing (Groq SDK / OpenRouter urllib / Ollama). |
| `agents/orchestrator.py` | Cache → direct dispatch → sticky → quick-classify → router → agent. Owns shared history. |
| `agents/base.py` | `Agent.run()` loop with `tools=…`, `VOICE_ADDENDUM`, namespace-stripping. |
| `agents/router.py` | Nano-tier intent classifier. |
| `agents/{chat,app,vision}_agent.py` | Three agents. ChatAgent is default. |
| `cache/intent_cache.py` | LRU exact-match cache, persisted to `~/.cache/jarvis/intents.json`. |
| `tools/vision.py` | Screen capture + OCR + describe + find-element + window introspection. |
| `vision/screen_state.py` | Singleton: latest screenshot, hash, OCR/describe cache. |
| `voice/pipecat_runtime.py` | Phase 4: Pipeline + fd silencer + persona-aware console. |
| `voice/services/jarvis_llm.py` | Pipecat LLMService that delegates to Orchestrator. |
| `voice/{capture,stt,tts,hotkey,wake,runtime}.py` | Phase 3 legacy stack (offline fallback). |
| `docs/voice.md` | Voice mode user docs (kept current). |

## Dev workflow

User preferences (per `~/.claude/projects/.../memory/feedback_workflow.md`):

- Test small changes before commit.
- Commit without `Co-Authored-By` trailer.
- Push to current branch.

Auth: `git push` works; `gh` may need re-auth if PR commands fail.

`.venv/` for Python deps. `requirements.txt` updated for Phase 4 (`pipecat-ai[silero,elevenlabs,local]`, `groq`, `httpx`, `webrtcvad-wheels`).

## Known gotchas

- **Two `GROQ_API_KEY=` lines in `.env`** would let an empty stub win because of `setdefault`. Always ensure single line per key.
- **Whisper STT artifacts** — adds "Amen", "Now", "Thanks" to phrases. Direct-dispatch trailing-strip loop handles common ones; extend if new ones appear.
- **Pipecat 1.1.0 deprecation warnings** — `OpenAISTTService(model=...)` and `ElevenLabsTTSService(voice_id=, model=)` warn but still work; migrate to `settings=...Settings(...)` later.
- **`LLMSettings: NOT_GIVEN` warning at startup** — fixed by populating an `LLMSettings` store in `JarvisLLMService.__init__` (see `_store_settings()`).
- **mic too hot** — wpctl set-volume cap mic at ~30% for sane VAD.
- **Sounddevice / portaudio** requires `apt install portaudio19-dev libsndfile1 ffmpeg` system packages.

## Open follow-ups

- Migrate Pipecat service kwargs from positional to `settings=Settings(...)` (silences deprecation warnings).
- Add Pipecat-side hotkey gating (currently always-on VAD only).
- Optional: switch app_agent's tool model to Groq Llama 3.3 70B once Groq tool-use reliability improves; would shave ~600ms.
- Add `--debug` CLI flag mirroring `JARVIS_DEBUG=1`.
- Streaming token-level emission from Orchestrator so TTS starts before full LLM reply lands (currently sentence-split after full reply). Needs Orchestrator-level streaming.

## Verification snippets

```bash
# Direct dispatch (no LLM, ~1ms)
.venv/bin/python -c "
import time
from agents.orchestrator import Orchestrator
o = Orchestrator()
for q in ['open firefox', 'Can you open Postman? Amen.', 'launch chrome please pal']:
    t0 = time.time()
    a, r = o.handle(q, voice=True)
    print(f'{q!r:45s} -> [{int((time.time()-t0)*1000)}ms] {r!r}')
"

# Groq path
.venv/bin/python -c "from llm.client import chat; print(chat([{'role':'user','content':'Reply: pong'}], tier='nano'))"

# Pipecat live
.venv/bin/python main.py --voice hotkey
# Look for: 'Voice runtime: pipecat (Groq STT + Groq LLM + ElevenLabs WS TTS)'
# Then: 'Listening… speak whenever (always-on VAD).'
# tail -f jarvis.log for per-turn timings.
```

## Plan reference

Full design + decision history: `~/.claude/plans/ollama-is-not-installed-toasty-lemon.md`. Phases 1-4 documented end-to-end. Don't write planning docs into the repo unless explicitly asked.
