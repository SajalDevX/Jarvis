#!/usr/bin/env python3
import os
import sys
import warnings
from contextlib import contextmanager

# Quiet noisy import-time output (ALSA/JACK/transformers/deprecations)
# unless JARVIS_DEBUG=1.
_QUIET = not os.environ.get("JARVIS_DEBUG")
if _QUIET:
    warnings.filterwarnings("ignore")
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")


@contextmanager
def _silence_stderr():
    """Temporarily redirect raw stderr fd to /dev/null (silences C libs too)."""
    if not _QUIET:
        yield
        return
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
        os.dup2(devnull, 2)
        try:
            yield
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            os.close(devnull)
    except Exception:
        yield


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


def _parse_voice_mode(argv: list[str]) -> str:
    """CLI flag --voice {off|hotkey|wake|both} overrides JARVIS_VOICE_MODE env."""
    for i, a in enumerate(argv):
        if a == "--voice" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--voice="):
            return a.split("=", 1)[1]
    return config.JARVIS_VOICE_MODE


def main():
    voice_mode = _parse_voice_mode(sys.argv[1:])

    log.info(f"Jarvis starting — offline={config.MODEL}, online={config.OPENROUTER_MODEL}, voice={voice_mode}")

    online = is_online()
    mode = (
        f"[green]online[/green] → {config.OPENROUTER_MODEL}"
        if online else f"[yellow]offline[/yellow] → {config.MODEL}"
    )

    voice_label = f"[magenta]voice:{voice_mode}[/magenta]" if voice_mode != "off" else "[dim]text only[/dim]"
    console.print(Panel(
        f"[bold cyan]Jarvis CLI[/bold cyan]\n"
        f"[dim]Mode: {mode}[/dim]   {voice_label}\n"
        f"[dim]Logs → {LOG_FILE}[/dim]\n"
        "[dim]Ctrl+C to exit. /reset to clear history.[/dim]",
        expand=False,
    ))

    orchestrator = Orchestrator()
    on_tool = make_tool_callback()

    # Voice mode: hand off to a voice runtime instead of text loop.
    # Pipecat path (sub-second target) requires Groq + ElevenLabs + online.
    # Otherwise fall back to the legacy capture/STT/TTS loop.
    if voice_mode != "off":
        use_pipecat = (
            online
            and bool(config.GROQ_API_KEY)
            and bool(config.ELEVENLABS_API_KEY)
        )
        try:
            if use_pipecat:
                console.print("[dim]Voice runtime: [bold green]pipecat[/bold green] (Groq STT + Groq LLM + ElevenLabs WS TTS)[/dim]")
                from voice.pipecat_runtime import PipecatVoiceRuntime
                PipecatVoiceRuntime(orchestrator, console=console, quiet=_QUIET).run()
            else:
                console.print("[dim]Voice runtime: [yellow]legacy[/yellow] (offline / missing keys)[/dim]")
                from voice.runtime import VoiceRuntime
                VoiceRuntime(orchestrator, mode=voice_mode).run(console=console)
        except KeyboardInterrupt:
            console.print("\n[dim]Bye.[/dim]")
        return

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
