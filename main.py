#!/usr/bin/env python3
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

import config
from logger import log, LOG_FILE
from llm.factory import is_online
from agents.graph import build_graph

console = Console()


def render_step(step: dict):
    """Pretty-print a streaming step from LangGraph."""
    for node_name, node_state in step.items():
        msgs = node_state.get("messages", [])
        for m in msgs:
            if isinstance(m, ToolMessage):
                console.print(f"  [green]✓[/green] [dim]{m.name}[/dim] → {m.content}")
            elif isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    console.print(f"  [yellow]→[/yellow] [dim]{tc['name']}[/dim]({tc['args']})")


def main():
    if len(sys.argv) > 1:
        config.MODEL = sys.argv[1]

    log.info(f"Jarvis starting — offline={config.MODEL}, online={config.OPENROUTER_MODEL}")

    online = is_online()
    mode = (
        f"[green]online[/green] → {config.OPENROUTER_MODEL}"
        if online else f"[yellow]offline[/yellow] → {config.MODEL}"
    )

    console.print(Panel(
        f"[bold cyan]Jarvis CLI[/bold cyan]  [dim](LangGraph)[/dim]\n"
        f"[dim]Mode: {mode}[/dim]\n"
        f"[dim]Logs → {LOG_FILE}[/dim]\n"
        "[dim]Ctrl+C to exit. /reset to clear history.[/dim]",
        expand=False,
    ))

    graph = build_graph()
    history: list = []

    while True:
        try:
            user_input = Prompt.ask("\n[bold]You[/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            sys.exit(0)

        if not user_input:
            continue

        if user_input == "/reset":
            history.clear()
            console.print("[dim]History cleared.[/dim]")
            continue

        history.append(HumanMessage(content=user_input))
        log.info(f"User: {user_input}")

        final_state = None
        try:
            with Status("[dim]thinking...[/dim]", console=console, spinner="dots"):
                for step in graph.stream(
                    {"messages": history, "agent": ""},
                    stream_mode="updates",
                ):
                    render_step(step)
                    final_state = step
        except Exception as e:
            log.error(f"Graph run failed: {e}", exc_info=True)
            console.print(f"[red]Error:[/red] {e}")
            history.pop()
            continue

        # Extract final assistant message
        if final_state:
            for node_state in final_state.values():
                for m in node_state.get("messages", []):
                    if isinstance(m, AIMessage) and m.content:
                        history.append(m)
                        console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {m.content}")
                        break


if __name__ == "__main__":
    main()
