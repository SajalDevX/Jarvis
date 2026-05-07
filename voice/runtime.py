"""Voice runtime — wires hotkey + wake-word to capture → STT → orchestrator → TTS.

All existing tool calls (open_app, smart_open_app, vision tools, etc.) work
exactly as in text mode — the agent loop is unchanged. Only I/O channels swap.
"""
from __future__ import annotations

import threading
import time

from logger import log
from voice import capture, stt, tts


class VoiceRuntime:
    def __init__(self, orchestrator, mode: str = "both"):
        self.orch = orchestrator
        self.mode = mode  # "hotkey" | "wake" | "both"
        self._busy = threading.Lock()
        self._stop = threading.Event()
        self._wake = None
        self._hotkey = None

    def _make_voice_cb(self, console):
        def cb(name, args, result):
            if console:
                console.print(f"  [green]✓[/green] [dim]{name}[/dim] → {result}")
        return cb

    def _on_trigger(self, console=None):
        """Single user-turn cycle: capture → STT → orchestrator → TTS."""
        if not self._busy.acquire(blocking=False):
            log.info("Already processing a turn — ignoring trigger")
            return
        try:
            t0 = time.time()
            # Stop any ongoing TTS (barge-in)
            tts.request_stop()
            time.sleep(0.05)

            wav = capture.record_until_silence()
            if not wav:
                log.info("Empty capture, skipping")
                return
            t_cap = time.time() - t0

            user_text = stt.transcribe(wav, language="en")
            if not user_text:
                log.info("STT empty, skipping")
                return
            t_stt = time.time() - t0

            if console:
                console.print(f"\n[bold]You:[/bold] {user_text}")

            agent_name, reply = self.orch.handle(
                user_text,
                on_tool_call=self._make_voice_cb(console),
                voice=True,
            )
            t_agent = time.time() - t0

            if reply:
                if console:
                    console.print(f"[bold cyan]Jarvis[/bold cyan] [dim]({agent_name})[/dim]: {reply}")
                tts.speak(reply)

            log.info(
                f"Voice turn: cap={t_cap:.2f}s stt={t_stt:.2f}s "
                f"agent={t_agent - t_stt:.2f}s total={time.time()-t0:.2f}s"
            )
        except Exception as e:
            log.error(f"Voice turn failed: {e}", exc_info=True)
        finally:
            self._busy.release()

    def run(self, console=None):
        """Block until user kills the process."""
        from config import JARVIS_HOTKEY, JARVIS_WAKE_MODEL

        trigger = lambda: self._on_trigger(console)

        if self.mode in ("hotkey", "both"):
            from voice.hotkey import HotkeyListener
            self._hotkey = HotkeyListener(JARVIS_HOTKEY)
            self._hotkey.start(on_release_edge=trigger)

        if self.mode in ("wake", "both"):
            from voice.wake import WakeListener
            self._wake = WakeListener(JARVIS_WAKE_MODEL)
            self._wake.start(on_wake=trigger)

        if console:
            console.print(f"[dim]Voice mode '[bold]{self.mode}[/bold]' active.[/dim]")
            if self.mode in ("hotkey", "both"):
                console.print(f"[dim]Press {JARVIS_HOTKEY} to talk.[/dim]")
            if self.mode in ("wake", "both"):
                console.print(f"[dim]Or say '{JARVIS_WAKE_MODEL.replace('_', ' ').replace('hey jarvis v0 1', 'Hey Jarvis')}'[/dim]")

        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            if self._hotkey:
                self._hotkey.stop()
            if self._wake:
                self._wake.stop()
