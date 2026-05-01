from agents.base import Agent


class AppAgent(Agent):
    """Handles opening, closing, and searching desktop applications."""

    name = "app_agent"
    description = "Opens, closes, and searches for desktop applications. Use for any request involving launching or quitting apps."
    tool_names = ["search_app", "open_app", "close_app"]
    tier = "fast"  # app tasks are simple, use fast tier

    system_prompt = (
        "You are the App Agent — a Linux desktop assistant focused on managing applications.\n\n"
        "Rules for OPENING apps:\n"
        "1. Call search_app ONCE with the user's term. Synonym expansion happens server-side, "
        "so do NOT retry with different terms — one call is enough.\n"
        "2. EXACT-MATCH RULE (most important): if any result's name (case-insensitive, "
        "ignoring leading articles) matches what the user asked, OPEN IT IMMEDIATELY with "
        "open_app — do NOT ask for confirmation. Examples:\n"
        "   - User: 'open text editor'  →  results include 'Text Editor → gnome-text-editor'  →  call open_app('gnome-text-editor')\n"
        "   - User: 'open firefox'      →  results include 'Firefox → firefox'  →  call open_app('firefox')\n"
        "3. NO EXACT MATCH but partial/alternative matches found: ask 'Should I open [closest name]?' "
        "and wait. Only ask once — don't list every option.\n"
        "4. NO MATCHES at all: tell the user the app isn't installed.\n\n"
        "Rules for CLOSING apps: call close_app directly. Skip search.\n\n"
        "Be concise. After opening, reply with one short confirmation sentence."
    )
