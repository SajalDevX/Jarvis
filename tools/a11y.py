"""AT-SPI (Linux accessibility) tools via dogtail.

Lets the agent click / type into native widgets WITHOUT cursor movement —
a real synthetic activation routed through the toolkit. ~100ms, deterministic
when the app exposes a11y (GTK, Qt with QT_ACCESSIBILITY=1, native Firefox,
LibreOffice).

Falls back gracefully when AT-SPI bus is unavailable; tools return a string
the LLM can read ("AT-SPI unavailable: <reason>") so the agent can switch
to vision+xdotool fallback.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from logger import log
from tools.base import Tool


# Lazy import — gi/dogtail probe expensive and may fail on systems without
# AT-SPI bus. Module-level None means "not yet attempted".
_DOGTAIL_OK: Optional[bool] = None
_DOGTAIL_ERR: str = ""


def _ensure_dogtail() -> tuple[bool, str]:
    """Returns (ok, err). Imports dogtail/Atspi once, caches result."""
    global _DOGTAIL_OK, _DOGTAIL_ERR
    if _DOGTAIL_OK is not None:
        return _DOGTAIL_OK, _DOGTAIL_ERR
    try:
        import gi  # noqa: F401
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # noqa: F401
        # Disable dogtail's debug spam + config writes
        os.environ.setdefault("DOGTAIL_DISABLE_AUTODETECT", "1")
        os.environ.setdefault("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        # Suppress dogtail's own logger noise
        from dogtail.config import config as _cfg  # type: ignore
        _cfg.logDebugToFile = False
        _cfg.logDebugToStdOut = False
        from dogtail import tree  # noqa: F401
        _DOGTAIL_OK, _DOGTAIL_ERR = True, ""
    except Exception as e:
        _DOGTAIL_OK, _DOGTAIL_ERR = False, f"{type(e).__name__}: {e}"
        log.warning(f"AT-SPI / dogtail unavailable: {_DOGTAIL_ERR}")
    return _DOGTAIL_OK, _DOGTAIL_ERR


def _focused_window():
    """Return the currently-focused dogtail Application's first frame, or None."""
    from dogtail.tree import root
    for app in root.applications():
        try:
            for frame in app.findChildren(lambda n: n.roleName in ("frame", "window") and n.showing):
                return frame
        except Exception:
            continue
    return None


def _find_app_by_match(match: str):
    """Return dogtail Application whose name contains `match` (ci)."""
    from dogtail.tree import root
    target = match.strip().lower()
    for app in root.applications():
        try:
            if target in (app.name or "").lower():
                return app
        except Exception:
            continue
    return None


def _summarize_node(node, max_children: int = 50) -> dict:
    """Walk down a few levels, return a compact dict the LLM can read."""
    seen = 0

    def walk(n, depth: int = 0):
        nonlocal seen
        if depth > 4 or seen >= max_children:
            return None
        seen += 1
        try:
            entry = {
                "role": getattr(n, "roleName", "?") or "?",
                "name": (getattr(n, "name", "") or "")[:60],
            }
            children = []
            try:
                kids = list(n.children)[:max_children - seen]
            except Exception:
                kids = []
            for c in kids:
                w = walk(c, depth + 1)
                if w:
                    children.append(w)
            if children:
                entry["children"] = children
            return entry
        except Exception:
            return None

    return walk(node) or {}


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


class A11yTreeTool(Tool):
    name = "a11y_tree"
    description = (
        "Dump the accessibility tree of the focused window (or named app). "
        "Lists role + name of every visible widget. Use this BEFORE a11y_click "
        "to see what the agent can target. Read-only — never gated."
    )
    parameters = {
        "type": "object",
        "properties": {
            "app_match": {
                "type": "string",
                "description": "Optional: match an app by name substring (e.g. 'firefox'). Default: focused window.",
            }
        },
        "required": [],
    }

    def execute(self, app_match: Optional[str] = None) -> str:
        ok, err = _ensure_dogtail()
        if not ok:
            return f"AT-SPI unavailable: {err}"
        try:
            if app_match:
                app = _find_app_by_match(app_match)
                if app is None:
                    return f"No app matches {app_match!r}"
                node = app
            else:
                node = _focused_window()
                if node is None:
                    return "No focused window found via AT-SPI"
            return json.dumps(_summarize_node(node), separators=(",", ":"))[:4000]
        except Exception as e:
            return f"a11y_tree error: {e}"


class A11yFindTool(Tool):
    name = "a11y_find"
    description = (
        "Locate a widget by role + name in the focused window. "
        "Returns {found, role, name, actions} as JSON. "
        "Roles: 'push button', 'menu item', 'check box', 'text', 'entry', 'link'. "
        "Read-only — never gated. Useful for the agent to verify the target exists "
        "before calling a11y_click."
    )
    parameters = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "AT-SPI role ('push button', 'menu item', etc)."},
            "name": {"type": "string", "description": "Substring of widget name (case-insensitive)."},
            "app_match": {"type": "string", "description": "Optional app name substring."},
        },
        "required": ["role", "name"],
    }

    def execute(self, role: str, name: str, app_match: Optional[str] = None) -> str:
        ok, err = _ensure_dogtail()
        if not ok:
            return f"AT-SPI unavailable: {err}"
        try:
            if app_match:
                root_node = _find_app_by_match(app_match)
                if root_node is None:
                    return json.dumps({"found": False, "reason": f"no app {app_match!r}"})
            else:
                root_node = _focused_window()
                if root_node is None:
                    return json.dumps({"found": False, "reason": "no focused window"})
            target_role = role.lower().strip()
            target_name = name.lower().strip()
            for n in root_node.findChildren(
                lambda x: (x.roleName or "").lower() == target_role
                and target_name in (x.name or "").lower()
            ):
                actions = []
                try:
                    actions = [a for a in (n.actions or {}).keys()]
                except Exception:
                    pass
                return json.dumps({
                    "found": True,
                    "role": n.roleName,
                    "name": n.name,
                    "actions": actions,
                })
            return json.dumps({"found": False, "reason": "no match"})
        except Exception as e:
            return f"a11y_find error: {e}"


def _gate(tool_name: str, kwargs: dict) -> tuple[bool, str]:
    from tools.desktop_actions import _gate_check
    return _gate_check(tool_name, kwargs)


class A11yClickTool(Tool):
    name = "a11y_click"
    description = (
        "Click a widget BY ROLE + NAME using the accessibility action — "
        "no cursor movement, no focus change. Faster and more reliable than "
        "screen_click. Try this BEFORE falling back to ground_element + screen_click."
    )
    parameters = {
        "type": "object",
        "properties": {
            "role": {"type": "string"},
            "name": {"type": "string", "description": "Substring of widget name."},
            "app_match": {"type": "string", "description": "Optional app name substring."},
        },
        "required": ["role", "name"],
    }

    def execute(self, role: str, name: str, app_match: Optional[str] = None) -> str:
        ok, reason = _gate(self.name, {"role": role, "name": name})
        if not ok:
            return reason
        ready, err = _ensure_dogtail()
        if not ready:
            return f"AT-SPI unavailable: {err}"
        try:
            if app_match:
                root_node = _find_app_by_match(app_match)
                if root_node is None:
                    return f"No app matches {app_match!r}"
            else:
                root_node = _focused_window()
                if root_node is None:
                    return "No focused window via AT-SPI"
            target_role = role.lower().strip()
            target_name = name.lower().strip()
            matches = root_node.findChildren(
                lambda x: (x.roleName or "").lower() == target_role
                and target_name in (x.name or "").lower()
            )
            if not matches:
                return f"a11y_click: no {role}={name!r}"
            n = matches[0]
            n.click()  # dogtail wraps action 'click'
            log.info(f"a11y_click: {role}={name!r}")
            return f"Clicked {role}={n.name!r} via AT-SPI"
        except Exception as e:
            return f"a11y_click error: {e}"


class A11yTypeTool(Tool):
    name = "a11y_type"
    description = (
        "Type text into a named entry/text widget via AT-SPI. Sets the widget's "
        "text directly — no cursor, no per-character keystrokes. Faster than "
        "screen_type for forms. Falls back with error if widget not found or "
        "doesn't accept text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "Usually 'entry' or 'text'."},
            "name": {"type": "string", "description": "Substring of widget name."},
            "text": {"type": "string"},
            "app_match": {"type": "string", "description": "Optional app name substring."},
        },
        "required": ["role", "name", "text"],
    }

    def execute(self, role: str, name: str, text: str, app_match: Optional[str] = None) -> str:
        ok, reason = _gate(self.name, {"role": role, "name": name, "text_len": len(text)})
        if not ok:
            return reason
        ready, err = _ensure_dogtail()
        if not ready:
            return f"AT-SPI unavailable: {err}"
        try:
            if app_match:
                root_node = _find_app_by_match(app_match)
                if root_node is None:
                    return f"No app matches {app_match!r}"
            else:
                root_node = _focused_window()
                if root_node is None:
                    return "No focused window via AT-SPI"
            target_role = role.lower().strip()
            target_name = name.lower().strip()
            matches = root_node.findChildren(
                lambda x: (x.roleName or "").lower() == target_role
                and target_name in (x.name or "").lower()
            )
            if not matches:
                return f"a11y_type: no {role}={name!r}"
            n = matches[0]
            try:
                n.text = text  # dogtail setter
            except Exception as e:
                # Some widgets need typeText() (synthesized keystrokes)
                try:
                    n.typeText(text)
                except Exception as e2:
                    return f"a11y_type both methods failed: text={e} | typeText={e2}"
            log.info(f"a11y_type: {role}={name!r} <- {len(text)} chars")
            return f"Typed {len(text)} chars into {role}={n.name!r}"
        except Exception as e:
            return f"a11y_type error: {e}"
