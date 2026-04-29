# Jarvis CLI

Local AI desktop assistant. Chat in terminal to open/close apps and run commands.

**Online:** uses OpenRouter (cloud model, better quality)  
**Offline:** uses Ollama (local model, no internet needed)

## Setup

```bash
# 1. Install dependencies
python3 -m venv .venv
.venv/bin/pip install rich

# 2. Configure
cp .env.example .env
# Edit .env — add your OpenRouter API key

# 3. Install Ollama (for offline mode)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:4b

# 4. Run
ollama serve          # keep running in background
.venv/bin/python main.py
```

## Usage

```
You: open firefox
You: close spotify
You: what files are in my home directory
You: open terminal
```

## Config (`.env`)

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Get at openrouter.ai/keys |
| `OPENROUTER_MODEL` | `qwen/qwen3.5` | Model used when online |
| `JARVIS_MODEL` | `qwen3.5:4b` | Ollama model used when offline |
| `JARVIS_OLLAMA_URL` | `http://localhost:11434/api/chat` | Ollama server URL |

## Override model at runtime

```bash
.venv/bin/python main.py qwen3.5:4b
```
