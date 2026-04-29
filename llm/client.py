import json
import socket
import urllib.request
import urllib.error

from tools.registry import TOOL_DEFINITIONS
from logger import log


def is_online() -> bool:
    try:
        socket.setdefaulttimeout(2)
        socket.create_connection(("8.8.8.8", 53))
        log.debug("Network check: online")
        return True
    except OSError:
        log.debug("Network check: offline")
        return False


def chat(messages: list) -> tuple[str, list, dict]:
    if is_online():
        log.debug("Routing to OpenRouter")
        return _chat_openrouter(messages)
    log.debug("Routing to Ollama (offline)")
    return _chat_ollama(messages)


def _chat_openrouter(messages: list) -> tuple[str, list, dict]:
    from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL

    log.debug(f"OpenRouter request: model={OPENROUTER_MODEL}, messages={len(messages)}")

    payload = json.dumps({
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "stream": False,
        "max_tokens": 1024,
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
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
        body = e.read().decode()
        log.error(f"OpenRouter HTTP {e.code}: {body}")
        raise ConnectionError(f"OpenRouter {e.code}: {body}") from e
    except urllib.error.URLError as e:
        log.error(f"OpenRouter URL error: {e}")
        raise ConnectionError(f"OpenRouter error: {e}") from e

    choice = data.get("choices", [{}])[0]
    finish_reason = choice.get("finish_reason")
    msg = choice.get("message", {})
    reply = msg.get("content") or msg.get("reasoning_content") or msg.get("reasoning") or ""
    tool_calls_raw = msg.get("tool_calls") or []

    log.debug(f"OpenRouter response: finish_reason={finish_reason}, content_len={len(reply)}, tool_calls={len(tool_calls_raw)}")
    if tool_calls_raw:
        log.debug(f"Tool calls: {[tc['function']['name'] for tc in tool_calls_raw]}")

    tool_calls = [
        {
            "id": tc.get("id", ""),
            "function": {
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            }
        }
        for tc in tool_calls_raw
    ]

    return reply.strip(), tool_calls, msg


def _chat_ollama(messages: list) -> tuple[str, list, dict]:
    from config import MODEL, OLLAMA_URL

    log.debug(f"Ollama request: model={MODEL}, messages={len(messages)}")

    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
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

    log.debug(f"Ollama response: content_len={len(reply)}, tool_calls={len(tool_calls)}")

    return reply.strip(), tool_calls, msg
