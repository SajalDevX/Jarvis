import subprocess
import shutil
import glob
import configparser

from logger import log
from tools.base import Tool

ALIASES = {
    "browser": "firefox",
    "chrome": "google-chrome",
    "files": "nautilus",
    "file manager": "nautilus",
    "terminal": "gnome-terminal",
    "text editor": "gnome-text-editor",
    "gedit": "gnome-text-editor",
    "calculator": "gnome-calculator",
    "settings": "gnome-control-center",
    "music": "rhythmbox",
    "video": "vlc",
    "photos": "eog",
}


class OpenAppTool(Tool):
    name = "open_app"
    description = "Open a desktop application by its command (e.g. firefox, gnome-text-editor, vlc). Prefer calling search_app first if unsure of exact command."
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Exact command to launch (e.g. 'gnome-text-editor', not 'text editor')"}
        },
        "required": ["app_name"],
    }

    def execute(self, app_name: str) -> str:
        raw = app_name.lower().strip()
        cmd = ALIASES.get(raw, raw)
        log.debug(f"open_app: input='{app_name}' → '{cmd}'")

        if shutil.which(cmd):
            try:
                proc = subprocess.Popen(
                    [cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                log.info(f"Launched '{cmd}' PID={proc.pid}")
                return f"Opened {cmd} (PID {proc.pid})"
            except Exception as e:
                log.error(f"Launch failed: {e}")
                return f"Failed to open '{cmd}': {e}"

        log.debug(f"'{cmd}' not in PATH, fallback xdg-open")
        try:
            proc = subprocess.Popen(
                ["xdg-open", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info(f"Launched via xdg-open PID={proc.pid}")
            return f"Opened {cmd} via xdg-open (PID {proc.pid})"
        except Exception as e:
            log.error(f"xdg-open failed: {e}")
            return f"Failed to open '{cmd}': {e}"


class CloseAppTool(Tool):
    name = "close_app"
    description = "Close/kill a running desktop application by name."
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "App name or process pattern to kill"}
        },
        "required": ["app_name"],
    }

    def execute(self, app_name: str) -> str:
        raw = app_name.lower().strip()
        cmd = ALIASES.get(raw, raw)
        log.debug(f"close_app: input='{app_name}' → '{cmd}'")

        result = subprocess.run(["pkill", "-f", cmd], capture_output=True)
        if result.returncode == 0:
            log.info(f"Killed '{cmd}'")
            return f"Closed {cmd}"
        log.warning(f"No process found for '{cmd}'")
        return f"No running process found for '{cmd}'"


class SearchAppTool(Tool):
    name = "search_app"
    description = "Search for installed desktop apps matching a name or category. Always call this BEFORE open_app when unsure if an app exists. Searches names, categories, and descriptions of all installed apps."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "App name, category, or keyword (e.g. 'notepad', 'text editor', 'browser', 'image viewer')"}
        },
        "required": ["query"],
    }

    def execute(self, query: str) -> str:
        log.debug(f"search_app: '{query}'")
        q = query.lower()
        matches = []

        for path in glob.glob("/usr/share/applications/*.desktop"):
            cp = configparser.ConfigParser(interpolation=None)
            try:
                cp.read(path)
            except Exception:
                continue
            if not cp.has_section("Desktop Entry"):
                continue

            name = cp.get("Desktop Entry", "Name", fallback="")
            exec_cmd = cp.get("Desktop Entry", "Exec", fallback="")
            generic = cp.get("Desktop Entry", "GenericName", fallback="")
            categories = cp.get("Desktop Entry", "Categories", fallback="")
            comment = cp.get("Desktop Entry", "Comment", fallback="")
            no_display = cp.get("Desktop Entry", "NoDisplay", fallback="false").lower()

            if no_display == "true" or not exec_cmd:
                continue

            exec_clean = exec_cmd.split()[0].split("/")[-1]
            for token in ["%f", "%u", "%F", "%U", "%i", "%c", "%k"]:
                exec_clean = exec_clean.replace(token, "")
            exec_clean = exec_clean.strip()

            haystack = f"{name} {generic} {categories} {comment}".lower()
            if q in haystack:
                matches.append(f"{name} → {exec_clean}")

        if not matches:
            log.info(f"search_app no results for '{query}'")
            return f"No installed apps found matching '{query}'"

        log.info(f"search_app: {len(matches)} results")
        return "Installed apps matching:\n" + "\n".join(matches[:8])


class RunCommandTool(Tool):
    name = "run_command"
    description = "Run a shell command and return its output. Use for quick read-only system tasks (ls, cat, ps, etc.)."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"}
        },
        "required": ["command"],
    }

    def execute(self, command: str) -> str:
        log.debug(f"run_command: {command}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout.strip() or result.stderr.strip() or "(no output)"
            log.debug(f"exit={result.returncode} out={output[:200]}")
            return output
        except subprocess.TimeoutExpired:
            log.error(f"Timeout: {command}")
            return "Command timed out after 30s"
