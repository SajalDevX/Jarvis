import os
from pathlib import Path

# Load .env manually
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Offline (Ollama)
MODEL = os.environ.get("JARVIS_MODEL", "qwen3.5:4b")
OLLAMA_BASE_URL = os.environ.get("JARVIS_OLLAMA_BASE_URL", "http://localhost:11434")

# Online (OpenRouter — OpenAI-compatible)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_URL_BASE = "https://openrouter.ai/api/v1"
