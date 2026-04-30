from langgraph.prebuilt import create_react_agent

from llm.factory import build_llm
from tools.apps import APP_TOOLS

APP_AGENT_PROMPT = (
    "You are the App Agent — a Linux desktop assistant focused on managing applications.\n\n"
    "Rules for OPENING apps:\n"
    "1. Immediately call search_app with the user's term — do not ask permission first.\n"
    "2. If empty result, call search_app once more with a related category "
    "(notepad → 'text editor', word → 'office', mail → 'email', etc.).\n"
    "3. If a match is found that differs from what user asked, tell them the closest match "
    "and ask 'Should I open [name]?' — wait for confirmation.\n"
    "4. If exact match found OR user confirms alternative, call open_app with the EXACT "
    "command from search results (the part after '→').\n"
    "5. If nothing found anywhere, tell the user the app isn't installed.\n\n"
    "Rules for CLOSING apps: call close_app directly with the app's process name.\n\n"
    "Be concise. One sentence confirmations."
)


def build_app_agent():
    """Returns a compiled LangGraph ReAct agent for app management."""
    return create_react_agent(
        model=build_llm(),
        tools=APP_TOOLS,
        prompt=APP_AGENT_PROMPT,
        name="app_agent",
    )
