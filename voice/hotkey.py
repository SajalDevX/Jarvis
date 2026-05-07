"""Global push-to-talk hotkey via pynput. Default: Ctrl+Space."""
from __future__ import annotations

import threading
from typing import Callable

from logger import log


class HotkeyListener:
    def __init__(self, hotkey: str = "<ctrl>+<space>"):
        self.hotkey = hotkey
        self._listener = None

    def start(self, on_release_edge: Callable[[], None]):
        from pynput import keyboard

        def fire():
            log.debug(f"Hotkey {self.hotkey} released → triggering")
            threading.Thread(target=on_release_edge, daemon=True).start()

        # GlobalHotKeys fires on full chord match. We treat as edge.
        self._listener = keyboard.GlobalHotKeys({self.hotkey: fire})
        self._listener.start()
        log.info(f"Hotkey listener started: {self.hotkey}")

    def stop(self):
        if self._listener:
            self._listener.stop()
            log.info("Hotkey listener stopped")
