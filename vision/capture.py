"""Screen capture primitives. Uses mss (fast, cross-platform).

Active-window capture queries xdotool when available, falls back to full screen.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import time
from pathlib import Path

import mss
from PIL import Image

from logger import log


CACHE_DIR = Path.home() / ".cache" / "jarvis" / "screen"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAX_KEEP = 10


def _rotate_cache():
    """Keep last N screenshots, delete older."""
    files = sorted(CACHE_DIR.glob("shot_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[MAX_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def _new_cache_path() -> Path:
    return CACHE_DIR / f"shot_{int(time.time() * 1000)}.png"


def capture_full_screen() -> Path:
    """Grab the primary monitor. Returns saved PNG path."""
    out = _new_cache_path()
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 0 is "all monitors", 1 is primary
        img = sct.grab(monitor)
        Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX").save(out, "PNG")
    log.debug(f"capture_full_screen → {out} ({out.stat().st_size} bytes)")
    _rotate_cache()
    return out


def _active_window_geometry() -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) of active window. Requires xdotool. None if unavailable."""
    if not shutil.which("xdotool"):
        return None
    try:
        wid = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
        out = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", wid],
            text=True,
        )
        env = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env[k] = int(v)
        return env["X"], env["Y"], env["WIDTH"], env["HEIGHT"]
    except (subprocess.CalledProcessError, KeyError, ValueError) as e:
        log.warning(f"Active window geometry failed: {e}")
        return None


def _silence_xlib_errors():
    """Context-managerless: dup2 fd 2 → /dev/null, return restore fn.

    Xlib's default error handler writes raw 'X Error of failed request' lines
    to fd 2 from C, bypassing Python's stderr. Silence at fd level briefly
    during mss.grab() since mss can hit a benign protocol race when the
    active window moves mid-call.
    """
    import os as _os
    try:
        devnull = _os.open(_os.devnull, _os.O_WRONLY)
        saved = _os.dup(2)
        _os.dup2(devnull, 2)

        def restore():
            try:
                _os.dup2(saved, 2)
                _os.close(saved)
                _os.close(devnull)
            except Exception:
                pass
        return restore
    except Exception:
        return lambda: None


def capture_active_window() -> Path:
    """Capture only the active window. Falls back to full screen if xdotool missing."""
    geom = _active_window_geometry()
    if geom is None:
        log.debug("xdotool unavailable — falling back to full-screen capture")
        return capture_full_screen()

    x, y, w, h = geom
    out = _new_cache_path()
    restore = _silence_xlib_errors()
    try:
        with mss.mss() as sct:
            img = sct.grab({"left": x, "top": y, "width": w, "height": h})
            Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX").save(out, "PNG")
    finally:
        restore()
    log.debug(f"capture_active_window {x},{y},{w}x{h} → {out}")
    _rotate_cache()
    return out


def downscale_for_llm(path: Path, max_width: int = 768, jpeg_quality: int = 65) -> bytes:
    """Resize + JPEG-encode an image for cheap multimodal upload.

    Cuts payload ~5x vs raw PNG. Returns the encoded bytes (caller base64s for API).
    """
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    return buf.getvalue()
