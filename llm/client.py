import json
import socket
import urllib.request
import urllib.error

from logger import log


def is_online() -> bool:
    try:
        socket.setdefaulttimeout(2)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False


def _resolve_model(tier: str) -> tuple[str, int]:
    """Map tier → (model_id, max_tokens) based on connectivity."""
    from config import (
        TIER_MODELS_ONLINE,
        TIER_MODELS_OFFLINE,
        TIER_MAX_TOKENS,
        OPENROUTER_API_KEY,
    )

    online = is_online() and bool(OPENROUTER_API_KEY)
    table = TIER_MODELS_ONLINE if online else TIER_MODELS_OFFLINE
    model = table.get(tier, table["fast"])
    max_tokens = TIER_MAX_TOKENS.get(tier, 1024)
    return model, max_tokens


def chat(
    messages: list,
    tools: list | None = None,
    tier: str = "fast",
) -> tuple[str, list, dict]:
    """Send messages to the LLM for the given tier. Returns (reply, tool_calls, raw_msg).

    Routes to OpenRouter when online, Ollama when offline.
    """
    model, max_tokens = _resolve_model(tier)
    log.debug(f"chat tier={tier} → model={model}")

    if is_online():
        from config import OPENROUTER_API_KEY
        if OPENROUTER_API_KEY:
            return _chat_openrouter(messages, tools or [], model, max_tokens)

    return _chat_ollama(messages, tools or [], model)


def _chat_openrouter(
    messages: list,
    tools: list,
    model: str,
    max_tokens: int,
) -> tuple[str, list, dict]:
    from config import OPENROUTER_API_KEY, OPENROUTER_URL

    log.debug(f"OpenRouter req: model={model}, msgs={len(messages)}, tools={len(tools)}, max_tokens={max_tokens}")

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "jarvis-cli",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()
        log.error(f"OpenRouter HTTP {e.code}: {body_err}")
        raise ConnectionError(f"OpenRouter {e.code}: {body_err}") from e
    except urllib.error.URLError as e:
        log.error(f"OpenRouter URL error: {e}")
        raise ConnectionError(f"OpenRouter error: {e}") from e

    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})
    reply = msg.get("content") or msg.get("reasoning_content") or msg.get("reasoning") or ""
    raw_tool_calls = msg.get("tool_calls") or []

    log.debug(f"OpenRouter resp: content_len={len(reply)}, tools={len(raw_tool_calls)}")

    tool_calls = [
        {
            "id": tc.get("id", ""),
            "function": {
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            },
        }
        for tc in raw_tool_calls
    ]

    return reply.strip(), tool_calls, msg


def _chat_ollama(messages: list, tools: list, model: str) -> tuple[str, list, dict]:
    from config import OLLAMA_URL

    log.debug(f"Ollama req: model={model}, msgs={len(messages)}, tools={len(tools)}")

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        body["tools"] = tools

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        log.error(f"Ollama error: {e}")
        raise ConnectionError(f"Cannot reach Ollama at {OLLAMA_URL}: {e}") from e

    msg = data.get("message", {})
    reply = msg.get("content") or ""
    tool_calls = msg.get("tool_calls") or []

    log.debug(f"Ollama resp: content_len={len(reply)}, tools={len(tool_calls)}")

    return reply.strip(), tool_calls, msg
