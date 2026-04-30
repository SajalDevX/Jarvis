from agents.base import Agent


class ChatAgent(Agent):
    """Handles small talk, greetings, simple Q&A — no tools, runs on nano tier."""

    name = "chat_agent"
    description = "Conversational replies with no tool use. Cheap and fast."
    tool_names = []
    tier = "nano"

    system_prompt = (
        "You are Jarvis, a friendly Linux desktop assistant. "
        "Reply briefly and naturally. One or two sentences max. "
        "No greetings if user didn't greet you."
    )
