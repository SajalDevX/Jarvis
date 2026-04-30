import json
from abc import ABC

from llm.client import chat
from tools.registry import REGISTRY
from logger import log


class Agent(ABC):
    """Base class for any agent. Stateless — history is owned by the Orchestrator.

    Subclass and set: name, system_prompt, tool_names, tier.
    """

    name: str = ""
    description: str = ""
    system_prompt: str = ""
    tool_names: list[str] = []
    max_tool_rounds: int = 6
    tier: str = "fast"
    # When False, agent runs stateless — orchestrator passes empty history.
    # Useful for agents whose answers depend only on the current turn (e.g. vision).
    uses_history: bool = True

    @property
    def tools_schema(self) -> list[dict]:
        return REGISTRY.schemas(self.tool_names)

    def run(
        self,
        user_input: str,
        history: list[dict],
        on_tool_call=None,
        tier_override: str | None = None,
    ) -> tuple[str, list[dict]]:
        """Run a single user turn against the shared history.

        Args:
            user_input: latest user message
            history: shared conversation log (no system prompt). Filtered by orchestrator.
            on_tool_call: optional UI callback(name, args, result)
            tier_override: optional model tier override (router-suggested)

        Returns:
            (reply_text, new_turn_messages) where new_turn_messages is everything
            this turn produced (user msg, assistant msg(s), tool msg(s)) — orchestrator
            appends them to the shared history.
        """
        active_tier = tier_override or self.tier
        log.info(f"[{self.name}] User: {user_input} (tier={active_tier})")

        new_turn: list[dict] = [{"role": "user", "content": user_input}]
        full_messages: list[dict] = (
            [{"role": "system", "content": self.system_prompt}]
            + history
            + new_turn
        )

        reply, tool_calls, raw_msg = chat(
            full_messages, tools=self.tools_schema, tier=active_tier
        )
        new_turn.append(raw_msg)
        full_messages.append(raw_msg)

        rounds = 0
        while tool_calls and rounds < self.max_tool_rounds:
            rounds += 1
            log.debug(f"[{self.name}] tool round {rounds}")
            for tc in tool_calls:
                tname = tc["function"]["name"]
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    args = json.loads(args) if args else {}
                tool_call_id = tc.get("id", "")

                log.debug(f"[{self.name}] dispatch: {tname}({args})")
                result = REGISTRY.dispatch(tname, args)
                log.debug(f"[{self.name}] result: {result}")

                if on_tool_call:
                    on_tool_call(tname, args, result)

                tool_msg = {"role": "tool", "name": tname, "content": result}
                if tool_call_id:
                    tool_msg["tool_call_id"] = tool_call_id
                new_turn.append(tool_msg)
                full_messages.append(tool_msg)

            try:
                reply, tool_calls, raw_followup = chat(
                    full_messages, tools=self.tools_schema, tier=active_tier
                )
                new_turn.append(raw_followup)
                full_messages.append(raw_followup)
            except ConnectionError as e:
                log.error(f"[{self.name}] follow-up failed: {e}")
                return "", new_turn

        log.info(f"[{self.name}] Reply: {reply[:100]}")
        return reply, new_turn
