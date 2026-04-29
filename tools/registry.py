from tools.apps import open_app, close_app, run_command

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open a desktop application by name (e.g. firefox, vlc, nautilus)",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "App name or command to launch"}
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": "Close/kill a running desktop application by name",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "App name to kill"}
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return its output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"],
            },
        },
    },
]

_DISPATCH = {
    "open_app": open_app,
    "close_app": close_app,
    "run_command": run_command,
}


def dispatch(tool_name: str, args: dict) -> str:
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return f"Unknown tool: {tool_name}"
    return fn(**args)
