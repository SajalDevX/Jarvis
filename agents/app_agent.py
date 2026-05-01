from agents.base import Agent


class AppAgent(Agent):
    """Handles opening, closing, and searching desktop applications."""

    name = "app_agent"
    description = "Opens, closes, and searches for desktop applications. Use for any request involving launching or quitting apps."
    tool_names = ["smart_open_app", "search_app", "close_app"]
    tier = "fast"  # app tasks are simple, use fast tier

    system_prompt = (
        "You are the App Agent. You manage Linux desktop apps.\n\n"
        "OPEN: call smart_open_app(query) — it searches and opens in one step.\n"
        "  - If result starts with 'Opened', reply 'Opened X.' (one sentence).\n"
        "  - If result starts with 'AMBIGUOUS:', ask the user which option.\n"
        "  - If result starts with 'NOT_FOUND:', say the app isn't installed.\n\n"
        "CLOSE: call close_app(name).\n\n"
        "BROWSE: call search_app(query) only when user asks 'what apps are installed'.\n\n"
        "Be concise."
    )
