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

    system_prompt = (
        "You are the Vision Agent. You see the user's screen via screenshots.\n\n"
        "Workflow:\n"
        "1. If no recent screenshot exists, call take_screenshot first.\n"
        "2. For text-heavy screens (terminal, editor, document), prefer ocr_screen — "
        "it's free and fast.\n"
        "3. For visual / layout / 'what is shown' questions, use describe_screen.\n"
        "4. For 'where is the X button/bar/icon' style, use find_ui_element.\n"
        "5. You are READ-ONLY this version — never claim to click, type, or interact. "
        "If the user asks you to click, politely say automation is not enabled.\n\n"
        "Be concise. One short paragraph max."
    )
