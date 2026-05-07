"""Thin wrapper around xdotool for X11 desktop control.

All methods raise InputError on failure. Coordinates are screen pixels.
Caller is responsible for safety / allowlist gating — this layer is dumb.

Wayland sessions are detected and refused with a clear message; ydotool
support can be wired later as a backend swap.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable

from logger import log


class InputError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScreenGeometry:
    width: int
    height: int


def _xdotool(*args: str, timeout: float = 3.0) -> str:
    cmd = ["xdotool", *args]
    log.debug(f"xdotool: {' '.join(cmd)}")
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise InputError("xdotool not installed (apt install xdotool)") from e
    except subprocess.TimeoutExpired as e:
        raise InputError(f"xdotool timed out: {' '.join(cmd)}") from e
    if out.returncode != 0:
        raise InputError(f"xdotool failed ({out.returncode}): {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def _xrandr_primary_geometry() -> ScreenGeometry:
    """Best-effort primary screen size via xrandr; falls back to xdotool getdisplaygeometry."""
    if shutil.which("xrandr"):
        try:
            out = subprocess.run(
                ["xrandr", "--current"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout
            for line in out.splitlines():
                if " primary " in line:
                    # e.g. "eDP-1 connected primary 1920x1080+0+0 (...)"
                    for tok in line.split():
                        if "x" in tok and "+" in tok:
                            wh = tok.split("+", 1)[0]
                            w, h = wh.split("x")
                            return ScreenGeometry(int(w), int(h))
        except Exception:
            pass
    try:
        out = _xdotool("getdisplaygeometry")
        w, h = out.split()
        return ScreenGeometry(int(w), int(h))
    except Exception:
        return ScreenGeometry(1920, 1080)


class Input:
    """X11 input via xdotool. One instance per session; reads geometry once."""

    def __init__(self):
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session and session != "x11":
            raise InputError(
                f"Display server is '{session}', not X11. xdotool only works on X11; "
                "use ydotool backend for Wayland (not yet implemented)."
            )
        if not shutil.which("xdotool"):
            raise InputError("xdotool not installed (apt install xdotool)")
        self.geometry = _xrandr_primary_geometry()
        log.info(f"Input: screen geometry = {self.geometry.width}x{self.geometry.height}")

    def _check_bounds(self, x: int, y: int) -> None:
        if not (0 <= x < self.geometry.width and 0 <= y < self.geometry.height):
            raise InputError(
                f"({x}, {y}) outside screen ({self.geometry.width}x{self.geometry.height})"
            )

    # --- mouse ---

    def mouse_move(self, x: int, y: int) -> None:
        self._check_bounds(x, y)
        _xdotool("mousemove", str(x), str(y))

    def click(self, x: int, y: int, button: int = 1) -> None:
        self._check_bounds(x, y)
        _xdotool("mousemove", str(x), str(y), "click", str(button))

    def double_click(self, x: int, y: int) -> None:
        self._check_bounds(x, y)
        _xdotool("mousemove", str(x), str(y), "click", "--repeat", "2", "--delay", "80", "1")

    def right_click(self, x: int, y: int) -> None:
        self.click(x, y, button=3)

    def middle_click(self, x: int, y: int) -> None:
        self.click(x, y, button=2)

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._check_bounds(x1, y1)
        self._check_bounds(x2, y2)
        _xdotool(
            "mousemove", str(x1), str(y1),
            "mousedown", "1",
            "mousemove", str(x2), str(y2),
            "mouseup", "1",
        )

    def scroll(self, direction: str, amount: int = 3) -> None:
        """direction: up|down|left|right; amount = number of wheel ticks."""
        button = {"up": 4, "down": 5, "left": 6, "right": 7}.get(direction.lower())
        if button is None:
            raise InputError(f"unknown scroll direction: {direction}")
        if amount < 1 or amount > 50:
            raise InputError(f"scroll amount {amount} out of range [1,50]")
        _xdotool("click", "--repeat", str(amount), "--delay", "30", str(button))

    # --- keyboard ---

    def type(self, text: str, delay_ms: int = 12) -> None:
        if not text:
            return
        # xdotool type --clearmodifiers handles modifier-key contamination
        _xdotool("type", "--clearmodifiers", "--delay", str(delay_ms), text, timeout=10.0)

    def key(self, combo: str) -> None:
        """Single key or chord, e.g. 'Return', 'ctrl+c', 'super+l'."""
        if not combo:
            raise InputError("empty key combo")
        # xdotool accepts the chord as one token
        _xdotool("key", "--clearmodifiers", combo)

    def keys(self, combos: Iterable[str]) -> None:
        for c in combos:
            self.key(c)
