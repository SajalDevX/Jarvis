from typing import Iterable

from tools.base import Tool
from tools.apps import OpenAppTool, CloseAppTool, SearchAppTool, RunCommandTool, SmartOpenAppTool
from tools.vision import (
    TakeScreenshotTool,
    OCRScreenTool,
    DescribeScreenTool,
    FindUIElementTool,
    ActiveWindowTool,
    ListWindowsTool,
)
from tools.ground import GroundElementTool
from tools.desktop_actions import (
    ScreenScreenshotTool,
    ScreenWaitTool,
    ScreenZoomTool,
    ScreenClickTool,
    ScreenDoubleClickTool,
    ScreenRightClickTool,
    ScreenMouseMoveTool,
    ScreenDragTool,
    ScreenScrollTool,
    ScreenTypeTool,
    ScreenKeyTool,
    FocusWindowTool,
)
from tools.cli_actions import (
    MediaControlTool,
    VolumeSetTool,
    VolumeMuteTool,
    WifiToggleTool,
    BluetoothToggleTool,
    XdgOpenTool,
    WindowResizeTool,
    WindowMoveTool,
    WorkspaceSwitchTool,
)
from tools.a11y import (
    A11yTreeTool,
    A11yFindTool,
    A11yClickTool,
    A11yTypeTool,
)
from tools.browser import (
    BrowserListProfilesTool,
    BrowserLaunchTool,
    BrowserAttachTool,
    BrowserGotoTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserPressTool,
    BrowserSnapshotTool,
    BrowserCloseTool,
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
    SmartOpenAppTool(),
    RunCommandTool(),
    TakeScreenshotTool(),
    OCRScreenTool(),
    DescribeScreenTool(),
    FindUIElementTool(),
    ActiveWindowTool(),
    ListWindowsTool(),
    # Phase 5: desktop control
    GroundElementTool(),
    ScreenScreenshotTool(),
    ScreenWaitTool(),
    ScreenZoomTool(),
    ScreenClickTool(),
    ScreenDoubleClickTool(),
    ScreenRightClickTool(),
    ScreenMouseMoveTool(),
    ScreenDragTool(),
    ScreenScrollTool(),
    ScreenTypeTool(),
    ScreenKeyTool(),
    FocusWindowTool(),
    # Phase 6: CLI / D-Bus action layer (fastest)
    MediaControlTool(),
    VolumeSetTool(),
    VolumeMuteTool(),
    WifiToggleTool(),
    BluetoothToggleTool(),
    XdgOpenTool(),
    WindowResizeTool(),
    WindowMoveTool(),
    WorkspaceSwitchTool(),
    # Phase 6: AT-SPI accessibility layer
    A11yTreeTool(),
    A11yFindTool(),
    A11yClickTool(),
    A11yTypeTool(),
    # Phase 6: browser layer (Playwright + CDP)
    BrowserListProfilesTool(),
    BrowserLaunchTool(),
    BrowserAttachTool(),
    BrowserGotoTool(),
    BrowserClickTool(),
    BrowserTypeTool(),
    BrowserPressTool(),
    BrowserSnapshotTool(),
    BrowserCloseTool(),
])
