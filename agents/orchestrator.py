import re

import os
import time

from agents.base import Agent
from agents.app_agent import AppAgent
from agents.chat_agent import ChatAgent
from agents.desktop_agent import DesktopAgent
from agents.router import RouterAgent
from agents.vision_agent import VisionAgent
from cache.intent_cache import IntentCache
from logger import log


CACHEABLE_REPLY_AGENTS = {"chat_agent"}

# Short user replies that almost certainly continue the previous agent's flow.
_FOLLOWUP_PATTERNS = re.compile(
    r"^(yes|yeah|yep|sure|ok|okay|y|no|nope|n|nah|"
    r"\d+|first|second|third|that one|the \w+|both|all|none|"
    r"go ahead|do it|cancel|stop|skip)$",
    re.IGNORECASE,
)


def _is_followup(text: str) -> bool:
    stripped = text.strip().rstrip(".!?").lower()
    return bool(len(stripped) <= 25 and _FOLLOWUP_PATTERNS.match(stripped))


# Soft cap on history size — beyond this, oldest entries trimmed (keep system + recent)
MAX_HISTORY_MESSAGES = 40


# Fast-classifier patterns: skip router LLM (~1s saved) for obvious intents.
_VISION_RE = re.compile(
    r"\b(screen|screenshot|ocr|describe my|what's on (my )?screen|"
    r"what is on (my )?screen|what does (it|the screen|my screen) say|"
    r"where is (the |a |an )|find (the |a |an )|"
    r"what (app|window|program) (is |'s )?(open|in focus|running|active)|"
    r"which (app|window) (is |'s )?(open|focused|active)|"
    r"focused window|active window|list (all )?windows)",
    re.IGNORECASE,
)
_APP_RE = re.compile(
    r"^(open|close|launch|quit|kill|start|terminate)\s+",
    re.IGNORECASE,
)

# Imperative UI control verbs → desktop_agent. Excludes "open/launch <app>" which
# direct-dispatch handles atomically. Matches text starting with the verb so
# "click the login button" routes correctly.
_DESKTOP_RE = re.compile(
    r"^(click|tap|double[-\s]?click|right[-\s]?click|press|type|paste|enter|"
    r"select|highlight|drag|scroll|swipe|fill\s+in|fill\s+out|submit|hit|"
    r"focus|switch\s+to|navigate\s+to|go\s+to|visit|browse\s+to|"
    r"move\s+(?:cursor|mouse))\b",
    re.IGNORECASE,
)

# Navigation intent (URL / website / "open X in browser") → desktop_agent.
# Distinct from _DESKTOP_RE because the verb is still "open", which would
# otherwise hit the app-launcher path.
_DESKTOP_NAV_RE = re.compile(
    r"^\s*(?:open|launch|load|pull\s+up|bring\s+up|fire\s+up)\b.*"
    r"(?:\b(?:in|on|via|with|within|inside)\s+(?:firefox|chrome|chromium|browser|safari|edge|brave|opera)\b"
    r"|\b(?:website|webpage|web\s+page|site|url|tab)\b"
    r"|\b(?:youtube|google\.com|github\.com|gmail|reddit)\b"
    r"|\.(?:com|org|net|io|dev)\b"
    r"|https?://)",
    re.IGNORECASE,
)

# --- Phase 6 direct-dispatch: shell-mappable intents bypass LLM entirely. --- #

_DIRECT_MEDIA_RE = re.compile(
    r"^(?:please\s+)?"
    r"(?P<action>play|pause|resume|stop|skip|next|previous|prev)"
    r"(?:\s+(?:the\s+)?(?:music|song|track|video|media))?"
    r"\s*[.!?]?$",
    re.IGNORECASE,
)

# "mute", "unmute", "volume 30", "volume to 30%", "set volume to 30%"
_DIRECT_VOLUME_RE = re.compile(
    r"^(?:please\s+)?(?:set\s+(?:the\s+)?)?"
    r"(?P<action>mute|unmute|volume(?:\s+(?:up|down|to)?)?(?:\s+(?:to|at))?)"
    r"\s*(?P<pct>\d{1,3})?\s*%?\s*[.!?]?$",
    re.IGNORECASE,
)

_DIRECT_WIFI_RE = re.compile(
    r"^(?:please\s+)?(?:turn\s+)?(?:wifi|wi-fi|wireless)\s+(?P<state>on|off)\s*[.!?]?$",
    re.IGNORECASE,
)

_DIRECT_BLUETOOTH_RE = re.compile(
    r"^(?:please\s+)?(?:turn\s+)?bluetooth\s+(?P<state>on|off)\s*[.!?]?$",
    re.IGNORECASE,
)

# Bare URL or "open <url>" / "go to <url>" → xdg_open. Fires before _DESKTOP_NAV_RE
# so we don't burn an LLM round-trip on something xdg-open can do in 1ms.
_DIRECT_URL_RE = re.compile(
    r"^(?:please\s+)?(?:open|go\s+to|visit|browse\s+to|navigate\s+to|launch|load)\s+"
    r"(?P<url>https?://\S+|\S+\.(?:com|org|net|io|dev|gg|co)(?:/\S*)?)\s*[.!?]?$",
    re.IGNORECASE,
)

# Even tighter: zero-LLM path for "open <app>" / "launch <app>" / "start <app>".
# Calls smart_open_app directly and returns a canned reply. Saves both router
# AND agent LLM calls (~600-1500ms in voice mode).
_DIRECT_OPEN_RE = re.compile(
    r"^(?:"
    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    r"(?:please\s+)?"
    r")?"
    r"(?:open|launch|start|run)\s+"
    r"(.+?)"
    r"(?:\s+(?:for|please)\s+(?:me|us))?"
    r"\s*[.!?]?$",
    re.IGNORECASE,
)


def _quick_classify(text: str) -> tuple[str, str] | None:
    """Pattern-only routing for unambiguous intents. None means 'use the LLM router'."""
    t = text.strip()
    # Desktop verbs are imperative — they always start the sentence and should
    # outrank vision keywords that might co-occur ("click the close button on
    # the focused window" → desktop, not vision).
    if _DESKTOP_RE.match(t):
        return "desktop_agent", "vision"
    # Navigation intents ("open youtube in firefox", "go to github.com", etc.)
    # share the verb 'open' with app-launch, but they're really desktop tasks.
    if _DESKTOP_NAV_RE.match(t):
        return "desktop_agent", "vision"
    if _APP_RE.match(t):
        return "app_agent", "fast"
    if _VISION_RE.search(t):
        return "vision_agent", "vision"
    return None


class Orchestrator:
    """Owns the shared conversation log. Picks an agent per turn.

    Flow:
      0. Sticky: short follow-up ('yes') → reuse previous agent
      1. Cache: exact-match → instant route (and maybe instant reply)
      2. Router: nano model classifies → agent + tier
      3. Filter history for the chosen agent (full if same agent, narrative-only if switching)
      4. Run agent → append produced messages back to shared history
    """

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self._default: Agent | None = None
        self._last_agent: Agent | None = None
        self._last_tier: str = "fast"
        self.router = RouterAgent()
        self.cache = IntentCache()
        # Shared message log (no system prompts). Each msg has role + content.
        # Tool messages have a "_agent" tag added so we know which agent owns them.
        self.history: list[dict] = []
        self._register_defaults()

    def _register_defaults(self):
        self.register(ChatAgent(), default=True)
        self.register(AppAgent())
        self.register(VisionAgent())
        self.register(DesktopAgent())

    def register(self, agent: Agent, default: bool = False):
        self.agents[agent.name] = agent
        if default:
            self._default = agent
        log.info(f"Registered agent: {agent.name} (tier={agent.tier})")

    def reset(self):
        """Clear shared conversation history."""
        self.history = []
        self._last_agent = None
        log.info("Orchestrator history cleared")

    def _filter_history_for(self, target_agent: Agent) -> list[dict]:
        """When the target agent is the same as last, pass full history.
        When switching agents, strip tool calls/results so the new agent doesn't
        see tools it doesn't have — keep narrative content only.
        Stateless agents (uses_history=False) get empty history.
        """
        if not getattr(target_agent, "uses_history", True):
            log.debug(f"{target_agent.name} is stateless — empty history")
            return []

        if self._last_agent and target_agent.name == self._last_agent.name:
            return self._strip_meta(self.history)

        # Cross-agent: keep user/assistant TEXT only
        narrative: list[dict] = []
        for m in self.history:
            role = m.get("role")
            if role == "tool":
                continue
            if role == "assistant":
                # Strip tool_calls but keep textual content
                content = m.get("content") or ""
                if content:
                    narrative.append({"role": "assistant", "content": content})
                continue
            if role == "user":
                narrative.append({"role": "user", "content": m.get("content", "")})
        return narrative

    @staticmethod
    def _strip_meta(messages: list[dict]) -> list[dict]:
        """Remove non-API fields (like _agent) before sending to the LLM."""
        out = []
        for m in messages:
            cleaned = {k: v for k, v in m.items() if not k.startswith("_")}
            out.append(cleaned)
        return out

    def _trim_history(self):
        """Keep history bounded. Drop oldest beyond MAX_HISTORY_MESSAGES."""
        if len(self.history) > MAX_HISTORY_MESSAGES:
            drop = len(self.history) - MAX_HISTORY_MESSAGES
            log.debug(f"Trimming {drop} oldest history entries")
            self.history = self.history[drop:]

    def _make_tool_callback(self, user_cb):
        """Wrap user's tool callback so we can post-process certain tool calls
        (e.g. auto-capture screen after open_app)."""
        auto_capture = os.environ.get("JARVIS_AUTO_CAPTURE", "true").lower() != "false"
        region = os.environ.get("JARVIS_CAPTURE_REGION", "active_window")

        def cb(name: str, args: dict, result: str):
            if user_cb:
                user_cb(name, args, result)

            # Auto-capture after a successful app open — gives next turn fresh visual context
            if auto_capture and name == "open_app" and result.startswith("Opened"):
                # Give the app a moment to actually paint
                time.sleep(0.6)
                try:
                    from vision.screen_state import SCREEN
                    info = SCREEN.capture(region=region)
                    log.info(f"auto-capture after open_app → {info['path']}")
                    self.history.append({
                        "role": "system",
                        "content": "[A screenshot of the just-opened app was captured and is available to vision_agent if asked.]",
                        "_agent": "orchestrator",
                    })
                except Exception as e:
                    log.warning(f"auto-capture failed (non-fatal): {e}")

        return cb

    def _try_shell_dispatch(self, user_input: str, wrapped_cb) -> tuple[str, str] | None:
        """Phase 6: zero-LLM path for shell-mappable intents (media, volume,
        wifi, bluetooth, url-open). Uses tools/cli_actions.py + xdg_open.
        Returns (agent_name, reply) on hit, else None.
        """
        text = user_input.strip()
        from tools.registry import REGISTRY

        def fire(tool: str, args: dict, success_msg: str) -> tuple[str, str]:
            result = REGISTRY.dispatch(tool, args)
            log.info(f"Shell dispatch: {tool}({args!r}) -> {result[:80]}")
            if wrapped_cb:
                wrapped_cb(tool, args, result)
            spoken = success_msg if not result.startswith(("REFUSED", "CliError")) else result
            return self._mirror_and_return(user_input, spoken, "app_agent")

        # 1. URL / website open via xdg-open
        m = _DIRECT_URL_RE.match(text)
        if m:
            url = m.group("url")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            return fire("xdg_open", {"target": url}, f"Opened {url}, sir.")

        # 2. Media (MPRIS)
        m = _DIRECT_MEDIA_RE.match(text)
        if m:
            action = m.group("action").lower()
            action = {"resume": "play", "skip": "next", "prev": "previous"}.get(action, action)
            return fire("media_control", {"action": action}, f"{action.capitalize()}d, sir.")

        # 3. Volume / mute
        m = _DIRECT_VOLUME_RE.match(text)
        if m:
            action = m.group("action").lower().strip()
            pct = m.group("pct")
            if action == "mute":
                return fire("volume_mute", {"state": True}, "Muted, sir.")
            if action == "unmute":
                return fire("volume_mute", {"state": False}, "Unmuted, sir.")
            if pct is not None:
                p = int(pct)
                return fire("volume_set", {"percent": p}, f"Volume set to {p} percent, sir.")

        # 4. Wi-Fi
        m = _DIRECT_WIFI_RE.match(text)
        if m:
            state = m.group("state").lower()
            return fire("wifi_toggle", {"state": state}, f"Wi-Fi {state}, sir.")

        # 5. Bluetooth
        m = _DIRECT_BLUETOOTH_RE.match(text)
        if m:
            state = m.group("state").lower()
            return fire("bluetooth_toggle", {"state": state}, f"Bluetooth {state}, sir.")

        return None

    def _mirror_and_return(self, user_input: str, reply: str, agent_name: str) -> tuple[str, str]:
        """Append turn to shared history and return."""
        self.history.append({"role": "user", "content": user_input, "_agent": "orchestrator"})
        self.history.append({"role": "assistant", "content": reply, "_agent": agent_name})
        self._trim_history()
        self._last_agent = self.agents.get(agent_name) or self._default
        self._last_tier = "fast"
        return agent_name, reply

    def _try_direct_dispatch(self, user_input: str, wrapped_cb) -> tuple[str, str] | None:
        """Pattern-match common 'open X' commands and run the tool synchronously.
        Returns (agent_name, reply) on success, else None to continue normal flow.
        """
        # Navigation intents like "open youtube in firefox" / "open google.com" /
        # "open the X website" are NOT app-launches — desktop_agent handles them.
        if re.search(
            r"\b(in|on|via|with|within|inside)\s+(firefox|chrome|chromium|browser|safari|edge|brave|opera)\b",
            user_input,
            re.IGNORECASE,
        ):
            return None
        if re.search(
            r"\b(website|webpage|web\s+page|site|url|tab|youtube|google\.com|github\.com|"
            r"\.com\b|\.org\b|\.net\b|\.io\b|https?://)",
            user_input,
            re.IGNORECASE,
        ):
            return None
        m = _DIRECT_OPEN_RE.match(user_input.strip())
        if not m:
            return None
        target = m.group(1).strip()
        # Trim trailing politeness + STT artifacts ("Amen" / "thanks" / "now" / etc.)
        # Loop because input like "text editor now thanks" has two trailing tokens.
        _trail = re.compile(
            r"[?,.!\s]*\b(please|now|already|right now|amen|thanks|thank you|"
            r"for me|for us|man|bro|dude|too|also|pal|buddy)\b[?,.!\s]*$",
            re.IGNORECASE,
        )
        while True:
            stripped = _trail.sub("", target).strip(" ?,.!")
            if stripped == target:
                break
            target = stripped
        # Skip obviously non-app phrases like "open the door", "open up"
        if not target or target.lower() in {"up", "the door", "it", "this", "that"}:
            return None
        from tools.registry import REGISTRY
        try:
            result = REGISTRY.dispatch("smart_open_app", {"query": target})
        except Exception as e:
            log.warning(f"direct dispatch failed for '{target}': {e}")
            return None
        # Tool returns "Opened <name>." on success or an error/ambiguity string.
        # Only short-circuit when the tool clearly succeeded — else fall through
        # so the LLM can clarify ambiguity.
        if not result.startswith("Opened"):
            log.debug(f"direct dispatch ambiguous → fallthrough: {result!r}")
            return None
        log.info(f"Direct dispatch: smart_open_app({target!r}) → no LLM")
        if wrapped_cb:
            try:
                wrapped_cb("smart_open_app", {"query": target}, result)
            except Exception as e:
                log.warning(f"direct-dispatch tool callback failed: {e}")
        # Voice-friendly reply: strip "(PID 12345)" parenthetical, drop "Opened "
        # prefix, format as "<App> is open, sir." for natural speech.
        spoken_app = re.sub(r"\s*\(PID\s+\d+\)\s*$", "", result).removeprefix("Opened ").rstrip(".")
        spoken = f"{spoken_app} is open, sir." if spoken_app else result
        # Mirror in shared history so vision/follow-ups see the action
        self.history.append({"role": "user", "content": user_input, "_agent": "orchestrator"})
        self.history.append({"role": "assistant", "content": spoken, "_agent": "app_agent"})
        self._trim_history()
        self._last_agent = self.agents.get("app_agent") or self._default
        self._last_tier = "fast"
        return "app_agent", spoken

    def handle(self, user_input: str, on_tool_call=None, voice: bool = False) -> tuple[str, str]:
        # Wrap callback for post-action hooks (auto-capture etc.)
        wrapped_cb = self._make_tool_callback(on_tool_call)

        # 0a-pre. Phase 6 shell dispatch: media / volume / wifi / xdg-open URL.
        if not (self._last_agent and _is_followup(user_input)):
            shell = self._try_shell_dispatch(user_input, wrapped_cb)
            if shell is not None:
                return shell

        # 0a. Zero-LLM direct dispatch: "open <app>" / "launch <app>" → call tool, canned reply.
        if not (self._last_agent and _is_followup(user_input)):
            direct = self._try_direct_dispatch(user_input, wrapped_cb)
            if direct is not None:
                return direct

        # 0. Sticky: short follow-up reuses prior agent
        if self._last_agent and _is_followup(user_input):
            log.info(f"Sticky route → {self._last_agent.name} (followup)")
            agent = self._last_agent
            tier = self._last_tier
        else:
            # 1. Cache check
            cached = self.cache.get(user_input)
            if cached:
                agent_name = cached.agent
                tier = cached.tier
                if cached.reply:
                    log.info(f"Cache hit (full): {agent_name}/{tier}")
                    self._last_agent = self.agents.get(agent_name) or self._default
                    self._last_tier = tier
                    # Add to history so future agents have context
                    self.history.append({"role": "user", "content": user_input})
                    self.history.append({"role": "assistant", "content": cached.reply})
                    self._trim_history()
                    return agent_name, cached.reply
                log.info(f"Cache hit (route only): {agent_name}/{tier}")
            else:
                # 1.5 Quick pattern classify (skip router LLM if obvious)
                quick = _quick_classify(user_input)
                if quick:
                    agent_name, tier = quick
                    log.info(f"Quick classify → {agent_name}/{tier}")
                else:
                    # 2. Router classifies via LLM
                    agent_name, tier = self.router.classify(user_input)

            agent = self.agents.get(agent_name) or self._default

        # 3. Filter shared history for this agent
        history_view = self._filter_history_for(agent)

        # 4. Run agent — get reply + new messages it produced this turn
        reply, new_turn = agent.run(
            user_input,
            history=history_view,
            on_tool_call=wrapped_cb,
            tier_override=tier,
            voice=voice,
        )

        # 5. Tag each new message with owning agent and append to shared history
        for m in new_turn:
            m.setdefault("_agent", agent.name)
        self.history.extend(new_turn)
        self._trim_history()

        # 6. Update sticky state + cache
        self._last_agent = agent
        self._last_tier = tier
        cache_reply = reply if agent.name in CACHEABLE_REPLY_AGENTS and reply else None
        self.cache.put(user_input, agent.name, tier, cache_reply)

        return agent.name, reply
