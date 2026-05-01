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

# Synonyms: when user says LHS, also search RHS terms
SYNONYMS = {
    "notepad": ["text editor", "editor"],
    "notes": ["text editor", "notebook", "editor"],
    "note": ["text editor", "notebook", "editor"],
    "notebook": ["text editor", "editor"],
    "wordpad": ["text editor", "office", "writer"],
    "word": ["office", "writer", "document"],
    "excel": ["spreadsheet", "office", "calc"],
    "powerpoint": ["presentation", "office", "impress"],
    "paint": ["image editor", "drawing", "graphics"],
    "photoshop": ["image editor", "graphics", "gimp"],
    "explorer": ["file manager", "files"],
    "finder": ["file manager", "files"],
    "cmd": ["terminal", "shell"],
    "powershell": ["terminal", "shell"],
    "edge": ["browser", "web"],
    "safari": ["browser", "web"],
    "outlook": ["email", "mail"],
    "thunderbird": ["email", "mail"],
    "spotify": ["music", "audio player"],
    "vlc": ["video", "media player"],
    "movie": ["video", "media player"],
    "photos": ["image viewer", "gallery"],
    "camera": ["webcam", "cheese"],
    "zoom": ["video conference", "meeting"],
    "discord": ["chat", "messaging"],
    "telegram": ["chat", "messaging"],
    "whatsapp": ["chat", "messaging"],
}

# Cached app index — built once on first search, reused for the session
_APP_INDEX: list[dict] | None = None


def _build_app_index() -> list[dict]:
    """Parse all .desktop files once. Includes system, user, snap, flatpak."""
    paths: list[str] = []
    for d in [
        "/usr/share/applications",
        "/usr/local/share/applications",
        "/var/lib/snapd/desktop/applications",
        "/var/lib/flatpak/exports/share/applications",
        f"{__import__('os').path.expanduser('~')}/.local/share/applications",
    ]:
        paths.extend(glob.glob(f"{d}/*.desktop"))

    apps = []
    for path in paths:
        cp = configparser.ConfigParser(interpolation=None)
        try:
            cp.read(path)
        except Exception:
            continue
        if not cp.has_section("Desktop Entry"):
            continue

        name = cp.get("Desktop Entry", "Name", fallback="")
        exec_cmd = cp.get("Desktop Entry", "Exec", fallback="")
        no_display = cp.get("Desktop Entry", "NoDisplay", fallback="false").lower()
        if no_display == "true" or not exec_cmd:
            continue

        exec_clean = exec_cmd.split()[0].split("/")[-1]
        for token in ["%f", "%u", "%F", "%U", "%i", "%c", "%k"]:
            exec_clean = exec_clean.replace(token, "")
        exec_clean = exec_clean.strip()

        haystack = " ".join([
            name,
            cp.get("Desktop Entry", "GenericName", fallback=""),
            cp.get("Desktop Entry", "Categories", fallback=""),
            cp.get("Desktop Entry", "Comment", fallback=""),
            cp.get("Desktop Entry", "Keywords", fallback=""),
        ]).lower()

        apps.append({"name": name, "exec": exec_clean, "haystack": haystack})

    log.info(f"App index built: {len(apps)} apps")
    return apps


def _get_index() -> list[dict]:
    global _APP_INDEX
    if _APP_INDEX is None:
        _APP_INDEX = _build_app_index()
    return _APP_INDEX


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
    description = (
        "Search installed desktop apps by name, category, or keyword. "
        "Returns matches from cached index across system, user, snap, and flatpak apps. "
        "Automatically expands common synonyms (e.g. 'notepad' also searches 'text editor'). "
        "Call this ONCE before open_app — no need to retry with different terms."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "App name, category, or keyword (e.g. 'notepad', 'browser', 'image viewer')"}
        },
        "required": ["query"],
    }

    def execute(self, query: str) -> str:
        q = query.lower().strip()
        log.debug(f"search_app: '{q}'")

        # Drop filler words so "notes app" → "notes"
        FILLER = {"app", "application", "program", "the", "a", "an", "open", "please"}
        tokens = [t for t in q.split() if t not in FILLER]
        cleaned = " ".join(tokens) if tokens else q

        # Build query set: cleaned phrase + each token + their synonyms
        queries = {cleaned}
        queries.update(tokens)
        for term in [cleaned] + tokens:
            queries.update(SYNONYMS.get(term, []))

        index = _get_index()
        seen = set()
        matches = []

        for term in queries:
            for app in index:
                if term in app["haystack"]:
                    key = (app["name"], app["exec"])
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append(f"{app['name']} → {app['exec']}")

        if not matches:
            log.info(f"search_app no results for '{q}' (tried {queries})")
            return f"No installed apps found matching '{query}'"

        log.info(f"search_app: {len(matches)} results for '{q}'")
        return "Installed apps matching:\n" + "\n".join(matches[:10])


class SmartOpenAppTool(Tool):
    """One-shot search + open. Saves a model round-trip when intent is clear.

    Searches the app index using the user's term (with synonyms / filler stripped),
    then opens the best match. Returns ambiguous-match info if no clear winner.
    """
    name = "smart_open_app"
    description = (
        "Open a desktop app by user-friendly name. Internally searches with synonym "
        "expansion and filler-word stripping, then launches the best match. "
        "Use this for 'open X' / 'launch X' / 'run X' style requests — single tool call. "
        "Returns ambiguous-match info if multiple non-exact candidates exist."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What the user wants to open (e.g. 'text editor', 'browser', 'firefox')",
            }
        },
        "required": ["query"],
    }

    def execute(self, query: str) -> str:
        q = query.lower().strip()
        log.debug(f"smart_open_app: '{q}'")

        # Stage 1: alias / direct command match
        if q in ALIASES:
            return open_app_impl(ALIASES[q])
        if shutil.which(q):
            return open_app_impl(q)

        # Stage 2: search the index using the same logic as SearchAppTool
        FILLER = {"app", "application", "program", "the", "a", "an", "open", "please"}
        tokens = [t for t in q.split() if t not in FILLER]
        cleaned = " ".join(tokens) if tokens else q

        terms = {cleaned}
        terms.update(tokens)
        for term in [cleaned] + tokens:
            terms.update(SYNONYMS.get(term, []))

        from tools.apps import _get_index  # avoid forward ref
        index = _get_index()
        seen = set()
        matches = []
        exact_matches = []

        for term in terms:
            for app in index:
                key = (app["name"], app["exec"])
                if key in seen:
                    continue
                if term in app["haystack"]:
                    seen.add(key)
                    matches.append(app)
                    # Exact match: user's cleaned query equals app name (case-insensitive)
                    if cleaned == app["name"].lower():
                        exact_matches.append(app)

        # Open if exact match
        if len(exact_matches) >= 1:
            return open_app_impl(exact_matches[0]["exec"])

        # If only one candidate at all, open it
        if len(matches) == 1:
            return open_app_impl(matches[0]["exec"])

        # If first match's name contains the cleaned query, open it (substring match)
        if matches:
            for app in matches:
                if cleaned in app["name"].lower():
                    return open_app_impl(app["exec"])

        # Multiple ambiguous candidates — ask user
        if matches:
            options = ", ".join(f"{a['name']}" for a in matches[:5])
            return f"AMBIGUOUS: multiple candidates for '{query}': {options}. Ask user which one."

        return f"NOT_FOUND: no installed app matches '{query}'."


def open_app_impl(cmd: str) -> str:
    """Shared open implementation used by OpenAppTool and SmartOpenAppTool."""
    log.debug(f"open_app_impl: '{cmd}'")
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
    try:
        proc = subprocess.Popen(
            ["xdg-open", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Opened {cmd} via xdg-open (PID {proc.pid})"
    except Exception as e:
        log.error(f"xdg-open failed: {e}")
        return f"Failed to open '{cmd}': {e}"


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
