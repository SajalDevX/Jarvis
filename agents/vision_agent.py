from agents.base import Agent


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
