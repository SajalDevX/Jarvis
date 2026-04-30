from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from agents.app_agent import build_app_agent
from logger import log


class JarvisState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    agent: str


def route(state: JarvisState) -> str:
    """Pick which agent should handle this turn. Extend as agents are added."""
    last = state["messages"][-1]
    text = last.content.lower() if hasattr(last, "content") else ""

    app_kw = ["open", "close", "launch", "quit", "kill", "start", "search app"]
    if any(kw in text for kw in app_kw):
        log.debug("Route → app_agent")
        return "app_agent"

    log.debug("Route → app_agent (default)")
    return "app_agent"


def build_graph():
    """Build the orchestrator StateGraph.

    To add a new agent: build it, register it as a node, add its key to route()."""
    app_agent = build_app_agent()

    graph = StateGraph(JarvisState)
    graph.add_node("app_agent", app_agent)
    graph.add_conditional_edges(START, route, {"app_agent": "app_agent"})
    graph.add_edge("app_agent", END)

    return graph.compile()
