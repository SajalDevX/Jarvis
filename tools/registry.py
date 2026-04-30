from typing import Iterable

from tools.base import Tool
from tools.apps import OpenAppTool, CloseAppTool, SearchAppTool, RunCommandTool
from tools.vision import (
    TakeScreenshotTool,
    OCRScreenTool,
    DescribeScreenTool,
    FindUIElementTool,
    ActiveWindowTool,
    ListWindowsTool,
)


class ToolRegistry:
    """Holds tool instances. Agents subscribe to a subset by name."""

    def __init__(self, tools: Iterable[Tool]):
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self, names: Iterable[str] | None = None) -> list[dict]:
        if names is None:
            return [t.to_schema() for t in self._tools.values()]
        return [self._tools[n].to_schema() for n in names if n in self._tools]

    def dispatch(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        return tool.execute(**args)


# Global registry — register all tools here as project grows
REGISTRY = ToolRegistry([
    OpenAppTool(),
    CloseAppTool(),
    SearchAppTool(),
    RunCommandTool(),
    TakeScreenshotTool(),
    OCRScreenTool(),
    DescribeScreenTool(),
    FindUIElementTool(),
    ActiveWindowTool(),
    ListWindowsTool(),
])
