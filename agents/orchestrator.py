import re

from agents.base import Agent
from agents.app_agent import AppAgent
from agents.chat_agent import ChatAgent
from agents.router import RouterAgent
from cache.intent_cache import IntentCache
from logger import log


# Replies cached as full text — only for deterministic phrases that never change.
CACHEABLE_REPLY_AGENTS = {"chat_agent"}

# Short user replies that almost certainly continue the previous agent's flow.
_FOLLOWUP_PATTERNS = re.compile(
    r"^(yes|yeah|yep|sure|ok|okay|y|no|nope|n|nah|"
    r"\d+|first|second|third|that one|the \w+|both|all|none|"
    r"go ahead|do it|cancel|stop|skip)$",
    re.IGNORECASE,
)


def _is_followup(text: str) -> bool:
    """Heuristic: short reply likely continues prior agent (yes/no/pick a number)."""
    stripped = text.strip().rstrip(".!?").lower()
    if len(stripped) <= 25 and _FOLLOWUP_PATTERNS.match(stripped):
        return True
    return False


class Orchestrator:
    """Cache → (sticky / router) → Agent pipeline.

    Sticky routing: if last turn used an agent and current input looks like a
    follow-up ('yes', 'pick the second one'), keep using that agent so it
    retains the prior conversation context.
    """

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self._default: Agent | None = None
        self._last_agent: Agent | None = None
        self._last_tier: str = "fast"
        self.router = RouterAgent()
        self.cache = IntentCache()
        self._register_defaults()

    def _register_defaults(self):
        self.register(AppAgent(), default=True)
        self.register(ChatAgent())

    def register(self, agent: Agent, default: bool = False):
        self.agents[agent.name] = agent
        if default:
            self._default = agent
        log.info(f"Registered agent: {agent.name} (tier={agent.tier})")

    def handle(self, user_input: str, on_tool_call=None) -> tuple[str, str]:
        """Returns (agent_name, reply)."""
        # 0. Sticky: short follow-up → reuse previous agent (skip router + cache)
        if self._last_agent and _is_followup(user_input):
            log.info(f"Sticky route → {self._last_agent.name} (followup)")
            agent = self._last_agent
            tier = self._last_tier
            reply = agent.run(user_input, on_tool_call=on_tool_call, tier_override=tier)
            return agent.name, reply

        # 1. Cache check
        cached = self.cache.get(user_input)
        if cached:
            agent_name = cached.agent
            tier = cached.tier
            if cached.reply:
                log.info(f"Cache hit (full): {agent_name}/{tier}")
                self._last_agent = self.agents.get(agent_name) or self._default
                self._last_tier = tier
                return agent_name, cached.reply
            log.info(f"Cache hit (route only): {agent_name}/{tier}")
        else:
            # 2. Router classifies
            agent_name, tier = self.router.classify(user_input)

        # 3. Pick agent (fall back to default if unknown)
        agent = self.agents.get(agent_name) or self._default
        actual_name = agent.name

        # 4. Run agent with router-suggested tier override
        reply = agent.run(user_input, on_tool_call=on_tool_call, tier_override=tier)

        # 5. Remember for sticky routing
        self._last_agent = agent
        self._last_tier = tier

        # 6. Cache result
        cache_reply = reply if actual_name in CACHEABLE_REPLY_AGENTS and reply else None
        self.cache.put(user_input, actual_name, tier, cache_reply)

        return actual_name, reply
