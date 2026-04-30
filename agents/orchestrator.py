from agents.base import Agent
from agents.app_agent import AppAgent
from logger import log


class Orchestrator:
    """Routes user input to the appropriate agent.

    Current strategy: simple keyword routing. Future: LLM-based intent classification.
    """

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self._default: Agent | None = None
        self._register_defaults()

    def _register_defaults(self):
        app = AppAgent()
        self.register(app, default=True)

    def register(self, agent: Agent, default: bool = False):
        self.agents[agent.name] = agent
        if default:
            self._default = agent
        log.info(f"Registered agent: {agent.name}")

    def route(self, user_input: str) -> Agent:
        """Pick agent based on intent. For now, always returns default (app_agent)."""
        text = user_input.lower()

        # Simple keyword routing — extend as more agents are added
        app_keywords = ["open", "close", "launch", "quit", "kill", "start", "run app", "search app"]
        if any(kw in text for kw in app_keywords):
            return self.agents["app_agent"]

        return self._default

    def handle(self, user_input: str, on_tool_call=None) -> tuple[str, str]:
        """Run user input through the right agent. Returns (agent_name, reply)."""
        agent = self.route(user_input)
        log.debug(f"Routed to: {agent.name}")
        reply = agent.run(user_input, on_tool_call=on_tool_call)
        return agent.name, reply
