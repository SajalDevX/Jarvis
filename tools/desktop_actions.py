"""Tool subclasses for desktop control. Wire each to Input + AutomationGate.

Tools (Anthropic computer-use vocab, X11 backend via xdotool):
  screen_screenshot, screen_click, screen_double_click, screen_right_click,
  screen_type, screen_key, screen_scroll, screen_drag, screen_mouse_move,
  screen_zoom, screen_wait

Plus tools.ground.GroundElementTool for pixel grounding (registered separately).

Each action takes a fresh post-screenshot via SCREEN.capture() so the next
LLM step sees what changed. zoom returns a cropped region path.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from logger import log
from safety.automation import AutomationGate
from tools.base import Tool
from tools.desktop_input import Input, InputError
from vision.screen_state import SCREEN


# Singletons — shared across all action tool instances.
_INPUT: Input | None = None
_GATE: AutomationGate | None = None


def get_input() -> Input:
    global _INPUT
    if _INPUT is None:
        _INPUT = Input()
    return _INPUT


def get_gate() -> AutomationGate:
    global _GATE
    if _GATE is None:
        _GATE = AutomationGate()
        _GATE.reset_budget()
    return _GATE


def _post_action_capture(wait_ms: int = 200) -> None:
    """Brief pause for paint, then refresh the screen-state singleton."""
    time.sleep(wait_ms / 1000.0)
    try:
        SCREEN.capture()
    except Exception as e:
        log.warning(f"post-action capture failed: {e}")


def _active_class() -> str:
    """Best-effort active-window class for the gate. Empty on failure."""
    try:
        from vision.window_info import active_window_info
        info = active_window_info()
        return (info.get("app") or info.get("wm_class") or "").lower()
    except Exception:
        return ""


def _gate_check(tool_name: str, kwargs: dict, nearby_text: str = "") -> tuple[bool, str]:
    """Run the gate. Returns (proceed, reason). reason is the message
    to show the agent when refused / dry-run / confirmed."""
    g = get_gate()
    res = g.check(
        tool_name,
        kwargs,
        active_window_class=_active_class(),
        nearby_text=nearby_text,
    )
    log.debug(f"gate({tool_name}): {res.decision} {res.reason}")
    if res.decision == "allow":
        return True, ""
    if res.decision == "dry_run":
        return False, f"DRY-RUN: would have run {tool_name}({kwargs}). {res.reason}"
    if res.decision == "refuse":
        return False, f"REFUSED: {res.reason}"
    if res.decision == "confirm":
        # First-pass: refuse but tell agent to surface confirmation. Real
        # confirm-prompt UX is wired by the orchestrator/agent later.
        return False, f"CONFIRM-NEEDED: {res.prompt} ({res.reason})"
    return False, f"UNKNOWN: {res.decision}"


# --------------------------------------------------------------------------- #
# Read-only tools
# --------------------------------------------------------------------------- #


class ScreenScreenshotTool(Tool):
    name = "screen_screenshot"
    description = (
        "Capture the current screen and refresh the cached screenshot the "
        "vision tools see. Use sparingly — most actions auto-capture afterwards."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self) -> str:
        info = SCREEN.capture()
        return f"Captured {info['path']} ({info.get('width','?')}x{info.get('height','?')})"


class ScreenWaitTool(Tool):
    name = "screen_wait"
    description = (
        "Pause for a short time (max 5s). Use after an action when waiting for "
        "an animation or page load before re-grounding."
    )
    parameters = {
        "type": "object",
        "properties": {"ms": {"type": "integer", "description": "Milliseconds to wait, 0-5000."}},
        "required": ["ms"],
    }

    def execute(self, ms: int) -> str:
        ms = max(0, min(int(ms), 5000))
        time.sleep(ms / 1000.0)
        return f"Waited {ms}ms"


class ScreenZoomTool(Tool):
    name = "screen_zoom"
    description = (
        "Crop a rectangular region of the latest screenshot for higher detail. "
        "Use when ground_element returns low confidence or when you need to read "
        "small text. Coordinates are pixels in the FULL screen. Returns the "
        "cropped image path; subsequent ground_element will use the full image, "
        "so use this primarily for self-inspection / OCR."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x1": {"type": "integer"},
            "y1": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
        },
        "required": ["x1", "y1", "x2", "y2"],
    }

    def execute(self, x1: int, y1: int, x2: int, y2: int) -> str:
        path = SCREEN.latest_path()
        if path is None:
            SCREEN.capture()
            path = SCREEN.latest_path()
        if path is None:
            return "No screenshot available."
        with Image.open(path) as im:
            x1, y1, x2, y2 = sorted([x1, x2])[0], sorted([y1, y2])[0], sorted([x1, x2])[1], sorted([y1, y2])[1]
            x1 = max(0, x1); y1 = max(0, y1)
            x2 = min(im.width, x2); y2 = min(im.height, y2)
            if x2 <= x1 or y2 <= y1:
                return "Empty crop region."
            crop = im.crop((x1, y1, x2, y2))
            out = Path(path).with_suffix(".zoom.png")
            crop.save(out)
        return f"Zoomed region {x1},{y1}->{x2},{y2} saved to {out} ({crop.width}x{crop.height})"


# --------------------------------------------------------------------------- #
# Pointer / click tools
# --------------------------------------------------------------------------- #


def _ocr_near(x: int, y: int, radius: int = 80) -> str:
    """Best-effort OCR of a box around (x,y) for destructive-keyword detection."""
    try:
        import pytesseract
        path = SCREEN.latest_path()
        if path is None:
            return ""
        with Image.open(path) as im:
            x1 = max(0, x - radius * 2); y1 = max(0, y - radius)
            x2 = min(im.width, x + radius * 2); y2 = min(im.height, y + radius)
            crop = im.crop((x1, y1, x2, y2))
        return pytesseract.image_to_string(crop) or ""
    except Exception as e:
        log.debug(f"ocr_near failed: {e}")
        return ""


class ScreenClickTool(Tool):
    name = "screen_click"
    description = (
        "Left-click at pixel coordinates. ALWAYS call ground_element first to "
        "get coords — never invent them. After click, the screen is captured "
        "automatically; observe the new screenshot before the next action."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["x", "y"],
    }

    def execute(self, x: int, y: int) -> str:
        kwargs = {"x": x, "y": y}
        nearby = _ocr_near(x, y)
        ok, reason = _gate_check(self.name, kwargs, nearby_text=nearby)
        if not ok:
            return reason
        try:
            get_input().click(int(x), int(y))
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture()
        return f"Clicked ({x}, {y})."


class ScreenDoubleClickTool(Tool):
    name = "screen_double_click"
    description = "Double-click at pixel coordinates. Same rules as screen_click."
    parameters = ScreenClickTool.parameters

    def execute(self, x: int, y: int) -> str:
        ok, reason = _gate_check(self.name, {"x": x, "y": y}, nearby_text=_ocr_near(x, y))
        if not ok:
            return reason
        try:
            get_input().double_click(int(x), int(y))
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture()
        return f"Double-clicked ({x}, {y})."


class ScreenRightClickTool(Tool):
    name = "screen_right_click"
    description = "Right-click (context menu) at pixel coordinates."
    parameters = ScreenClickTool.parameters

    def execute(self, x: int, y: int) -> str:
        ok, reason = _gate_check(self.name, {"x": x, "y": y}, nearby_text=_ocr_near(x, y))
        if not ok:
            return reason
        try:
            get_input().right_click(int(x), int(y))
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture()
        return f"Right-clicked ({x}, {y})."


class ScreenMouseMoveTool(Tool):
    name = "screen_mouse_move"
    description = "Move the cursor to (x, y) without clicking. Useful for hover effects."
    parameters = ScreenClickTool.parameters

    def execute(self, x: int, y: int) -> str:
        ok, reason = _gate_check(self.name, {"x": x, "y": y})
        if not ok:
            return reason
        try:
            get_input().mouse_move(int(x), int(y))
        except InputError as e:
            return f"InputError: {e}"
        return f"Moved cursor to ({x}, {y})."


class ScreenDragTool(Tool):
    name = "screen_drag"
    description = (
        "Press, drag, release: left-button drag from (x1, y1) to (x2, y2). "
        "Use ground_element for both endpoints when feasible."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x1": {"type": "integer"},
            "y1": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
        },
        "required": ["x1", "y1", "x2", "y2"],
    }

    def execute(self, x1: int, y1: int, x2: int, y2: int) -> str:
        ok, reason = _gate_check(self.name, {"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        if not ok:
            return reason
        try:
            get_input().drag(int(x1), int(y1), int(x2), int(y2))
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture()
        return f"Dragged ({x1},{y1}) -> ({x2},{y2})."


class ScreenScrollTool(Tool):
    name = "screen_scroll"
    description = "Scroll the focused window. direction: up|down|left|right; amount = wheel ticks (1-50)."
    parameters = {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "integer", "description": "Wheel ticks, 1-50.", "default": 3},
        },
        "required": ["direction"],
    }

    def execute(self, direction: str, amount: int = 3) -> str:
        ok, reason = _gate_check(self.name, {"direction": direction, "amount": amount})
        if not ok:
            return reason
        try:
            get_input().scroll(direction, int(amount))
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture()
        return f"Scrolled {direction} x{amount}."


# --------------------------------------------------------------------------- #
# Keyboard
# --------------------------------------------------------------------------- #


class ScreenTypeTool(Tool):
    name = "screen_type"
    description = (
        "Type literal text into the focused widget. Click the target field "
        "first via screen_click. Do not include trailing newline — use "
        "screen_key('Return') instead."
    )
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, text: str) -> str:
        ok, reason = _gate_check(self.name, {"text_len": len(text)})
        if not ok:
            return reason
        try:
            get_input().type(text)
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture(wait_ms=120)
        return f"Typed {len(text)} chars."


class ScreenKeyTool(Tool):
    name = "screen_key"
    description = (
        "Press a key or chord. Examples: 'Return', 'Escape', 'ctrl+c', "
        "'ctrl+shift+t', 'super+l', 'Tab', 'BackSpace'. Uses xdotool key syntax."
    )
    parameters = {
        "type": "object",
        "properties": {"combo": {"type": "string"}},
        "required": ["combo"],
    }

    def execute(self, combo: str) -> str:
        ok, reason = _gate_check(self.name, {"combo": combo})
        if not ok:
            return reason
        try:
            get_input().key(combo)
        except InputError as e:
            return f"InputError: {e}"
        _post_action_capture(wait_ms=120)
        return f"Pressed {combo}."
