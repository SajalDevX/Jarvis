"""Fast window introspection — what app is in focus, window title, geometry.

Uses xdotool + xprop. ~10-50ms total. No LLM cost.
"""
from __future__ import annotations

import shutil
import subprocess

from logger import log


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def active_window_info() -> dict:
    """Return {title, app, class, pid, geometry} for the currently focused window.

    All fields best-effort; missing tools just leave fields empty.
    """
    out: dict = {
        "title": "",
        "app": "",
        "wm_class": "",
        "pid": "",
        "geometry": "",
    }

    if not shutil.which("xdotool"):
        log.debug("xdotool not in PATH")
        return out

    wid = _run(["xdotool", "getactivewindow"])
    if not wid:
        return out

    out["title"] = _run(["xdotool", "getwindowname", wid])
    out["pid"] = _run(["xdotool", "getwindowpid", wid])
    out["geometry"] = _run(["xdotool", "getwindowgeometry", wid])

    # WM_CLASS via xprop tells us the app — most reliable
    if shutil.which("xprop"):
        wm_class = _run(["xprop", "-id", wid, "WM_CLASS"])
        # Format: WM_CLASS(STRING) = "instance", "Class"
        if "=" in wm_class:
            parts = wm_class.split("=", 1)[1].strip().strip('"').split('", "')
            if len(parts) >= 2:
                out["wm_class"] = parts[1].rstrip('"')
                out["app"] = parts[1].rstrip('"')

    # Fallback: derive app from process command
    if not out["app"] and out["pid"]:
        cmd = _run(["ps", "-p", out["pid"], "-o", "comm="])
        if cmd:
            out["app"] = cmd

    return out


def list_windows() -> list[dict]:
    """List all open windows (title + window id). Uses wmctrl when available."""
    if not shutil.which("wmctrl"):
        return []
    raw = _run(["wmctrl", "-l"])
    windows = []
    for line in raw.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 4:
            windows.append({"id": parts[0], "desktop": parts[1], "host": parts[2], "title": parts[3]})
    return windows
