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


def chat(messages: list, tools: list | None = None) -> tuple[str, list, dict]:
    """Send messages to the active LLM. Returns (reply_text, tool_calls, raw_msg).

    Routes to OpenRouter when online, Ollama when offline.
    """
    if is_online():
        log.debug("LLM route: OpenRouter")
        return _chat_openrouter(messages, tools or [])
    log.debug("LLM route: Ollama")
    return _chat_ollama(messages, tools or [])


def _chat_openrouter(messages: list, tools: list) -> tuple[str, list, dict]:
    from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL

    log.debug(f"OpenRouter req: model={OPENROUTER_MODEL}, msgs={len(messages)}, tools={len(tools)}")

    body = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": 1024,
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


def _chat_ollama(messages: list, tools: list) -> tuple[str, list, dict]:
    from config import MODEL, OLLAMA_URL

    log.debug(f"Ollama req: model={MODEL}, msgs={len(messages)}, tools={len(tools)}")

    body = {
        "model": MODEL,
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
