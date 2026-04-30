#!/usr/bin/env python3
import sys
import uuid
import time

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
    for _, node_state in step.items():
        for m in node_state.get("messages", []):
            if isinstance(m, ToolMessage):
                console.print(f"  [green]✓[/green] [dim]{m.name}[/dim] → {m.content}")
            elif isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    console.print(f"  [yellow]→[/yellow] [dim]{tc['name']}[/dim]({tc['args']})")


def warmup(graph, thread_id: str):
    """Trigger heavy lazy-init in openai/httpx so first user turn is fast."""
    try:
        # Cheapest possible call — just a ping. Cost ~$0.0001.
        graph.invoke(
            {"messages": [HumanMessage(content="say 'ok'")]},
            config={
                "configurable": {"thread_id": thread_id + "_warmup"},
                "recursion_limit": 3,
            },
        )
    except Exception as e:
        log.warning(f"Warmup failed (non-fatal): {e}")


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

    thread_id = str(uuid.uuid4())

    with Status("[dim]warming up...[/dim]", console=console, spinner="dots"):
        graph = build_graph()
        warmup(graph, thread_id)

    while True:
        try:
            user_input = Prompt.ask("\n[bold]You[/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            sys.exit(0)

        if not user_input:
            continue

        if user_input == "/reset":
            thread_id = str(uuid.uuid4())
            console.print("[dim]History cleared.[/dim]")
            continue

        log.info(f"User: {user_input}")
        graph_config = {"configurable": {"thread_id": thread_id}}
        t0 = time.time()

        final_msg = None
        try:
            with Status("[dim]thinking...[/dim]", console=console, spinner="dots"):
                for step in graph.stream(
                    {"messages": [HumanMessage(content=user_input)]},
                    config=graph_config,
                    stream_mode="updates",
                ):
                    render_step(step)
                    # Track the latest AIMessage with content for final display
                    for node_state in step.values():
                        for m in node_state.get("messages", []):
                            if isinstance(m, AIMessage) and m.content and not getattr(m, "tool_calls", None):
                                final_msg = m
        except Exception as e:
            log.error(f"Graph run failed: {e}", exc_info=True)
            console.print(f"[red]Error:[/red] {e}")
            continue

        elapsed = time.time() - t0
        log.debug(f"Turn took {elapsed:.2f}s")

        if final_msg:
            console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {final_msg.content} [dim]({elapsed:.1f}s)[/dim]")
        else:
            console.print(f"[dim]Jarvis: (no response, {elapsed:.1f}s)[/dim]")


if __name__ == "__main__":
    main()
