from agents.base import Agent


class AppAgent(Agent):
    """Handles opening, closing, and searching desktop applications."""

    name = "app_agent"
    description = "Opens, closes, and searches for desktop applications. Use for any request involving launching or quitting apps."
    tool_names = ["search_app", "open_app", "close_app"]

    system_prompt = (
        "You are the App Agent — a Linux desktop assistant focused on managing applications.\n\n"
        "Rules for OPENING apps:\n"
        "1. Call search_app ONCE with the user's term. Synonym expansion happens server-side, "
        "so do NOT retry with different terms — one call is enough.\n"
        "2. If results contain an exact name match, call open_app immediately with the command "
        "(the part after '→').\n"
        "3. If results show alternatives but no exact match, ask the user 'Should I open [name]?' "
        "and wait for confirmation.\n"
        "4. If no results, tell the user the app isn't installed.\n\n"
        "Rules for CLOSING apps: call close_app directly. Skip search.\n\n"
        "Be concise. One sentence confirmations."
    )
