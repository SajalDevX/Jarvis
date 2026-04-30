#!/usr/bin/env python3
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status

import config
from logger import log, LOG_FILE
from agents.orchestrator import Orchestrator
from llm.client import is_online

console = Console()


def make_tool_callback():
    def cb(name: str, args: dict, result: str):
        console.print(f"  [green]✓[/green] [dim]{name}[/dim] → {result}")
    return cb


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
        f"[bold cyan]Jarvis CLI[/bold cyan]\n"
        f"[dim]Mode: {mode}[/dim]\n"
        f"[dim]Logs → {LOG_FILE}[/dim]\n"
        "[dim]Ctrl+C to exit. /reset to clear history.[/dim]",
        expand=False,
    ))

    orchestrator = Orchestrator()
    on_tool = make_tool_callback()

    while True:
        try:
            user_input = Prompt.ask("\n[bold]You[/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            log.info("Session ended")
            sys.exit(0)

        if not user_input:
            continue

        if user_input == "/reset":
            orchestrator.reset()
            console.print("[dim]History cleared.[/dim]")
            continue

        try:
            with Status("[dim]thinking...[/dim]", console=console, spinner="dots"):
                agent_name, reply = orchestrator.handle(user_input, on_tool_call=on_tool)
        except ConnectionError as e:
            log.error(f"Chat failed: {e}")
            console.print(f"[red]Error:[/red] {e}")
            continue

        if reply:
            console.print(f"\n[bold cyan]Jarvis[/bold cyan] [dim]({agent_name})[/dim]: {reply}")
        else:
            console.print("[dim]Jarvis: (no response)[/dim]")


if __name__ == "__main__":
    main()
