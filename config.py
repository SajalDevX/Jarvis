import os
from pathlib import Path

# Load .env manually (no dotenv dep)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Offline (Ollama)
MODEL = os.environ.get("JARVIS_MODEL", "qwen3.5:4b")
OLLAMA_URL = os.environ.get("JARVIS_OLLAMA_URL", "http://localhost:11434/api/chat")

# Online (OpenRouter — OpenAI-compatible)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash-lite")  # default fast model
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Groq (fastest LPU inference, OpenAI-compatible). Used for nano/fast tiers + STT.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "llama-3.1-8b-instant")
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Tiered model registry — pick model based on task complexity
TIER_MODELS_ONLINE = {
    "nano":   os.environ.get("JARVIS_TIER_NANO",   "google/gemini-2.5-flash-lite"),
    "fast":   os.environ.get("JARVIS_TIER_FAST",   "google/gemini-2.5-flash-lite"),
    "smart":  os.environ.get("JARVIS_TIER_SMART",  "google/gemini-2.5-flash"),
    "power":  os.environ.get("JARVIS_TIER_POWER",  "anthropic/claude-sonnet-4-6"),
    "vision": os.environ.get("JARVIS_TIER_VISION", "google/gemini-2.5-flash-lite"),
}

# Offline fallback — local model handles every tier
TIER_MODELS_OFFLINE = {tier: MODEL for tier in TIER_MODELS_ONLINE}

# Per-tier output cap (cost + speed guardrail)
TIER_MAX_TOKENS = {
    "nano":   256,
    "fast":   1024,
    "smart":  2048,
    "power":  4096,
    "vision": 1024,
}

# Voice mode
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel default
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")  # fastest WS streaming-input
JARVIS_VOICE_MODE = os.environ.get("JARVIS_VOICE_MODE", "off")  # off | hotkey | wake | both
JARVIS_HOTKEY = os.environ.get("JARVIS_HOTKEY", "<ctrl>+<space>")
JARVIS_WAKE_MODEL = os.environ.get("JARVIS_WAKE_MODEL", "hey_jarvis_v0.1")
JARVIS_VOICE_LANG = os.environ.get("JARVIS_VOICE_LANG", "en")
JARVIS_VAD_SILENCE_MS = int(os.environ.get("JARVIS_VAD_SILENCE_MS", "600"))


SYSTEM_PROMPT = (
    "You are Jarvis, a desktop assistant running on Linux. "
    "When the user asks to open an application, follow these steps WITHOUT asking permission first:\n"
    "1. Immediately call search_app with the app name the user mentioned.\n"
    "2. If not found, call search_app again with a related category (e.g. user says 'notepad' → search 'text editor').\n"
    "3. If a match is found, tell the user: 'I found [name] which is similar to [what they asked] — should I open it?' then wait.\n"
    "4. If user says yes, call open_app with the exact command from search results.\n"
    "5. If nothing found at all, tell the user it's not installed.\n"
    "When closing apps or running commands, act directly. Be concise."
)
