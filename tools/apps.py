import subprocess
import shutil
from logger import log

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


def open_app(app_name: str) -> str:
    raw = app_name.lower().strip()
    cmd = ALIASES.get(raw, raw)
    log.debug(f"open_app called: input='{app_name}' → resolved='{cmd}'")

    # Check if command exists in PATH
    if shutil.which(cmd):
        log.debug(f"Found '{cmd}' in PATH, launching directly")
        try:
            proc = subprocess.Popen(
                [cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info(f"Launched '{cmd}' with PID {proc.pid}")
            return f"Opened {cmd} (PID {proc.pid})"
        except Exception as e:
            log.error(f"Failed to launch '{cmd}': {e}")
            return f"Failed to open '{cmd}': {e}"
    else:
        log.debug(f"'{cmd}' not found in PATH, falling back to xdg-open")
        try:
            proc = subprocess.Popen(
                ["xdg-open", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info(f"Launched '{cmd}' via xdg-open with PID {proc.pid}")
            return f"Opened {cmd} via xdg-open (PID {proc.pid})"
        except Exception as e:
            log.error(f"xdg-open also failed for '{cmd}': {e}")
            return f"Failed to open '{cmd}': {e}"


def close_app(app_name: str) -> str:
    raw = app_name.lower().strip()
    cmd = ALIASES.get(raw, raw)
    log.debug(f"close_app called: input='{app_name}' → resolved='{cmd}'")

    result = subprocess.run(["pkill", "-f", cmd], capture_output=True)
    if result.returncode == 0:
        log.info(f"Killed processes matching '{cmd}'")
        return f"Closed {cmd}"
    log.warning(f"No process found for '{cmd}' (pkill returncode={result.returncode})")
    return f"No running process found for '{cmd}'"


def run_command(command: str) -> str:
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
        log.debug(f"run_command exit={result.returncode}, output={output[:200]}")
        return output
    except subprocess.TimeoutExpired:
        log.error(f"Command timed out: {command}")
        return "Command timed out after 30s"
