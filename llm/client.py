import base64
import json
import socket
import urllib.request
import urllib.error
from pathlib import Path

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
    image_paths: list[str] | None = None,
    image_max_width: int = 768,
) -> tuple[str, list, dict]:
    """Send messages to the LLM for the given tier. Returns (reply, tool_calls, raw_msg).

    Routes to OpenRouter when online, Ollama when offline.

    image_paths: optional list of local image file paths. Attached to the LAST
    user message as multimodal content. Only honored on the `vision` tier.
    """
    model, max_tokens = _resolve_model(tier)
    log.debug(f"chat tier={tier} → model={model}")

    if image_paths and tier != "vision":
        log.warning(f"image_paths supplied on non-vision tier '{tier}' — ignoring")
        image_paths = None

    if image_paths:
        messages = _attach_images(messages, image_paths, max_width=image_max_width)

    if is_online():
        from config import OPENROUTER_API_KEY, GROQ_API_KEY, GROQ_LLM_MODEL
        # Groq Llama 3.1 8B is fast (~250ms TTFT) but unreliable at tool calls —
        # it hallucinates replies instead of emitting tool_calls. So route to
        # Groq only for text-only nano/fast (router, chat). Tool-using turns
        # and vision stay on OpenRouter (Gemini).
        if (
            GROQ_API_KEY
            and tier in ("nano", "fast")
            and not image_paths
            and not tools
        ):
            return _chat_groq(messages, [], GROQ_LLM_MODEL, max_tokens)
        if OPENROUTER_API_KEY:
            return _chat_openrouter(messages, tools or [], model, max_tokens)

    return _chat_ollama(messages, tools or [], model)


def _attach_images(messages: list, image_paths: list[str], max_width: int = 768) -> list:
    """Mutate the last user message into multimodal content with images attached.

    Uses OpenAI/OpenRouter vision format:
      [{type: "text", text: "..."}, {type: "image_url", image_url: {url: "data:image/jpeg;base64,..."}}]
    """
    out = list(messages)
    if not out:
        return out

    # Find last user message
    last_user_idx = None
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        log.warning("_attach_images: no user message found")
        return out

    text_content = out[last_user_idx].get("content") or ""
    parts = [{"type": "text", "text": text_content}]
    for p in image_paths:
        path = Path(p)
        if not path.exists():
            log.warning(f"image not found: {p}")
            continue
        # Use already-encoded JPEG if downscaled, else read raw + base64
        from vision.capture import downscale_for_llm
        try:
            jpeg_bytes = downscale_for_llm(path, max_width=max_width)
            b64 = base64.b64encode(jpeg_bytes).decode("ascii")
            mime = "image/jpeg"
        except Exception as e:
            log.warning(f"downscale failed for {p}: {e} — sending raw")
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            mime = "image/png"
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    out[last_user_idx] = {"role": "user", "content": parts}
    return out


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


_GROQ_CLIENT = None


def _chat_groq(
    messages: list,
    tools: list,
    model: str,
    max_tokens: int,
) -> tuple[str, list, dict]:
    """Call Groq via the official SDK (handles UA / Cloudflare correctly).

    urllib gets 403 error 1010 from Cloudflare due to its default User-Agent;
    the SDK uses httpx + a proper UA and works.
    """
    global _GROQ_CLIENT
    from config import GROQ_API_KEY

    log.debug(f"Groq req: model={model}, msgs={len(messages)}, tools={len(tools)}, max_tokens={max_tokens}")

    if _GROQ_CLIENT is None:
        from groq import Groq
        _GROQ_CLIENT = Groq(api_key=GROQ_API_KEY)

    kwargs = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools

    try:
        resp = _GROQ_CLIENT.chat.completions.create(**kwargs)
    except Exception as e:
        log.error(f"Groq SDK error: {e}")
        raise ConnectionError(f"Groq error: {e}") from e

    msg_obj = resp.choices[0].message
    reply = msg_obj.content or ""
    raw_tool_calls = msg_obj.tool_calls or []

    log.debug(f"Groq resp: content_len={len(reply)}, tools={len(raw_tool_calls)}")

    tool_calls = [
        {
            "id": tc.id,
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        for tc in raw_tool_calls
    ]

    msg_dict = {
        "role": msg_obj.role,
        "content": reply,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in raw_tool_calls
        ] if raw_tool_calls else None,
    }

    return reply.strip(), tool_calls, msg_dict


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
