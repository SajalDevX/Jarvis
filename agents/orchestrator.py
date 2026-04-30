from agents.base import Agent
from agents.app_agent import AppAgent
from agents.chat_agent import ChatAgent
from agents.router import RouterAgent
from cache.intent_cache import IntentCache
from logger import log


# Replies cached as full text — only for deterministic phrases that never change
# (e.g. "what's your name"). We don't cache app-launching replies because state matters.
CACHEABLE_REPLY_AGENTS = {"chat_agent"}


class Orchestrator:
    """Cache → Router → Agent pipeline.

    1. Exact-match cache check (instant)
    2. Router classifies on nano model (~200ms)
    3. Selected agent runs on its tier (or router-suggested override)
    """

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self._default: Agent | None = None
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
        # 1. Cache check
        cached = self.cache.get(user_input)
        if cached:
            agent_name = cached.agent
            tier = cached.tier
            if cached.reply:
                log.info(f"Cache hit (full): {agent_name}/{tier}")
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

        # 5. Cache result
        cache_reply = reply if actual_name in CACHEABLE_REPLY_AGENTS and reply else None
        self.cache.put(user_input, actual_name, tier, cache_reply)

        return actual_name, reply
