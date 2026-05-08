"""Safety gate for desktop automation actions.

Evaluated in order on every action:
  1. Master switch (JARVIS_ALLOW_AUTOMATION)
  2. Dry-run flag (JARVIS_AUTOMATION_DRY_RUN)
  3. App allowlist (JARVIS_AUTOMATION_ALLOWLIST, csv of WM_CLASS values)
  4. Action budget (JARVIS_ACTION_BUDGET, default 30)
  5. Destructive proximity (OCR around target → keyword match)
  6. Out-of-bounds coords (Input.check_bounds in caller)

Result is one of: "allow" | "dry_run" | "refuse" | "confirm".
Caller is responsible for surfacing the confirmation prompt to the user.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from logger import log


# Verbs / nouns near a click target that should require explicit confirmation.
_DESTRUCTIVE_RE = re.compile(
    r"\b(delete|remove|send|pay|confirm|sign|publish|drop|reset|destroy|"
    r"wipe|erase|empty|terminate|shut\s?down|format|uninstall|purchase|"
    r"checkout|charge|transfer|withdraw|cancel\s+account)\b",
    re.IGNORECASE,
)

# Tools that are read-only — never gated.
_READ_ONLY_TOOLS = {
    "screen_screenshot",
    "screen_zoom",
    "screen_wait",
    "screen_mouse_move",   # cursor move alone is non-destructive
    "ground_element",
}


@dataclass
class GateResult:
    decision: str          # "allow" | "dry_run" | "refuse" | "confirm"
    reason: str = ""       # human-readable explanation
    prompt: str = ""       # confirmation prompt shown to user when decision="confirm"


@dataclass
class TaskBudget:
    used: int = 0
    max_actions: int = 30

    def reset(self, max_actions: Optional[int] = None) -> None:
        self.used = 0
        if max_actions is not None:
            self.max_actions = max_actions

    def consume(self) -> bool:
        if self.used >= self.max_actions:
            return False
        self.used += 1
        return True


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return False
    return default


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


@dataclass
class AutomationGate:
    """Per-orchestrator instance. Holds task budget and reads env per-call so
    the user can flip JARVIS_AUTOMATION_DRY_RUN mid-session for testing."""

    budget: TaskBudget = field(default_factory=TaskBudget)

    def reset_budget(self) -> None:
        cap = int(os.environ.get("JARVIS_ACTION_BUDGET", "30"))
        self.budget.reset(cap)

    @property
    def enabled(self) -> bool:
        return _env_bool("JARVIS_ALLOW_AUTOMATION", False)

    @property
    def dry_run(self) -> bool:
        return _env_bool("JARVIS_AUTOMATION_DRY_RUN", False)

    @property
    def allowlist(self) -> list[str]:
        return _env_csv(
            "JARVIS_AUTOMATION_ALLOWLIST",
            "firefox,google-chrome,chromium,code,gnome-text-editor,gnome-terminal,kitty,alacritty,nautilus,postman",
        )

    def check(
        self,
        tool_name: str,
        kwargs: dict,
        *,
        active_window_class: str = "",
        nearby_text: str = "",
    ) -> GateResult:
        # Read-only tools always allowed regardless of master switch.
        if tool_name in _READ_ONLY_TOOLS:
            return GateResult("allow", reason="read-only tool")

        # 1. Master switch
        if not self.enabled:
            return GateResult(
                "refuse",
                reason="JARVIS_ALLOW_AUTOMATION is not set; desktop automation disabled.",
            )

        # 4. Action budget (consume here so refuse still counts the attempt)
        if not self.budget.consume():
            return GateResult(
                "refuse",
                reason=f"action budget exhausted ({self.budget.max_actions} actions per task).",
            )

        # 3. App allowlist
        wlist = self.allowlist
        if "*" not in wlist and active_window_class:
            cls = active_window_class.lower()
            if not any(allowed in cls for allowed in wlist):
                return GateResult(
                    "refuse",
                    reason=f"active window class '{active_window_class}' is not in allowlist {wlist}.",
                )

        # 5. Destructive proximity (only on click-family tools with coords)
        if tool_name in {"screen_click", "screen_double_click", "screen_right_click"}:
            if nearby_text and _DESTRUCTIVE_RE.search(nearby_text):
                return GateResult(
                    "confirm",
                    reason=f"target near destructive keyword in {nearby_text!r}",
                    prompt=(
                        f"About to {tool_name} near text containing a destructive keyword. "
                        f"Reply with the confirm phrase (default 'yes do it') to proceed, "
                        f"anything else cancels."
                    ),
                )

        # 2. Dry-run last — passes safety, but doesn't execute.
        if self.dry_run:
            return GateResult(
                "dry_run",
                reason="JARVIS_AUTOMATION_DRY_RUN active — logged, not executed.",
            )

        return GateResult("allow")

    @staticmethod
    def confirm_phrase() -> str:
        return os.environ.get("JARVIS_AUTOMATION_CONFIRM_PHRASE", "yes do it").strip().lower()
