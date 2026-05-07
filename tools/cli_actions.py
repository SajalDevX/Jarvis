"""CLI / D-Bus action tools — fastest layer of DesktopAgent.

One-shot subprocess calls for media, volume, network, window, file/url open.
~1-10ms latency, zero LLM cost when fired via orchestrator direct-dispatch.

All write-tools pass through AutomationGate so the master switch still applies.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from logger import log
from tools.base import Tool


# ---- shared helpers --------------------------------------------------------- #


class CliError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    log.debug(f"$ {' '.join(cmd)}")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise CliError(f"{cmd[0]} not installed") from e
    except subprocess.TimeoutExpired as e:
        raise CliError(f"{cmd[0]} timed out") from e
    if out.returncode != 0:
        raise CliError(f"{cmd[0]} failed ({out.returncode}): {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def _gate(tool_name: str, kwargs: dict) -> tuple[bool, str]:
    from tools.desktop_actions import _gate_check  # reuse the same gate plumbing
    return _gate_check(tool_name, kwargs)


# ---- media (MPRIS) ---------------------------------------------------------- #


_PLAYERCTL = shutil.which("playerctl")


def _mpris_dbus(action: str) -> str:
    """Fallback when playerctl missing. Sends MPRIS command via dbus-send to
    the first running player on the session bus."""
    # List players on the bus
    names = _run(["dbus-send", "--session", "--print-reply",
                  "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                  "org.freedesktop.DBus.ListNames"])
    target = None
    for line in names.splitlines():
        m = re.search(r'"(org\.mpris\.MediaPlayer2\.[^"]+)"', line)
        if m:
            target = m.group(1)
            break
    if target is None:
        raise CliError("no MPRIS player running")
    method = {"play": "Play", "pause": "Pause", "playpause": "PlayPause",
              "next": "Next", "prev": "Previous", "previous": "Previous",
              "stop": "Stop"}.get(action.lower())
    if method is None:
        raise CliError(f"unknown media action: {action}")
    _run(["dbus-send", "--session", "--print-reply",
          f"--dest={target}", "/org/mpris/MediaPlayer2",
          f"org.mpris.MediaPlayer2.Player.{method}"])
    return f"{method} on {target.rsplit('.', 1)[-1]}"


class MediaControlTool(Tool):
    name = "media_control"
    description = (
        "Control any running media player (Spotify, VLC, browser audio) via MPRIS. "
        "Actions: play, pause, playpause, next, prev, stop. ~10ms, no GUI."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["play", "pause", "playpause", "next", "prev", "stop"]},
        },
        "required": ["action"],
    }

    def execute(self, action: str) -> str:
        ok, reason = _gate(self.name, {"action": action})
        if not ok:
            return reason
        try:
            if _PLAYERCTL:
                _run([_PLAYERCTL, action.replace("prev", "previous")])
                return f"playerctl {action}"
            return _mpris_dbus(action)
        except CliError as e:
            return f"CliError: {e}"


# ---- volume (PipeWire / wpctl) --------------------------------------------- #


_WPCTL = shutil.which("wpctl")


def _set_volume(percent: int) -> str:
    if not _WPCTL:
        raise CliError("wpctl not installed (PipeWire only)")
    pct = max(0, min(int(percent), 150))
    _run([_WPCTL, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{pct/100:.2f}"])
    return f"volume {pct}%"


def _set_mute(state: bool) -> str:
    if not _WPCTL:
        raise CliError("wpctl not installed")
    _run([_WPCTL, "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if state else "0"])
    return "muted" if state else "unmuted"


class VolumeSetTool(Tool):
    name = "volume_set"
    description = "Set master output volume (0-150 percent). PipeWire/wpctl."
    parameters = {
        "type": "object",
        "properties": {"percent": {"type": "integer", "description": "Volume 0-150."}},
        "required": ["percent"],
    }

    def execute(self, percent: int) -> str:
        ok, reason = _gate(self.name, {"percent": percent})
        if not ok:
            return reason
        try:
            return _set_volume(percent)
        except CliError as e:
            return f"CliError: {e}"


class VolumeMuteTool(Tool):
    name = "volume_mute"
    description = "Mute or unmute master output. state=true mutes; false unmutes."
    parameters = {
        "type": "object",
        "properties": {"state": {"type": "boolean"}},
        "required": ["state"],
    }

    def execute(self, state: bool) -> str:
        ok, reason = _gate(self.name, {"state": state})
        if not ok:
            return reason
        try:
            return _set_mute(bool(state))
        except CliError as e:
            return f"CliError: {e}"


# ---- network --------------------------------------------------------------- #


_NMCLI = shutil.which("nmcli")


class WifiToggleTool(Tool):
    name = "wifi_toggle"
    description = "Turn Wi-Fi on or off via NetworkManager."
    parameters = {
        "type": "object",
        "properties": {"state": {"type": "string", "enum": ["on", "off"]}},
        "required": ["state"],
    }

    def execute(self, state: str) -> str:
        ok, reason = _gate(self.name, {"state": state})
        if not ok:
            return reason
        if not _NMCLI:
            return "CliError: nmcli not installed"
        try:
            _run([_NMCLI, "radio", "wifi", state.lower()])
            return f"Wi-Fi {state}"
        except CliError as e:
            return f"CliError: {e}"


class BluetoothToggleTool(Tool):
    name = "bluetooth_toggle"
    description = "Power Bluetooth radio on or off."
    parameters = {
        "type": "object",
        "properties": {"state": {"type": "string", "enum": ["on", "off"]}},
        "required": ["state"],
    }

    def execute(self, state: str) -> str:
        ok, reason = _gate(self.name, {"state": state})
        if not ok:
            return reason
        bctl = shutil.which("bluetoothctl")
        if not bctl:
            return "CliError: bluetoothctl not installed"
        try:
            _run([bctl, "power", "on" if state.lower() == "on" else "off"])
            return f"Bluetooth {state}"
        except CliError as e:
            return f"CliError: {e}"


# ---- xdg-open / app launchers --------------------------------------------- #


_XDG_OPEN = shutil.which("xdg-open")


class XdgOpenTool(Tool):
    name = "xdg_open"
    description = (
        "Open a URL or file path with its default application. "
        "Faster and more reliable than clicking through a browser address bar. "
        "Examples: 'https://youtube.com', '/home/user/doc.pdf', 'mailto:x@y.com'."
    )
    parameters = {
        "type": "object",
        "properties": {"target": {"type": "string"}},
        "required": ["target"],
    }

    def execute(self, target: str) -> str:
        ok, reason = _gate(self.name, {"target": target})
        if not ok:
            return reason
        if not _XDG_OPEN:
            return "CliError: xdg-open not installed"
        try:
            # xdg-open detaches; don't wait for it
            subprocess.Popen(
                [_XDG_OPEN, target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return f"Opened {target}"
        except Exception as e:
            return f"CliError: {e}"


# ---- window / workspace management ---------------------------------------- #


_WMCTRL = shutil.which("wmctrl")


class WindowResizeTool(Tool):
    name = "window_resize"
    description = "Resize the active window. Width/height in pixels. Negative values keep current."
    parameters = {
        "type": "object",
        "properties": {
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
        "required": ["width", "height"],
    }

    def execute(self, width: int, height: int) -> str:
        ok, reason = _gate(self.name, {"width": width, "height": height})
        if not ok:
            return reason
        if not _WMCTRL:
            return "CliError: wmctrl not installed"
        try:
            _run([_WMCTRL, "-r", ":ACTIVE:", "-e", f"0,-1,-1,{int(width)},{int(height)}"])
            return f"Resized to {width}x{height}"
        except CliError as e:
            return f"CliError: {e}"


class WindowMoveTool(Tool):
    name = "window_move"
    description = "Move the active window to (x, y)."
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["x", "y"],
    }

    def execute(self, x: int, y: int) -> str:
        ok, reason = _gate(self.name, {"x": x, "y": y})
        if not ok:
            return reason
        if not _WMCTRL:
            return "CliError: wmctrl not installed"
        try:
            _run([_WMCTRL, "-r", ":ACTIVE:", "-e", f"0,{int(x)},{int(y)},-1,-1"])
            return f"Moved to ({x}, {y})"
        except CliError as e:
            return f"CliError: {e}"


class WorkspaceSwitchTool(Tool):
    name = "workspace_switch"
    description = "Switch to a workspace by 0-based index."
    parameters = {
        "type": "object",
        "properties": {"index": {"type": "integer"}},
        "required": ["index"],
    }

    def execute(self, index: int) -> str:
        ok, reason = _gate(self.name, {"index": index})
        if not ok:
            return reason
        if not _WMCTRL:
            return "CliError: wmctrl not installed"
        try:
            _run([_WMCTRL, "-s", str(int(index))])
            return f"Switched to workspace {index}"
        except CliError as e:
            return f"CliError: {e}"
