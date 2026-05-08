"""Router agent — classifies user intent on the cheapest model.

Returns (agent_name, tier) so the orchestrator can dispatch correctly.
Failure-safe: any error / malformed JSON → falls back to default agent + fast tier.
"""
import json
import re

from agents.base import Agent
from llm.client import chat
from logger import log


ROUTER_PROMPT = """You are an intent classifier. Output STRICT JSON only — no markdown, no explanation.

Schema:
{"agent": "app|vision|desktop|system|chat", "tier": "nano|fast|smart|power|vision"}

Agents:
- "app": open, close, launch, quit, list desktop applications
- "vision": observe-only questions about the screen — screenshot, OCR, "what's shown",
  "is it loaded", "what does it say", "describe my screen", "find the X button"
- "desktop": ACT on the screen — click, type, paste, scroll, drag, press a key,
  fill in a form, submit, close a tab, copy text, navigate a webpage
- "system": shell command, system info, file ops
- "chat": small talk, greetings, simple Q&A not requiring tools

Tiers:
- "nano": trivial reply ("hi", "thanks") — usually chat agent
- "fast": single-step action (open/close app) — most app cases
- "vision": any vision_agent task — required when agent=vision
- "smart": multi-step planning, analysis, summarization
- "power": code generation, complex reasoning, hard debugging

Output the JSON object on a single line. Nothing else."""


class RouterAgent(Agent):
    name = "router"
    description = "Classifies user intent and picks the right agent + tier"
    tool_names = []  # no tools — pure classification
    tier = "nano"
    system_prompt = ROUTER_PROMPT

    def classify(self, user_input: str) -> tuple[str, str]:
        """Returns (agent_name, tier). Falls back on errors."""
        msgs = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]
        try:
            reply, _, _ = chat(msgs, tools=None, tier=self.tier)
        except Exception as e:
            log.warning(f"Router LLM error: {e} — defaulting to app/fast")
            return "app_agent", "fast"

        # Strip markdown fences if model returned them
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", reply.strip())
        # Find first JSON object
        match = re.search(r"\{[^{}]*\}", cleaned)
        if not match:
            log.warning(f"Router non-JSON: {reply!r}")
            return "app_agent", "fast"

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            log.warning(f"Router JSON parse failed: {match.group(0)!r}")
            return "app_agent", "fast"

        agent = data.get("agent", "app").lower()
        tier = data.get("tier", "fast").lower()

        # Map short names → full agent names
        agent_map = {
            "app": "app_agent",
            "system": "app_agent",
            "chat": "chat_agent",
            "vision": "vision_agent",
            "desktop": "desktop_agent",
        }
        agent_name = agent_map.get(agent, "app_agent")

        # Validate tier
        if tier not in ("nano", "fast", "smart", "power", "vision"):
            tier = "fast"

        # If routing to vision/desktop agent, force vision tier (multimodal needed)
        if agent_name in ("vision_agent", "desktop_agent"):
            tier = "vision"

        log.info(f"Router classified: agent={agent_name} tier={tier}")
        return agent_name, tier
