#!/usr/bin/env python3
import sys
import json

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status

import config
from logger import log, LOG_FILE

console = Console()


def run_tool_calls(tool_calls: list) -> list:
    from tools.registry import dispatch

    tool_messages = []
    for tc in tool_calls:
        name = tc["function"]["name"]
        args = tc["function"]["arguments"]
        if isinstance(args, str):
            args = json.loads(args)

        tool_call_id = tc.get("id", "")
        log.debug(f"Dispatching tool: {name}({args}) id={tool_call_id}")
        result = dispatch(name, args)
        log.debug(f"Tool result: {result}")
        console.print(f"  [green]✓[/green] {result}")
        tool_msg = {"role": "tool", "name": name, "content": result}
        if tool_call_id:
            tool_msg["tool_call_id"] = tool_call_id
        tool_messages.append(tool_msg)

    return tool_messages


def main():
    if len(sys.argv) > 1:
        config.MODEL = sys.argv[1]

    log.info(f"Jarvis starting — offline model: {config.MODEL}, online model: {config.OPENROUTER_MODEL}")

    console.print(Panel(
        f"[bold cyan]Jarvis CLI[/bold cyan]  [dim]model: {config.MODEL}[/dim]\n"
        f"[dim]Logs → {LOG_FILE}[/dim]\n"
        "[dim]Type your request. Ctrl+C to exit.[/dim]",
        expand=False,
    ))

    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]

    from llm.client import chat, is_online

    online = is_online()
    mode = f"[green]online[/green] → {config.OPENROUTER_MODEL}" if online else f"[yellow]offline[/yellow] → {config.MODEL}"
    console.print(f"  Mode: {mode}\n")

    while True:
        try:
            user_input = Prompt.ask("\n[bold]You[/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            log.info("Session ended by user")
            sys.exit(0)

        if not user_input:
            continue

        log.info(f"User: {user_input}")
        messages.append({"role": "user", "content": user_input})

        try:
            with Status("[dim]thinking...[/dim]", console=console, spinner="dots"):
                reply, tool_calls, raw_msg = chat(messages)
        except ConnectionError as e:
            log.error(f"Chat failed: {e}")
            console.print(f"[red]Error:[/red] {e}")
            console.print("[dim]Run: ollama serve[/dim]")
            messages.pop()
            continue

        messages.append(raw_msg)

        if tool_calls:
            tool_messages = run_tool_calls(tool_calls)
            messages.extend(tool_messages)

            try:
                with Status("[dim]thinking...[/dim]", console=console, spinner="dots"):
                    reply, _, raw_followup = chat(messages)
                messages.append(raw_followup)
            except ConnectionError as e:
                log.error(f"Follow-up chat failed: {e}")
                reply = ""

        if reply:
            log.info(f"Jarvis: {reply}")
            console.print(f"\n[bold cyan]Jarvis:[/bold cyan] {reply}")
        elif not tool_calls:
            log.warning("Empty response with no tool calls")
            console.print("[dim]Jarvis: (no response)[/dim]")


if __name__ == "__main__":
    main()
