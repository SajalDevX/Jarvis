from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

import socket
from logger import log


def is_online() -> bool:
    try:
        socket.setdefaulttimeout(2)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False


def build_llm() -> BaseChatModel:
    """Build a LangChain chat model. OpenRouter when online, Ollama when offline."""
    from config import (
        OPENROUTER_API_KEY,
        OPENROUTER_MODEL,
        OPENROUTER_URL_BASE,
        MODEL,
        OLLAMA_BASE_URL,
    )

    if is_online() and OPENROUTER_API_KEY:
        log.info(f"LLM: OpenRouter / {OPENROUTER_MODEL}")
        return ChatOpenAI(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_URL_BASE,
            max_tokens=1024,
            default_headers={"HTTP-Referer": "jarvis-cli"},
        )

    log.info(f"LLM: Ollama / {MODEL}")
    return ChatOllama(
        model=MODEL,
        base_url=OLLAMA_BASE_URL,
    )
