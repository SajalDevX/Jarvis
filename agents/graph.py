from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import BaseMessage

from agents.app_agent import build_app_agent
from logger import log


class JarvisState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def route(state: JarvisState) -> str:
    """Pick which agent should handle this turn. Extend as agents grow."""
    last = state["messages"][-1]
    text = last.content.lower() if hasattr(last, "content") else ""

    app_kw = ["open", "close", "launch", "quit", "kill", "start", "search app"]
    if any(kw in text for kw in app_kw):
        return "app_agent"
    return "app_agent"  # only agent for now


def build_graph():
    """Build the orchestrator with persistent state via checkpointer.

    Use thread_id in config to keep history across turns.
    """
    app_agent = build_app_agent()

    graph = StateGraph(JarvisState)
    graph.add_node("app_agent", app_agent)
    graph.add_conditional_edges(START, route, {"app_agent": "app_agent"})
    graph.add_edge("app_agent", END)

    return graph.compile(checkpointer=InMemorySaver())
