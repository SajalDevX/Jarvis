import json
from abc import ABC
from typing import Iterable

from llm.client import chat
from tools.registry import REGISTRY
from logger import log


class Agent(ABC):
    """Base class for any agent. Subclass and set name, system_prompt, tool_names, tier."""

    name: str = ""
    description: str = ""
    system_prompt: str = ""
    tool_names: list[str] = []
    max_tool_rounds: int = 6
    tier: str = "fast"  # which model tier this agent uses by default

    def __init__(self):
        self.messages: list[dict] = [
            {"role": "system", "content": self.system_prompt}
        ]

    @property
    def tools_schema(self) -> list[dict]:
        return REGISTRY.schemas(self.tool_names)

    def reset(self):
        """Clear conversation history (keep system prompt)."""
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def run(self, user_input: str, on_tool_call=None, tier_override: str | None = None) -> str:
        """Run a single user turn. Returns final reply text.

        on_tool_call: optional callback(name, args, result) for UI feedback.
        tier_override: force a specific tier (e.g. router suggests "power").
        """
        active_tier = tier_override or self.tier
        log.info(f"[{self.name}] User: {user_input} (tier={active_tier})")
        self.messages.append({"role": "user", "content": user_input})

        reply, tool_calls, raw_msg = chat(self.messages, tools=self.tools_schema, tier=active_tier)
        self.messages.append(raw_msg)

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
                self.messages.append(tool_msg)

            try:
                reply, tool_calls, raw_followup = chat(
                    self.messages, tools=self.tools_schema, tier=active_tier
                )
                self.messages.append(raw_followup)
            except ConnectionError as e:
                log.error(f"[{self.name}] follow-up failed: {e}")
                return ""

        log.info(f"[{self.name}] Reply: {reply[:100]}")
        return reply
