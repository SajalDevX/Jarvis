"""Browser automation via Playwright + Chrome DevTools Protocol.

Strategy: launch user's installed Chrome with a debug port + chosen profile,
or attach to a running Chrome that already has the port open. Sessions persist
in the user-data-dir, so cookies/logins survive across launches.

All actions go through Playwright's accessibility-aware locators (CSS, role,
text) — far more reliable than pixel coords on web apps.

Tools:
  browser_list_profiles()           — read ~/.config/google-chrome/Local State
  browser_launch(profile)           — start Chrome with --remote-debugging-port
  browser_attach()                  — connect to existing :9222
  browser_goto(url)                 — navigate
  browser_click(target)             — selector OR visible text
  browser_type(target, text)        — fill text into a field
  browser_press(key)                — press a key (Enter, Tab, ...)
  browser_snapshot()                — return Playwright a11y tree (LLM picks selector)
  browser_close()                   — close the connection (Chrome stays running)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from logger import log
from tools.base import Tool


_DEFAULT_PORT = int(os.environ.get("JARVIS_CHROME_DEBUG_PORT", "9222"))
_DEFAULT_USER_DATA_DIR = os.path.expanduser(
    os.environ.get("JARVIS_CHROME_USER_DATA_DIR", "~/.config/google-chrome")
)


# --------------------------------------------------------------------------- #
# Singleton state
# --------------------------------------------------------------------------- #


class _BrowserState:
    """Lazily-managed Playwright + browser handle. One instance per process."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def attached(self) -> bool:
        return self._browser is not None

    def _ensure_pw(self):
        if self._pw is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
        return self._pw

    def attach(self, port: int = _DEFAULT_PORT) -> str:
        pw = self._ensure_pw()
        try:
            self._browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as e:
            return f"CDP attach failed on :{port} ({e}). Launch Chrome with --remote-debugging-port first."
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context()
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        log.info(f"browser: attached to CDP :{port}")
        return f"Attached to Chrome on :{port}"

    def page(self):
        if self._page is None:
            raise RuntimeError("Browser not attached. Call browser_launch or browser_attach first.")
        return self._page

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None


_STATE = _BrowserState()


def _load_profiles() -> dict[str, str]:
    """Map display-name -> profile-directory (e.g. 'Sajal (work)' -> 'Profile 3')."""
    local_state = Path(_DEFAULT_USER_DATA_DIR) / "Local State"
    if not local_state.exists():
        return {}
    try:
        raw = json.loads(local_state.read_text())
    except Exception:
        return {}
    cache = raw.get("profile", {}).get("info_cache", {})
    mapping: dict[str, str] = {}
    for dir_name, info in cache.items():
        display = info.get("name") or dir_name
        user = info.get("user_name") or ""
        key = f"{display} ({user})" if user else display
        mapping[key] = dir_name
        # Also expose by username and dir alone for fuzzy matching
        if user:
            mapping[user] = dir_name
        mapping[dir_name] = dir_name
    return mapping


def _resolve_profile(name: str) -> Optional[str]:
    """Fuzzy-match a profile name → profile-directory string."""
    if not name:
        return None
    profiles = _load_profiles()
    if name in profiles:
        return profiles[name]
    n = name.lower()
    for k, v in profiles.items():
        if n in k.lower():
            return v
    return None


def _is_port_open(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def _gate(tool_name: str, kwargs: dict) -> tuple[bool, str]:
    from tools.desktop_actions import _gate_check
    return _gate_check(tool_name, kwargs)


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


class BrowserListProfilesTool(Tool):
    name = "browser_list_profiles"
    description = (
        "List Chrome profiles available on this system. Read-only — never gated. "
        "Returns JSON mapping display-name → profile-directory."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self) -> str:
        profiles = _load_profiles()
        if not profiles:
            return "No Chrome profiles found at " + _DEFAULT_USER_DATA_DIR
        # Deduplicate display names (we put multiple keys into mapping for fuzzy match)
        seen: dict[str, str] = {}
        for k, v in profiles.items():
            if v not in seen.values() and "(" in k:
                seen[k] = v
        return json.dumps(seen, separators=(",", ":"))


class BrowserLaunchTool(Tool):
    name = "browser_launch"
    description = (
        "Launch Chrome with a specific profile and debug port (default 9222), then "
        "attach Playwright. Reuses the running Chrome if the port is already open. "
        "profile is fuzzy-matched against display name, email, or directory."
    )
    parameters = {
        "type": "object",
        "properties": {
            "profile": {
                "type": "string",
                "description": "Profile name, email, or directory ('Default', 'Profile 3', 'sajal@x.com').",
            },
            "url": {
                "type": "string",
                "description": "Optional initial URL to load.",
            },
        },
        "required": [],
    }

    def execute(self, profile: Optional[str] = None, url: Optional[str] = None) -> str:
        ok, reason = _gate(self.name, {"profile": profile})
        if not ok:
            return reason
        port = _DEFAULT_PORT
        # Already running with debug port → just attach
        if _is_port_open(port):
            msg = _STATE.attach(port)
            if profile:
                msg += " (note: existing Chrome may not match requested profile — change profile via browser UI)"
            if url:
                _STATE.page().goto(url, timeout=15000)
                msg += f"; navigated to {url}"
            return msg
        # Launch fresh Chrome with the chosen profile
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            return "google-chrome / chromium not installed"
        profile_dir = _resolve_profile(profile or "Default") or "Default"
        cmd = [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={_DEFAULT_USER_DATA_DIR}",
            f"--profile-directory={profile_dir}",
            "--restore-last-session",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if url:
            cmd.append(url)
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return f"launch failed: {e}"
        # Wait up to 8s for the debug port to come up
        deadline = time.time() + 8.0
        while time.time() < deadline and not _is_port_open(port):
            time.sleep(0.25)
        if not _is_port_open(port):
            return f"Chrome launched but :{port} did not open in 8s. Check chrome flags."
        attached = _STATE.attach(port)
        return f"Launched Chrome profile {profile_dir!r}; {attached}"


class BrowserAttachTool(Tool):
    name = "browser_attach"
    description = (
        "Attach Playwright to a Chrome already running with --remote-debugging-port. "
        "Use after browser_launch, or when the user manually started Chrome with the port."
    )
    parameters = {
        "type": "object",
        "properties": {"port": {"type": "integer"}},
        "required": [],
    }

    def execute(self, port: int = _DEFAULT_PORT) -> str:
        ok, reason = _gate(self.name, {"port": port})
        if not ok:
            return reason
        if not _is_port_open(port):
            return f"Nothing listening on :{port}"
        return _STATE.attach(port)


class BrowserGotoTool(Tool):
    name = "browser_goto"
    description = "Navigate the active page to a URL."
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    }

    def execute(self, url: str) -> str:
        ok, reason = _gate(self.name, {"url": url})
        if not ok:
            return reason
        if not _STATE.attached:
            return "Browser not attached. Call browser_launch first."
        try:
            _STATE.page().goto(url, timeout=15000)
            return f"Navigated to {url}"
        except Exception as e:
            return f"goto error: {e}"


def _resolve_target(target: str):
    """Resolve a user-friendly target string to a Playwright Locator.

    Heuristics:
      - Looks like CSS / XPath → use directly
      - Looks like 'role:Name' (e.g. 'button:Sign in') → role-based
      - Otherwise → match by visible text (get_by_text)
    """
    page = _STATE.page()
    t = target.strip()
    if t.startswith(("//", "css=", "xpath=", "text=", "role=")):
        return page.locator(t)
    if ":" in t and t.split(":", 1)[0].lower() in {
        "button", "link", "textbox", "checkbox", "radio", "menuitem", "tab", "heading", "img"
    }:
        role, name = t.split(":", 1)
        return page.get_by_role(role.strip().lower(), name=name.strip())
    if any(c in t for c in "#.[]>"):
        return page.locator(t)  # CSS-ish
    return page.get_by_text(t, exact=False).first


class BrowserClickTool(Tool):
    name = "browser_click"
    description = (
        "Click an element on the active web page. target accepts: CSS selector, "
        "'role:Name' (e.g. 'button:Sign in'), or visible text. Use browser_snapshot "
        "first to find good targets."
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
        if not _STATE.attached:
            return "Browser not attached"
        try:
            loc = _resolve_target(target)
            loc.click(timeout=8000)
            return f"Clicked {target!r}"
        except Exception as e:
            return f"click error: {e}"


class BrowserTypeTool(Tool):
    name = "browser_type"
    description = "Type text into a field. target = CSS / role:name / visible text of the field."
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["target", "text"],
    }

    def execute(self, target: str, text: str) -> str:
        ok, reason = _gate(self.name, {"target": target, "text_len": len(text)})
        if not ok:
            return reason
        if not _STATE.attached:
            return "Browser not attached"
        try:
            loc = _resolve_target(target)
            loc.fill(text, timeout=8000)
            return f"Typed {len(text)} chars into {target!r}"
        except Exception as e:
            return f"type error: {e}"


class BrowserPressTool(Tool):
    name = "browser_press"
    description = "Press a key on the active page (Enter, Tab, Escape, ArrowDown, etc.)."
    parameters = {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    }

    def execute(self, key: str) -> str:
        ok, reason = _gate(self.name, {"key": key})
        if not ok:
            return reason
        if not _STATE.attached:
            return "Browser not attached"
        try:
            _STATE.page().keyboard.press(key)
            return f"Pressed {key}"
        except Exception as e:
            return f"press error: {e}"


class BrowserSnapshotTool(Tool):
    name = "browser_snapshot"
    description = (
        "Return the accessibility tree of the active page (role + name + value). "
        "Read-only — never gated. Use to discover selectors before clicking."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self) -> str:
        if not _STATE.attached:
            return "Browser not attached"
        try:
            tree = _STATE.page().accessibility.snapshot(interesting_only=True)
            if tree is None:
                return "(empty snapshot)"
            return json.dumps(tree, separators=(",", ":"))[:5000]
        except Exception as e:
            return f"snapshot error: {e}"


class BrowserCloseTool(Tool):
    name = "browser_close"
    description = "Disconnect Playwright (Chrome stays running). Use when done with browser tasks."
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self) -> str:
        _STATE.close()
        return "Detached."
