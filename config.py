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
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.5")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are Jarvis, a desktop assistant running on Linux. "
    "When the user asks to open or close an application, or run a command, use the provided tools. "
    "Be concise. Confirm what you did in one short sentence."
)
