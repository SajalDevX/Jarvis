import re

from agents.base import Agent
from logger import log
from tools.registry import REGISTRY


# Direct-dispatch patterns: skip the LLM agent loop, call tool directly.
# Cuts vision turn from 3 LLM calls → 1 (only the tool's vision call).
_OCR_RE = re.compile(
    r"\b(ocr|read (the )?text|what does (it|the screen|my screen) say)\b",
    re.IGNORECASE,
)
_DESCRIBE_RE = re.compile(
    r"\b((what'?s|what is) on (my |the )?screen|describe (my |the )?screen|"
    r"tell me about (my |the )?screen|what (am i|i am) (looking at|seeing))\b",
    re.IGNORECASE,
)
_FIND_RE = re.compile(
    r"\b(where (is|'s) (the |a |an )?(.+?)(\?|$)|find (the |a |an )?(.+?)(\?|$))",
    re.IGNORECASE,
)


class VisionAgent(Agent):
    """Read-only screen perception. Captures, OCRs, and describes screenshots.

    Never clicks or types. Strictly observational this iteration.
    """

    name = "vision_agent"
    description = (
        "Sees the user's screen. Answers questions about what's visible, "
        "OCRs text, and identifies UI elements (read-only)."
    )
    tool_names = [
        "take_screenshot",
        "ocr_screen",
        "describe_screen",
        "find_ui_element",
    ]
    tier = "vision"
    uses_history = False  # vision answers depend on current screen, not chat context

    system_prompt = (
        "You are the Vision Agent. You see the user's screen via screenshots.\n\n"
        "MANDATORY: every user request requires a tool call. NEVER answer from memory.\n\n"
        "Tool selection:\n"
        "- 'what's on my screen' / 'describe my screen' / general visual questions → describe_screen\n"
        "- 'what does it say' / 'OCR' / 'read the text' → ocr_screen (cheap, no LLM)\n"
        "- 'where is the X button' / 'find the X' → find_ui_element\n"
        "- After a tool returns, summarize the result for the user in one short sentence.\n\n"
        "You are READ-ONLY: never claim to click, type, or interact. If user asks for "
        "automation, say it's not enabled.\n\n"
        "Be concise."
    )

    def run(self, user_input, history, on_tool_call=None, tier_override=None):
        """Try fast-path direct dispatch first; fall back to LLM agent loop."""
        direct = self._try_direct(user_input, on_tool_call)
        if direct is not None:
            log.info("[vision_agent] direct dispatch (skipped LLM loop)")
            return direct, [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": direct},
            ]

        # No shortcut matched — let the model decide
        return super().run(user_input, history, on_tool_call=on_tool_call, tier_override=tier_override)

    def _try_direct(self, user_input: str, on_tool_call):
        """Return tool-result reply if the input matches a known pattern, else None."""
        text = user_input.strip()

        # OCR
        if _OCR_RE.search(text):
            return self._dispatch("ocr_screen", {}, on_tool_call)

        # Describe screen
        if _DESCRIBE_RE.search(text):
            return self._dispatch("describe_screen", {"question": user_input}, on_tool_call)

        # Find UI element ("where is X" / "find X")
        m = _FIND_RE.search(text)
        if m:
            target = (m.group(4) or m.group(7) or "").strip().rstrip("?.!").strip()
            if target and len(target) <= 60:
                return self._dispatch(
                    "find_ui_element",
                    {"description": target},
                    on_tool_call,
                )
        return None

    @staticmethod
    def _dispatch(tool_name: str, args: dict, on_tool_call) -> str:
        result = REGISTRY.dispatch(tool_name, args)
        if on_tool_call:
            on_tool_call(tool_name, args, result)
        return result
